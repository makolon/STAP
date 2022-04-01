from typing import Any, Sequence, Tuple

import numpy as np  # type: ignore
import torch  # type: ignore

from temporal_policies import agents, dynamics, utils
from temporal_policies.planners import base as planners


class CEMPlanner(planners.Planner):
    "Planner using the Improved Cross Entropy Method."""

    def __init__(
        self,
        policies: Sequence[agents.Agent],
        dynamics: dynamics.Dynamics,
        num_iterations: int = 8,
        num_samples: int = 128,
        num_elites: int = 16,
        standard_deviation: float = 1.0,
        keep_elites_fraction: float = 0.0,
        population_decay: float = 1.0,
        momentum: float = 0.0,
    ):
        """Constructs the iCEM planner.

        Args:
            policies: Policies used to evaluate trajecotries.
            dynamics: Dynamics model.
            num_iterations: Number of CEM iterations.
            num_samples: Number of samples to generate per CEM iteration.
            num_elites: Number of elites to select from population.
            standard_deviation: Used to sample random actions. Will be scaled by
                the action space.
            keep_elites_fraction: Fraction of elites to keep between iterations.
            population_decay: Population decay applied after each iteration.
            momentum: Momentum of distribution updates.
        """
        super().__init__(policies=policies, dynamics=dynamics)
        self._num_iterations = num_iterations
        self._num_samples = num_samples
        self._num_elites = max(2, min(num_elites, self.num_samples // 2))
        self._standard_deviation = standard_deviation

        # Improved CEM parameters.
        self._num_elites_to_keep = int(keep_elites_fraction * self.num_elites + 0.5)
        self._population_decay = population_decay
        self._momentum = momentum

    @property
    def num_iterations(self) -> int:
        """Number of CEM iterations."""
        return self._num_iterations

    @property
    def num_samples(self) -> int:
        """Number of samples to generate per CEM iteration."""
        return self._num_samples

    @property
    def num_elites(self) -> int:
        """Number of elites to select from population."""
        return self._num_elites

    @property
    def standard_deviation(self) -> float:
        """Unnormalized standard deviation for sampling random actions."""
        return self._standard_deviation

    @property
    def num_elites_to_keep(self) -> int:
        """Number of elites to keep between iterations."""
        return self._num_elites_to_keep

    @property
    def population_decay(self) -> float:
        """Population decay applied after each iteration."""
        return self._population_decay

    @property
    def momentum(self) -> float:
        """Momentum of distribution updates."""
        return self._momentum

    def _compute_initial_distribution(
        self, state: torch.Tensor, action_skeleton: Sequence[Tuple[int, Any]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Computes the initial popoulation distribution.

        The mean is generated by randomly rolling out a random trajectory using
        the dynamics model. The standard deviation is scaled according to the
        action space for each action in the skeleton.

        Args:
            state: Start state.
            action_skeleton: List of (idx_policy, policy_args) 2-tuples.

        Returns:
            2-tuple (mean, std).
        """
        T = len(action_skeleton)

        # Roll out a trajectory.
        states, _, _ = self.dynamics.rollout(state, action_skeleton)
        mean = states.numpy()

        # Scale the standard deviations by the action spaces.
        std = utils.null_tensor(self.dynamics.action_space, (T,))
        for t, (idx_policy, policy_args) in action_skeleton:
            a = self.policies[idx_policy].action_space
            std[t] = self.standard_deviation * 0.5 * (a.high - a.low)

        return mean, std

    def plan(
        self, observation: Any, action_skeleton: Sequence[Tuple[int, Any]]
    ) -> Tuple[np.ndarray, float]:
        """Runs `num_iterations` of CEM.

        Args:
            observation: Environment observation.
            action_skeleton: List of (idx_policy, policy_args) 2-tuples.

        Returns:
            2-tuple (actions [T, dim_actions], success_probability).
        """
        num_samples = self.num_samples

        state = self.dynamics.encode(observation).repeat(self.num_samples, -1)

        # Initialize distribution.
        mean, std = self._compute_initial_distribution(state[0], action_skeleton)
        value_fns = [
            self.policies[idx_policy].critic for idx_policy, _ in action_skeleton
        ]
        elites = np.empty((0, *mean.shape), dtype=mean.dtype)
        p_elites = np.empty(0)

        best_actions = None
        p_best_success = -float("inf")

        for _ in range(self.num_iterations):
            # Sample from distribution.
            samples = mean + std * np.randon.randn(*mean.shape)

            # Roll out trajectories.
            policies = [agents.ConstantAgent(action) for action in samples]
            states, actions, p_transitions = self.dynamics.rollout(
                state, action_skeleton, policies
            )

            # Evaluate trajectories.
            p_success = planners.evaluate_trajectory(
                value_fns, states, actions, p_transitions
            )

            # Append subset of elites from previous iteration.
            samples = np.concatenate(
                (samples, elites[: self.num_elites_to_keep]), axis=0
            )
            p_success = np.concatenate(
                (p_success, p_elites[: self.num_elites_to_keep]), axis=0
            )

            # Sort trajectories in descending order of success probability.
            idx_sorted = np.argsort(p_success)[::-1]
            samples = samples[idx_sorted]
            p_success = p_success[idx_sorted]

            # Compute elites.
            elites = samples[: self.num_elites]
            p_elites = p_success[: self.num_elites]

            # Track best action.
            if p_success[0] > p_best_success:
                p_best_success = p_success[0]
                best_actions = actions[:, idx_sorted[0]]

            # Update distribution.
            mean = self.momentum * mean + (1 - self.momentum) * elites.mean(axis=0)
            std = self.momentum * std + (1 - self.momentum) * elites.std(axis=0)

            # Decay population size.
            num_samples = int(self.population_decay * num_samples + 0.5)
            num_samples = max(num_samples, 2 * self.num_elites)

        return best_actions, p_best_success
