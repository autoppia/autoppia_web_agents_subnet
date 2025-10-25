from __future__ import annotations

"""Adapters that bridge the RL validator with the IWA concurrent evaluator."""

import logging
import random
from typing import Any, Mapping, Optional, Sequence

from ..envs.types import BrowserSnapshot, TaskSpec

logger = logging.getLogger(__name__)


class ConcurrentEvaluatorAdapter:
    """Thin wrapper around the IWA concurrent evaluator and task repositories."""

    def __init__(
        self,
        *,
        evaluator: Optional[Any] = None,
        task_repository: Optional[Any] = None,
        bootstrap_kwargs: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._bootstrap_kwargs = dict(bootstrap_kwargs or {})
        self._bootstrap = None
        if evaluator is None or task_repository is None:
            self._bootstrap = self._bootstrap_factory()
        self._evaluator = evaluator or self._resolve_evaluator()
        self._task_repository = task_repository or self._resolve_task_repository()

        if self._evaluator is None:
            raise RuntimeError(
                "ConcurrentEvaluatorAdapter could not locate an evaluator. "
                "Ensure autoppia_iwa is installed and AppBootstrap exposes one."
            )
        if self._task_repository is None:
            raise RuntimeError(
                "ConcurrentEvaluatorAdapter could not locate a task repository. "
                "Provide one explicitly or ensure AppBootstrap exposes it."
            )

    # ------------------------------------------------------------------
    # Task sampling
    # ------------------------------------------------------------------
    def sample_task(self, options: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        options = dict(options or {})
        index = options.get("index")

        repository = self._task_repository
        task = None

        if index is not None:
            for method_name in (
                "get_by_index",
                "get_task_by_index",
                "task_at",
                "__getitem__",
            ):
                method = getattr(repository, method_name, None)
                if callable(method):
                    try:
                        task = method(index)
                        break
                    except Exception:  # pragma: no cover - defensive path
                        continue

        if task is None:
            for method_name in ("sample_task", "sample", "random", "get_random_task"):
                method = getattr(repository, method_name, None)
                if callable(method):
                    try:
                        task = method(options)
                        break
                    except TypeError:
                        try:
                            task = method()
                            break
                        except Exception:  # pragma: no cover - defensive path
                            continue

        if task is None and hasattr(repository, "tasks"):
            tasks = getattr(repository, "tasks")
            try:
                tasks_list = list(tasks)
            except TypeError:  # pragma: no cover - defensive path
                tasks_list = []
            if tasks_list:
                index = int(index) % len(tasks_list) if index is not None else random.randrange(len(tasks_list))
                task = tasks_list[index]

        if task is None:
            raise RuntimeError("Task repository did not return a task")

        return self._task_to_dict(task)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    def evaluate_snapshot(
        self,
        *,
        task: TaskSpec,
        previous: Optional[BrowserSnapshot],
        current: BrowserSnapshot,
    ) -> Any:
        evaluator = self._evaluator
        candidates: Sequence[str] = (
            "evaluate_snapshot",
            "evaluate_state",
            "evaluate",
            "__call__",
        )
        task_obj = self._to_task_object(task)
        for name in candidates:
            method = getattr(evaluator, name, None)
            if callable(method):
                try:
                    if name == "__call__":
                        return method(task_obj, previous, current)
                    return method(task=task_obj, previous=previous, current=current)
                except TypeError:
                    try:
                        return method(task_obj, previous, current)
                    except Exception as exc:  # pragma: no cover - best effort
                        logger.debug("Evaluator %s failed via %s: %s", evaluator, name, exc)
                        continue
                except Exception as exc:  # pragma: no cover - best effort
                    logger.debug("Evaluator %s failed via %s: %s", evaluator, name, exc)
                    continue
        raise AttributeError(
            f"Evaluator {type(evaluator)!r} does not expose a callable evaluation method"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _bootstrap_factory(self):
        try:
            from autoppia_iwa.src.bootstrap import AppBootstrap  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("Failed to import AppBootstrap: %s", exc)
            return None
        return AppBootstrap(**self._bootstrap_kwargs)

    def _resolve_evaluator(self) -> Optional[Any]:
        bootstrap = self._bootstrap
        if bootstrap is None:
            return None
        for attr in ("concurrent_evaluator", "evaluator", "benchmark_evaluator"):
            evaluator = getattr(bootstrap, attr, None)
            if evaluator is not None:
                return evaluator
        container = getattr(bootstrap, "di_container", None)
        if container is not None:
            for key in (
                "concurrent_evaluator",
                "benchmark_evaluator",
                "validator_evaluator",
            ):
                try:
                    evaluator = container.resolve(key)  # type: ignore[attr-defined]
                    if evaluator is not None:
                        return evaluator
                except Exception:  # pragma: no cover - optional dependency
                    continue
        return None

    def _resolve_task_repository(self) -> Optional[Any]:
        bootstrap = self._bootstrap
        if bootstrap is None:
            return None
        for attr in (
            "task_repository",
            "benchmark_task_repository",
            "tasks_repository",
            "benchmark_dataset",
        ):
            repository = getattr(bootstrap, attr, None)
            if repository is not None:
                return repository
        container = getattr(bootstrap, "di_container", None)
        if container is not None:
            for key in (
                "task_repository",
                "benchmark_task_repository",
                "tasks_repository",
            ):
                try:
                    repository = container.resolve(key)  # type: ignore[attr-defined]
                    if repository is not None:
                        return repository
                except Exception:  # pragma: no cover - optional dependency
                    continue
        return None

    @staticmethod
    def _task_to_dict(task: Any) -> Mapping[str, Any]:
        task_id = getattr(task, "id", None) or getattr(task, "task_id", None) or ""
        demo_web_id = getattr(task, "demo_web_id", None) or getattr(task, "project_id", None) or ""
        goal = getattr(task, "prompt", None) or getattr(task, "goal", None) or ""
        metadata = getattr(task, "metadata", None) or getattr(task, "extra", None) or {}
        return {
            "task_id": str(task_id),
            "demo_web_id": str(demo_web_id),
            "goal": str(goal),
            "metadata": dict(metadata) if isinstance(metadata, Mapping) else {},
        }

    def _to_task_object(self, task: TaskSpec) -> Any:
        try:
            from autoppia_iwa.src.data_generation.domain.classes import Task as IWATask  # type: ignore
        except Exception:  # pragma: no cover - optional dependency
            return task

        try:
            return IWATask(
                id=task.task_id,
                prompt=task.goal,
                demo_web_id=task.demo_web_id,
                metadata=task.metadata,
            )
        except TypeError:
            try:
                return IWATask(
                    task_id=task.task_id,
                    goal=task.goal,
                    demo_web_id=task.demo_web_id,
                    metadata=task.metadata,
                )
            except Exception:  # pragma: no cover - fallback to TaskSpec
                return task


__all__ = ["ConcurrentEvaluatorAdapter"]

