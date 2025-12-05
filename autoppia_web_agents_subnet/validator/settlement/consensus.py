from __future__ import annotations

import time
from typing import Any, Dict, Optional

import bittensor as bt
from bittensor import AsyncSubtensor  # type: ignore

from autoppia_web_agents_subnet.validator.config import (
    ENABLE_DISTRIBUTED_CONSENSUS,
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO,
    IPFS_API_URL,
)
from autoppia_web_agents_subnet.utils.commitments import (
    read_all_plain_commitments,
    write_plain_commitment_json,
)
from autoppia_web_agents_subnet.utils.ipfs_client import aadd_json, aget_json
from autoppia_web_agents_subnet.utils.log_colors import ipfs_tag, consensus_tag


def _stake_to_float(stake_val: Any) -> float:
    """Convert various stake representations to a float TAO value."""
    try:
        # bittensor Balance
        from bittensor.utils.balance import Balance  # type: ignore

        if isinstance(stake_val, Balance):
            return float(stake_val.tao)
    except Exception:
        pass
    try:
        return float(stake_val)
    except Exception:
        return 0.0


def _hotkey_to_uid_map(mg) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    try:
        for i, ax in enumerate(getattr(mg, "axons", []) or []):
            hk = getattr(ax, "hotkey", None)
            if hk:
                mapping[hk] = i
    except Exception:
        pass
    # fallback to hotkeys array
    try:
        for i, hk in enumerate(getattr(mg, "hotkeys", []) or []):
            mapping.setdefault(hk, i)
    except Exception:
        pass
    return mapping


async def publish_round_snapshot(
    *,
    validator,
    st: AsyncSubtensor,
    round_number: Optional[int],
    tasks_completed: int,
) -> Optional[str]:
    """
    Publish a mid-round snapshot to IPFS and commit CID on-chain.

    Returns the CID if successful, else None.
    """
    if not ENABLE_DISTRIBUTED_CONSENSUS:
        bt.logging.warning(consensus_tag("Disabled - skipping publish"))
        return None

    # Build payload: per-miner averages so far
    boundaries = validator.round_manager.get_current_boundaries()
    start_epoch = boundaries["round_start_epoch"]
    target_epoch = boundaries["target_epoch"]
    start_block = int(boundaries["round_start_block"])
    target_block = int(boundaries["target_block"])
    avg_rewards = validator.round_manager.get_average_rewards()
    round_rewards = getattr(validator.round_manager, "round_rewards", {}) or {}
    round_times = getattr(validator.round_manager, "round_times", {}) or {}

    # Build per-miner stats to share via IPFS (score + timing + task counters)
    stats_list = []
    for uid, score in (avg_rewards or {}).items():
        rewards_arr = round_rewards.get(uid, []) or []
        times_arr = round_times.get(uid, []) or []
        tasks_sent = len(rewards_arr)
        tasks_success = len([r for r in rewards_arr if r >= 0.5])
        tasks_failed = max(tasks_sent - tasks_success, 0)
        avg_eval_time = sum(times_arr) / len(times_arr) if times_arr else 0.0
        stats_list.append(
            {
                "uid": int(uid),
                "score": float(score),
                "avg_eval_time": float(avg_eval_time),
                "tasks_sent": int(tasks_sent),
                "tasks_success": int(tasks_success),
                "tasks_failed": int(tasks_failed),
            }
        )

    payload = {
        "payload_version": 2,
        # Round/window
        "round_number": int(round_number) if round_number is not None else None,
        "round_start_block": start_block,
        "target_block": target_block,
        "epoch_start": float(start_epoch),
        "epoch_end": float(target_epoch),
        # Validator identity fields
        "validator_hotkey": validator.wallet.hotkey.ss58_address,
        "validator_uid": int(validator.uid),
        "validator_round_id": getattr(validator, "current_round_id", None),
        "validator_version": getattr(validator, "version", None),
        # Per-miner stats (includes score)
        "stats": stats_list,
        # Timestamp for auditability
        "timestamp": time.time(),
    }

    try:
        # 🔍 LOG: Show FULL payload being uploaded
        import json
        payload_json = json.dumps(payload, indent=2, sort_keys=True)

        bt.logging.info("=" * 80)
        round_num_log = payload.get("round_number")
        stats_len = len(payload.get("stats", []) or [])
        bt.logging.info(
            ipfs_tag(
                "UPLOAD",
                f"Round {round_num_log} | {stats_len} miners | Validator UID {payload.get('validator_uid')}",
            )
        )
        bt.logging.info(ipfs_tag("UPLOAD", f"Payload:\n{payload_json}"))

        cid, sha_hex, byte_len = await aadd_json(
            payload,
            filename=f"autoppia_commit_r{round_num_log or 'X'}.json",
            api_url=IPFS_API_URL,
            pin=True,
            sort_keys=True,
        )

        # 🔍 LOG: IPFS upload success
        bt.logging.success(ipfs_tag("UPLOAD", f"✅ SUCCESS - CID: {cid}"))
        bt.logging.info(ipfs_tag("UPLOAD", f"Size: {byte_len} bytes | SHA256: {sha_hex[:16]}..."))
        bt.logging.info(ipfs_tag("UPLOAD", f"Download: http://ipfs.metahash73.com:5001/api/v0/cat?arg={cid}"))
        bt.logging.info("=" * 80)
        
        # FASE 2: Save the actual payload that was uploaded (for finish_round)
        validator._ipfs_uploaded_payload = payload
        # Also save the CID immediately (even if commit fails later)
        validator._ipfs_upload_cid = str(cid)
        validator._consensus_publish_timestamp = time.time()  # Save timestamp when published
        
        # FASE 3: Save local scores at publish time (before consensus can change them)
        validator._local_avg_rewards_at_publish = dict(avg_rewards)
    except Exception as e:
        bt.logging.error("=" * 80)
        bt.logging.error(ipfs_tag("UPLOAD", f"❌ FAILED | Error: {type(e).__name__}: {e}"))
        bt.logging.error(ipfs_tag("UPLOAD", f"API URL: {IPFS_API_URL}"))
        import traceback
        bt.logging.error(ipfs_tag("UPLOAD", f"Traceback:\n{traceback.format_exc()}"))
        bt.logging.error("=" * 80)
        return None

    # On-chain commitment: v4 (CID-only), bind to epoch window
    commit_v4 = {
        "v": 4,
        "e": int(target_epoch) - 1,
        "pe": int(target_epoch),
        "sb": start_block,
        "tb": target_block,
        "c": str(cid),
        "r": int(round_number) if round_number is not None else None,
    }

    try:
        bt.logging.info(
            f"📮 CONSENSUS COMMIT START | blocks {start_block}→{target_block} | "
            f"e={commit_v4['e']}→pe={commit_v4['pe']} r={commit_v4.get('r')} cid={commit_v4['c']}"
        )
        ok = False
        try:
            ok = await write_plain_commitment_json(
                st,
                wallet=validator.wallet,
                data=commit_v4,
                netuid=validator.config.netuid,
            )
        except Exception as e:
            # Catch and log commit exceptions explicitly to avoid bubbling up and
            # prematurely aborting the validator forward loop.
            import asyncio as _asyncio
            if isinstance(e, _asyncio.CancelledError):
                bt.logging.warning(
                    f"📮 CONSENSUS COMMIT RESULT | status=failed error=CancelledError: {e}"
                )
                ok = False
            else:
                raise
        if ok:
            # Record commit context on validator for later aggregation spread checks
            try:
                commit_block = validator.subtensor.get_current_block()
            except Exception:
                commit_block = None
            else:
                try:
                    validator._consensus_commit_block = commit_block
                    validator._consensus_commit_cid = str(cid)
                except Exception:
                    pass

            bt.logging.success(ipfs_tag("BLOCKCHAIN", f"✅ Commitment successful | CID: {cid}"))
            return str(cid)
        else:
            bt.logging.warning(ipfs_tag("BLOCKCHAIN", "⚠️ Commitment failed - write returned false"))
            return None
    except Exception as e:
        bt.logging.error("=" * 80)
        bt.logging.error(ipfs_tag("BLOCKCHAIN", f"❌ Commitment failed | Error: {type(e).__name__}: {e}"))
        import traceback
        bt.logging.error(ipfs_tag("BLOCKCHAIN", f"Traceback:\n{traceback.format_exc()}"))
        bt.logging.error("=" * 80)
        return None


async def aggregate_scores_from_commitments(
    *,
    validator,
    st: AsyncSubtensor,
    start_block: int,
    target_block: int,
) -> tuple[Dict[int, float], Dict[str, Any]]:
    """
    Read all validators' commitments for this round block window and compute
    stake-weighted average scores per miner UID.

    Returns a tuple: (final_scores, details)
      - final_scores: Dict[uid -> aggregated score]
      - details:
          {
            "validators": [ {"hotkey": str, "uid": int|"?", "stake": float, "cid": str} ],
            "scores_by_validator": { hotkey: { uid: score } }
          }
    """
    if not ENABLE_DISTRIBUTED_CONSENSUS:
        raise RuntimeError("Consensus aggregation requested while distributed consensus is disabled")

    # Build hotkey->uid and stake map
    hk_to_uid = _hotkey_to_uid_map(validator.metagraph)
    stake_list = getattr(validator.metagraph, "stake", None)

    def stake_for_hk(hk: str) -> float:
        uid = hk_to_uid.get(hk)
        if uid is None:
            raise RuntimeError(f"No UID mapping found for hotkey {hk}")
        if stake_list is None:
            raise RuntimeError("Metagraph stake information is unavailable")
        try:
            return _stake_to_float(stake_list[uid])  # type: ignore[index]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Unable to read stake for UID {uid}") from exc

    # Fetch all plain commitments and select those for this round (v4 with CID)
    blocks_per_epoch = getattr(validator.round_manager, "BLOCKS_PER_EPOCH", 360)

    commits = await read_all_plain_commitments(st, netuid=validator.config.netuid, block=None)
    start_epoch = start_block / blocks_per_epoch
    target_epoch = target_block / blocks_per_epoch
    expected_window = f"{start_block:,}→{target_block:,} (epochs {start_epoch:.2f}→{target_epoch:.2f})"
    bt.logging.info(consensus_tag(f"Aggregate | Expected blocks {expected_window} | Commitments found: {len(commits or {})}"))
    if commits:
        bt.logging.info(consensus_tag(f"Found {len(commits)} validator commitments:"))
        for hk, entry in list(commits.items())[:5]:
            sb = entry.get("sb") or entry.get("round_start_block")
            tb = entry.get("tb") or entry.get("target_block")
            window_str = f"blocks {sb}→{tb}" if sb is not None and tb is not None else f"epochs {entry.get('e')}→{entry.get('pe')}"
            bt.logging.info(consensus_tag(f"  - {hk[:12]}... | {window_str} | CID {str(entry.get('c', 'N/A'))[:24]}..."))

    expected_start_block = int(start_block)
    expected_target_block = int(target_block)

    bt.logging.info(f"[CONSENSUS] Filtering commitments for current block window: {expected_start_block:,}→{expected_target_block:,}")

    weighted_sum: Dict[int, float] = {}
    weight_total: Dict[int, float] = {}

    included = 0
    skipped_wrong_window = 0
    skipped_missing_cid = 0
    skipped_low_stake = 0
    skipped_ipfs = 0
    skipped_wrong_window_list: list[tuple[str, int, int]] = []  # (hk, start_block, target_block)
    skipped_missing_cid_list: list[str] = []
    skipped_low_stake_list: list[tuple[str, float]] = []  # (hk, stake)
    skipped_ipfs_list: list[tuple[str, str]] = []  # (hk, cid)

    fetched: list[tuple[str, str, float]] = []
    scores_by_validator: Dict[str, Dict[int, float]] = {}
    stats_by_validator: Dict[str, Dict[int, Dict[str, Any]]] = {}
    stats_accumulator: Dict[int, Dict[str, float]] = {}

    blocks_per_epoch = getattr(validator.round_manager, "BLOCKS_PER_EPOCH", 360)

    def _coerce_int(val) -> Optional[int]:
        try:
            if val is None:
                return None
            return int(val)
        except Exception:
            return None

    def _extract_block_window_from_entry(entry_dict: Dict[str, Any]) -> Optional[tuple[int, int]]:
        sb = _coerce_int(entry_dict.get("sb"))
        tb = _coerce_int(entry_dict.get("tb"))
        if sb is not None and tb is not None:
            return sb, tb
        sb = _coerce_int(entry_dict.get("round_start_block"))
        tb = _coerce_int(entry_dict.get("target_block"))
        if sb is not None and tb is not None:
            return sb, tb
        return None

    def _extract_block_window_from_payload(payload_dict: Dict[str, Any]) -> Optional[tuple[int, int]]:
        sb = _coerce_int(payload_dict.get("round_start_block"))
        tb = _coerce_int(payload_dict.get("target_block"))
        if sb is not None and tb is not None:
            return sb, tb
        es = payload_dict.get("es")
        et = payload_dict.get("et")
        try:
            if es is not None and et is not None:
                start_b = int(round(float(es) * blocks_per_epoch))
                target_b = int(round(float(et) * blocks_per_epoch))
                return start_b, target_b
        except Exception:
            return None
        return None

    for hk, entry in (commits or {}).items():
        if not isinstance(entry, dict):
            bt.logging.info(f"[CONSENSUS] Skip {hk[:12]}... | Reason: entry is not dict")
            continue

        entry_window = _extract_block_window_from_entry(entry)
        if entry_window is not None:
            entry_sb, entry_tb = entry_window
            if entry_sb != expected_start_block or entry_tb != expected_target_block:
                skipped_wrong_window += 1
                skipped_wrong_window_list.append((hk, entry_sb, entry_tb))
                bt.logging.debug(
                    f"⏭️ Skip {hk[:10]}…: wrong window (has blocks {entry_sb}→{entry_tb}, need {expected_start_block}→{expected_target_block})"
                )
                continue

        cid = entry.get("c")
        if not isinstance(cid, str) or not cid:
            skipped_missing_cid += 1
            skipped_missing_cid_list.append(hk)
            bt.logging.debug(f"⏭️ Skip {hk[:10]}…: missing or invalid CID")
            continue

        st_val = stake_for_hk(hk)
        validator_uid = hk_to_uid.get(hk, "?")

        if st_val < float(MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO):
            skipped_low_stake += 1
            skipped_low_stake_list.append((hk, st_val))
            bt.logging.debug(
                f"⏭️ Skip {hk[:10]}…: low stake ({st_val:.1f}τ < {float(MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO):.1f}τ)"
            )
            continue

        try:
            payload, _norm, _h = await aget_json(cid, api_url=IPFS_API_URL)
            import json

            payload_json = json.dumps(payload, indent=2, sort_keys=True)

            payload_window = _extract_block_window_from_payload(payload) if isinstance(payload, dict) else None
            if payload_window is not None:
                payload_sb, payload_tb = payload_window
                if payload_sb != expected_start_block or payload_tb != expected_target_block:
                    skipped_wrong_window += 1
                    skipped_wrong_window_list.append((hk, payload_sb, payload_tb))
                    bt.logging.debug(
                        f"⏭️ Skip {hk[:10]}…: payload window {payload_sb}→{payload_tb} does not match {expected_start_block}→{expected_target_block}"
                    )
                    continue

            bt.logging.info("=" * 80)
            bt.logging.info(f"[IPFS] [DOWNLOAD] Validator {hk[:12]}... (UID {validator_uid}) | CID: {cid}")
            bt.logging.info(f"[IPFS] [DOWNLOAD] URL: http://ipfs.metahash73.com:5001/api/v0/cat?arg={cid}")
            bt.logging.info(f"[IPFS] [DOWNLOAD] Payload:\n{payload_json}")
            bt.logging.success(f"[IPFS] [DOWNLOAD] ✅ SUCCESS - Round {payload.get('r')} | {len(payload.get('scores', {}))} miners | Stake: {st_val:.2f}τ")
            bt.logging.info("=" * 80)
        except Exception as e:
            skipped_ipfs += 1
            skipped_ipfs_list.append((hk, str(cid)))
            bt.logging.error(f"❌ IPFS DOWNLOAD FAILED | cid={str(cid)[:20]} error={type(e).__name__}: {e}")
            continue
        if not isinstance(payload, dict):
            bt.logging.info(f"[CONSENSUS] Skip {hk[:12]}... | Reason: payload is not dict")
            continue

        # Stats entries (required)
        stats_entries = payload.get("stats")
        if not isinstance(stats_entries, list):
            bt.logging.debug(f"⏭️ Skip {hk[:10]}…: payload missing required 'stats' list")
            continue

        per_val_stats: Dict[int, Dict[str, Any]] = {}
        per_val_scores: Dict[int, float] = {}

        for item in stats_entries:
            if not isinstance(item, dict):
                continue
            try:
                uid_val = int(item.get("uid"))
            except Exception:
                continue
            stat_entry: Dict[str, Any] = {}
            score_val: Optional[float] = None
            if "score" in item:
                try:
                    score_val = float(item["score"])
                    stat_entry["score"] = score_val
                except Exception:
                    score_val = None
            for key in ("avg_eval_time", "tasks_sent", "tasks_success", "tasks_failed"):
                if key in item:
                    try:
                        stat_entry[key] = float(item[key]) if key == "avg_eval_time" else int(item[key])
                    except Exception:
                        continue
            if stat_entry:
                per_val_stats[uid_val] = stat_entry
                if score_val is not None:
                    per_val_scores[uid_val] = score_val
                # Accumulate aggregates per miner
                acc = stats_accumulator.setdefault(
                    uid_val,
                    {
                        "avg_eval_time_sum": 0.0,
                        "avg_eval_time_count": 0.0,
                        "tasks_sent_sum": 0.0,
                        "tasks_sent_count": 0.0,
                        "tasks_success_sum": 0.0,
                        "tasks_success_count": 0.0,
                        "tasks_failed_sum": 0.0,
                        "tasks_failed_count": 0.0,
                    },
                )
                if "avg_eval_time" in stat_entry:
                    acc["avg_eval_time_sum"] += float(stat_entry["avg_eval_time"])
                    acc["avg_eval_time_count"] += 1
                if "tasks_sent" in stat_entry:
                    acc["tasks_sent_sum"] += float(stat_entry["tasks_sent"])
                    acc["tasks_sent_count"] += 1
                if "tasks_success" in stat_entry:
                    acc["tasks_success_sum"] += float(stat_entry["tasks_success"])
                    acc["tasks_success_count"] += 1
                if "tasks_failed" in stat_entry:
                    acc["tasks_failed_sum"] += float(stat_entry["tasks_failed"])
                    acc["tasks_failed_count"] += 1

        # Require stats with score; otherwise skip this validator
        if not per_val_scores:
            bt.logging.debug(f"⏭️ Skip {hk[:10]}…: no scores found in stats")
            continue

        # Apply stake-weighted aggregation using per_val_scores
        for uid, val in per_val_scores.items():
            effective_weight = st_val if st_val > 0.0 else 1.0
            weighted_sum[uid] = weighted_sum.get(uid, 0.0) + effective_weight * val
            weight_total[uid] = weight_total.get(uid, 0.0) + effective_weight

        included += 1
        fetched.append((hk, cid, st_val))
        scores_by_validator[hk] = per_val_scores
        if per_val_stats:
            stats_by_validator[hk] = per_val_stats

    result: Dict[int, float] = {}
    for uid, wsum in weighted_sum.items():
        denom = weight_total.get(uid, 0.0)
        if denom > 0:
            result[uid] = float(wsum / denom)

    if included > 0:
        all_stakes_zero = all(stake == 0.0 for _, _, stake in fetched)
        consensus_mode = "simple average (all 0τ)" if all_stakes_zero else "stake-weighted"

        bt.logging.success(
            f"[CONSENSUS] ✅ Aggregation complete | Validators: {included} | Miners: {len(result)} | Mode: {consensus_mode}"
        )
        bt.logging.info(
            f"[CONSENSUS] Skipped | Wrong window: {skipped_wrong_window} | Missing CID: {skipped_missing_cid} | Low stake: {skipped_low_stake} | IPFS fail: {skipped_ipfs}"
        )
        # Extra verbose logs to diagnose stake/epoch filtering
        try:
            if skipped_low_stake_list:
                low_str = ", ".join([f"{hk[:10]}…({stake:.0f}τ)" for hk, stake in skipped_low_stake_list])
                bt.logging.debug(f"   ⏭️ Low-stake excluded: {low_str}")
            if skipped_wrong_window_list:
                wrong_str = ", ".join([f"{hk[:10]}…(sb={sb},tb={tb})" for hk, sb, tb in skipped_wrong_window_list])
                bt.logging.debug(f"   ⏭️ Wrong-window excluded: {wrong_str}")
            if skipped_missing_cid_list:
                miss_str = ", ".join([f"{hk[:10]}…" for hk in skipped_missing_cid_list])
                bt.logging.debug(f"   ⏭️ Missing-CID excluded: {miss_str}")
            if skipped_ipfs_list:
                ipfs_str = ", ".join([f"{hk[:10]}…:{cid[:10]}…" for hk, cid in skipped_ipfs_list])
                bt.logging.debug(f"   ⏭️ IPFS-failed: {ipfs_str}")
        except Exception:
            pass
        if len(result) > 0:
            # Log validator contributions used for the aggregation so we can inspect their raw scores.
            try:
                bt.logging.info(
                    f"[CONSENSUS] Validators included ({included}): "
                    + ", ".join(f"{hk[:12]}…(stake={stake:.2f}τ)" for hk, _, stake in fetched)
                )
                for hk, cid, stake in fetched:
                    per_val_scores = scores_by_validator.get(hk, {})
                    miner_count = len(per_val_scores)
                    bt.logging.info(
                        f"[CONSENSUS]   ↳ {hk[:12]}… | miners={miner_count} | stake={stake:.2f}τ | cid={cid}"
                    )
                    if per_val_scores:
                        top_items = list(per_val_scores.items())[:10]
                        for uid, score in top_items:
                            bt.logging.info(f"[CONSENSUS]      UID {uid}: {score:.4f}")
                        if miner_count > len(top_items):
                            bt.logging.info(
                                f"[CONSENSUS]      … {miner_count - len(top_items)} more miners omitted for brevity"
                            )
            except Exception:
                pass
            bt.logging.info(f"[CONSENSUS] Aggregated scores ({len(result)} miners):")
            top_sample = list(sorted(result.items(), key=lambda x: x[1], reverse=True))[:10]
            for uid, score in top_sample:
                bt.logging.info(f"[CONSENSUS]   UID {uid}: {score:.4f}")
        else:
            bt.logging.warning(f"[CONSENSUS] ⚠️ No miners aggregated (all scores were <= 0 or no common miners)")
    else:
        bt.logging.warning(f"[CONSENSUS] ⚠️ No validators included in aggregation")
        bt.logging.info(
            f"[CONSENSUS] Reasons | Wrong window: {skipped_wrong_window} | Missing CID: {skipped_missing_cid} | Low stake: {skipped_low_stake} | IPFS fail: {skipped_ipfs} | Total commits: {len(commits or {})}"
        )

    # Build details structure for reporting/visualization
    validators_info = [
        {"hotkey": hk, "uid": hk_to_uid.get(hk, "?"), "stake": stake, "cid": cid}
        for hk, cid, stake in fetched
    ]
    # Aggregate stats per miner across validators (simple averages where available)
    stats_by_miner: Dict[int, Dict[str, float]] = {}
    for uid, agg in stats_accumulator.items():
        stats_by_miner[uid] = {}
        if agg.get("avg_eval_time_count", 0) > 0:
            stats_by_miner[uid]["avg_eval_time"] = float(
                agg["avg_eval_time_sum"] / agg["avg_eval_time_count"]
            )
        if agg.get("tasks_sent_count", 0) > 0:
            stats_by_miner[uid]["tasks_sent"] = float(
                agg["tasks_sent_sum"] / agg["tasks_sent_count"]
            )
        if agg.get("tasks_success_count", 0) > 0:
            stats_by_miner[uid]["tasks_success"] = float(
                agg["tasks_success_sum"] / agg["tasks_success_count"]
            )
        if agg.get("tasks_failed_count", 0) > 0:
            stats_by_miner[uid]["tasks_failed"] = float(
                agg["tasks_failed_sum"] / agg["tasks_failed_count"]
            )

    details = {
        "validators": validators_info,
        "scores_by_validator": scores_by_validator,
        "stats_by_validator": stats_by_validator,
        "stats_by_miner": stats_by_miner,
        "skips": {
            "wrong_window": skipped_wrong_window_list,
            "missing_cid": skipped_missing_cid_list,
            "low_stake": skipped_low_stake_list,
            "ipfs_fail": skipped_ipfs_list,
        },
    }

    return result, details
