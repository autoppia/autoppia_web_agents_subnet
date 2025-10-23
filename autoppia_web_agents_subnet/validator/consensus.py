from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Tuple

import bittensor as bt
from bittensor import AsyncSubtensor  # type: ignore

from autoppia_web_agents_subnet.validator.config import (
    SHARE_SCORING,
    CONSENSUS_COMMIT_AT_FRACTION,
    MIN_VALIDATOR_STAKE_TO_SHARE_SCORES,
    MIN_VALIDATOR_STAKE_TO_AGGREGATE,
    IPFS_API_URL,
)
from autoppia_web_agents_subnet.utils.ipfs_client import aadd_json, aget_json, minidumps
from autoppia_web_agents_subnet.utils.commitments import (
    write_plain_commitment_json,
    read_all_plain_commitments,
)


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
    if not SHARE_SCORING:
        return None

    # Stake gate: only publish if our stake >= threshold
    try:
        my_uid = int(validator.uid)
        my_stake = _stake_to_float(validator.metagraph.stake[my_uid])  # type: ignore[index]
        if my_stake < float(MIN_VALIDATOR_STAKE_TO_SHARE_SCORES):
            bt.logging.info(
                f"Consensus publish skipped: stake {my_stake:.3f} < threshold {MIN_VALIDATOR_STAKE_TO_SHARE_SCORES:.3f}"
            )
            return None
    except Exception:
        pass

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
        bt.logging.info(
            f"📤 CONSENSUS PUBLISH | round={payload['r']} es={payload['es']} et={payload['et']} "
            f"tasks={payload['n']} agents={payload['agents']} active={str(SHARE_SCORING).lower()}"
        )
        bt.logging.debug(
            "Consensus payload (preview keys): "
            f"scores={len(payload.get('scores') or {})} hk={payload.get('hk')[:10]}… "
            f"vrid={payload.get('validator_round_id')} vv={payload.get('validator_version')}"
        )
        cid, sha_hex, byte_len = await aadd_json(
            payload,
            filename=f"autoppia_commit_r{payload['r'] or 'X'}.json",
            api_url=IPFS_API_URL,
            pin=True,
            sort_keys=True,
        )
    except Exception as e:
        bt.logging.warning(f"IPFS publish failed: {e}")
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
        ok = await write_plain_commitment_json(
            st,
            wallet=validator.wallet,
            data=commit_v4,
            netuid=validator.config.netuid,
        )
        if ok:
            # Record commit context on validator for later aggregation spread checks
            try:
                commit_block = validator.subtensor.get_current_block()
            except Exception:
                commit_block = None
            try:
                validator._consensus_commit_block = commit_block
                validator._consensus_commit_cid = str(cid)
            except Exception:
                pass

            bt.logging.info(
                "📬 CONSENSUS COMMIT | "
                f"e={commit_v4['e']}→pe={commit_v4['pe']} r={commit_v4.get('r')} "
                f"cid={cid} bytes={byte_len} sha256={sha_hex}"
            )
            if commit_block is not None:
                bt.logging.debug(
                    f"Commit recorded at block {commit_block} (will wait for spread before aggregation)"
                )
            return str(cid)
        else:
            bt.logging.warning("On-chain commitment write returned False")
            return None
    except Exception as e:
        bt.logging.warning(f"Commitment write failed: {e}")
        return None


async def aggregate_scores_from_commitments(
    *,
    validator,
    st: AsyncSubtensor,
    start_epoch: float,
    target_epoch: float,
) -> Dict[int, float]:
    """
    Read all validators' commitments for this round window and compute stake-weighted
    average scores per miner UID.
    """
    if not SHARE_SCORING:
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
            f"🔎 CONSENSUS AGGREGATE | expected e={int(target_epoch)-1} pe={int(target_epoch)} | commits_seen={len(commits or {})}"
        )
    except Exception as e:
        bt.logging.warning(f"Failed to read commitments: {e}")
        commits = {}

    # Decide expected e/pe
    e = int(target_epoch) - 1
    pe = int(target_epoch)

    # Accumulate and weight
    weighted_sum: Dict[int, float] = {}
    weight_total: Dict[int, float] = {}

    included = 0
    skipped_wrong_epoch = 0
    skipped_missing_cid = 0
    skipped_low_stake = 0
    skipped_ipfs = 0

    fetched: list[tuple[str, str, float]] = []  # (hotkey, cid, stake)

    for hk, entry in (commits or {}).items():
        if not isinstance(entry, dict):
            continue
        # Match by epoch window only; do not filter by validator version or similar
        if int(entry.get("e", -1)) != e or int(entry.get("pe", -1)) != pe:
            skipped_wrong_epoch += 1
            continue
        cid = entry.get("c")
        if not isinstance(cid, str) or not cid:
            skipped_missing_cid += 1
            continue

        # Stake filter
        st_val = stake_for_hk(hk)
        if st_val < float(MIN_VALIDATOR_STAKE_TO_AGGREGATE):
            skipped_low_stake += 1
            continue

        # Fetch payload from IPFS
        try:
            payload, _norm, _h = await aget_json(cid, api_url=IPFS_API_URL)
        except Exception as e:
            skipped_ipfs += 1
            bt.logging.debug(f"Skip hk={hk[:10]}… — IPFS fetch failed: {e}")
            continue
        if not isinstance(payload, dict):
            continue

        # Validate payload matches window
        try:
            if float(payload.get("es")) != float(start_epoch):
                # Allow float rounding mismatches? Keep strict for now.
                pass
            if float(payload.get("et")) != float(target_epoch):
                pass
        except Exception:
            # still accept; we bound by e/pe already
            pass

        scores = payload.get("scores")
        if not isinstance(scores, dict):
            continue

        # Accumulate stake-weighted
        for uid_s, sc in scores.items():
            try:
                uid = int(uid_s)
                val = float(sc)
            except Exception:
                continue
            if val <= 0:
                continue
            weighted_sum[uid] = weighted_sum.get(uid, 0.0) + st_val * val
            weight_total[uid] = weight_total.get(uid, 0.0) + st_val
        included += 1
        fetched.append((hk, cid, st_val))

    # Normalize
    result: Dict[int, float] = {}
    for uid, wsum in weighted_sum.items():
        denom = weight_total.get(uid, 0.0)
        if denom > 0:
            result[uid] = float(wsum / denom)

    # Summary logs
    if included > 0:
        # Info-level: who was included (short hk) and their CIDs
        hk_list = ", ".join([f"{hk[:10]}…:{cid[:12]}…({stake:.0f}τ)" for hk, cid, stake in fetched])
        bt.logging.info(
            f"🤝 CONSENSUS INCLUDED | validators={included} | miners={len(result)} | {hk_list}"
        )
        # Debug: breakdown of skips
        bt.logging.debug(
            f"Skips — wrong_epoch={skipped_wrong_epoch} missing_cid={skipped_missing_cid} "
            f"low_stake={skipped_low_stake} ipfs_fail={skipped_ipfs}"
        )
        # Debug: show a small sample of aggregated results
        try:
            top_sample = list(sorted(result.items(), key=lambda x: x[1], reverse=True))[:5]
            bt.logging.debug(
                "Aggregated sample: " + ", ".join([f"uid{u}:{s:.4f}" for u, s in top_sample])
            )
        except Exception:
            pass
    else:
        bt.logging.warning("🤝 CONSENSUS INCLUDED | validators=0 (no aggregated scores)")

    return result
