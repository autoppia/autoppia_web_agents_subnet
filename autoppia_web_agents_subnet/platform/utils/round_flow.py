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
        # Even on resume, ensure the backend still has this round (dev DBs may be reset).
        # Re-send start_round idempotently; backend treats duplicates as OK.
        log_iwap_phase("Phase 1", "resume: verifying start_round on backend", level="warning")
        try:
            await ctx.iwap_client.start_round(
                validator_identity=validator_identity,
                validator_round=validator_round,
                validator_snapshot=validator_snapshot,
            )
            ctx._phases["p1_done"] = True
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (409, 500):
                # Treat as idempotent success
                ctx._phases["p1_done"] = True
                log_iwap_phase(
                    "Phase 1",
                    f"start_round returned {status} (already exists); continuing idempotently",
                    level="warning",
                )
            else:
                log_iwap_phase(
                    "Phase 1",
                    f"start_round verification failed for round_id={ctx.current_round_id}",
                    level="error",
                    exc_info=True,
                )
                return
        finally:
            try:
                ctx._save_round_state()
            except Exception:
                pass
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
        # Idempotently re-send tasks to ensure backend state is present after resumes.
        log_iwap_phase("Phase 2", "resume: verifying set_tasks on backend", level="warning")
        try:
            await ctx.iwap_client.set_tasks(
                validator_round_id=ctx.current_round_id,
                tasks=list(ctx.current_round_tasks.values()),
            )
            ctx._phases["p2_done"] = True
        except httpx.HTTPStatusError:
            log_iwap_phase(
                "Phase 2",
                f"set_tasks verification failed for round_id={ctx.current_round_id}",
                level="error",
                exc_info=True,
            )
            return
        finally:
            try:
                ctx._save_round_state()
            except Exception:
                pass
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
            try:
                await ctx.iwap_client.start_agent_run(
                    validator_round_id=ctx.current_round_id,
                    agent_run=agent_run,
                    miner_identity=miner_identity,
                    miner_snapshot=miner_snapshot,
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                body = exc.response.text if exc.response is not None else ""
                # If validator_round is missing on backend (e.g., after API reset), re-create and retry once.
                if status == 400 and "Validator round" in body and "not found" in body:
                    log_iwap_phase(
                        "Phase 3",
                        "start_agent_run failed due to missing round; re-submitting start_round + set_tasks and retrying",
                        level="warning",
                    )
                    try:
                        await ctx.iwap_client.start_round(
                            validator_identity=validator_identity,
                            validator_round=validator_round,
                            validator_snapshot=validator_snapshot,
                        )
                    except Exception:
                        pass
                    try:
                        await ctx.iwap_client.set_tasks(
                            validator_round_id=ctx.current_round_id,
                            tasks=list(ctx.current_round_tasks.values()),
                        )
                    except Exception:
                        pass
                    # Retry once
                    await ctx.iwap_client.start_agent_run(
                        validator_round_id=ctx.current_round_id,
                        agent_run=agent_run,
                        miner_identity=miner_identity,
                        miner_snapshot=miner_snapshot,
                    )
                else:
                    raise
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
