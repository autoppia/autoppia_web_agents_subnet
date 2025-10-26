from __future__ import annotations

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
    avg_rewards = validator.round_manager.get_average_rewards()

    # Agents that actually received/produced scores (participated)
    try:
        participants = len([u for u, arr in (validator.round_manager.round_rewards or {}).items() if arr])
    except Exception:
        participants = len(getattr(validator, "active_miner_uids", []) or [])

    payload = {
        "v": 1,
        # Round/window
        "r": int(round_number) if round_number is not None else None,
        "round_number": int(round_number) if round_number is not None else None,
        "es": float(start_epoch),
        "et": float(target_epoch),
        # Validator identity fields
        "hk": validator.wallet.hotkey.ss58_address,
        "validator_hotkey": validator.wallet.hotkey.ss58_address,
        "uid": int(validator.uid),  # compact legacy
        "validator_uid": int(validator.uid),
        "validator_id": str(validator.uid),
        "validator_round_id": getattr(validator, "current_round_id", None),
        "validator_version": getattr(validator, "version", None),
        # Stats snapshot
        "n": int(tasks_completed),  # tasks completed so far
        "tasks_completed": int(tasks_completed),
        "agents": int(participants),
        "scores": {str(int(uid)): float(score) for uid, score in (avg_rewards or {}).items()},
    }

    try:
        # 🔍 LOG: Show FULL payload being uploaded
        import json
        payload_json = json.dumps(payload, indent=2, sort_keys=True)

        bt.logging.info("=" * 80)
        bt.logging.info(ipfs_tag("UPLOAD", f"Round {payload['r']} | {len(payload.get('scores', {}))} miners | Validator UID {payload['uid']}"))
        bt.logging.info(ipfs_tag("UPLOAD", f"Payload:\n{payload_json}"))

        cid, sha_hex, byte_len = await aadd_json(
            payload,
            filename=f"autoppia_commit_r{payload['r'] or 'X'}.json",
            api_url=IPFS_API_URL,
            pin=True,
            sort_keys=True,
        )

        # 🔍 LOG: IPFS upload success
        bt.logging.success(ipfs_tag("UPLOAD", f"✅ SUCCESS - CID: {cid}"))
        bt.logging.info(ipfs_tag("UPLOAD", f"Size: {byte_len} bytes | SHA256: {sha_hex[:16]}..."))
        bt.logging.info(ipfs_tag("UPLOAD", f"Download: http://ipfs.metahash73.com:5001/api/v0/cat?arg={cid}"))
        bt.logging.info("=" * 80)
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
        "c": str(cid),
        "r": int(round_number) if round_number is not None else None,
    }

    try:
        bt.logging.info(
            f"📮 CONSENSUS COMMIT START | e={commit_v4['e']}→pe={commit_v4['pe']} "
            f"r={commit_v4.get('r')} cid={commit_v4['c']}"
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
            bt.logging.warning(ipfs_tag("BLOCKCHAIN", f"⚠️ Commitment failed - write returned false"))
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
    start_epoch: float,
    target_epoch: float,
) -> tuple[Dict[int, float], Dict[str, Any]]:
    """
    Read all validators' commitments for this round window and compute stake-weighted
    average scores per miner UID.

    Returns a tuple: (final_scores, details)
      - final_scores: Dict[uid -> aggregated score]
      - details:
          {
            "validators": [ {"hotkey": str, "uid": int|"?", "stake": float, "cid": str} ],
            "scores_by_validator": { hotkey: { uid: score } }
          }
    """
    if not ENABLE_DISTRIBUTED_CONSENSUS:
        return {}

    # Build hotkey->uid and stake map
    hk_to_uid = _hotkey_to_uid_map(validator.metagraph)
    stake_list = getattr(validator.metagraph, "stake", None)

    def stake_for_hk(hk: str) -> float:
        try:
            uid = hk_to_uid.get(hk)
            if uid is None:
                return 0.0
            return _stake_to_float(stake_list[uid]) if stake_list is not None else 0.0  # type: ignore[index]
        except Exception:
            return 0.0

    # Fetch all plain commitments and select those for this round (v4 with CID)
    try:
        commits = await read_all_plain_commitments(st, netuid=validator.config.netuid, block=None)
        bt.logging.info(
            consensus_tag(f"Aggregate | Expected epochs {int(target_epoch)-1}→{int(target_epoch)} | Commitments found: {len(commits or {})}")
        )
        if commits:
            bt.logging.info(consensus_tag(f"Found {len(commits)} validator commitments:"))
            for hk, entry in list(commits.items())[:5]:
                bt.logging.info(
                    consensus_tag(f"  - {hk[:12]}... | Epochs {entry.get('e')}→{entry.get('pe')} | CID {str(entry.get('c', 'N/A'))[:24]}...")
                )
    except Exception as e:
        bt.logging.error(f"❌ Failed to read commitments from blockchain: {e}")
        commits = {}

    e = int(target_epoch) - 1
    pe = int(target_epoch)

    bt.logging.info(f"[CONSENSUS] Filtering commitments for current epoch window: {e}→{pe}")

    weighted_sum: Dict[int, float] = {}
    weight_total: Dict[int, float] = {}

    included = 0
    skipped_wrong_epoch = 0
    skipped_missing_cid = 0
    skipped_low_stake = 0
    skipped_ipfs = 0
    skipped_wrong_epoch_list: list[tuple[str, int, int]] = []  # (hk, e, pe)
    skipped_missing_cid_list: list[str] = []
    skipped_low_stake_list: list[tuple[str, float]] = []  # (hk, stake)
    skipped_ipfs_list: list[tuple[str, str]] = []  # (hk, cid)

    fetched: list[tuple[str, str, float]] = []
    scores_by_validator: Dict[str, Dict[int, float]] = {}

    for hk, entry in (commits or {}).items():
        if not isinstance(entry, dict):
            bt.logging.info(f"[CONSENSUS] Skip {hk[:12]}... | Reason: entry is not dict")
            continue

        entry_e = int(entry.get("e", -1))
        entry_pe = int(entry.get("pe", -1))
        if entry_e != e or entry_pe != pe:
            skipped_wrong_epoch += 1
            skipped_wrong_epoch_list.append((hk, entry_e, entry_pe))
            bt.logging.debug(
                f"⏭️ Skip {hk[:10]}…: wrong epoch (has e={entry_e} pe={entry_pe}, need e={e} pe={pe})"
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

        scores = payload.get("scores")
        if not isinstance(scores, dict):
            continue

        # Record per-validator scores (converted to int uid)
        per_val_map: Dict[int, float] = {}
        for uid_s, sc in scores.items():
            try:
                uid = int(uid_s)
                val = float(sc)
            except Exception:
                continue
            effective_weight = st_val if st_val > 0.0 else 1.0
            weighted_sum[uid] = weighted_sum.get(uid, 0.0) + effective_weight * val
            weight_total[uid] = weight_total.get(uid, 0.0) + effective_weight
            per_val_map[uid] = val
        included += 1
        fetched.append((hk, cid, st_val))
        scores_by_validator[hk] = per_val_map

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
            f"[CONSENSUS] Skipped | Wrong epoch: {skipped_wrong_epoch} | Missing CID: {skipped_missing_cid} | Low stake: {skipped_low_stake} | IPFS fail: {skipped_ipfs}"
        )
        # Extra verbose logs to diagnose stake/epoch filtering
        try:
            if skipped_low_stake_list:
                low_str = ", ".join([f"{hk[:10]}…({stake:.0f}τ)" for hk, stake in skipped_low_stake_list])
                bt.logging.debug(f"   ⏭️ Low-stake excluded: {low_str}")
            if skipped_wrong_epoch_list:
                wrong_str = ", ".join([f"{hk[:10]}…(e={ee},pe={ppe})" for hk, ee, ppe in skipped_wrong_epoch_list])
                bt.logging.debug(f"   ⏭️ Wrong-epoch excluded: {wrong_str}")
            if skipped_missing_cid_list:
                miss_str = ", ".join([f"{hk[:10]}…" for hk in skipped_missing_cid_list])
                bt.logging.debug(f"   ⏭️ Missing-CID excluded: {miss_str}")
            if skipped_ipfs_list:
                ipfs_str = ", ".join([f"{hk[:10]}…:{cid[:10]}…" for hk, cid in skipped_ipfs_list])
                bt.logging.debug(f"   ⏭️ IPFS-failed: {ipfs_str}")
        except Exception:
            pass
        if len(result) > 0:
            bt.logging.info(f"[CONSENSUS] Aggregated scores ({len(result)} miners):")
            top_sample = list(sorted(result.items(), key=lambda x: x[1], reverse=True))[:10]
            for uid, score in top_sample:
                bt.logging.info(f"[CONSENSUS]   UID {uid}: {score:.4f}")
        else:
            bt.logging.warning(f"[CONSENSUS] ⚠️ No miners aggregated (all scores were <= 0 or no common miners)")
    else:
        bt.logging.warning(f"[CONSENSUS] ⚠️ No validators included in aggregation")
        bt.logging.info(
            f"[CONSENSUS] Reasons | Wrong epoch: {skipped_wrong_epoch} | Missing CID: {skipped_missing_cid} | Low stake: {skipped_low_stake} | IPFS fail: {skipped_ipfs} | Total commits: {len(commits or {})}"
        )

    # Build details structure for reporting/visualization
    validators_info = [
        {"hotkey": hk, "uid": hk_to_uid.get(hk, "?"), "stake": stake, "cid": cid}
        for hk, cid, stake in fetched
    ]
    details = {
        "validators": validators_info,
        "scores_by_validator": scores_by_validator,
        "skips": {
            "wrong_epoch": skipped_wrong_epoch_list,
            "missing_cid": skipped_missing_cid_list,
            "low_stake": skipped_low_stake_list,
            "ipfs_fail": skipped_ipfs_list,
        },
    }

    return result, details
