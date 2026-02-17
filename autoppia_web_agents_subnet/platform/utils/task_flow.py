from __future__ import annotations

from typing import Any, Dict, List, Optional
import re
from datetime import datetime, timezone

import httpx

import bittensor as bt
from autoppia_web_agents_subnet.platform import models as iwa_models
from autoppia_web_agents_subnet.platform import client as iwa_main
from .iwa_core import (
    log_iwap_phase,
    log_gif_event,
    extract_gif_bytes,
)


def _normalize_action_payload(action: Any) -> Dict[str, Any]:
    """
    Normalize heterogeneous action objects into a JSON-serializable dict.

    Supports:
    - Pydantic models (model_dump)
    - Plain dicts
    - Objects with __dict__ (e.g., dataclasses or custom action classes)

    Also flattens nested "action" or "attributes" payloads when present,
    so stored actions are reproducible (selector/text/url/x/y, etc.).
    """
    action_dict: Dict[str, Any] = {}

    if action is None:
        return {"type": "unknown"}

    if isinstance(action, dict):
        action_dict = dict(action)
    elif hasattr(action, "model_dump"):
        try:
            action_dict = action.model_dump(mode="json", exclude_none=True)
        except Exception:
            try:
                action_dict = dict(action)
            except Exception:
                action_dict = {"type": getattr(action, "type", "unknown")}
    elif hasattr(action, "__dict__"):
        try:
            action_dict = {k: v for k, v in vars(action).items() if not k.startswith("_")}
        except Exception:
            action_dict = {"type": getattr(action, "type", "unknown")}
    else:
        action_dict = {"type": getattr(action, "type", "unknown")}

    # Flatten nested "action" payloads if present (legacy formats)
    nested_action = action_dict.get("action")
    if isinstance(nested_action, dict):
        merged = dict(nested_action)
        for k, v in action_dict.items():
            if k != "action" and k not in merged:
                merged[k] = v
        action_dict = merged

    # Flatten "attributes" into top-level if present (common miner formats)
    attrs = action_dict.get("attributes")
    if isinstance(attrs, dict):
        for k, v in attrs.items():
            if k not in action_dict or action_dict.get(k) in (None, "", [], {}):
                action_dict[k] = v

    # If the payload is still too thin, try to pull common fields directly
    # from the object (helps when model_dump returns only type/attributes).
    for key in ("selector", "text", "value", "url", "x", "y", "button", "keys", "delta", "go_back", "go_forward"):
        if key not in action_dict:
            try:
                val = getattr(action, key, None)
            except Exception:
                val = None
            if val is not None:
                action_dict[key] = val

    # Ensure selector is JSON-serializable if it's a model
    sel = action_dict.get("selector")
    if hasattr(sel, "model_dump"):
        try:
            action_dict["selector"] = sel.model_dump(mode="json", exclude_none=True)
        except Exception:
            pass

    # Drop empty attributes if we already have useful fields
    if action_dict.get("attributes") == {}:
        if len(action_dict) > 2 or (len(action_dict) == 2 and "type" in action_dict):
            action_dict.pop("attributes", None)

    return action_dict


def _is_thin_action(action_dict: Dict[str, Any]) -> bool:
    """Detect actions that only contain type/empty attributes (no reproducible details)."""
    if not isinstance(action_dict, dict):
        return True
    attrs = action_dict.get("attributes")
    if isinstance(attrs, dict) and attrs:
        return False
    for k, v in action_dict.items():
        if k in ("type", "attributes"):
            continue
        if v not in (None, "", [], {}):
            return False
    return True


def _normalize_llm_usage(raw: Any) -> Optional[List[Dict[str, Any]]]:
    """Normalize llm_usage to list of {provider, model, tokens, cost} dicts."""
    if not isinstance(raw, list):
        return None
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        provider = item.get("provider")
        model = item.get("model")
        tokens = item.get("tokens")
        cost = item.get("cost")
        if tokens is not None:
            try:
                tokens = int(tokens)
            except Exception:
                tokens = None
        if cost is not None:
            try:
                cost = float(cost)
            except Exception:
                cost = None
        if provider is None and model is None and tokens is None and cost is None:
            continue
        out.append(
            {
                "provider": provider,
                "model": model,
                "tokens": tokens,
                "cost": cost,
            }
        )
    return out or None


def _extract_season_round(validator_round_id: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    if not validator_round_id:
        return None, None
    match = re.match(r"validator_round_(\d+)_(\d+)_", str(validator_round_id))
    if not match:
        return None, None
    try:
        return int(match.group(1)), int(match.group(2))
    except Exception:
        return None, None


def _summarize_llm_usage(llm_usage: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    if not llm_usage:
        return None
    total_tokens = 0
    total_cost = 0.0
    providers: Dict[str, float] = {}
    for item in llm_usage:
        if not isinstance(item, dict):
            continue
        tokens = item.get("tokens")
        cost = item.get("cost")
        provider = item.get("provider")
        if isinstance(tokens, (int, float)):
            total_tokens += int(tokens)
        if isinstance(cost, (int, float)):
            total_cost += float(cost)
            if isinstance(provider, str) and provider:
                providers[provider] = providers.get(provider, 0.0) + float(cost)
    return {
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "providers": providers,
    }


def _build_execution_steps(execution_history: Any) -> List[Dict[str, Any]]:
    if not isinstance(execution_history, list):
        return []
    steps: List[Dict[str, Any]] = []
    for idx, item in enumerate(execution_history):
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if isinstance(action, dict):
            action = _normalize_action_payload(action)
        snapshot = item.get("browser_snapshot") or item.get("observation")
        timestamp = None
        if isinstance(snapshot, dict):
            timestamp = snapshot.get("timestamp") or snapshot.get("time")
        exec_time = item.get("execution_time")
        exec_time_ms = None
        if isinstance(exec_time, (int, float)):
            exec_time_ms = int(exec_time * 1000)
        step = {
            "step_index": idx,
            "timestamp": timestamp,
            "agent_call": item.get("agent_call"),
            "llm_usage": item.get("llm_usage"),
            "action": action,
            "observation": snapshot,
            "success": item.get("successfully_executed", item.get("success")),
            "error": item.get("error"),
            "execution_time_ms": exec_time_ms,
        }
        steps.append(step)
    return steps


def _sanitize_for_json(obj: Any, *, _depth: int = 0) -> Any:
    """Best-effort conversion to JSON-serializable data."""
    if _depth > 8:
        return str(obj)
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_for_json(item, _depth=_depth + 1) for item in obj]
    if isinstance(obj, dict):
        cleaned: Dict[str, Any] = {}
        for key, value in obj.items():
            if callable(value):
                continue
            cleaned[str(key)] = _sanitize_for_json(value, _depth=_depth + 1)
        return cleaned
    if callable(obj):
        return str(obj)
    for attr in ("model_dump", "dict"):
        try:
            method = getattr(obj, attr, None)
            if callable(method):
                return _sanitize_for_json(method(), _depth=_depth + 1)
        except Exception:
            pass
    try:
        return _sanitize_for_json(vars(obj), _depth=_depth + 1)
    except Exception:
        return str(obj)


def _build_task_log_payload(
    *,
    task_payload: Any,
    agent_run: Any,
    miner_uid: int,
    eval_score: float,
    reward: float,
    exec_time: float,
    evaluation_meta: Dict[str, Any],
    validator_round_id: Optional[str],
    validator_uid: Optional[int],
) -> Dict[str, Any]:
    execution_history = evaluation_meta.get("execution_history", []) if isinstance(evaluation_meta, dict) else []
    steps = _build_execution_steps(execution_history)
    steps_success = len([s for s in steps if s.get("success")])
    llm_usage = _normalize_llm_usage(evaluation_meta.get("llm_usage")) if isinstance(evaluation_meta, dict) else None
    season, round_in_season = _extract_season_round(validator_round_id)
    created_at = datetime.now(timezone.utc).isoformat()
    task_prompt = getattr(task_payload, "prompt", None)
    task_url = getattr(task_payload, "url", None)
    use_case = getattr(task_payload, "use_case", None)
    website = getattr(task_payload, "web_project_id", None) or getattr(task_payload, "web", None)

    payload = {
        "schema_version": "1.0",
        "task_id": getattr(task_payload, "task_id", None),
        "agent_run_id": getattr(agent_run, "agent_run_id", None),
        "validator_round_id": validator_round_id,
        "season": season,
        "round_in_season": round_in_season,
        "miner_uid": miner_uid,
        "validator_uid": validator_uid,
        "created_at": created_at,
        "task": {
            "prompt": task_prompt,
            "url": task_url,
            "website": website,
            "use_case": use_case,
        },
        "summary": {
            "status": "success" if eval_score and eval_score > 0 else "fail",
            "reward": float(reward),
            "eval_score": float(eval_score),
            "eval_time_sec": float(exec_time),
            "steps_total": len(steps),
            "steps_success": steps_success,
        },
        "steps": steps,
        "raw": {
            "execution_history": execution_history if isinstance(execution_history, list) else [],
            "llm_usage": llm_usage or [],
        },
    }
    request_payload = {
        "task_id": payload.get("task_id"),
        "agent_run_id": payload.get("agent_run_id"),
        "validator_round_id": payload.get("validator_round_id"),
        "season": payload.get("season"),
        "round_in_season": payload.get("round_in_season"),
        "miner_uid": payload.get("miner_uid"),
        "validator_uid": payload.get("validator_uid"),
        "payload": payload,
    }
    return _sanitize_for_json(request_payload)


def prepare_evaluation_payload(
    *,
    ctx,
    task_payload,
    agent_run,
    miner_uid: int,
    solution,
    eval_score: float,
    evaluation_meta: Dict[str, Any],
    test_results_data: List[Any],
    exec_time: float,
    reward: float,
) -> Dict[str, Any]:
    """
    Prepare a single evaluation payload for submission to IWAP.

    This function extracts the common logic for building task, task_solution,
    and evaluation payloads from the raw evaluation data.

    Args:
        ctx: Validator context
        task_payload: IWAP task payload
        agent_run: Agent run model
        miner_uid: Miner UID
        solution: Task solution from miner
        eval_score: Evaluation score
        evaluation_meta: Evaluation metadata dict
        test_results_data: Test results list
        exec_time: Execution time
        reward: Calculated reward value
    Returns:
        Dict containing task, task_solution, evaluation, and evaluation_result
    """
    validator_hotkey = ctx.wallet.hotkey.ss58_address

    miner_hotkey = None
    try:
        miner_hotkey = ctx.metagraph.hotkeys[miner_uid]
    except Exception:
        miner_hotkey = None

    # Handle None solution (miner didn't respond)
    if solution is None:
        raw_actions = []
    else:
        raw_actions = getattr(solution, "actions", []) or []

    actions_payload: List[Dict[str, Any]] = []
    for action in raw_actions:
        actions_payload.append(_normalize_action_payload(action))

    # If actions are empty/thin, try to derive them from execution_history.
    history = evaluation_meta.get("execution_history") if isinstance(evaluation_meta, dict) else None
    derived_actions: List[Dict[str, Any]] = []
    if isinstance(history, list):
        for item in history:
            if isinstance(item, dict):
                hist_action = item.get("action")
                if isinstance(hist_action, dict):
                    derived_actions.append(_normalize_action_payload(hist_action))
    if derived_actions and (not actions_payload or all(_is_thin_action(a) for a in actions_payload)):
        actions_payload = derived_actions

    # Use the full task_id from IWAP payload for generating IDs
    iwap_task_id = task_payload.task_id
    task_solution_id = iwa_main.generate_task_solution_id(iwap_task_id, miner_uid)
    evaluation_id = iwa_main.generate_evaluation_id(iwap_task_id, miner_uid)

    # Ensure evaluation_meta is a dict
    if not isinstance(evaluation_meta, dict):
        evaluation_meta = {}
    evaluation_metadata = dict(evaluation_meta)

    # Remove fields that are already in specific EvaluationResultIWAP fields
    evaluation_metadata.pop("gif_recording", None)
    evaluation_metadata.pop("final_score", None)
    evaluation_metadata.pop("eval_score", None)
    evaluation_metadata.pop("reward", None)
    evaluation_metadata.pop("version_ok", None)
    evaluation_metadata.pop("notes", None)
    evaluation_metadata.pop("error_message", None)
    evaluation_metadata.pop("feedback", None)
    evaluation_metadata.pop("execution_history", None)
    evaluation_metadata.pop("test_results", None)
    evaluation_metadata.pop("raw_score", None)
    evaluation_metadata.pop("evaluation_time", None)
    evaluation_metadata.pop("stats", None)

    # Mark timeout in metadata if execution time reaches TIMEOUT
    try:
        from autoppia_web_agents_subnet.validator.config import TIMEOUT

        is_timeout = False
        if exec_time is not None and TIMEOUT is not None:
            is_timeout = float(exec_time) >= float(TIMEOUT)
        if evaluation_metadata.get("timeout") is True:
            is_timeout = True
        if is_timeout:
            evaluation_metadata["timeout"] = True
    except Exception:
        pass

    recording_payload = getattr(solution, "recording", None) if solution is not None else None
    if isinstance(recording_payload, dict):
        recording_payload = dict(recording_payload)
        # Avoid logging/storing base64 GIF in task_solution payload.
        recording_payload.pop("gif_recording", None)

    task_solution_payload = iwa_models.TaskSolutionIWAP(
        solution_id=task_solution_id,
        task_id=iwap_task_id,
        agent_run_id=agent_run.agent_run_id,
        validator_round_id=ctx.current_round_id,
        validator_uid=int(ctx.uid),
        validator_hotkey=validator_hotkey,
        miner_uid=miner_uid,
        miner_hotkey=miner_hotkey,
        actions=actions_payload,
        recording=recording_payload,
    )

    # Build llm_usage for backend (evaluation_llm_usage table)
    llm_usage: Optional[List[Dict[str, Any]]] = _normalize_llm_usage(evaluation_meta.get("llm_usage"))

    evaluation_result_payload = iwa_models.EvaluationResultIWAP(
        evaluation_id=evaluation_id,
        validator_round_id=ctx.current_round_id,
        agent_run_id=agent_run.agent_run_id,
        task_id=task_payload.task_id,
        task_solution_id=task_solution_id,
        validator_uid=int(ctx.uid),
        validator_hotkey=validator_hotkey,  # Required field
        miner_uid=miner_uid,
        eval_score=eval_score,
        reward=reward,
        test_results=test_results_data or [],
        execution_history=evaluation_meta.get("execution_history", []),
        feedback=evaluation_meta.get("feedback"),
        evaluation_time=evaluation_meta.get("evaluation_time", exec_time),
        stats=evaluation_meta.get("stats"),
        gif_recording=None,
        metadata=evaluation_metadata,
        llm_usage=llm_usage,
    )

    return {
        "task": task_payload.to_payload(),
        "task_solution": task_solution_payload.to_payload(),
        "evaluation": evaluation_result_payload.to_payload(),
        "evaluation_result": evaluation_result_payload.to_payload(),
    }


async def submit_task_results(
    ctx,
    *,
    task_item,
    task_solutions,
    eval_scores,
    test_results_list,
    evaluation_results,
    execution_times,
    rewards: List[float],
) -> None:
    if not ctx.current_round_id or not ctx.current_round_tasks:
        return

    task = task_item.task
    base_task_id = getattr(task, "id", None)
    if base_task_id is None:
        return

    # Build the full task_id that matches what was stored in IWAP
    # The task_id in IWAP includes the validator_round_id prefix
    full_task_id = f"{ctx.current_round_id}_{base_task_id}"

    # Try to get task_payload using the full task_id first
    task_payload = ctx.current_round_tasks.get(full_task_id)
    # Fallback to base_task_id for backward compatibility
    if task_payload is None:
        task_payload = ctx.current_round_tasks.get(base_task_id)
    if task_payload is None:
        return

    try:
        if not getattr(task_payload, "is_web_real", False):
            project_name = getattr(task_item.project, "name", None)
            if project_name:
                task_payload.url = str(project_name)
    except Exception:
        pass

    validator_hotkey = ctx.wallet.hotkey.ss58_address

    try:
        from autoppia_web_agents_subnet.validator.config import TIMEOUT
    except ImportError:
        TIMEOUT = 180.0

    # CRITICAL: Always create evaluations for ALL miners that have agent_runs
    # active_miner_uids should match current_agent_runs, but iterate over agent_runs to be safe
    # Each miner with agent_run MUST have a TaskSolution and Evaluation for each task

    for idx, miner_uid in enumerate(ctx.active_miner_uids):
        # Get agent_run - if it doesn't exist, skip (shouldn't happen, but handle gracefully)
        agent_run = ctx.current_agent_runs.get(miner_uid)
        if agent_run is None:
            bt.logging.warning(f"⚠️ Miner {miner_uid} is in active_miner_uids but has no agent_run. This should not happen - agent_run should be created during handshake.")
            continue

        # Get solution and evaluation data for this miner
        # task_solutions, eval_scores, etc. are aligned with active_miner_uids by index
        if idx < len(task_solutions):
            solution = task_solutions[idx]
            eval_score = float(eval_scores[idx]) if idx < len(eval_scores) else 0.0
            evaluation_meta = evaluation_results[idx] if idx < len(evaluation_results) else {}
            test_results_data = test_results_list[idx] if idx < len(test_results_list) else []
            exec_time = float(execution_times[idx]) if idx < len(execution_times) else TIMEOUT
        else:
            # Shouldn't happen - task_solutions should have same length as active_miner_uids
            # But handle gracefully: create empty evaluation
            solution = None
            eval_score = 0.0
            evaluation_meta = {}
            test_results_data = []
            exec_time = TIMEOUT

        miner_hotkey = None
        try:
            miner_hotkey = ctx.metagraph.hotkeys[miner_uid]
        except Exception:
            miner_hotkey = None

        # Handle None solution (miner didn't respond)
        if solution is None:
            raw_actions = []
        else:
            raw_actions = getattr(solution, "actions", []) or []

        actions_payload: List[Dict[str, Any]] = []
        log_iwap_phase(
            "Phase 4",
            f"🔧 Converting {len(raw_actions)} actions for miner_uid={miner_uid}",
            level="debug",
        )

        for action_idx, action in enumerate(raw_actions):
            action_dict = _normalize_action_payload(action)
            actions_payload.append(action_dict)
            log_iwap_phase(
                "Phase 4",
                f"  Action {action_idx} (normalized): {action_dict}",
                level="debug",
            )

        # Use the full task_id from IWAP payload for generating IDs
        iwap_task_id = task_payload.task_id
        task_solution_id = iwa_main.generate_task_solution_id(iwap_task_id, miner_uid)
        evaluation_id = iwa_main.generate_evaluation_id(iwap_task_id, miner_uid)

        # Ensure evaluation_meta is a dict
        if not isinstance(evaluation_meta, dict):
            evaluation_meta = {}
        evaluation_metadata = dict(evaluation_meta)

        # Remove fields that are already in specific EvaluationResultIWAP fields
        # These should not be in metadata
        evaluation_metadata.pop("gif_recording", None)
        evaluation_metadata.pop("final_score", None)  # Legacy field name
        evaluation_metadata.pop("eval_score", None)  # Now a separate field
        evaluation_metadata.pop("reward", None)  # Now a separate field
        evaluation_metadata.pop("version_ok", None)
        evaluation_metadata.pop("notes", None)
        evaluation_metadata.pop("error_message", None)
        evaluation_metadata.pop("feedback", None)  # feedback is a separate field
        evaluation_metadata.pop("execution_history", None)  # execution_history is a separate field
        evaluation_metadata.pop("test_results", None)  # test_results is a separate field
        evaluation_metadata.pop("raw_score", None)  # raw_score is a separate field
        evaluation_metadata.pop("evaluation_time", None)  # evaluation_time is a separate field
        evaluation_metadata.pop("stats", None)  # stats is a separate field

        gif_payload = evaluation_meta.get("gif_recording")

        # Only keep metadata if it has useful information (not empty)
        if not evaluation_metadata:
            evaluation_metadata = {}

        # Marcar timeout en metadata si el tiempo de ejecución alcanza el TIMEOUT
        try:
            from autoppia_web_agents_subnet.validator.config import TIMEOUT

            is_timeout = False
            if exec_time is not None and TIMEOUT is not None:
                is_timeout = float(exec_time) >= float(TIMEOUT)
            if evaluation_metadata.get("timeout") is True:
                is_timeout = True
            if is_timeout:
                evaluation_metadata["timeout"] = True
        except Exception:
            # No bloquear el flujo si falla la detección de timeout
            pass
        # Calculate reward - use rewards array if available, otherwise calculate from eval_score
        # 🔍 CRITICAL: If eval_score = 1.0, reward must be at least EVAL_SCORE_WEIGHT (0.995), never 0.0
        if idx < len(rewards):
            reward_value = float(rewards[idx])
        else:
            # Fallback: if eval_score = 1.0, reward should be at least EVAL_SCORE_WEIGHT
            # If eval_score = 0.0, reward = 0.0
            if eval_score >= 1.0:
                # Use minimum reward (EVAL_SCORE_WEIGHT) if task was completed but reward not available
                from autoppia_web_agents_subnet.validator.config import EVAL_SCORE_WEIGHT

                reward_value = float(EVAL_SCORE_WEIGHT)  # Minimum reward for completed task
            else:
                reward_value = 0.0  # Failed task = 0 reward

        task_solution_payload = iwa_models.TaskSolutionIWAP(
            solution_id=task_solution_id,
            task_id=iwap_task_id,  # Use the full task_id from IWAP payload
            agent_run_id=agent_run.agent_run_id,
            validator_round_id=ctx.current_round_id,
            validator_uid=int(ctx.uid),
            validator_hotkey=validator_hotkey,
            miner_uid=miner_uid,
            miner_hotkey=miner_hotkey,
            actions=actions_payload,
            recording=getattr(solution, "recording", None) if solution is not None else None,
        )

        # Build llm_usage for backend (same as prepare_evaluation_payload)
        llm_usage_inner: Optional[List[Dict[str, Any]]] = _normalize_llm_usage(evaluation_meta.get("llm_usage"))

        evaluation_result_payload = iwa_models.EvaluationResultIWAP(
            evaluation_id=evaluation_id,
            validator_round_id=ctx.current_round_id,
            agent_run_id=agent_run.agent_run_id,
            task_id=task_payload.task_id,  # Use the full task_id from IWAP payload
            task_solution_id=task_solution_id,
            validator_uid=int(ctx.uid),
            validator_hotkey=validator_hotkey,
            miner_uid=miner_uid,
            eval_score=eval_score,  # Evaluation score (tests/actions only)
            reward=reward_value,  # Reward (eval_score + time_score)
            test_results=test_results_data or [],
            execution_history=evaluation_meta.get("execution_history", []),
            feedback=evaluation_meta.get("feedback"),
            evaluation_time=evaluation_meta.get("evaluation_time", exec_time),
            stats=evaluation_meta.get("stats"),
            gif_recording=None,
            metadata=evaluation_metadata,
            llm_usage=llm_usage_inner,
        )

        if (miner_uid, iwap_task_id) in ctx._completed_pairs:
            log_iwap_phase(
                "Phase 4",
                f"⏭️ Skipping add_evaluation for miner_uid={miner_uid}, task_id={iwap_task_id} (already completed)",
                level="warning",
            )
            continue

        add_evaluation_message = f"Calling add_evaluation for miner_uid={miner_uid}, task_id={iwap_task_id}, agent_run_id={agent_run.agent_run_id}"
        log_iwap_phase("Phase 4", add_evaluation_message)

        gif_to_upload: Optional[bytes] | Optional[str] = None
        if gif_payload:
            payload_size = len(gif_payload) if isinstance(gif_payload, (bytes, str)) else 0
            log_gif_event(
                f"GIF detected: {payload_size} bytes - will upload after creating evaluation",
                level="debug",
            )
            gif_to_upload = gif_payload
        else:
            log_iwap_phase(
                "Phase 4",
                f"No GIF payload received for evaluation_id={evaluation_id}",
                level="debug",
            )

        try:
            await ctx.iwap_client.add_evaluation(
                validator_round_id=ctx.current_round_id,
                agent_run_id=agent_run.agent_run_id,
                task=task_payload,
                task_solution=task_solution_payload,
                evaluation_result=evaluation_result_payload,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 409:
                # Already exists - mark as completed
                log_iwap_phase(
                    "Phase 4",
                    f"add_evaluation returned 409 for miner_uid={miner_uid}, task_id={iwap_task_id}; marking as completed",
                    level="warning",
                )
                ctx._completed_pairs.add((miner_uid, iwap_task_id))
            else:
                # HTTP error - log but don't skip, try to retry or at least mark the attempt
                add_evaluation_error = f"add_evaluation HTTP error for miner_uid={miner_uid}, task_id={iwap_task_id}: {exc}"
                log_iwap_phase("Phase 4", add_evaluation_error, level="error", exc_info=True)
                bt.logging.error(
                    f"❌ CRITICAL: HTTP error creating evaluation for miner_uid={miner_uid}, task_id={iwap_task_id}, agent_run_id={agent_run.agent_run_id}. "
                    f"Status: {exc.response.status_code if exc.response else 'unknown'}. "
                    f"This evaluation MUST be created - retrying may be needed."
                )
                # Don't continue - the evaluation is essential, but we can't create it if HTTP fails
                # The error is logged, but we can't proceed without a successful HTTP call
        except Exception as exc:
            # Any other error - log as critical
            add_evaluation_error = f"add_evaluation failed for miner_uid={miner_uid}, task_id={iwap_task_id}: {exc}"
            log_iwap_phase("Phase 4", add_evaluation_error, level="error", exc_info=True)
            bt.logging.error(
                f"❌ CRITICAL: Failed to create evaluation for miner_uid={miner_uid}, task_id={iwap_task_id}, agent_run_id={agent_run.agent_run_id}. "
                f"Error: {type(exc).__name__}: {exc}. "
                f"This will result in an agent_run without evaluations, which should NEVER happen."
            )
            # Don't continue - we've logged the error, but can't create evaluation if the call fails
        else:
            add_evaluation_success = f"add_evaluation completed for miner_uid={miner_uid}, task_id={iwap_task_id}"
            log_iwap_phase("Phase 4", add_evaluation_success, level="success")
            ctx._completed_pairs.add((miner_uid, iwap_task_id))

            if gif_to_upload:
                gif_bytes = extract_gif_bytes(gif_to_upload)
                if gif_bytes:
                    log_gif_event(f"Starting upload for evaluation_id={evaluation_id} bytes={len(gif_bytes)}")
                    try:
                        uploaded_url = await ctx.iwap_client.upload_evaluation_gif(evaluation_id, gif_bytes)
                        if uploaded_url:
                            log_gif_event(
                                f"Uploaded successfully to AWS: {uploaded_url}",
                                level="success",
                            )
                        else:
                            log_gif_event(
                                f"Upload completed without URL for evaluation_id={evaluation_id}",
                                level="warning",
                            )
                    except Exception as e:  # noqa: BLE001
                        log_gif_event(
                            f"Failed to upload for evaluation_id={evaluation_id}: {str(e)}",
                            level="error",
                            exc_info=True,
                        )
                else:
                    log_gif_event(
                        "Skipped upload: invalid payload (failed to extract bytes)",
                        level="warning",
                    )

            try:
                from autoppia_web_agents_subnet.validator.config import UPLOAD_TASK_LOGS
            except Exception:
                UPLOAD_TASK_LOGS = False
            if UPLOAD_TASK_LOGS:
                try:
                    task_log_payload = _build_task_log_payload(
                        task_payload=task_payload,
                        agent_run=agent_run,
                        miner_uid=miner_uid,
                        eval_score=eval_score,
                        reward=reward_value,
                        exec_time=exec_time,
                        evaluation_meta=evaluation_meta,
                        validator_round_id=ctx.current_round_id,
                        validator_uid=int(ctx.uid),
                    )
                    await ctx.iwap_client.upload_task_log(task_log_payload)
                except Exception as log_exc:  # noqa: BLE001
                    log_iwap_phase(
                        "Phase 4",
                        f"Task log upload failed for task_id={iwap_task_id} miner_uid={miner_uid}: {log_exc}",
                        level="warning",
                    )

        accumulators = ctx.agent_run_accumulators.setdefault(miner_uid, {"reward": 0.0, "eval_score": 0.0, "execution_time": 0.0, "tasks": 0})
        accumulators["reward"] += float(reward_value)
        accumulators["eval_score"] += float(eval_score)
        accumulators["execution_time"] += exec_time
        accumulators["tasks"] += 1

        agent_run.total_tasks = accumulators["tasks"]
        agent_run.completed_tasks = accumulators["tasks"]
        agent_run.total_reward = accumulators["reward"]
        agent_run.average_reward = accumulators["reward"] / accumulators["tasks"] if accumulators["tasks"] else None
        agent_run.average_score = accumulators["eval_score"] / accumulators["tasks"] if accumulators["tasks"] else None
        agent_run.average_execution_time = accumulators["execution_time"] / accumulators["tasks"] if accumulators["tasks"] else None
