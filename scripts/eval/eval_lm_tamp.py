"""
Usage:

PYTHONPATH=. python scripts/eval/eval_lm_tamp.py  --planner-config configs/pybullet/planners/ablation/policy_cem.yaml --env-config configs/pybullet/envs/official/domains/constrained_packing/tamp0.yaml 
--policy-checkpoints models/20221105/decoupled_state/pick/ckpt_model_10.pt models/20221105/decoupled_state/place/ckpt_model_10.pt models/20221105/decoupled_state/pull/ckpt_model_10.pt 
models/20221105/decoupled_state/push/ckpt_model_10.pt --dynamics-checkpoint models/20221105/decoupled_state/ckpt_model_10/dynamics/final_model.pt --seed 0 
--pddl-domain configs/pybullet/envs/official/domains/constrained_packing/tamp0_domain.pddl --pddl-problem configs/pybullet/envs/official/domains/constrained_packing/tamp0_problem.pddl 
--max-depth 4 --timeout 10 --closed-loop 1 --num-eval 100 --path plots/20221105/decoupled_state/tamp_experiment/constrained_packing/tamp0 --verbose 0 --engine davinci
"""

import argparse
import pathlib
import pickle
import random
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple, Union

import numpy as np
import symbolic
import tqdm
from helm.common.authentication import Authentication
from configs.base_config import LMConfig

from temporal_policies import dynamics, envs, planners
from temporal_policies.envs.pybullet.table import (
    predicates,
    primitives as table_primitives,
)
from temporal_policies.envs.pybullet.table.objects import Object
from temporal_policies.evaluation.utils import get_goal_props_instantiated, get_object_relationships, get_possible_props, get_prop_testing_objs, get_task_plan_primitives_instantiated, is_satisfy_goal_props
from temporal_policies.task_planners.goals import get_goal_from_lm, is_valid_goal_props
from temporal_policies.task_planners.lm_data_structures import (
    APIType,
    CurrentExample,
    InContextExample,
)
from temporal_policies.task_planners.task_plans import get_task_plans_from_lm
from temporal_policies.utils import recording, timing

from temporal_policies.task_planners.lm_utils import (
    get_examples_from_json_dir,
    generate_lm_response,
    load_lm_cache,
    register_api_key,
    save_lm_cache,
)


def seed_generator(
    num_eval: int,
    path_results: Optional[Union[str, pathlib.Path]] = None,
) -> Generator[
    Tuple[
        Optional[int],
        Optional[Tuple[np.ndarray, planners.PlanningResult, Optional[List[float]]]],
    ],
    None,
    None,
]:
    if path_results is not None:
        npz_files = sorted(
            pathlib.Path(path_results).glob("results_*.npz"),
            key=lambda x: int(x.stem.split("_")[-1]),
        )
        for npz_file in npz_files:
            with open(npz_file, "rb") as f:
                npz = np.load(f, allow_pickle=True)
                seed: int = npz["seed"].item()
                rewards = np.array(npz["rewards"])
                plan = planners.PlanningResult(
                    actions=np.array(npz["actions"]),
                    states=np.array(npz["states"]),
                    p_success=npz["p_success"].item(),
                    values=np.array(npz["values"]),
                )
                t_planner: List[float] = npz["t_planner"].item()

            yield seed, (rewards, plan, t_planner)

    if num_eval is not None:
        yield 0, None
        for _ in range(num_eval - 1):
            yield None, None


def scale_actions(
    actions: np.ndarray,
    env: envs.Env,
    action_skeleton: Sequence[envs.Primitive],
) -> np.ndarray:
    scaled_actions = actions.copy()
    for t, primitive in enumerate(action_skeleton):
        action_dims = primitive.action_space.shape[0]
        scaled_actions[..., t, :action_dims] = primitive.scale_action(
            actions[..., t, :action_dims]
        )

    return scaled_actions


def task_plan(
    pddl: symbolic.Pddl,
    env: envs.Env,
    max_depth: int = 5,
    timeout: float = 10.0,
    verbose: bool = False,
) -> Generator[List[envs.Primitive], None, None]:
    planner = symbolic.Planner(pddl, pddl.initial_state)
    bfs = symbolic.BreadthFirstSearch(
        planner.root, max_depth=max_depth, timeout=timeout, verbose=False
    )
    for plan in bfs:
        action_skeleton = [
            env.get_primitive_info(action_call=str(node.action)) for node in plan[1:]
        ]
        yield action_skeleton

def evaluate_plan(
    idx_iter: int,
    env: envs.Env,
    planner: planners.Planner,
    action_skeleton: Sequence[envs.Primitive],
    plan: planners.PlanningResult,
    rewards: np.ndarray,
    path: pathlib.Path,
    grid_resolution: Optional[int] = None,
) -> Dict[str, Any]:
    assert isinstance(env, envs.pybullet.TableEnv)
    recorder = recording.Recorder()
    recorder.start()
    for primitive, predicted_state, action in zip(
        action_skeleton, plan.states[1:], plan.actions
    ):
        env.set_primitive(primitive)
        env._recording_text = (
            "Action: ["
            + ", ".join([f"{a:.2f}" for a in primitive.scale_action(action)])
            + "]"
        )

        recorder.add_frame(frame=env.render())
        env.set_observation(predicted_state)
        recorder.add_frame(frame=env.render())
    recorder.stop()
    recorder.save(path / f"predicted_trajectory_{idx_iter}.gif")

    return {}


def eval_lm_tamp(
    planner_config: Union[str, pathlib.Path],
    env_config: Union[str, pathlib.Path, Dict[str, Any]],
    policy_checkpoints: Optional[Sequence[Optional[Union[str, pathlib.Path]]]],
    scod_checkpoints: Optional[Sequence[Optional[Union[str, pathlib.Path]]]],
    dynamics_checkpoint: Optional[Union[str, pathlib.Path]],
    device: str,
    num_eval: int,
    path: Union[str, pathlib.Path],
    closed_loop: int,
    pddl_domain: str,  # file path
    pddl_root_dir: str,
    pddl_domain_name: str,
    pddl_problem: str,  # file path
    max_depth: int = 5,
    timeout: float = 10.0,
    verbose: bool = False,
    load_path: Optional[Union[str, pathlib.Path]] = None,
    seed: Optional[int] = None,
    gui: Optional[int] = None,
    lm_cache_file: Optional[Union[str, pathlib.Path]] = None,
    n_examples: Optional[int] = 1,
    custom_in_context_example_robot_prompt: str = "Top 1 robot action sequences: ",
    custom_in_context_example_robot_format: str = "python list of lists",
    custom_robot_prompt: str = "Top 2 robot action sequences (python list of lists): ",
    custom_robot_answer_format: str = "python list of lists",
    engine: Optional[str] = None,
    temperature: Optional[int] = 0,
    logprobs: Optional[int] = 1,
    api_type: Optional[APIType] = APIType.HELM,
    max_tokens: Optional[int] = 100,
    auth: Optional[Authentication] = None,
) -> None:
    examples = get_examples_from_json_dir(pddl_root_dir + "/" + pddl_domain_name)
    examples = random.sample(examples, n_examples)

    lm_cfg = LMConfig(
        engine=engine,
        temperature=temperature,
        logprobs=logprobs,
        echo=False,
        api_type=api_type,
        max_tokens=max_tokens,
    )
    lm_cache: Dict[str, str] = load_lm_cache(pathlib.Path(lm_cache_file))
    timer = timing.Timer()

    # Load environment.
    env_kwargs = {}
    if gui is not None:
        env_kwargs["gui"] = bool(gui)
    env_factory = envs.EnvFactory(config=env_config)
    env = env_factory(**env_kwargs)

    prop_testing_objs: Dict[str, Object] = get_prop_testing_objs(env)

    # Load planner.
    planner = planners.load(
        config=planner_config,
        env=env,
        policy_checkpoints=policy_checkpoints,
        scod_checkpoints=scod_checkpoints,
        dynamics_checkpoint=dynamics_checkpoint,
        device=device,
    )
    path = pathlib.Path(path) / pathlib.Path(planner_config).stem
    path.mkdir(parents=True, exist_ok=True)

    # Run TAMP.
    num_success = 0
    pbar = tqdm.tqdm(
        seed_generator(num_eval, load_path), f"Evaluate {path.name}", dynamic_ncols=True
    )
    for idx_iter, (seed, loaded_plan) in enumerate(pbar):
        # Initialize environment.
        observation, info = env.reset(seed=seed)
        seed = info["seed"]
        state = env.get_state()

        task_plans = []
        motion_plans = []
        motion_planner_times = []
        INSTRUCTION = "Ensure the red block is on the table."  # one of the examples needs to use the hook
        INSTRUCTION = "Grab the red block."
        available_predicates = [
            "on",
            "inhand",
        ]

        objects: List[str] = list(env.objects.keys())
        object_relationships = get_object_relationships(
            observation, env.objects, available_predicates, use_hand_state=False
        )
        possible_props: List[predicates.Predicate] = get_possible_props(env.objects, available_predicates)

        predicted_goal_props: List[str]
        predicted_goal_props, lm_cache = get_goal_from_lm(
            INSTRUCTION,
            objects,
            object_relationships,
            pddl_domain,
            pddl_problem,
            examples=examples,
            lm_cfg=lm_cfg,
            auth=auth,
            lm_cache=lm_cache,
        )

        if is_valid_goal_props(predicted_goal_props, possible_props):
            parsed_goal_props = [
                symbolic.problem.parse_proposition(prop)
                for prop in predicted_goal_props
            ]
            goal_props_callable: List[predicates.Predicate] = get_goal_props_instantiated(parsed_goal_props)
        else:
            raise ValueError("Invalid goal props")
            
        save_lm_cache(lm_cache_file, lm_cache)

        # generate prompt from environment observation
        generated_task_plans, lm_cache = get_task_plans_from_lm(
            INSTRUCTION,
            predicted_goal_props,
            objects,
            object_relationships,
            pddl_domain,
            pddl_problem,
            examples=examples,
            custom_in_context_example_robot_prompt=custom_in_context_example_robot_prompt,
            custom_in_context_example_robot_format=custom_in_context_example_robot_format,
            custom_robot_prompt=custom_robot_prompt,
            custom_robot_answer_format=custom_robot_answer_format,
            lm_cfg=lm_cfg,
            auth=auth,
            lm_cache=lm_cache,
        )

        action_skeletons_instantiated = get_task_plan_primitives_instantiated(generated_task_plans, env)
        # save the lm_cache
        with open(lm_cache_file, "wb") as f:
            print(f"Saving lm_cache to {lm_cache_file}...")
            pickle.dump(lm_cache, f, protocol=pickle.HIGHEST_PROTOCOL)

        # if performing entire task plan generation e.g. open_ended generation
        for action_skeleton in action_skeletons_instantiated:
            timer.tic("motion_planner")
            env.set_primitive(action_skeleton[0])
            plan = planner.plan(env.get_observation(), action_skeleton)
            t_motion_planner = timer.toc("motion_planner")

            task_plans.append(action_skeleton)
            motion_plans.append(plan)
            motion_planner_times.append(t_motion_planner)

            # Reset env for oracle value/dynamics.
            if isinstance(planner.dynamics, dynamics.OracleDynamics):
                env.set_state(state)

            if "greedy" in str(planner_config):
                break

        # Filter out plans that do not reach the goal.
        goal_reaching_task_plans = []
        goal_reaching_motion_plans = []
        goal_reaching_task_p_successes = []
        for task_plan, motion_plan in zip(task_plans, motion_plans):
            # find first timestep where the goal is reached
            for i, state in enumerate(motion_plan.states):
                if is_satisfy_goal_props(goal_props_callable, prop_testing_objs, state, use_hand_state=False):
                    goal_reaching_task_plans.append(task_plan[:i])
                    goal_reaching_motion_plans.append(motion_plan.actions[:i])
                    # probability of success is the probability of success (i.e. value) 
                    # at each timestep multiplied together
                    p_success = np.prod([value for value in motion_plan.values[:i]])
                    print(f"p_success: {p_success}")
                    goal_reaching_task_p_successes.append(p_success)

        idx_best = np.argmax(goal_reaching_task_p_successes)

        best_task_plan = task_plans[idx_best]
        best_motion_plan = motion_plans[idx_best]

        if closed_loop:
            env.record_start()

            # Execute one step.
            action = best_motion_plan.actions[0]
            assert isinstance(action, np.ndarray)
            state = best_motion_plan.states[0]
            assert isinstance(state, np.ndarray)
            p_success = best_motion_plan.p_success
            value = best_motion_plan.values[0]
            env.set_primitive(best_task_plan[0])
            _, reward, _, _, _ = env.step(action)

            # Run closed-loop planning on the rest.
            rewards, plan, t_planner = planners.run_closed_loop_planning(
                env, best_task_plan[1:], planner, timer
            )
            rewards = np.append(reward, rewards)
            plan = planners.PlanningResult(
                actions=np.concatenate((action[None, ...], plan.actions), axis=0),
                states=np.concatenate((state[None, ...], plan.states), axis=0),
                p_success=p_success * plan.p_success,
                values=np.append(value, plan.values),
            )
            env.record_stop()

            # Save recording.
            gif_path = path / f"planning_{idx_iter}.gif"
            if (rewards == 0.0).any():
                gif_path = gif_path.parent / f"{gif_path.name}_fail{gif_path.suffix}"
            env.record_save(gif_path, reset=True)

            if t_planner is not None:
                motion_planner_times += t_planner
        else:
            # Execute plan.
            rewards = planners.evaluate_plan(
                env,
                task_plans[idx_best],
                motion_plans[idx_best].actions,
                gif_path=path / f"planning_{idx_iter}.gif",
            )

        if rewards.prod() > 0:
            num_success += 1
        pbar.set_postfix(
            dict(
                success=rewards.prod(),
                **{f"r{t}": r for t, r in enumerate(rewards)},
                num_successes=f"{num_success} / {idx_iter + 1}",
            )
        )

        # Print planning results.
        if verbose:
            print("success:", rewards.prod(), rewards)
            print(
                "predicted success:",
                motion_plans[idx_best].p_success,
                motion_plans[idx_best].values,
            )
            if closed_loop:
                print(
                    "visited predicted success:",
                    motion_plans[idx_best].p_visited_success,
                    motion_plans[idx_best].visited_values,
                )
            for primitive, action in zip(
                task_plans[idx_best], motion_plans[idx_best].actions
            ):
                if isinstance(primitive, table_primitives.Primitive):
                    primitive_action = str(primitive.Action(action))
                    primitive_action = primitive_action.replace("\n", "\n  ")
                    print(
                        "-", primitive, primitive_action[primitive_action.find("{") :]
                    )
                else:
                    print("-", primitive, action)
            print("discarded plans:")
            for idx_plan in range(len(task_plans)):
                if idx_plan == idx_best:
                    continue
                print(
                    "  - predicted success:",
                    motion_plans[idx_plan].p_success,
                    motion_plans[idx_plan].values,
                )
                for primitive, action in zip(
                    task_plans[idx_plan], motion_plans[idx_plan].actions
                ):
                    if isinstance(primitive, table_primitives.Primitive):
                        primitive_action = str(primitive.Action(action))
                        primitive_action = primitive_action.replace("\n", "\n      ")
                        print(
                            "    -",
                            primitive,
                            primitive_action[primitive_action.find("{") :],
                        )
                    else:
                        print("    -", primitive, action)
            continue

        # Save planning results.
        with open(path / f"results_{idx_iter}.npz", "wb") as f:
            save_dict = {
                "args": {
                    "planner_config": planner_config,
                    "env_config": env_config,
                    "policy_checkpoints": policy_checkpoints,
                    "dynamics_checkpoint": dynamics_checkpoint,
                    "device": device,
                    "num_eval": num_eval,
                    "path": path,
                    "pddl_domain": pddl_domain,
                    "pddl_problem": pddl_problem,
                    "max_depth": max_depth,
                    "timeout": timeout,
                    "seed": seed,
                    "verbose": verbose,
                },
                "observation": observation,
                "state": state,
                "action_skeleton": list(map(str, task_plans[idx_best])),
                "actions": motion_plans[idx_best].actions,
                "states": motion_plans[idx_best].states,
                "scaled_actions": scale_actions(
                    motion_plans[idx_best].actions, env, task_plans[idx_best]
                ),
                "p_success": motion_plans[idx_best].p_success,
                "values": motion_plans[idx_best].values,
                "rewards": rewards,
                # "visited_actions": motion_plans[idx_best].visited_actions,
                # "scaled_visited_actions": scale_actions(
                #     motion_plans[idx_best].visited_actions, env, action_skeleton
                # ),
                # "visited_states": motion_plans[idx_best].visited_states,
                "p_visited_success": motion_plans[idx_best].p_visited_success,
                # "visited_values": motion_plans[idx_best].visited_values,
                # "t_task_planner": t_task_planner,
                # "t_motion_planner": t_motion_planner,
                "t_planner": motion_planner_times,
                "seed": seed,
                "discarded": [
                    {
                        "action_skeleton": list(map(str, task_plans[i])),
                        # "actions": motion_plans[i].actions,
                        # "states": motion_plans[i].states,
                        # "scaled_actions": scale_actions(
                        #     motion_plans[i].actions, env, task_plans[i]
                        # ),
                        "p_success": motion_plans[i].p_success,
                        # "values": motion_plans[i].values,
                        # "visited_actions": motion_plans[i].visited_actions,
                        # "scaled_visited_actions": scale_actions(
                        #     motion_plans[i].visited_actions, env, action_skeleton
                        # ),
                        # "visited_states": motion_plans[i].visited_states,
                        "p_visited_success": motion_plans[i].p_visited_success,
                        # "visited_values": motion_plans[i].visited_values,
                    }
                    for i in range(len(task_plans))
                    if i != idx_best
                ],
            }
            np.savez_compressed(f, **save_dict)  # type: ignore


def main(args: argparse.Namespace) -> None:
    if args.api_type.value == APIType.OPENAI.value:
        api_key = "***REMOVED***"
    elif args.api_type.value == APIType.HELM.value:
        api_key = "***REMOVED***"
    else:
        raise ValueError("Invalid API type")
    auth = register_api_key(args.api_type, api_key)
    eval_lm_tamp(**vars(args), auth=auth)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--planner-config", "--planner", "-c", help="Path to planner config"
    )
    parser.add_argument("--env-config", "--env", "-e", help="Path to env config")
    parser.add_argument(
        "--policy-checkpoints", "-p", nargs="+", help="Policy checkpoints"
    )
    parser.add_argument("--scod-checkpoints", "-s", nargs="+", help="SCOD checkpoints")
    parser.add_argument("--dynamics-checkpoint", "-d", help="Dynamics checkpoint")
    parser.add_argument("--device", default="auto", help="Torch device")
    parser.add_argument(
        "--num-eval", "-n", type=int, default=1, help="Number of eval iterations"
    )
    parser.add_argument("--path", default="plots", help="Path for output plots")
    parser.add_argument(
        "--closed-loop", default=1, type=int, help="Run closed-loop planning"
    )
    parser.add_argument("--seed", type=int, help="Random seed")
    parser.add_argument("--gui", type=int, help="Show pybullet gui")
    parser.add_argument("--verbose", type=int, default=1, help="Print debug messages")
    parser.add_argument("--pddl-domain", help="Pddl domain")
    parser.add_argument("--pddl-problem", help="Pddl problem")
    parser.add_argument(
        "--max-depth", type=int, default=4, help="Task planning search depth"
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Task planning timeout"
    )
    # EvaluationConfig
    parser.add_argument(
        "--lm_cache_file", type=str, default="lm_cache.pkl", help="LM cache file"
    )
    # PDDLConfig
    parser.add_argument(
        "--pddl-root-dir",
        type=str,
        default="configs/pybullet/envs/official/domains",
        help="PDDL root dir",
    )
    parser.add_argument(
        "--pddl-domain-name",
        type=str,
        default="constrained_packing",
        help="PDDL domain",
        choices=["constrained_packing", "hook_reach"],
    )
    # PromptConfig
    parser.add_argument(
        "--n-examples",
        type=int,
        default=1,
        help="Number of examples to use in in context prompt",
    )
    # LMConfig
    parser.add_argument(
        "--engine",
        type=str,
        default="curie",
        help="LM engine (curie or davinci or baggage or ada)",
    )
    parser.add_argument("--temperature", type=float, default=0, help="LM temperature")
    parser.add_argument("--api_type", type=APIType, default=APIType.HELM, help="API to use")
    parser.add_argument("--max_tokens", type=int, default=100, help="LM max tokens")
    parser.add_argument("--logprobs", type=int, default=1, help="LM logprobs")

    args = parser.parse_args()

    main(args)
