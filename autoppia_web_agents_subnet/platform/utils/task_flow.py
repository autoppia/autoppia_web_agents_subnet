from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

import bittensor as bt
from autoppia_web_agents_subnet.platform import models as iwa_models
from autoppia_web_agents_subnet.platform import client as iwa_main
from .iwa_core import (
    log_iwap_phase,
    log_gif_event,
    extract_gif_bytes,
)


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
    llm_cost: Optional[float] = None,
    llm_tokens: Optional[int] = None,
    llm_provider: Optional[str] = None,
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
        llm_cost: Total LLM cost in USD (optional)
        llm_tokens: Total LLM tokens used (optional)
        llm_provider: LLM provider used, e.g., "openai", "chutes" (optional)
    
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
        if hasattr(action, "model_dump"):
            actions_payload.append(action.model_dump(mode="json", exclude_none=True))
        elif hasattr(action, "__dict__"):
            actions_payload.append(dict(action.__dict__))
        else:
            actions_payload.append({"type": getattr(action, "type", "unknown")})
    
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
        recording=getattr(solution, "recording", None) if solution is not None else None,
    )
    
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
        llm_cost=llm_cost,
        llm_tokens=llm_tokens,
        llm_provider=llm_provider,
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

    # CRITICAL: Always create evaluations for ALL miners that have agent_runs
    # active_miner_uids should match current_agent_runs, but iterate over agent_runs to be safe
    # Each miner with agent_run MUST have a TaskSolution and Evaluation for each task
    
    for idx, miner_uid in enumerate(ctx.active_miner_uids):
        # Get agent_run - if it doesn't exist, skip (shouldn't happen, but handle gracefully)
        agent_run = ctx.current_agent_runs.get(miner_uid)
        if agent_run is None:
            bt.logging.warning(
                f"⚠️ Miner {miner_uid} is in active_miner_uids but has no agent_run. "
                f"This should not happen - agent_run should be created during handshake."
            )
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
            if hasattr(action, "model_dump"):
                action_dict = action.model_dump(mode="json", exclude_none=True)
                actions_payload.append(action_dict)
                log_iwap_phase(
                    "Phase 4",
                    f"  Action {action_idx} (model_dump): {action_dict}",
                    level="debug",
                )
            elif hasattr(action, "__dict__"):
                action_dict = dict(action.__dict__)
                actions_payload.append(action_dict)
                log_iwap_phase(
                    "Phase 4",
                    f"  Action {action_idx} (__dict__): {action_dict}",
                    level="debug",
                )
            else:
                action_dict = {"type": getattr(action, "type", "unknown")}
                actions_payload.append(action_dict)
                log_iwap_phase(
                    "Phase 4",
                    f"  Action {action_idx} (fallback): {action_dict}",
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
                    f"add_evaluation returned 409 for miner_uid={miner_uid}, task_id={task_id}; marking as completed",
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
