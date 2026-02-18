from __future__ import annotations

import base64
import os
import time
from typing import Tuple, Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import bittensor as bt

from autoppia_web_agents_subnet.utils.iwa_log_filter import enforce_iwa_log_filter
from autoppia_web_agents_subnet.validator.config import (
    AGENT_STEP_TIMEOUT,
    MAXIMUM_EXECUTION_TIME,
    SHOULD_RECORD_GIF,
)

from autoppia_iwa.src.data_generation.tasks.classes import Task
from autoppia_iwa.src.evaluation.stateful_evaluator import AsyncStatefulEvaluator, ScoreDetails

try:
    from autoppia_iwa.src.web_agents.apified_iterative_agent import (  # type: ignore
        ApifiedWebAgent,
    )
except Exception:  # pragma: no cover - compatibility with older IWA layouts
    try:
        from autoppia_iwa.src.web_agents import (  # type: ignore
            ApifiedWebAgent,
        )
    except Exception:
        class ApifiedWebAgent:  # type: ignore[valid-type]
            def __init__(self, *_, **__):  # pragma: no cover
                raise RuntimeError(
                    "ApifiedWebAgent unavailable: configure OPENAI_API_KEY/LLM_PROVIDER in IWA "
                    "environment or install web_agents module."
                )


# Compatibility alias for legacy imports.
ApifiedWebCUA = ApifiedWebAgent
WebAgentClass = ApifiedWebAgent
from autoppia_iwa.src.web_agents.classes import TaskSolution, sanitize_snapshot_html


def _to_screenshot_b64(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw or None
    if isinstance(raw, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(raw)).decode("ascii")
    return None

try:
    from autoppia_iwa.src.evaluation.shared.utils import make_gif_from_screenshots
except Exception:
    def make_gif_from_screenshots(frames: list[str]) -> str | None:  # pragma: no cover - env-specific compatibility
        return None


def _augment_demo_web_url(url: str, *, web_agent_id: str, validator_id: str) -> str:
    """
    Demo websites persist `web_agent_id` / `validator_id` from URL query params
    into localStorage on initial page load. The IWA evaluator uses these ids when
    resetting/querying backend events, so we must ensure the navigated URL
    includes them.
    """
    if not url:
        return url
    try:
        split = urlsplit(url)
        q = dict(parse_qsl(split.query, keep_blank_values=True))
        q["X-WebAgent-Id"] = web_agent_id
        q["web_agent_id"] = web_agent_id
        q["X-Validator-Id"] = validator_id
        q["validator_id"] = validator_id
        return urlunsplit(split._replace(query=urlencode(q, doseq=True)))
    except Exception:
        return url


async def evaluate_with_stateful_cua(
    *,
    task: Task,
    uid: int,
    base_url: str,
    max_steps: int = 30,
) -> Tuple[float, float, TaskSolution]:
    """
    Evaluate a sandboxed miner agent using AsyncStatefulEvaluator + ApifiedWebAgent.
    """
    enforce_iwa_log_filter()

    # Avoid mutating a shared task object across miners/batches.
    try:
        task_for_eval = task.model_copy(deep=True)  # type: ignore[attr-defined]
    except Exception:
        try:
            import copy

            task_for_eval = copy.deepcopy(task)
        except Exception:
            task_for_eval = task

    # Demo websites persist attribution ids from URL query params into localStorage
    # on initial page load. If the ids are missing/mismatched, the backend event
    # queries will return empty and tasks will score 0.
    try:
        if not bool(getattr(task_for_eval, "is_web_real", False)):
            web_agent_id = str(uid)
            validator_id = os.getenv("VALIDATOR_ID", "custom_validator")
            original_url = str(getattr(task_for_eval, "url", "") or "")
            augmented_url = _augment_demo_web_url(
                original_url,
                web_agent_id=web_agent_id,
                validator_id=validator_id,
            )
            if augmented_url and augmented_url != original_url:
                setattr(task_for_eval, "url", augmented_url)
                bt.logging.debug(f"[stateful_cua_eval] augmented demo url for uid={uid} validator_id={validator_id}: {augmented_url}")
    except Exception:
        pass

    agent = ApifiedWebCUA(
        id=str(uid),
        name=f"miner-{uid}",
        base_url=base_url,
        timeout=AGENT_STEP_TIMEOUT,
    )
    evaluator = AsyncStatefulEvaluator(
        task=task_for_eval,
        web_agent_id=str(uid),
        should_record_gif=SHOULD_RECORD_GIF,
    )

    start_ts = time.time()
    final_score: ScoreDetails = ScoreDetails()

    try:
        step_index = 0
        step_result = await evaluator.reset()
        final_score = step_result.score
        history: list[dict[str, Any]] = []

        while step_index < max_steps and not bool(final_score.success):
            if time.time() - start_ts >= MAXIMUM_EXECUTION_TIME:
                bt.logging.warning(
                    f"[stateful_cua_eval] miner {uid} hard timeout reached for task {getattr(task, 'id', '?')}: "
                    f"{time.time() - start_ts:.2f}s >= {MAXIMUM_EXECUTION_TIME:.2f}s"
                )
                break

            snapshot = step_result.snapshot
            html = sanitize_snapshot_html(snapshot.html or "", str(uid))
            current_url = snapshot.url or task_for_eval.url

            try:
                # Send task WITH placeholders to agent - agent should return actions with placeholders
                screenshot = getattr(snapshot, "screenshot", None)
                if screenshot is None:
                    screenshot = getattr(snapshot, "screenshot_after", None)
                actions = await agent.act(
                    task=task_for_eval,  # Send task with placeholders, NOT replaced
                    snapshot_html=html,
                    screenshot=_to_screenshot_b64(screenshot),
                    url=current_url,
                    step_index=step_index,
                    history=history,
                )
            except Exception as exc:
                bt.logging.warning(f"[stateful_cua_eval] miner {uid} /act failed: {exc}")
                actions = []

            # Single-step semantics: execute at most one action per loop.
            action_executed = None
            if actions:
                action = actions[0]
                action_executed = action
                step_result = await evaluator.step(action)
            else:
                step_result = await evaluator.step(None)

            # Provide minimal action execution history back to the agent on the next step.
            try:
                exec_ok = True
                exec_err = None
                ar = step_result.action_result
                if ar is not None:
                    exec_ok = bool(getattr(ar, "successfully_executed", True))
                    exec_err = getattr(ar, "error", None)

                history.append(
                    {
                        "step": int(step_index),
                        "action": getattr(action_executed, "type", None) if action_executed is not None else "NOOP",
                        # Some agents use candidate_id for loop detection; we don't have it here.
                        "candidate_id": None,
                        "text": getattr(action_executed, "text", None) if action_executed is not None else None,
                        "exec_ok": exec_ok,
                        "error": exec_err,
                    }
                )
            except Exception:
                pass

            final_score = step_result.score
            step_index += 1

            if time.time() - start_ts >= MAXIMUM_EXECUTION_TIME:
                bt.logging.warning(
                    f"[stateful_cua_eval] miner {uid} hard timeout reached after step {step_index}: "
                    f"{time.time() - start_ts:.2f}s >= {MAXIMUM_EXECUTION_TIME:.2f}s"
                )
                break

    except Exception as exc:
        bt.logging.error(f"[stateful_cua_eval] miner {uid} evaluation error: {exc}")
        final_score = ScoreDetails()
    finally:
        # Snapshot minimal solution from the evaluator history for similarity penalties.
        try:
            history = list(getattr(evaluator, "history", []) or [])
            actions = []
            screenshot_frames: list[str] = []
            for h in history:
                try:
                    a = getattr(h, "action", None)
                    if a is not None:
                        actions.append(a)
                    if SHOULD_RECORD_GIF:
                        snap = getattr(h, "browser_snapshot", None)
                        shot = getattr(snap, "screenshot_after", None) if snap is not None else None
                        if isinstance(shot, str) and shot:
                            screenshot_frames.append(shot)
                except Exception:
                    continue
            recording_payload: Any = history
            if SHOULD_RECORD_GIF and screenshot_frames:
                try:
                    encoded = make_gif_from_screenshots(screenshot_frames)
                    if isinstance(encoded, (bytes, bytearray)):
                        gif_b64 = bytes(encoded).decode("utf-8")
                    elif isinstance(encoded, str):
                        gif_b64 = encoded
                    else:
                        gif_b64 = None
                    if gif_b64:
                        recording_payload = {
                            "execution_history": history,
                            "gif_recording": gif_b64,
                        }
                except Exception as exc:
                    bt.logging.warning(f"[stateful_cua_eval] failed to create GIF for miner {uid}: {exc}")
            solution = TaskSolution(
                task_id=str(getattr(task, "id", "")),
                actions=actions,
                web_agent_id=str(uid),
                recording=recording_payload,
            )
        except Exception:
            # If we cannot reconstruct a solution, append a minimal empty one
            solution = TaskSolution(task_id=str(getattr(task, "id", "")), actions=[], web_agent_id=str(uid))

        try:
            await evaluator.close()
        except Exception:
            pass

    score = max(0.0, min(final_score.raw_score, 1.0))
    elapsed = max(time.time() - start_ts, 0.0)
    return score, elapsed, solution


__all__ = ["evaluate_with_stateful_cua"]
