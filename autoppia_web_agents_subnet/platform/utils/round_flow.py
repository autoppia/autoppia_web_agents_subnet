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

    # 🔍 FIX: Fetch a fresh block height to avoid TTL-cached values around round boundaries
    # self.block is cached with 12s TTL. If block advances within that TTL, we send a stale round
    # and backend returns "round_number mismatch". Always use fresh block for round calculation.
    original_block = current_block
    try:
        latest_block = ctx.subtensor.get_current_block()
        if latest_block is not None:
            current_block = int(latest_block)
            if current_block != original_block:
                bt.logging.info(
                    f"[IWAP] Block refresh: using fresh_block={current_block:,} "
                    f"(was {original_block:,}, diff={current_block - original_block})"
                )
    except Exception:
        # If refresh fails, use the passed block (fallback)
        pass

    validator_identity = build_validator_identity(ctx)
    validator_snapshot = build_validator_snapshot(ctx, ctx.current_round_id)
    
    # 🔍 IMPORTANT: Recalculate boundaries with refreshed block to ensure consistency
    # get_current_boundaries() uses self.start_block (from original block), but we need
    # boundaries consistent with the refreshed current_block for round_number calculation
    boundaries = ctx.round_manager.get_round_boundaries(current_block, log_debug=False)
    max_epochs = max(1, int(round(ROUND_SIZE_EPOCHS))) if ROUND_SIZE_EPOCHS else 1
    start_epoch_raw = boundaries["round_start_epoch"]
    start_epoch = math.floor(start_epoch_raw)
    round_metadata: Dict[str, Any] = {
        "round_start_epoch_raw": start_epoch_raw,
        "target_epoch": boundaries.get("target_epoch"),
    }

    # 🔍 Calculate season and round within season
    from autoppia_web_agents_subnet.platform import client as iwa_main
    round_blocks = int(ctx.round_manager.ROUND_BLOCK_LENGTH)
    
    season_number = iwa_main.compute_season_number(current_block)
    round_number_in_season = iwa_main.compute_round_number_in_season(current_block, round_blocks)
    
    bt.logging.info(
        f"[IWAP] Season calculation: block={current_block:,} | "
        f"season_number={season_number} | "
        f"round_number_in_season={round_number_in_season} | "
        f"round_blocks={round_blocks}"
    )
    
    miner_count = len(getattr(ctx, "active_miner_uids", []))

    start_round_message = (
        f"Calling start_round with season={season_number}, "
        f"round_in_season={round_number_in_season}, "
        f"tasks={n_tasks}, miners={miner_count}, "
        f"round_id={ctx.current_round_id}"
    )
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
        bt.logging.info("✅ Validator will proceed with: handshake → tasks → evaluations → SET WEIGHTS on-chain")
        return

    # Use round_start_block from boundaries (not current_block) for consistency
    round_start_block = int(boundaries.get("round_start_block", current_block) or current_block)
    
    validator_round = iwa_models.ValidatorRoundIWAP(
        validator_round_id=ctx.current_round_id,
        season_number=season_number,
        round_number_in_season=round_number_in_season,
        validator_uid=int(ctx.uid),
        validator_hotkey=validator_identity.hotkey,
        validator_coldkey=validator_identity.coldkey,
        start_block=round_start_block,
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

    task_count = len(ctx.current_round_tasks)
    set_tasks_message = f"Calling set_tasks with tasks={task_count} for round_id={ctx.current_round_id}"
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

        agent_run_id = iwa_main.generate_agent_run_id(miner_uid)
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
                ctx.current_agent_runs[miner_uid] = agent_run
                ctx.current_miner_snapshots[miner_uid] = ctx.current_miner_snapshots.get(miner_uid) or miner_snapshot
                ctx.agent_run_accumulators.setdefault(miner_uid, {"reward": 0.0, "eval_score": 0.0, "execution_time": 0.0, "tasks": 0})
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
            # Update local state for bookkeeping
            ctx.current_agent_runs[miner_uid] = agent_run
            ctx.current_miner_snapshots[miner_uid] = miner_snapshot
            ctx.agent_run_accumulators.setdefault(miner_uid, {"reward": 0.0, "eval_score": 0.0, "execution_time": 0.0, "tasks": 0})


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
        bt.logging.info("✅ Round completed locally - weights were set on-chain successfully")
        return True

    ended_at = time.time()
    for agent_run in ctx.current_agent_runs.values():
        agent_run.ended_at = ended_at
        agent_run.elapsed_sec = max(0.0, ended_at - agent_run.started_at)

    sorted_miners = sorted(avg_rewards.items(), key=lambda item: item[1], reverse=True)
    summary = {
        "tasks_completed": tasks_completed,
        "active_miners": len(avg_rewards),
    }

    # Get local scores (pre-consensus) if they were saved during IPFS publish
    # If not available, use current avg_rewards (backward compatible)
    local_avg_rewards = getattr(ctx, "_local_avg_rewards_at_publish", None) or avg_rewards

    # Calculate ranks with FINAL scores (for consensus) - needed for post_consensus_evaluation
    rank_map_final = {uid: rank for rank, (uid, _score) in enumerate(sorted_miners, start=1)}

    # Calculate local avg_eval_scores (average of eval_scores for each miner)
    local_avg_eval_scores = {}
    round_eval_scores = getattr(ctx.round_manager, "round_eval_scores", {}) or {}
    for uid, eval_scores_list in round_eval_scores.items():
        if eval_scores_list:
            local_avg_eval_scores[uid] = sum(eval_scores_list) / len(eval_scores_list)
        else:
            local_avg_eval_scores[uid] = 0.0

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

    # Build local_evaluation (pre-consensus) - without weight
    # local_avg_rewards: Dict[uid -> avg_reward] where avg_reward = average of all rewards for that miner
    local_evaluation_miners = []
    local_stats_by_miner: Dict[int, Dict[str, Any]] = {}
    
    # Guardar local_evaluation antes de finish_round para que pueda ser incluido en IPFS
    # (se construye aquí porque necesitamos los datos antes de que termine el round)
    for miner_uid, agent_run in ctx.current_agent_runs.items():
        # Use LOCAL rank for local_evaluation (consistent with local scores)
        rank_value = rank_map_local.get(miner_uid)
        # Use LOCAL avg_reward (pre-consensus) for local_evaluation
        avg_reward_value = local_avg_rewards.get(miner_uid, 0.0)

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
        
        # Obtener miner_hotkey
        miner_hotkey = None
        try:
            # Primero intentar desde snapshots guardados
            miner_snapshot = ctx.current_miner_snapshots.get(miner_uid)
            if miner_snapshot and hasattr(miner_snapshot, "miner_hotkey"):
                miner_hotkey = miner_snapshot.miner_hotkey
            # Fallback a metagraph
            if not miner_hotkey:
                miner_hotkey = ctx.metagraph.hotkeys[miner_uid] if miner_uid < len(ctx.metagraph.hotkeys) else None
        except Exception:
            pass

        miner_stats_entry = {
            "tasks_failed": miner_tasks_failed,
            "tasks_attempted": miner_tasks_attempted,
            "tasks_completed": miner_tasks_completed,
            "avg_evaluation_time": float(avg_time),
        }
        local_stats_by_miner[miner_uid] = {
            "avg_eval_time": float(avg_time),
            "tasks_sent": int(miner_tasks_attempted),
            "tasks_success": int(miner_tasks_completed),
            "tasks_failed": int(miner_tasks_failed),
        }

        # Get local avg_eval_score
        local_avg_eval_score = local_avg_eval_scores.get(miner_uid, 0.0)

        local_evaluation_miners.append(
            {
                "rank": rank_value,
                "avg_reward": float(avg_reward_value),  # Average of all rewards for this miner (pre-consensus, local to this validator)
                "avg_eval_score": float(local_avg_eval_score),  # Average of all eval_scores for this miner (pure evaluation score, 0-1)
                "miner_uid": miner_uid,
                "miner_hotkey": miner_hotkey,  # Miner hotkey for identification
                "miner_name": miner_name,
                "agent_run_id": agent_run.agent_run_id,
                **miner_stats_entry,
            }
        )

    # Build agent_run summaries (still needed for agent_runs field)
    agent_run_summaries: List[iwa_models.FinishRoundAgentRunIWAP] = []
    for miner_data in local_evaluation_miners:
        agent_run_summaries.append(
            iwa_models.FinishRoundAgentRunIWAP(
                agent_run_id=miner_data["agent_run_id"],
                rank=miner_data["rank"],
                miner_name=miner_data["miner_name"],
                avg_reward=miner_data["avg_reward"],
                avg_evaluation_time=miner_data["avg_evaluation_time"],
                tasks_attempted=miner_data["tasks_attempted"],
                tasks_completed=miner_data["tasks_completed"],
                tasks_failed=miner_data["tasks_failed"],
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
                round_num = ctx.round_manager.calculate_round(current_block)
        except Exception:
            # Fallback to stored value if calculation fails
            round_num = getattr(ctx, "_current_round_number", 0) or getattr(ctx, "current_round_number", 0)

    # Build emission info (will be added to round_metadata)
    # alpha_price will be calculated by backend
    from autoppia_web_agents_subnet.validator.config import BURN_AMOUNT_PERCENTAGE, BURN_UID
    
    emission_info = {
        "burn_percentage": float(BURN_AMOUNT_PERCENTAGE) * 100,  # Convert to percentage
        "burn_recipient_uid": int(BURN_UID),
    }

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
        emission=emission_info,
    )

    # Build local_evaluation (what THIS validator evaluated - pre-consensus)
    local_evaluation = {"timestamp": ended_at, "miners": local_evaluation_miners}
    
    # Actualizar el payload IPFS guardado para incluir local_evaluation
    # (aunque se publique antes, actualizamos el payload guardado para que tenga la info completa)
    if hasattr(ctx, "validator") and hasattr(ctx.validator, "_ipfs_uploaded_payload"):
        ctx.validator._ipfs_uploaded_payload["local_evaluation"] = local_evaluation

    # FASE 2: IPFS uploaded data (what THIS validator published)
    ipfs_uploaded = None
    consensus_cid = getattr(ctx, "_consensus_commit_cid", None)
    # Also check if we have the payload (even if commit failed)
    ipfs_payload = getattr(ctx, "_ipfs_uploaded_payload", None)
    ipfs_upload_cid = getattr(ctx, "_ipfs_upload_cid", None)

    if consensus_cid:
        # Use the ACTUAL payload that was uploaded to IPFS (saved when published)
        if not ipfs_payload:
            ipfs_payload = {"note": "Payload not available"}

        ipfs_uploaded = {
            "cid": consensus_cid,
            "published_at": getattr(ctx, "_consensus_publish_timestamp", ended_at - 100),
            "reveal_round": getattr(ctx, "_consensus_reveal_round", 0),
            "commit_version": 4,
            "payload": ipfs_payload,
        }
    elif ipfs_payload and ipfs_upload_cid:
        # Fallback: if we have payload and CID but no consensus_cid (commit failed), still save what we uploaded
        ipfs_uploaded = {
            "cid": ipfs_upload_cid,
            "published_at": getattr(ctx, "_consensus_publish_timestamp", ended_at - 100),
            "reveal_round": getattr(ctx, "_consensus_reveal_round", 0),
            "commit_version": None,  # No commit version if commit failed
            "payload": ipfs_payload,
            "note": "IPFS upload succeeded but blockchain commit may have failed",
        }

    # FASE 3: IPFS downloaded data (what was downloaded from ALL validators)
    # Los payloads descargados tienen la misma estructura que los que se suben (ipfs_uploaded)
    ipfs_downloaded = None
    agg_meta = getattr(ctx, "_agg_meta_cache", None)
    if agg_meta and isinstance(agg_meta, dict):
        # Obtener los payloads originales descargados de IPFS
        downloaded_payloads = agg_meta.get("downloaded_payloads", [])
        
        if downloaded_payloads:
            # Calcular total_stake y validators_participated
            total_stake = sum(p.get("stake", 0.0) for p in downloaded_payloads)
            
            # Guardar los payloads originales tal cual se descargaron de IPFS
            # Cada payload tiene la misma estructura que ipfs_uploaded
            ipfs_downloaded = {
                "timestamp": ended_at,
                "validators_participated": len(downloaded_payloads),
                "total_stake": total_stake,
                "payloads": downloaded_payloads,  # Lista de payloads originales con la misma estructura que ipfs_uploaded
            }

    # Build post_consensus_evaluation (after consensus)
    # NOTE: emission is now in round_metadata, not here
    post_consensus_evaluation = None

    # Get consensus scores (from agg cache if available, otherwise use avg_rewards as fallback)
    # consensus_scores: Dict[uid -> consensus_reward] where consensus_reward = stake-weighted average of avg_rewards from all validators
    consensus_scores = getattr(ctx, "_agg_scores_cache", None)
    if not consensus_scores:
        # Fallback: use avg_rewards if consensus not available
        consensus_scores = avg_rewards

    stats_by_miner = {}
    if agg_meta and isinstance(agg_meta, dict):
        stats_by_miner = agg_meta.get("stats_by_miner", {}) or {}

    if consensus_scores and isinstance(consensus_scores, dict):
        # Calculate ranks from consensus scores
        sorted_consensus = sorted(consensus_scores.items(), key=lambda item: item[1], reverse=True)
        rank_map_consensus = {uid: rank for rank, (uid, _consensus_reward) in enumerate(sorted_consensus, start=1)}

        # Build post_consensus miners list - include all miners with weight > 0 (including burn_uid)
        # BURN_AMOUNT_PERCENTAGE and BURN_UID are already imported above
        
        post_consensus_miners = []
        # First, add all miners from consensus_scores
        for miner_uid, consensus_reward in consensus_scores.items():
            weight = final_weights.get(miner_uid, 0.0)
            rank = rank_map_consensus.get(miner_uid)
            
            # Obtener stats: primero del consensus, luego locales como fallback
            consensus_stats = stats_by_miner.get(miner_uid) or {}
            local_stats = local_stats_by_miner.get(miner_uid) or {}
            
            # Obtener miner_hotkey
            miner_hotkey = None
            try:
                # Primero intentar desde snapshots guardados
                miner_snapshot = ctx.current_miner_snapshots.get(miner_uid)
                if miner_snapshot and hasattr(miner_snapshot, "miner_hotkey"):
                    miner_hotkey = miner_snapshot.miner_hotkey
                # Fallback a metagraph
                if not miner_hotkey:
                    miner_hotkey = ctx.metagraph.hotkeys[miner_uid] if miner_uid < len(ctx.metagraph.hotkeys) else None
            except Exception:
                pass

            # Get avg_eval_score: consensus primero, luego local
            post_consensus_avg_eval_score = consensus_stats.get("avg_eval_score")
            if post_consensus_avg_eval_score is None:
                # Fallback to local avg_eval_score if not in aggregated stats
                post_consensus_avg_eval_score = local_avg_eval_scores.get(miner_uid, 0.0)

            # Asegurar que siempre tengamos los campos requeridos por el backend
            # Usar consensus si está disponible, sino usar datos locales
            avg_eval_time = consensus_stats.get("avg_eval_time") or local_stats.get("avg_eval_time", 0.0)
            tasks_sent = consensus_stats.get("tasks_sent") or local_stats.get("tasks_sent", 0)
            tasks_success = consensus_stats.get("tasks_success") or local_stats.get("tasks_success", 0)

            post_consensus_miners.append(
                {
                    "miner_uid": miner_uid,
                    "miner_hotkey": miner_hotkey,  # Miner hotkey for identification
                    "consensus_reward": float(consensus_reward),  # Stake-weighted average of avg_rewards from all validators
                    "avg_eval_score": float(post_consensus_avg_eval_score),  # Average eval_score (from aggregated stats or local fallback)
                    "avg_eval_time": float(avg_eval_time),  # SIEMPRE presente - consensus o local
                    "tasks_sent": int(tasks_sent),  # SIEMPRE presente - consensus o local
                    "tasks_success": int(tasks_success),  # SIEMPRE presente - consensus o local
                    "weight": float(weight),
                    "rank": rank,
                }
            )

        # Add burn_uid if it has weight > 0 but is not in consensus_scores
        burn_uid = int(BURN_UID)
        burn_weight = final_weights.get(burn_uid, 0.0)
        if burn_weight > 0.0 and burn_uid not in consensus_scores:
            # Burn UID gets a rank after all consensus miners
            max_rank = max(rank_map_consensus.values()) if rank_map_consensus else 0
            # Obtener miner_hotkey para burn_uid
            burn_miner_hotkey = None
            try:
                burn_miner_hotkey = ctx.metagraph.hotkeys[burn_uid] if burn_uid < len(ctx.metagraph.hotkeys) else None
            except Exception:
                pass
            
            post_consensus_miners.append(
                {
                    "miner_uid": burn_uid,
                    "miner_hotkey": burn_miner_hotkey,  # Miner hotkey for identification
                    "consensus_reward": 0.0,  # Burn UID doesn't have a reward
                    "weight": float(burn_weight),
                    "rank": max_rank + 1,
                }
            )

        post_consensus_evaluation = {
            "miners": post_consensus_miners,
            "timestamp": ended_at,
        }
        
        # NOTA: post_consensus_evaluation NO se sube a IPFS
        # Se calcula DESPUÉS de descargar todos los IPFS de otros validadores
        # Solo se guarda para enviarlo al backend en finish_round

    finish_request = iwa_models.FinishRoundIWAP(
        status="completed",
        ended_at=ended_at,
        summary=summary,
        agent_runs=agent_run_summaries,
        round_metadata=round_metadata,
        local_evaluation=local_evaluation,
        post_consensus_evaluation=post_consensus_evaluation,
        ipfs_uploaded=ipfs_uploaded,
        ipfs_downloaded=ipfs_downloaded,
    )

    round_id = ctx.current_round_id
    post_consensus_miners_count = len(post_consensus_evaluation.get("miners", [])) if post_consensus_evaluation else 0
    finish_round_message = f"Calling finish_round for round_id={round_id}, post_consensus_miners={post_consensus_miners_count}, tasks_completed={tasks_completed}"
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
    return success
