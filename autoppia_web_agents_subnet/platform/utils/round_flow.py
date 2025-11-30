from __future__ import annotations

import math
import time
from typing import Any, Dict, List

import httpx
import bittensor as bt

from autoppia_web_agents_subnet.validator.config import ROUND_SIZE_EPOCHS
from autoppia_web_agents_subnet.platform import models as iwa_models
from autoppia_web_agents_subnet.platform import client as iwa_main
from .iwa_core import (
    log_iwap_phase,
    build_validator_identity,
    build_validator_snapshot,
)


def _extract_validator_round_id(resp: Any) -> str:
    if not isinstance(resp, dict):
        raise RuntimeError("IWAP start_round response must be a dictionary")

    direct = resp.get("validator_round_id")
    if isinstance(direct, str) and direct.strip():
        return direct

    data_section = resp.get("data")
    if isinstance(data_section, dict):
        nested = data_section.get("validator_round_id")
        if isinstance(nested, str) and nested.strip():
            return nested

    raise RuntimeError("IWAP start_round response missing 'validator_round_id'")


def _parse_round_mismatch(exc: httpx.HTTPStatusError) -> tuple[int | None, int | None] | None:
    response = exc.response
    if response is None or response.status_code != 400:
        return None
    detail: Any = None
    try:
        detail = response.json()
    except Exception:
        try:
            detail = response.text
        except Exception:
            detail = None
    if isinstance(detail, dict) and "detail" in detail:
        detail = detail["detail"]
    if isinstance(detail, dict) and detail.get("error") == "round_number mismatch":
        expected = detail.get("expectedRoundNumber")
        got = detail.get("got")
        try:
            expected = int(expected) if expected is not None else None
        except (TypeError, ValueError):
            expected = None
        try:
            got = int(got) if got is not None else None
        except (TypeError, ValueError):
            got = None
        return expected, got
    return None


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

    stored_round_number = getattr(ctx, "_current_round_number", None)
    if stored_round_number is not None:
        try:
            round_number = int(stored_round_number)
        except Exception:
            round_number = await ctx.round_manager.calculate_round(current_block)
    else:
        round_number = await ctx.round_manager.calculate_round(current_block)
        try:
            ctx._current_round_number = int(round_number)
        except Exception:
            pass
    miner_count = len(getattr(ctx, "active_miner_uids", []))

    start_round_message = f"Calling start_round with round_number={round_number}, " f"tasks={n_tasks}, miners={miner_count}, " f"round_id={ctx.current_round_id}"
    log_iwap_phase("Phase 1", start_round_message)

    # Try to authenticate with IWAP, but don't kill validator if it fails
    try:
        await ctx.iwap_client.auth_check()
        ctx._iwap_offline_mode = False
        log_iwap_phase("Auth", "✅ IWAP authentication successful", level="success")
    except Exception as exc:
        # CRITICAL: IWAP is down, but validator MUST continue and set weights
        ctx._iwap_offline_mode = True
        bt.logging.critical(
            f"🔴 CRITICAL: IWAP authentication FAILED - Continuing in OFFLINE mode\n"
            f"   → IWAP endpoint unreachable: {exc}\n"
            f"   → Validator will continue: handshake, tasks, and SET WEIGHTS on-chain\n"
            f"   → IWAP data (leaderboard/dashboard) will NOT be updated this round\n"
            f"   → On-chain consensus and rewards WILL PROCEED normally"
        )
        log_iwap_phase(
            "Auth",
            f"⚠️ IWAP offline - validator continuing without dashboard sync: {exc}",
            level="error",
            exc_info=False,
        )

    # If IWAP is offline, skip all backend sync but continue validation
    if getattr(ctx, "_iwap_offline_mode", False):
        log_iwap_phase(
            "Phase 1",
            "⚠️ OFFLINE MODE: Skipping all IWAP backend calls - validator continues normally",
            level="warning",
        )
        # Mark phases as done so validator doesn't get stuck
        ctx._phases["p1_done"] = True
        ctx._phases["p2_done"] = True
        bt.logging.info("✅ Validator will proceed with: handshake → tasks → evaluations → SET WEIGHTS on-chain")
        return

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
            resp = await ctx.iwap_client.start_round(
                validator_identity=validator_identity,
                validator_round=validator_round,
                validator_snapshot=validator_snapshot,
            )
            vrid = _extract_validator_round_id(resp)
            if vrid != ctx.current_round_id:
                ctx.current_round_id = vrid
            ctx._phases["p1_done"] = True
            try:
                ctx._save_round_state()
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError("Failed to persist round state after start_round verification") from exc
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
                try:
                    ctx._save_round_state()
                except Exception as save_exc:  # noqa: BLE001
                    raise RuntimeError("Failed to persist round state after start_round verification") from save_exc
            else:
                mismatch = _parse_round_mismatch(exc)
                if mismatch is not None:
                    expected, got = mismatch
                    log_iwap_phase(
                        "Phase 1",
                        ("start_round verification rejected due to round_number mismatch " f"(expected={expected}, got={got}); continuing without IWAP sync"),
                        level="error",
                    )
                else:
                    log_iwap_phase(
                        "Phase 1",
                        f"start_round verification failed for round_id={ctx.current_round_id} (status={status}); continuing without IWAP sync",
                        level="error",
                    )
    else:
        try:
            resp = await ctx.iwap_client.start_round(
                validator_identity=validator_identity,
                validator_round=validator_round,
                validator_snapshot=validator_snapshot,
            )
            vrid = _extract_validator_round_id(resp)
            if vrid != ctx.current_round_id:
                ctx.current_round_id = vrid
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (409, 500):
                log_iwap_phase(
                    "Phase 1",
                    f"start_round returned {status} (already exists); continuing idempotently",
                    level="warning",
                )
                ctx._phases["p1_done"] = True
                try:
                    ctx._save_round_state()
                except Exception as save_exc:  # noqa: BLE001
                    raise RuntimeError("Failed to persist round state after start_round") from save_exc
            else:
                mismatch = _parse_round_mismatch(exc)
                if mismatch is not None:
                    expected, got = mismatch
                    log_iwap_phase(
                        "Phase 1",
                        ("start_round rejected due to round_number mismatch " f"(expected={expected}, got={got}); continuing without IWAP sync"),
                        level="error",
                    )
                else:
                    log_iwap_phase(
                        "Phase 1",
                        f"start_round failed for round_id={ctx.current_round_id}",
                        level="error",
                        exc_info=False,
                    )
        except Exception as exc:  # noqa: BLE001
            log_iwap_phase(
                "Phase 1",
                f"start_round failed for round_id={ctx.current_round_id}: {exc}; continuing without IWAP sync",
                level="error",
            )
        else:
            log_iwap_phase(
                "Phase 1",
                f"start_round completed for round_id={ctx.current_round_id}",
                level="success",
            )
            ctx._phases["p1_done"] = True
            try:
                ctx._save_round_state()
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError("Failed to persist round state after start_round") from exc

    task_count = len(ctx.current_round_tasks)
    set_tasks_message = f"Calling set_tasks with tasks={task_count} for round_id={ctx.current_round_id}"
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
                exc_info=False,
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
                    exc_info=False,
                )
                return
        except Exception:
            log_iwap_phase(
                "Phase 2",
                f"set_tasks failed for round_id={ctx.current_round_id}",
                level="error",
                exc_info=False,
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
        agent_run_id = existing_run.agent_run_id if existing_run else iwa_main.generate_agent_run_id(miner_uid)
        agent_run = iwa_models.AgentRunIWAP(
            agent_run_id=agent_run_id,
            validator_round_id=ctx.current_round_id,
            validator_uid=int(ctx.uid),
            validator_hotkey=validator_identity.hotkey,
            miner_uid=miner_uid,
            miner_hotkey=miner_hotkey,
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
                ctx.current_miner_snapshots[miner_uid] = ctx.current_miner_snapshots.get(miner_uid) or miner_snapshot
                ctx.agent_run_accumulators.setdefault(miner_uid, {"reward": 0.0, "score": 0.0, "execution_time": 0.0, "tasks": 0})
                try:
                    ctx._save_round_state()
                except Exception:
                    pass
                continue
            start_agent_run_message = f"Calling start_agent_run for miner_uid={miner_uid}, agent_run_id={agent_run_id}"
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
                try:
                    ctx.current_agent_runs[miner_uid] = agent_run
                    ctx.current_miner_snapshots[miner_uid] = ctx.current_miner_snapshots.get(miner_uid) or miner_snapshot
                    ctx.agent_run_accumulators.setdefault(miner_uid, {"reward": 0.0, "score": 0.0, "execution_time": 0.0, "tasks": 0})
                    ctx._save_round_state()
                except Exception:
                    pass
            else:
                start_agent_run_error = f"start_agent_run failed for miner_uid={miner_uid}, agent_run_id={agent_run_id}"
                log_iwap_phase(
                    "Phase 3",
                    start_agent_run_error,
                    level="error",
                    exc_info=False,
                )
                continue
        except Exception:
            start_agent_run_error = f"start_agent_run failed for miner_uid={miner_uid}, agent_run_id={agent_run_id}"
            log_iwap_phase("Phase 3", start_agent_run_error, level="error", exc_info=False)
            continue
        else:
            start_agent_run_success = f"start_agent_run completed for miner_uid={miner_uid}, agent_run_id={agent_run_id}"
            log_iwap_phase("Phase 3", start_agent_run_success, level="success")
            # Update local state for crash-resume and bookkeeping
            try:
                ctx.current_agent_runs[miner_uid] = agent_run
                ctx.current_miner_snapshots[miner_uid] = miner_snapshot
                ctx.agent_run_accumulators.setdefault(miner_uid, {"reward": 0.0, "score": 0.0, "execution_time": 0.0, "tasks": 0})
                ctx._save_round_state()
            except Exception:
                pass


async def finish_round_flow(
    ctx,
    *,
    avg_rewards: Dict[int, float],
    final_weights: Dict[int, float],
    tasks_completed: int,
) -> bool:
    if not ctx.current_round_id:
        return True

    # If IWAP is offline, skip backend sync but still cleanup state
    if getattr(ctx, "_iwap_offline_mode", False):
        log_iwap_phase(
            "Phase 5",
            "⚠️ OFFLINE MODE: Skipping finish_round backend call - cleaning up local state",
            level="warning",
        )
        ctx._reset_iwap_round_state()
        ctx._remove_round_state()
        bt.logging.info("✅ Round completed locally - weights were set on-chain successfully")
        return True

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

    # Get local scores (pre-consensus) if they were saved during IPFS publish
    # If not available, use current avg_rewards (backward compatible)
    local_avg_rewards = getattr(ctx, "_local_avg_rewards_at_publish", None) or avg_rewards

    # Build agent_run summaries with complete information
    # Calculate ranks with FINAL scores (for weights/consensus)
    rank_map_final = {uid: rank for rank, (uid, _score) in enumerate(sorted_miners, start=1)}

    # Calculate ranks with LOCAL scores + time as tiebreaker
    # Build list of (uid, score, avg_time) for each miner
    miners_with_time = []
    round_times = getattr(ctx.round_manager, "round_times", {}) or {}
    for uid, score in local_avg_rewards.items():
        times = round_times.get(uid, []) or []
        avg_time = sum(times) / len(times) if times else 999999.0  # High time if no data
        miners_with_time.append((uid, score, avg_time))

    # Sort by score (desc), then by time (asc) for tiebreaker
    sorted_miners_local = sorted(miners_with_time, key=lambda x: (-x[1], x[2]))  # -score (desc), time (asc)
    rank_map_local = {uid: rank for rank, (uid, _score, _time) in enumerate(sorted_miners_local, start=1)}

    agent_run_summaries: List[iwa_models.FinishRoundAgentRunIWAP] = []

    for miner_uid, agent_run in ctx.current_agent_runs.items():
        # Use LOCAL rank for local_evaluation (consistent with local scores)
        rank_value = rank_map_local.get(miner_uid)
        weight_value = final_weights.get(miner_uid)
        # Use LOCAL score (pre-consensus) for local_evaluation
        score_value = local_avg_rewards.get(miner_uid, 0.0)

        # Calculate tasks completed/failed (safe access)
        round_rewards = getattr(ctx.round_manager, "round_rewards", {}) or {}
        miner_rewards = round_rewards.get(miner_uid, []) or []
        miner_tasks_attempted = len(miner_rewards)
        miner_tasks_completed = len([r for r in miner_rewards if r >= 0.5])
        miner_tasks_failed = miner_tasks_attempted - miner_tasks_completed

        # Calculate avg evaluation time (safe access)
        round_times = getattr(ctx.round_manager, "round_times", {}) or {}
        times = round_times.get(miner_uid, []) or []
        avg_time = sum(times) / len(times) if times else 0.0

        # Get miner name from agent_run
        miner_name = getattr(agent_run, "agent_name", None) or f"Miner {miner_uid}"

        agent_run_summaries.append(
            iwa_models.FinishRoundAgentRunIWAP(
                agent_run_id=agent_run.agent_run_id,
                rank=rank_value,
                weight=float(weight_value) if weight_value is not None else None,
                miner_name=miner_name,
                score=float(score_value),
                avg_evaluation_time=float(avg_time),
                tasks_attempted=miner_tasks_attempted,
                tasks_completed=miner_tasks_completed,
                tasks_failed=miner_tasks_failed,
            )
        )

    # Build round metadata (safe access to all fields)
    try:
        boundaries = ctx.round_manager.get_current_boundaries() if hasattr(ctx, "round_manager") else {}
    except Exception:
        boundaries = {}

    # Get round number from Round Manager (most reliable source)
    round_num = 0
    if hasattr(ctx, "round_manager"):
        try:
            # Round Manager always knows the current round
            current_block = getattr(ctx, "block", None)
            if current_block:
                round_num = await ctx.round_manager.calculate_round(current_block)
        except Exception:
            # Fallback to stored value if calculation fails
            round_num = getattr(ctx, "_current_round_number", 0) or getattr(ctx, "current_round_number", 0)

    round_metadata = iwa_models.RoundMetadataIWAP(
        round_number=int(round_num or 0),
        started_at=float(getattr(ctx, "round_start_time", ended_at - 3600) or (ended_at - 3600)),
        ended_at=float(ended_at),
        start_block=int(boundaries.get("round_start_block", 0) or 0),
        end_block=int(boundaries.get("target_block", 0) or 0),
        start_epoch=float(boundaries.get("round_start_epoch", 0.0) or 0.0),
        end_epoch=float(boundaries.get("target_epoch", 0.0) or 0.0),
        tasks_total=int(tasks_completed or 0),
        tasks_completed=int(tasks_completed or 0),
        miners_responded_handshake=len(getattr(ctx, "active_miner_uids", []) or []),
        miners_active=len(avg_rewards or {}),
    )

    # Build local_evaluation (what THIS validator evaluated)
    local_evaluation = {"timestamp": ended_at, "miners": [run.to_payload() for run in agent_run_summaries]}

    # FASE 2: IPFS uploaded data (what THIS validator published)
    ipfs_uploaded = None
    consensus_cid = getattr(ctx, "_consensus_commit_cid", None)
    if consensus_cid:
        # Use the ACTUAL payload that was uploaded to IPFS (saved when published)
        ipfs_payload = getattr(ctx, "_ipfs_uploaded_payload", None)

        # Fallback: if payload wasn't saved, don't include it (just CID)
        if not ipfs_payload:
            ipfs_payload = {"note": "Payload not available"}

        ipfs_uploaded = {
            "cid": consensus_cid,
            "published_at": getattr(ctx, "_consensus_publish_timestamp", ended_at - 100),
            "reveal_round": getattr(ctx, "_consensus_reveal_round", 0),
            "commit_version": 4,
            "payload": ipfs_payload,
        }

    # FASE 3: IPFS downloaded data (what was downloaded from ALL validators)
    ipfs_downloaded = None
    agg_meta = getattr(ctx, "_agg_meta_cache", None)
    if agg_meta and isinstance(agg_meta, dict):
        # Extract validators data from consensus metadata
        validators_list = agg_meta.get("validators", [])
        scores_by_validator = agg_meta.get("scores_by_validator", {})

        # Build structured ipfs_downloaded
        validators_data = []
        total_stake = 0.0

        for val_info in validators_list:
            validator_hk = val_info.get("hotkey", "")
            validator_uid = val_info.get("uid", "?")
            validator_stake = float(val_info.get("stake", 0))
            validator_cid = val_info.get("cid", "")

            # Get scores from this validator
            validator_scores = scores_by_validator.get(validator_hk, {})

            # Try to get validator name (if available in metagraph or cached)
            validator_name = None
            if isinstance(validator_uid, int):
                # Could look up in metagraph, but for now just use UID
                validator_name = f"Validator {validator_uid}"

            validators_data.append(
                {
                    "validator_uid": validator_uid,
                    "validator_hotkey": validator_hk,
                    "validator_name": validator_name,
                    "stake": validator_stake,
                    "ipfs_cid": validator_cid,
                    "scores": {int(uid): float(score) for uid, score in validator_scores.items()},
                }
            )

            total_stake += validator_stake

        ipfs_downloaded = {"timestamp": ended_at, "validators_participated": len(validators_data), "total_stake": total_stake, "validators": validators_data}

    finish_request = iwa_models.FinishRoundIWAP(
        status="completed",
        winners=winners,
        winner_scores=winner_scores,
        weights=weights_payload,
        ended_at=ended_at,
        summary=summary,
        agent_runs=agent_run_summaries,
        round_metadata=round_metadata,
        local_evaluation=local_evaluation,
        ipfs_uploaded=ipfs_uploaded,
        ipfs_downloaded=ipfs_downloaded,
    )

    round_id = ctx.current_round_id
    finish_round_message = f"Calling finish_round for round_id={round_id}, winners={len(winners)}, tasks_completed={tasks_completed}"
    log_iwap_phase("Phase 5", finish_round_message)
    success = False
    try:
        await ctx.iwap_client.finish_round(
            validator_round_id=round_id,
            finish_request=finish_request,
        )
    except Exception as exc:  # noqa: BLE001
        error_msg = f"finish_round failed for round_id={round_id} ({type(exc).__name__}: {exc})"
        log_iwap_phase("Phase 5", error_msg, level="error", exc_info=False)
        bt.logging.error(f"IWAP finish_round failed for round_id={round_id}: {exc}")
        success = False
    else:
        log_iwap_phase(
            "Phase 5",
            f"finish_round completed for round_id={round_id}",
            level="success",
        )
        success = True
    finally:
        ctx._reset_iwap_round_state()
        ctx._remove_round_state()
    return success
