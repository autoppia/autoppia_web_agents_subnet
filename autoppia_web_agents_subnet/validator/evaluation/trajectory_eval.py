from __future__ import annotations

import asyncio
import copy
import time
from typing import Any

import bittensor as bt
from autoppia_iwa.src.data_generation.tasks.classes import Task
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.evaluation.concurrent_evaluator import ConcurrentEvaluator
from autoppia_iwa.src.evaluation.legacy.concurrent_config import EvaluatorConfig
from autoppia_iwa.src.web_agents.apified_harvester import ApifiedHarvester
from autoppia_iwa.src.web_agents.classes import TaskSolution

from autoppia_web_agents_subnet.utils.iwa_log_filter import enforce_iwa_log_filter
from autoppia_web_agents_subnet.validator.config import (
    SHOULD_RECORD_GIF,
    TASK_TIMEOUT_SECONDS,
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


async def _await_with_task_timeout(coro: Any, *, start_ts: float) -> Any:
    remaining = _remaining_task_timeout(start_ts)
    if remaining <= 0.0:
        raise TimeoutError
    return await asyncio.wait_for(coro, timeout=remaining)


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
            timeout=float(TASK_TIMEOUT_SECONDS),
            endpoint_path="/find_trayectory",
        )

        solution = await _await_with_task_timeout(trajectory_client.find_trayectory(task_for_eval), start_ts=start_ts)
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

        evaluator_config = EvaluatorConfig(
            should_record_gif=SHOULD_RECORD_GIF,
            enable_grouping_tasks=False,
            verbose_logging=False,
            debug_mode=False,
            browser_timeout=max(float(TASK_TIMEOUT_SECONDS) * 1000.0, 1000.0),
        )
        evaluator = ConcurrentEvaluator(web_project=project, config=evaluator_config)
        result = await _await_with_task_timeout(evaluator.evaluate_single_task_solution(task_for_eval, solution), start_ts=start_ts)

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

    except asyncio.TimeoutError:
        bt.logging.warning(
            f"[trajectory_eval] miner {uid} hard timeout for task {getattr(task, 'id', '?')}: {time.monotonic() - start_ts:.2f}s >= {TASK_TIMEOUT_SECONDS:.2f}s"
        )
    except Exception as exc:
        bt.logging.error(f"[trajectory_eval] miner {uid} evaluation error for task {getattr(task, 'id', '?')}: {exc}")

    elapsed = min(max(time.monotonic() - start_ts, 0.0), float(TASK_TIMEOUT_SECONDS))
    return 0.0, elapsed, solution


__all__ = ["evaluate_trajectory"]
