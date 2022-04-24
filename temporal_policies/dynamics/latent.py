import pathlib
from typing import Any, Dict, Optional, Sequence, Tuple, Type, Union

import gym  # type: ignore
import torch  # type: ignore

from temporal_policies import agents, networks
from temporal_policies.dynamics.base import Dynamics
from temporal_policies.utils import configs


class LatentDynamics(Dynamics):
    """Base dynamics class."""

    def __init__(
        self,
        policies: Sequence[agents.RLAgent],
        network_class: Union[str, Type[networks.dynamics.Dynamics]],
        network_kwargs: Dict[str, Any],
        state_space: Optional[gym.spaces.Space] = None,
        action_space: Optional[gym.spaces.Space] = None,
        checkpoint: Optional[Union[str, pathlib.Path]] = None,
        device: str = "auto",
    ):
        """Initializes the dynamics model network, dataset, and optimizer.

        Args:
            policies: Ordered list of all policies.
            network_class: Dynamics model network class.
            network_kwargs: Kwargs for network class.
            state_space: Optional state space.
            action_space: Optional action space.
            checkpoint: Dynamics checkpoint.
            device: Torch device.
        """
        network_class = configs.get_class(network_class, networks)
        self._network = network_class(**network_kwargs)

        super().__init__(
            policies=policies,
            state_space=state_space,
            action_space=action_space,
            device=device,
        )

        self._steps = 0
        self._epochs = 0

        if checkpoint is not None:
            self.load(checkpoint, strict=True)

    @property
    def network(self) -> networks.dynamics.Dynamics:
        """Dynamics model network."""
        return self._network

    def load_state_dict(
        self, state_dict: Dict[str, Dict[str, torch.Tensor]], strict: bool = True
    ):
        """Loads the dynamics state dict.

        Args:
            state_dict: Torch state dict.
            strict: Ensure state_dict keys match networks exactly.
        """
        self.network.load_state_dict(state_dict["dynamics"], strict=strict)

    def state_dict(self) -> Dict[str, Dict[str, torch.Tensor]]:
        """Gets the dynamics state dict."""
        return {
            "dynamics": self.network.state_dict(),
        }

    def load(self, checkpoint: Union[str, pathlib.Path], strict: bool = True) -> None:
        """Loads the model from the given checkpoint.

        Args:
            checkpoint: Checkpoint path.
            strict: Make sure the state dict keys match.
        """
        state_dict = torch.load(checkpoint, map_location=self.device)
        self.load_state_dict(state_dict)

    def save(self, path: Union[str, pathlib.Path], name: str):
        """Saves a checkpoint of the model and the optimizers.

        Args:
            path: Directory of checkpoint.
            name: Name of checkpoint (saved as `path/name.pt`).
        """
        torch.save(self.state_dict(), pathlib.Path(path) / f"{name}.pt")

    def create_optimizers(
        self,
        optimizer_class: Type[torch.optim.Optimizer],
        optimizer_kwargs: Dict[str, Any],
    ) -> Dict[str, torch.optim.Optimizer]:
        """Creates the optimizers for training.

        This method is called by the Trainer class.

        Args:
            optimizer_class: Optimizer class.
            optimizer_kwargs: Kwargs for optimizer class.
        Returns:
            Dict of optimizers.
        """
        optimizers = {
            "dynamics": optimizer_class(self.network.parameters(), **optimizer_kwargs)
        }
        return optimizers

    def to(self, device: Union[str, torch.device]) -> Dynamics:
        """Transfers networks to device."""
        super().to(device)
        self.network.to(self.device)
        return self

    def train_mode(self) -> None:
        """Switches to training mode."""
        self.network.train()

    def eval_mode(self) -> None:
        """Switches to eval mode."""
        self.network.eval()

    def forward(
        self,
        state: torch.Tensor,
        idx_policy: torch.Tensor,
        action: Sequence[torch.Tensor],
        policy_args: Optional[Any] = None,
    ) -> torch.Tensor:
        """Predicts the next latent state given the current latent state and
        action.

        Args:
            state: Current latent state.
            idx_policy: Index of executed policy.
            action: Policy action.
            policy_args: Auxiliary policy arguments.

        Returns:
            Prediction of next latent state.
        """
        dz = self.network(state, idx_policy, action)
        return state + dz

    def compute_loss(
        self,
        observation: Any,
        idx_policy: torch.Tensor,
        action: Sequence[torch.Tensor],
        next_observation: torch.Tensor,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """Computes the L2 loss between the predicted next latent and the latent
        encoded from the given next observation.

        Args:
            observation: Common observation across all policies.
            idx_policy: Index of executed policy.
            action: Policy parameters.
            next_observation: Next observation.

        Returns:
            L2 loss.
        """
        # Predict next latent state.
        latent = self.encode(observation, idx_policy)
        next_latent_pred = self.forward(latent, idx_policy, action)

        # Encode next latent state.
        next_latent = self.encode(next_observation, idx_policy)

        # Compute L2 loss.
        l2_loss = torch.nn.functional.mse_loss(next_latent_pred, next_latent)

        metrics = {
            "l2_loss": l2_loss.item(),
        }

        return l2_loss, metrics

    def train_step(
        self,
        step: int,
        batch: Dict[str, Any],
        optimizers: Dict[str, torch.optim.Optimizer],
        schedulers: Dict[str, torch.optim.lr_scheduler._LRScheduler],
    ) -> Dict[str, float]:
        """Executes one training step.

        Args:
            step: Training step.
            batch: Training batch.
            optimizers: Optimizers created in `LatentDynamics.create_optimizers()`.
            schedulers: Schedulers with the same keys as `optimizers`.

        Returns:
            Computed loss.
        """
        loss, metrics = self.compute_loss(**batch)

        optimizers["dynamics"].zero_grad()
        loss.backward()
        optimizers["dynamics"].step()
        schedulers["dynamics"].step()

        return metrics
