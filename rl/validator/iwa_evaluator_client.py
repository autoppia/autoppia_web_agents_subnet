from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional

from ..envs.types import BrowserSnapshot, TaskSpec
from ..utils import load_object


@dataclass
class ValidatorFeedback:
    success: bool = False
    invalid: bool = False
    shaped_reward: float = 0.0
    milestones: List[str] = None

    def __post_init__(self) -> None:
        if self.milestones is None:
            self.milestones = []


class IWAValidator:
    """Thin adapter on top of the IWA evaluator client."""

    def __init__(
        self,
        config: Optional[Mapping[str, Any]] = None,
        client: Optional[Any] = None,
    ) -> None:
        self._config = dict(config or {})
        if client is None:
            client_cfg = dict(self._config.get("client") or {})
            client = self._load_client_from_config(client_cfg)
        self._client = client

    # ------------------------------------------------------------------
    # Task sampling helpers
    # ------------------------------------------------------------------
    def sample_task(self, options: Optional[Mapping[str, Any]] = None) -> TaskSpec:
        options = options or {}
        if hasattr(self._client, "sample_task"):
            task_dict = self._client.sample_task(options)
        else:
            task_pool: Iterable[Mapping[str, Any]] = self._config.get("task_pool") or []
            if not task_pool:
                raise RuntimeError("Task pool is empty; configure validator.task_pool or provide a client")
            task_dict = dict(task_pool[int(options.get("index", 0)) % len(task_pool)])
        return TaskSpec(
            task_id=str(task_dict.get("task_id")),
            demo_web_id=str(task_dict.get("demo_web_id")),
            goal=str(task_dict.get("goal")),
            metadata=dict(task_dict.get("metadata") or {}),
        )

    # ------------------------------------------------------------------
    # Evaluation helpers
    # ------------------------------------------------------------------
    def evaluate(
        self,
        task: TaskSpec,
        previous: Optional[BrowserSnapshot],
        current: BrowserSnapshot,
    ) -> ValidatorFeedback:
        if self._client is None:
            return ValidatorFeedback()

        if hasattr(self._client, "evaluate_snapshot"):
            result = self._client.evaluate_snapshot(task=task, previous=previous, current=current)
        elif hasattr(self._client, "evaluate"):
            result = self._client.evaluate(task=task, snapshot=current)
        else:
            raise AttributeError("Validator client must expose evaluate_snapshot or evaluate")

        if isinstance(result, ValidatorFeedback):
            return result

        # Attempt to coerce dictionaries or other simple structures
        success = bool(result.get("success")) if isinstance(result, Mapping) else False
        invalid = bool(result.get("invalid")) if isinstance(result, Mapping) else False
        shaped_reward = float(result.get("reward", 0.0)) if isinstance(result, Mapping) else 0.0
        milestones = list(result.get("milestones", [])) if isinstance(result, Mapping) else []
        return ValidatorFeedback(
            success=success,
            invalid=invalid,
            shaped_reward=shaped_reward,
            milestones=milestones,
        )

    def _load_client_from_config(self, client_cfg: Mapping[str, object]) -> Optional[Any]:
        if not client_cfg:
            return None

        entrypoint = client_cfg.get("class") or client_cfg.get("entrypoint")
        if not entrypoint:
            raise ValueError("Validator client configuration must include 'class' or 'entrypoint'")

        try:
            client_cls = load_object(str(entrypoint))
        except (ImportError, AttributeError) as exc:
            # Defer to task_pool based sampling if the heavy dependency is missing.
            from logging import getLogger

            getLogger(__name__).warning(
                "Failed to import validator client '%s': %s", entrypoint, exc
            )
            return None

        kwargs = dict(client_cfg.get("kwargs") or {})
        return client_cls(**kwargs)


__all__ = ["IWAValidator", "ValidatorFeedback"]
