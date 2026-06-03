from __future__ import annotations

import asyncio
import copy
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import bittensor as bt
from autoppia_iwa.src.data_generation.tasks.classes import Task
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.evaluation.concurrent_evaluator import ConcurrentEvaluator
from autoppia_iwa.src.evaluation.legacy.concurrent_config import EvaluatorConfig
from autoppia_iwa.src.web_agents.apified_harvester import ApifiedHarvester
from autoppia_iwa.src.web_agents.classes import TaskSolution

from autoppia_web_agents_subnet.utils.iwa_log_filter import enforce_iwa_log_filter
from autoppia_web_agents_subnet.validator.config import (
    FIND_TRAJECTORY_TIMEOUT_SECONDS,
    SHOULD_RECORD_GIF,
    TASK_TIMEOUT_SECONDS,
    TRAJECTORY_ACTION_TIMEOUT_SECONDS,
    TRAJECTORY_REPLAY_TIMEOUT_SECONDS,
)


def _clone_task(task: Task) -> Task:
    try:
        return task.model_copy(deep=True)  # type: ignore[attr-defined]
    except Exception:
        try:
            return copy.deepcopy(task)
        except Exception:
            return task


def _empty_solution(task: Task, uid: int) -> TaskSolution:
    return TaskSolution(task_id=str(getattr(task, "id", "")), actions=[], web_agent_id=str(uid))


def _remaining_task_timeout(start_ts: float) -> float:
    return max(float(TASK_TIMEOUT_SECONDS) - float(time.monotonic() - start_ts), 0.0)


class TrajectoryPhaseTimeout(asyncio.TimeoutError):
    def __init__(self, phase: str, timeout: float):
        super().__init__(f"{phase} timed out after {timeout:.2f}s")
        self.phase = phase
        self.timeout = timeout


def _consume_cancelled_task(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except BaseException:
        pass


async def _await_with_hard_timeout(coro: Any, *, timeout: float, phase: str) -> Any:
    if timeout <= 0.0:
        raise TrajectoryPhaseTimeout(phase, timeout)
    task = asyncio.create_task(coro)
    done, pending = await asyncio.wait({task}, timeout=timeout)
    if task in done:
        return task.result()
    for pending_task in pending:
        pending_task.cancel()
        pending_task.add_done_callback(_consume_cancelled_task)
    raise TrajectoryPhaseTimeout(phase, timeout)


def _extract_seed(url: str | None) -> str | None:
    if not url:
        return None
    try:
        values = parse_qs(urlparse(url).query).get("seed") or []
        seed = str(values[0]).strip() if values else ""
        return seed or None
    except Exception:
        return None


def _url_with_seed(url: str | None, seed: str | None) -> str | None:
    if not url or not seed:
        return url
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return url
        query = parse_qs(parsed.query, keep_blank_values=True)
        if query.get("seed") == [str(seed)]:
            return url
        query["seed"] = [str(seed)]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
    except Exception:
        return url


def _normalize_navigation_seeds(solution: TaskSolution, task: Task) -> None:
    seed = _extract_seed(getattr(task, "url", None))
    if not seed:
        return

    updated = 0
    for action in getattr(solution, "actions", []) or []:
        if action.__class__.__name__ != "NavigateAction":
            continue
        current_url = getattr(action, "url", None)
        next_url = _url_with_seed(current_url, seed)
        if next_url and next_url != current_url:
            setattr(action, "url", next_url)
            updated += 1

    if updated:
        bt.logging.info(
            f"[trajectory_eval] normalized seed={seed} on {updated} NavigateAction URL(s) for task {getattr(task, 'id', '?')}"
        )


async def _await_find_trajectory(coro: Any, *, start_ts: float) -> Any:
    remaining_task_timeout = _remaining_task_timeout(start_ts)
    timeout = min(float(FIND_TRAJECTORY_TIMEOUT_SECONDS), remaining_task_timeout)
    return await _await_with_hard_timeout(coro, timeout=timeout, phase="find_trayectory")


async def _await_replay(coro: Any, *, start_ts: float) -> Any:
    remaining_task_timeout = _remaining_task_timeout(start_ts)
    timeout = min(float(TRAJECTORY_REPLAY_TIMEOUT_SECONDS), remaining_task_timeout)
    return await _await_with_hard_timeout(coro, timeout=timeout, phase="trajectory_replay")


def _exception_detail(exc: Exception) -> str:
    parts = [f"{type(exc).__name__}: {exc}"]
    for attr in ("status", "message", "url", "path", "reason"):
        value = getattr(exc, attr, None)
        if value:
            parts.append(f"{attr}={value}")
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        parts.append(f"cause={type(cause).__name__}: {cause}")
        for attr in ("status", "message", "url", "path", "reason"):
            value = getattr(cause, attr, None)
            if value:
                parts.append(f"cause_{attr}={value}")
    return " | ".join(parts)


async def evaluate_trajectory(
    *,
    task: Task,
    project: WebProject,
    uid: int,
    base_url: str,
    max_tools: int = 30,
) -> tuple[float, float, TaskSolution]:
    """
    Evaluate a miner-produced trajectory.

    The miner receives the task once via /find_trayectory and returns a canonical
    trajectory: list[tool_call]. IWA converts that trajectory to replay actions and
    ConcurrentEvaluator replays it against the task tests.
    """
    enforce_iwa_log_filter()
    start_ts = time.monotonic()
    task_for_eval = _clone_task(task)
    solution = _empty_solution(task_for_eval, uid)

    try:
        trajectory_client = ApifiedHarvester(
            id=str(uid),
            name=f"miner-{uid}",
            base_url=base_url,
            timeout=float(FIND_TRAJECTORY_TIMEOUT_SECONDS),
            endpoint_path="/find_trayectory",
        )

        solution = await _await_find_trajectory(trajectory_client.find_trayectory(task_for_eval), start_ts=start_ts)
        solution.task_id = str(getattr(task_for_eval, "id", getattr(solution, "task_id", "")))
        solution.web_agent_id = str(uid)

        replay_actions = list(getattr(solution, "actions", []) or [])
        if max_tools is not None and int(max_tools) > 0 and len(replay_actions) > int(max_tools):
            bt.logging.warning(
                f"[trajectory_eval] miner {uid} returned {len(replay_actions)} trajectory tools for task {getattr(task_for_eval, 'id', '?')}; truncating to {int(max_tools)}"
            )
            solution.actions = replay_actions[: int(max_tools)]

        solution.replace_credentials(str(uid))
        solution.actions = solution.replace_web_agent_id()
        _normalize_navigation_seeds(solution, task_for_eval)

        evaluator_config = EvaluatorConfig(
            should_record_gif=SHOULD_RECORD_GIF,
            enable_grouping_tasks=False,
            verbose_logging=False,
            debug_mode=False,
            browser_timeout=max(float(TRAJECTORY_ACTION_TIMEOUT_SECONDS) * 1000.0, 1000.0),
        )
        evaluator = ConcurrentEvaluator(web_project=project, config=evaluator_config)
        result = await _await_replay(evaluator.evaluate_single_task_solution(task_for_eval, solution), start_ts=start_ts)

        recording_payload: dict[str, Any] = {}
        execution_history = getattr(result, "execution_history", None)
        if isinstance(execution_history, list):
            recording_payload["execution_history"] = execution_history
        gif_recording = getattr(result, "gif_recording", None)
        if gif_recording:
            recording_payload["gif_recording"] = gif_recording
        if recording_payload:
            solution.recording = recording_payload

        raw_score = getattr(result, "raw_score", None)
        final_score = getattr(result, "final_score", None)
        score_value = raw_score if raw_score is not None else final_score
        score = max(0.0, min(float(score_value or 0.0), 1.0))
        elapsed = min(max(time.monotonic() - start_ts, 0.0), float(TASK_TIMEOUT_SECONDS))
        return score, elapsed, solution

    except asyncio.TimeoutError as exc:
        phase = getattr(exc, "phase", "task")
        phase_timeout = getattr(exc, "timeout", None)
        phase_msg = f" phase={phase}"
        if phase_timeout is not None:
            phase_msg += f" phase_timeout={float(phase_timeout):.2f}s"
        bt.logging.warning(
            f"[trajectory_eval] miner {uid} timeout for task {getattr(task, 'id', '?')}:{phase_msg} elapsed={time.monotonic() - start_ts:.2f}s find_trayectory_timeout={FIND_TRAJECTORY_TIMEOUT_SECONDS:.2f}s replay_timeout={TRAJECTORY_REPLAY_TIMEOUT_SECONDS:.2f}s action_timeout={TRAJECTORY_ACTION_TIMEOUT_SECONDS:.2f}s task_timeout={TASK_TIMEOUT_SECONDS:.2f}s"
        )
    except Exception as exc:
        bt.logging.error(
            f"[trajectory_eval] miner {uid} evaluation error for task {getattr(task, 'id', '?')} base_url={base_url}: {_exception_detail(exc)}"
        )

    elapsed = min(max(time.monotonic() - start_ts, 0.0), float(TASK_TIMEOUT_SECONDS))
    return 0.0, elapsed, solution


__all__ = ["evaluate_trajectory"]
