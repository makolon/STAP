import os
from os import path
import time
import argparse
import numpy as np
import yaml
import json
from copy import deepcopy
import pprint

import temporal_policies.algs.planners.pybox2d as pybox2d_planners
import temporal_policies.envs.pybox2d as pybox2d_envs


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--exec-config", type=str, required=True, help="Path to execution configs")
    parser.add_argument("--checkpoints", nargs="+", type=str, required=True, help="Path to model checkpoints")
    parser.add_argument("--path", type=str, required=True, help="Path to save json files")
    parser.add_argument("--num-eps", type=int, default=1, help="Number of episodes to unit test across")
    parser.add_argument("--device", "-d", type=str, default="auto")
    args = parser.parse_args()

    # Setup
    with open(args.exec_config, "r") as fs: exec_config = yaml.safe_load(fs)
    env_cls = [vars(pybox2d_envs)[subtask["env"]] for subtask in exec_config["task"]]
    planner = vars(pybox2d_planners)[exec_config["planner"]](
        task=exec_config["task"],
        checkpoints=args.checkpoints,
        device=args.device,
        **exec_config["planner_kwargs"]
    )
    fname = path.splitext(path.split(args.exec_config)[1])[0] + ".json"
    fdir = path.split(path.dirname(args.exec_config))[-1]
    fpath = path.join(args.path, fdir, fname)
    assert not path.exists(fpath), "Save path already exists"
    if not os.path.exists(path.dirname(fpath)): os.makedirs(path.dirname(fpath))
    
    # Evaluate
    ep_rewards = np.zeros(args.num_eps)
    micro_steps = np.zeros(args.num_eps)
    macro_steps = np.zeros(args.num_eps)
    time_per_primitive = np.zeros(args.num_eps)

    for i in range(args.num_eps):
        step = 0
        reward = 0
        ep_time = 0
        prev_env = None
        for j, env in enumerate(env_cls):
            config = deepcopy(planner._get_config(j))
            curr_env = env(**config) if prev_env is None else env.load(prev_env, **config)
            
            st = time.time()
            for _ in range(curr_env._max_episode_steps):
                action = planner.plan(j, curr_env)
                obs, rew, done, info = curr_env.step(action)
                reward += rew
                step += 1
                if done: break

            ep_time += time.time() - st
            if not info["success"]: break
            
            prev_env = curr_env

        ep_rewards[i] = reward
        micro_steps[i] = step
        macro_steps[i] = j + 1
        time_per_primitive[i] = ep_time / (j + 1)
    
    # Log results
    results = {}
    results["return_mean"] = ep_rewards.mean()
    results["return_std"] = ep_rewards.std()
    results["return_min"] = ep_rewards.min()
    results["return_max"] = ep_rewards.max()
    results["return_min_percentage"] = (ep_rewards == ep_rewards.min()).sum() / (i+1)
    results["return_max_percentage"] = (ep_rewards == ep_rewards.max()).sum() / (i+1)
    results["frequency_mean"] = (1 / time_per_primitive).mean()
    results["frequency_std"] = (1 / time_per_primitive).std()
    results["primitives_mean"] = macro_steps.mean()
    results["primitives_std"] = macro_steps.std()
    results["steps_mean"] = micro_steps.mean()
    results["steps_std"] = micro_steps.std()
    print(f"Results for {path.split(args.exec_config)[1]} over {i+1} runs:")
    pprint.pprint(results, indent=4)
    with open(fpath, "w") as fs: json.dump(results, fs)
