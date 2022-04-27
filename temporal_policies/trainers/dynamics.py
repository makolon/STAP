import pathlib
from typing import Any, Dict, List, Optional, Sequence, Type, Union

import numpy as np  # type: ignore
import torch  # type: ignore
import tqdm  # type: ignore

from temporal_policies import datasets, dynamics, processors
from temporal_policies.schedulers import DummyScheduler
from temporal_policies.trainers.agents import AgentTrainer
from temporal_policies.trainers.base import Trainer
from temporal_policies.trainers.utils import load as load_trainer
from temporal_policies.utils import configs, tensors
from temporal_policies.utils.typing import WrappedBatch, DynamicsBatch


class DynamicsTrainer(Trainer[dynamics.LatentDynamics, DynamicsBatch, WrappedBatch]):
    """Dynamics trainer."""

    def __init__(
        self,
        path: Union[str, pathlib.Path],
        dynamics: dynamics.LatentDynamics,
        dataset_class: Union[str, Type[torch.utils.data.IterableDataset]],
        dataset_kwargs: Dict[str, Any],
        processor_class: Union[
            str, Type[processors.Processor]
        ] = processors.IdentityProcessor,
        processor_kwargs: Dict[str, Any] = {},
        optimizer_class: Union[str, Type[torch.optim.Optimizer]] = torch.optim.Adam,
        optimizer_kwargs: Dict[str, Any] = {"lr": 1e-3},
        scheduler_class: Optional[
            Union[str, Type[torch.optim.lr_scheduler._LRScheduler]]
        ] = None,
        scheduler_kwargs: Dict[str, Any] = {},
        checkpoint: Optional[Union[str, pathlib.Path]] = None,
        policy_checkpoints: Optional[Sequence[Union[str, pathlib.Path]]] = None,
        agent_trainers: Optional[Sequence[AgentTrainer]] = None,
        device: str = "auto",
        num_train_steps: int = 100000,
        num_eval_steps: int = 100,
        eval_freq: int = 1000,
        log_freq: int = 100,
        profile_freq: Optional[int] = None,
        eval_metric: str = "l2_loss",
        num_data_workers: int = 0,
    ):
        """Prepares the dynamics trainer for training.

        Args:
            path: Output path.
            dataset_class: Dynamics model dataset class or class name.
            dataset_kwargs: Kwargs for dataset class.
            eval_dataset_kwargs: Kwargs for eval dataset.
            processor_class: Batch data processor calss.
            processor_kwargs: Kwargs for processor.
            optimizer_class: Dynamics model optimizer class.
            optimizer_kwargs: Kwargs for optimizer class.
            scheduler_class: Optional optimizer scheduler class.
            scheduler_kwargs: Kwargs for scheduler class.
            checkpoint: Optional path to trainer checkpoint.
            policy_checkpoints: List of policy checkpoints. Either this or
                agent_trainers must be specified.
            agent_trainers: List of agent trainers. Either this or
                policy_checkpoints must be specified.
            device: Torch device.
            num_train_steps: Number of steps to train.
            num_eval_steps: Number of steps per evaluation.
            eval_freq: Evaluation frequency.
            log_freq: Logging frequency.
            profile_freq: Profiling frequency.
            eval_metric: Metric to use for evaluation.
            num_data_workers: Number of workers to use for dataloader.
        """
        path = pathlib.Path(path) / "dynamics"

        # Get agent trainers.
        if agent_trainers is None:
            if policy_checkpoints is None:
                raise ValueError(
                    "One of agent_trainers or policy_checkpoints must be specified"
                )
            agent_trainers = []
            for policy_checkpoint in policy_checkpoints:
                policy_path = pathlib.Path(policy_checkpoint)
                if policy_path.is_file():
                    policy_path = policy_path.parent
                policy_checkpoint = policy_path / "train_checkpoint.pt"
                agent_trainer = load_trainer(checkpoint=policy_checkpoint)
                assert isinstance(agent_trainer, AgentTrainer)
                agent_trainers.append(agent_trainer)

        dataset_class = configs.get_class(dataset_class, datasets)
        dataset = dataset_class(
            [trainer.dataset for trainer in agent_trainers], **dataset_kwargs
        )
        eval_dataset = dataset_class(
            [trainer.eval_dataset for trainer in agent_trainers], **dataset_kwargs
        )

        processor_class = configs.get_class(processor_class, processors)
        processor = processor_class(
            dynamics.policies[0].observation_space,
            dynamics.action_space,
            **processor_kwargs
        )

        optimizer_class = configs.get_class(optimizer_class, torch.optim)
        optimizers = dynamics.create_optimizers(optimizer_class, optimizer_kwargs)

        if scheduler_class is None:
            scheduler_class = DummyScheduler
        else:
            scheduler_class = configs.get_class(
                scheduler_class, torch.optim.lr_scheduler
            )
        schedulers = {
            key: scheduler_class(optimizer, **scheduler_kwargs)
            for key, optimizer in optimizers.items()
        }

        super().__init__(
            path=path,
            model=dynamics,
            dataset=dataset,
            eval_dataset=eval_dataset,
            processor=processor,
            optimizers=optimizers,
            schedulers=schedulers,
            checkpoint=checkpoint,
            device=device,
            num_pretrain_steps=0,
            num_train_steps=num_train_steps,
            num_eval_steps=num_eval_steps,
            eval_freq=eval_freq,
            log_freq=log_freq,
            profile_freq=profile_freq,
            eval_metric=eval_metric,
            num_data_workers=num_data_workers,
        )

        self._eval_dataloader: Optional[torch.utils.data.DataLoader] = None

    @property
    def dynamics(self) -> dynamics.LatentDynamics:
        """Dynamics model being trained."""
        return self.model

    def process_batch(self, batch: WrappedBatch) -> DynamicsBatch:
        """Formats the replay buffer batch for the dynamics model.

        Args:
            batch: Replay buffer batch.

        Returns:
            Dict with (observation, idx_policy, action, next_observation).
        """
        dynamics_batch = DynamicsBatch(
            observation=batch["observation"],
            idx_policy=batch["idx_replay_buffer"],
            action=batch["action"],
            next_observation=batch["next_observation"],
        )
        return tensors.to(dynamics_batch, self.device)

    def evaluate(self) -> List[Dict[str, np.ndarray]]:
        """Evaluates the model.

        Returns:
            Eval metrics.
        """
        if self._eval_dataloader is None:
            self._eval_dataloader = self.create_dataloader(self.eval_dataset, 1)

        self.eval_mode()

        eval_metrics_list = []
        for eval_step, batch in enumerate(tqdm.tqdm(self._eval_dataloader)):
            if eval_step == self.num_eval_steps:
                break

            with torch.no_grad():
                batch = self.process_batch(batch)
                loss, metrics = self.dynamics.compute_loss(**batch)

            eval_metrics_list.append(metrics)

        self.train_mode()

        return eval_metrics_list
