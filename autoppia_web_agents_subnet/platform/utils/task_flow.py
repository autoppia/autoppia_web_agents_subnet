from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from autoppia_web_agents_subnet.platform import models as iwa_models
from autoppia_web_agents_subnet.platform import client as iwa_main
from .iwa_core import (
    log_iwap_phase,
    log_gif_event,
    extract_gif_bytes,
)


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
    task_id = getattr(task, "id", None)
    if task_id is None:
        return

    task_payload = ctx.current_round_tasks.get(task_id)
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

    for idx, miner_uid in enumerate(ctx.active_miner_uids):
        if idx >= len(task_solutions):
            break

        agent_run = ctx.current_agent_runs.get(miner_uid)
        if agent_run is None:
            continue

        miner_hotkey = None
        try:
            miner_hotkey = ctx.metagraph.hotkeys[miner_uid]
        except Exception:
            miner_hotkey = None

        solution = task_solutions[idx]
        actions_payload: List[Dict[str, Any]] = []

        raw_actions = getattr(solution, "actions", []) or []
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

        task_solution_id = iwa_main.generate_task_solution_id(task_id, miner_uid)
        evaluation_id = iwa_main.generate_evaluation_id(task_id, miner_uid)
        final_score = float(eval_scores[idx]) if idx < len(eval_scores) else 0.0
        evaluation_meta = evaluation_results[idx] if idx < len(evaluation_results) else {}
        if not isinstance(evaluation_meta, dict):
            evaluation_meta = {}
        evaluation_metadata = dict(evaluation_meta)
        gif_payload = evaluation_metadata.pop("gif_recording", evaluation_meta.get("gif_recording"))
        test_results_data = test_results_list[idx] if idx < len(test_results_list) else []
        exec_time = float(execution_times[idx]) if idx < len(execution_times) else 0.0
        reward_value = rewards[idx] if idx < len(rewards) else final_score

        task_solution_payload = iwa_models.TaskSolutionIWAP(
            solution_id=task_solution_id,
            task_id=task_id,
            agent_run_id=agent_run.agent_run_id,
            validator_round_id=ctx.current_round_id,
            validator_uid=int(ctx.uid),
            validator_hotkey=validator_hotkey,
            miner_uid=miner_uid,
            miner_hotkey=miner_hotkey,
            actions=actions_payload,
            web_agent_id=getattr(solution, "web_agent_id", None),
            recording=getattr(solution, "recording", None),
        )

        evaluation_result_payload = iwa_models.EvaluationResultIWAP(
            evaluation_id=evaluation_id,
            validator_round_id=ctx.current_round_id,
            agent_run_id=agent_run.agent_run_id,
            task_id=task_id,
            task_solution_id=task_solution_id,
            validator_uid=int(ctx.uid),
            miner_uid=miner_uid,
            final_score=final_score,
            test_results=test_results_data or [],
            execution_history=evaluation_meta.get("execution_history", []),
            feedback=evaluation_meta.get("feedback"),
            web_agent_id=getattr(solution, "web_agent_id", None),
            raw_score=evaluation_meta.get("raw_score", final_score),
            evaluation_time=evaluation_meta.get("evaluation_time", exec_time),
            stats=evaluation_meta.get("stats"),
            gif_recording=None,
            metadata=evaluation_metadata,
        )

        if (miner_uid, task_id) in ctx._completed_pairs:
            log_iwap_phase(
                "Phase 4",
                f"⏭️ Skipping add_evaluation for miner_uid={miner_uid}, task_id={task_id} (already completed)",
                level="warning",
            )
            continue

        add_evaluation_message = f"Calling add_evaluation for miner_uid={miner_uid}, task_id={task_id}, agent_run_id={agent_run.agent_run_id}"
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
                log_iwap_phase(
                    "Phase 4",
                    f"add_evaluation returned 409 for miner_uid={miner_uid}, task_id={task_id}; marking as completed",
                    level="warning",
                )
                ctx._completed_pairs.add((miner_uid, task_id))
                continue
            else:
                add_evaluation_error = f"add_evaluation failed for miner_uid={miner_uid}, task_id={task_id}"
                log_iwap_phase("Phase 4", add_evaluation_error, level="error", exc_info=True)
                continue
        except Exception:
            add_evaluation_error = f"add_evaluation failed for miner_uid={miner_uid}, task_id={task_id}"
            log_iwap_phase("Phase 4", add_evaluation_error, level="error", exc_info=True)
        else:
            add_evaluation_success = f"add_evaluation completed for miner_uid={miner_uid}, task_id={task_id}"
            log_iwap_phase("Phase 4", add_evaluation_success, level="success")
            try:
                ctx._eval_records.append(
                    {
                        "miner_uid": miner_uid,
                        "task_id": task_id,
                        "reward": float(reward_value),
                        "final_score": float(final_score),
                        "exec_time": float(exec_time),
                    }
                )
            except Exception:
                pass
            ctx._completed_pairs.add((miner_uid, task_id))

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

        accumulators = ctx.agent_run_accumulators.setdefault(miner_uid, {"reward": 0.0, "score": 0.0, "execution_time": 0.0, "tasks": 0})
        accumulators["reward"] += float(reward_value)
        accumulators["score"] += float(final_score)
        accumulators["execution_time"] += exec_time
        accumulators["tasks"] += 1

        agent_run.total_tasks = accumulators["tasks"]
        agent_run.completed_tasks = accumulators["tasks"]
        agent_run.total_reward = accumulators["reward"]
        agent_run.average_reward = accumulators["reward"] / accumulators["tasks"] if accumulators["tasks"] else None
        agent_run.average_score = accumulators["score"] / accumulators["tasks"] if accumulators["tasks"] else None
        agent_run.average_execution_time = accumulators["execution_time"] / accumulators["tasks"] if accumulators["tasks"] else None
