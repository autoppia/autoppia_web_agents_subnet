from __future__ import annotations

import math
import time
from typing import Any, Dict, List

import httpx

from autoppia_web_agents_subnet.validator.config import ROUND_SIZE_EPOCHS
from autoppia_web_agents_subnet.platform import models as iwa_models
from autoppia_web_agents_subnet.platform import main as iwa_main
from .iwa_core import (
    log_iwap_phase,
    build_validator_identity,
    build_validator_snapshot,
    extract_gif_bytes,
)


async def start_round_flow(ctx, *, current_block: int, n_tasks: int) -> None:
    if not ctx.current_round_id:
        return

    validator_identity = build_validator_identity(ctx)
    validator_snapshot = build_validator_snapshot(ctx, ctx.current_round_id)
    boundaries = ctx.round_manager.get_current_boundaries()
    max_epochs = max(1, int(round(ROUND_SIZE_EPOCHS))) if ROUND_SIZE_EPOCHS else 1
    start_epoch_raw = boundaries["round_start_epoch"]
    start_epoch = math.floor(start_epoch_raw)
    round_metadata: Dict[str, Any] = {
        "round_start_epoch_raw": start_epoch_raw,
        "target_epoch": boundaries.get("target_epoch"),
    }

    round_number = await ctx.round_manager.calculate_round(current_block)
    miner_count = len(getattr(ctx, "active_miner_uids", []))

    start_round_message = (
        f"Calling start_round with round_number={round_number}, "
        f"tasks={n_tasks}, miners={miner_count}, "
        f"round_id={ctx.current_round_id}"
    )
    log_iwap_phase("Phase 1", start_round_message)

    try:
        await ctx.iwap_client.auth_check()
    except Exception as exc:
        log_iwap_phase(
            "Auth",
            f"Validator auth check failed – aborting round: {exc}",
            level="error",
            exc_info=True,
        )
        raise SystemExit("Validator authentication failed; shutting down") from exc

    validator_round = iwa_models.ValidatorRoundIWAP(
        validator_round_id=ctx.current_round_id,
        round_number=round_number,
        validator_uid=int(ctx.uid),
        validator_hotkey=validator_identity.hotkey,
        validator_coldkey=validator_identity.coldkey,
        start_block=current_block,
        start_epoch=start_epoch,
        max_epochs=max_epochs,
        max_blocks=ctx.round_manager.BLOCKS_PER_EPOCH,
        n_tasks=n_tasks,
        n_miners=len(ctx.active_miner_uids),
        n_winners=max(1, len(ctx.active_miner_uids)) if ctx.active_miner_uids else 1,
        started_at=ctx.round_start_timestamp or time.time(),
        summary={"tasks": n_tasks},
        metadata=round_metadata,
    )

    if ctx._phases.get("p1_done"):
        log_iwap_phase("Phase 1", "resume: skipping start_round (already done)", level="warning")
    else:
        try:
            await ctx.iwap_client.start_round(
                validator_identity=validator_identity,
                validator_round=validator_round,
                validator_snapshot=validator_snapshot,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (409, 500):
                log_iwap_phase(
                    "Phase 1",
                    f"start_round returned {status} (already exists); continuing idempotently",
                    level="warning",
                )
                ctx._phases["p1_done"] = True
            else:
                log_iwap_phase(
                    "Phase 1",
                    f"start_round failed for round_id={ctx.current_round_id}",
                    level="error",
                    exc_info=True,
                )
                return
        except Exception:
            log_iwap_phase(
                "Phase 1",
                f"start_round failed for round_id={ctx.current_round_id}",
                level="error",
                exc_info=True,
            )
            return
        else:
            log_iwap_phase(
                "Phase 1",
                f"start_round completed for round_id={ctx.current_round_id}",
                level="success",
            )
            ctx._phases["p1_done"] = True
        finally:
            try:
                ctx._save_round_state()
            except Exception:
                pass

    task_count = len(ctx.current_round_tasks)
    set_tasks_message = (
        f"Calling set_tasks with tasks={task_count} for round_id={ctx.current_round_id}"
    )
    if ctx._phases.get("p2_done"):
        log_iwap_phase("Phase 2", "resume: skipping set_tasks (already done)", level="warning")
    else:
        log_iwap_phase("Phase 2", set_tasks_message)

        try:
            await ctx.iwap_client.set_tasks(
                validator_round_id=ctx.current_round_id,
                tasks=ctx.current_round_tasks.values(),
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (409, 500):
                log_iwap_phase(
                    "Phase 2",
                    f"set_tasks returned {status} (duplicates); continuing idempotently",
                    level="warning",
                )
                ctx._phases["p2_done"] = True
            else:
                log_iwap_phase(
                    "Phase 2",
                    f"set_tasks failed for round_id={ctx.current_round_id}",
                    level="error",
                    exc_info=True,
                )
                return
        except Exception:
            log_iwap_phase(
                "Phase 2",
                f"set_tasks failed for round_id={ctx.current_round_id}",
                level="error",
                exc_info=True,
            )
            return
        else:
            log_iwap_phase(
                "Phase 2",
                f"set_tasks completed for round_id={ctx.current_round_id}",
                level="success",
            )
            ctx._phases["p2_done"] = True
        finally:
            try:
                ctx._save_round_state()
            except Exception:
                pass

    coldkeys = getattr(ctx.metagraph, "coldkeys", [])
    now_ts = time.time()
    for miner_uid in ctx.active_miner_uids:
        miner_hotkey = None
        try:
            miner_hotkey = ctx.metagraph.hotkeys[miner_uid]
        except Exception:
            pass

        miner_coldkey = None
        try:
            if coldkeys:
                miner_coldkey = coldkeys[miner_uid]
        except Exception:
            miner_coldkey = None

        handshake_payload = ctx.round_handshake_payloads.get(miner_uid)

        miner_identity = iwa_main.build_miner_identity(
            miner_uid=miner_uid,
            miner_hotkey=miner_hotkey,
            miner_coldkey=miner_coldkey,
            agent_key=None,
        )
        miner_snapshot = iwa_main.build_miner_snapshot(
            validator_round_id=ctx.current_round_id,
            miner_uid=miner_uid,
            miner_hotkey=miner_hotkey,
            miner_coldkey=miner_coldkey,
            agent_key=None,
            handshake_payload=handshake_payload,
            now_ts=now_ts,
        )

        existing_run = ctx.current_agent_runs.get(miner_uid)
        agent_run_id = (
            existing_run.agent_run_id if existing_run else iwa_main.generate_agent_run_id(miner_uid)
        )
        agent_run = iwa_models.AgentRunIWAP(
            agent_run_id=agent_run_id,
            validator_round_id=ctx.current_round_id,
            validator_uid=int(ctx.uid),
            validator_hotkey=validator_identity.hotkey,
            miner_uid=miner_uid,
            miner_hotkey=miner_hotkey,
            miner_agent_key=None,
            is_sota=False,
            version=getattr(handshake_payload, "agent_version", None),
            started_at=now_ts,
            metadata={"handshake_note": getattr(handshake_payload, "note", None)},
        )

        try:
            if existing_run:
                log_iwap_phase(
                    "Phase 3",
                    f"resume: skipping start_agent_run for miner_uid={miner_uid} (already started)",
                    level="warning",
                )
                ctx.current_agent_runs[miner_uid] = existing_run
                ctx.current_miner_snapshots[miner_uid] = (
                    ctx.current_miner_snapshots.get(miner_uid) or miner_snapshot
                )
                ctx.agent_run_accumulators.setdefault(
                    miner_uid, {"reward": 0.0, "score": 0.0, "execution_time": 0.0, "tasks": 0}
                )
                try:
                    ctx._save_round_state()
                except Exception:
                    pass
                continue
            start_agent_run_message = (
                f"Calling start_agent_run for miner_uid={miner_uid}, agent_run_id={agent_run_id}"
            )
            log_iwap_phase("Phase 3", start_agent_run_message)
            await ctx.iwap_client.start_agent_run(
                validator_round_id=ctx.current_round_id,
                agent_run=agent_run,
                miner_identity=miner_identity,
                miner_snapshot=miner_snapshot,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (409, 500):
                log_iwap_phase(
                    "Phase 3",
                    f"start_agent_run returned {status} for miner_uid={miner_uid} (already exists); continuing",
                    level="warning",
                )
            else:
                start_agent_run_error = (
                    f"start_agent_run failed for miner_uid={miner_uid}, agent_run_id={agent_run_id}"
                )
                log_iwap_phase(
                    "Phase 3",
                    start_agent_run_error,
                    level="error",
                    exc_info=True,
                )
                continue
        except Exception:
            start_agent_run_error = (
                f"start_agent_run failed for miner_uid={miner_uid}, agent_run_id={agent_run_id}"
            )
            log_iwap_phase("Phase 3", start_agent_run_error, level="error", exc_info=True)
            continue
        else:
            start_agent_run_success = (
                f"start_agent_run completed for miner_uid={miner_uid}, agent_run_id={agent_run_id}"
            )
            log_iwap_phase("Phase 3", start_agent_run_success, level="success")


async def finish_round_flow(
    ctx,
    *,
    avg_rewards: Dict[int, float],
    final_weights: Dict[int, float],
    tasks_completed: int,
) -> None:
    if not ctx.current_round_id:
        return

    ended_at = time.time()
    for agent_run in ctx.current_agent_runs.values():
        agent_run.ended_at = ended_at
        agent_run.elapsed_sec = max(0.0, ended_at - agent_run.started_at)

    sorted_miners = sorted(avg_rewards.items(), key=lambda item: item[1], reverse=True)
    winners: List[iwa_models.RoundWinnerIWAP] = []
    winner_scores: List[float] = []
    for rank, (uid, score) in enumerate(sorted_miners[:3], start=1):
        miner_hotkey = None
        try:
            miner_hotkey = ctx.metagraph.hotkeys[uid]
        except Exception:
            miner_hotkey = None
        winners.append(
            iwa_models.RoundWinnerIWAP(
                miner_uid=uid,
                miner_hotkey=miner_hotkey,
                rank=rank,
                score=float(score),
            )
        )
        winner_scores.append(float(score))

    weights_payload = {str(uid): float(weight) for uid, weight in final_weights.items()}
    summary = {
        "tasks_completed": tasks_completed,
        "active_miners": len(avg_rewards),
    }

    rank_map = {uid: rank for rank, (uid, _score) in enumerate(sorted_miners, start=1)}
    agent_run_summaries: List[iwa_models.FinishRoundAgentRunIWAP] = []
    for miner_uid, agent_run in ctx.current_agent_runs.items():
        rank_value = rank_map.get(miner_uid)
        weight_value = final_weights.get(miner_uid)
        agent_run_summaries.append(
            iwa_models.FinishRoundAgentRunIWAP(
                agent_run_id=agent_run.agent_run_id,
                rank=rank_value,
                weight=float(weight_value) if weight_value is not None else None,
            )
        )

    finish_request = iwa_models.FinishRoundIWAP(
        status="completed",
        winners=winners,
        winner_scores=winner_scores,
        weights=weights_payload,
        ended_at=ended_at,
        summary=summary,
        agent_runs=agent_run_summaries,
    )

    round_id = ctx.current_round_id
    finish_round_message = (
        f"Calling finish_round for round_id={round_id}, winners={len(winners)}, tasks_completed={tasks_completed}"
    )
    log_iwap_phase("Phase 5", finish_round_message)
    try:
        await ctx.iwap_client.finish_round(
            validator_round_id=round_id,
            finish_request=finish_request,
        )
    except Exception:
        log_iwap_phase(
            "Phase 5",
            f"finish_round failed for round_id={round_id}",
            level="error",
            exc_info=True,
        )
        raise
    else:
        log_iwap_phase(
            "Phase 5",
            f"finish_round completed for round_id={round_id}",
            level="success",
        )
    finally:
        ctx._reset_iwap_round_state()
        ctx._remove_round_state()


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
            miner_agent_key=None,
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

        add_evaluation_message = (
            f"Calling add_evaluation for miner_uid={miner_uid}, task_id={task_id}, agent_run_id={agent_run.agent_run_id}"
        )
        log_iwap_phase("Phase 4", add_evaluation_message)

        gif_to_upload = None
        if gif_payload:
            payload_size = len(gif_payload) if isinstance(gif_payload, (bytes, str)) else 0
            log_iwap_phase(
                "Phase 4",
                f"🎬 GIF detected: {payload_size} bytes - will upload after creating evaluation",
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
                try:
                    ctx._save_round_state()
                except Exception:
                    pass
                continue
            else:
                add_evaluation_error = (
                    f"add_evaluation failed for miner_uid={miner_uid}, task_id={task_id}"
                )
                log_iwap_phase("Phase 4", add_evaluation_error, level="error", exc_info=True)
                continue
        except Exception:
            add_evaluation_error = (
                f"add_evaluation failed for miner_uid={miner_uid}, task_id={task_id}"
            )
            log_iwap_phase("Phase 4", add_evaluation_error, level="error", exc_info=True)
        else:
            add_evaluation_success = (
                f"add_evaluation completed for miner_uid={miner_uid}, task_id={task_id}"
            )
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
            try:
                ctx._save_round_state()
            except Exception:
                pass

            if gif_to_upload:
                gif_bytes = extract_gif_bytes(gif_to_upload)
                if gif_bytes:
                    log_iwap_phase(
                        "Phase 4",
                        f"🎬 Uploading GIF to AWS for evaluation_id={evaluation_id} bytes={len(gif_bytes)}",
                    )
                    try:
                        uploaded_url = await ctx.iwap_client.upload_evaluation_gif(
                            evaluation_id, gif_bytes
                        )
                        if uploaded_url:
                            log_iwap_phase(
                                "Phase 4",
                                f"✅ GIF uploaded successfully to AWS: {uploaded_url}",
                                level="success",
                            )
                        else:
                            log_iwap_phase(
                                "Phase 4",
                                f"⚠️  GIF upload completed without URL for evaluation_id={evaluation_id}",
                                level="warning",
                            )
                    except Exception as e:  # noqa: BLE001
                        log_iwap_phase(
                            "Phase 4",
                            f"❌ Failed to upload GIF for evaluation_id={evaluation_id}: {str(e)}",
                            level="error",
                            exc_info=True,
                        )
                else:
                    log_iwap_phase(
                        "Phase 4",
                        "⚠️  Skipped GIF upload: invalid payload (failed to extract bytes)",
                        level="warning",
                    )

        accumulators = ctx.agent_run_accumulators.setdefault(
            miner_uid, {"reward": 0.0, "score": 0.0, "execution_time": 0.0, "tasks": 0}
        )
        accumulators["reward"] += float(reward_value)
        accumulators["score"] += float(final_score)
        accumulators["execution_time"] += exec_time
        accumulators["tasks"] += 1

        agent_run.total_tasks = accumulators["tasks"]
        agent_run.completed_tasks = accumulators["tasks"]
        agent_run.total_reward = accumulators["reward"]
        agent_run.average_reward = (
            accumulators["reward"] / accumulators["tasks"] if accumulators["tasks"] else None
        )
        agent_run.average_score = (
            accumulators["score"] / accumulators["tasks"] if accumulators["tasks"] else None
        )
        agent_run.average_execution_time = (
            accumulators["execution_time"] / accumulators["tasks"] if accumulators["tasks"] else None
        )

