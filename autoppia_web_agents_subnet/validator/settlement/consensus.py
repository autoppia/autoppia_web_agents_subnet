from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

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
        from bittensor.utils.balance import Balance  # type: ignore

        if isinstance(stake_val, Balance):
            return float(stake_val.tao)
    except Exception:
        pass
    try:
        return float(stake_val)
    except Exception:
        return 0.0


def _hotkey_to_uid_map(metagraph) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    try:
        for i, ax in enumerate(getattr(metagraph, "axons", []) or []):
            hk = getattr(ax, "hotkey", None)
            if hk:
                mapping[hk] = i
    except Exception:
        pass
    try:
        for i, hk in enumerate(getattr(metagraph, "hotkeys", []) or []):
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

    boundaries = validator.round_manager.get_current_boundaries()
    start_epoch = boundaries["round_start_epoch"]
    target_epoch = boundaries["target_epoch"]
    start_block = int(boundaries["round_start_block"])
    target_block = int(boundaries["target_block"])
    avg_rewards = validator.round_manager.get_average_rewards()

    try:
        participants = len([u for u, arr in (validator.round_manager.round_rewards or {}).items() if arr])
    except Exception:
        participants = len(getattr(validator, "active_miner_uids", []) or [])

    payload = {
        "v": 1,
        "r": int(round_number) if round_number is not None else None,
        "round_number": int(round_number) if round_number is not None else None,
        "es": float(start_epoch),
        "et": float(target_epoch),
        "round_start_block": start_block,
        "target_block": target_block,
        "hk": validator.wallet.hotkey.ss58_address,
        "validator_hotkey": validator.wallet.hotkey.ss58_address,
        "uid": int(validator.uid),
        "validator_uid": int(validator.uid),
        "validator_id": str(validator.uid),
        "validator_round_id": getattr(validator, "current_round_id", None),
        "validator_version": getattr(validator, "version", None),
        "n": int(tasks_completed),
        "tasks_completed": int(tasks_completed),
        "agents": int(participants),
        "scores": {str(int(uid)): float(score) for uid, score in (avg_rewards or {}).items()},
    }

    try:
        import json

        payload_json = json.dumps(payload, indent=2, sort_keys=True)

        bt.logging.info("=" * 80)
        bt.logging.info(ipfs_tag("UPLOAD", f"Round {payload.get('r')} | {len(payload.get('scores', {}))} miners"))
        bt.logging.info(ipfs_tag("UPLOAD", f"Payload:\n{payload_json}"))

        cid, sha_hex, byte_len = await aadd_json(
            payload,
            filename=f"autoppia_commit_r{payload['r'] or 'X'}.json",
            api_url=IPFS_API_URL,
            pin=True,
            sort_keys=True,
        )

        bt.logging.success(ipfs_tag("UPLOAD", f"✅ SUCCESS - CID: {cid}"))
        bt.logging.info(ipfs_tag("UPLOAD", f"Size: {byte_len} bytes | SHA256: {sha_hex[:16]}..."))
        bt.logging.info("=" * 80)
    except Exception as exc:
        bt.logging.error("=" * 80)
        bt.logging.error(ipfs_tag("UPLOAD", f"❌ FAILED | Error: {type(exc).__name__}: {exc}"))
        bt.logging.error(ipfs_tag("UPLOAD", f"API URL: {IPFS_API_URL}"))
        import traceback

        bt.logging.error(ipfs_tag("UPLOAD", f"Traceback:\n{traceback.format_exc()}"))
        bt.logging.error("=" * 80)
        return None

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
        ok = await write_plain_commitment_json(
            st,
            wallet=validator.wallet,
            data=commit_v4,
            netuid=validator.config.netuid,
        )
        if ok:
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
        bt.logging.warning(ipfs_tag("BLOCKCHAIN", "⚠️ Commitment failed - write returned false"))
        return None
    except Exception as exc:
        bt.logging.error("=" * 80)
        bt.logging.error(ipfs_tag("BLOCKCHAIN", f"❌ Commitment failed | Error: {type(exc).__name__}: {exc}"))
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
) -> Tuple[Dict[int, float], Dict[str, Any]]:
    """
    Fetch commitments in the given block window and produce aggregated scores.
    Returns (scores, metadata)
    """
    if not ENABLE_DISTRIBUTED_CONSENSUS:
        return {}, {}

    try:
        commits = await read_all_plain_commitments(
            st,
            wallet=validator.wallet,
            netuid=validator.config.netuid,
        )
    except Exception as exc:
        bt.logging.warning(f"[CONSENSUS] Failed to read commitments: {exc}")
        return {}, {}

    uid_map = _hotkey_to_uid_map(validator.metagraph)

    selected = []
    for commit in commits:
        data = commit.get("data") or {}
        cid = data.get("c")
        sb = data.get("sb")
        tb = data.get("tb")
        if cid is None or sb is None or tb is None:
            continue
        if int(sb) != int(start_block) or int(tb) != int(target_block):
            continue

        hotkey = commit.get("hotkey")
        if not hotkey:
            continue
        uid = uid_map.get(hotkey)
        if uid is None:
            continue

        stake = _stake_to_float(commit.get("stake", 0.0))
        if stake < float(MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO or 0.0):
            bt.logging.debug(
                f"[CONSENSUS] Skipping hotkey {hotkey[:10]}…: insufficient stake {stake}"
            )
            continue

        selected.append((uid, cid, stake))

    if not selected:
        bt.logging.warning("[CONSENSUS] No commitments matched criteria.")
        return {}, {}

    aggregated: Dict[int, float] = {}
    total_stake = 0.0

    for uid, cid, stake in selected:
        try:
            payload = await aget_json(cid, gateways=None)
        except Exception as exc:
            bt.logging.warning(f"[CONSENSUS] Failed to fetch {cid}: {exc}")
            continue

        scores = payload.get("scores") or {}
        for k, v in scores.items():
            try:
                miner_uid = int(k)
                score_val = float(v)
            except Exception:
                continue
            aggregated[miner_uid] = aggregated.get(miner_uid, 0.0) + score_val * stake
        total_stake += stake

    if total_stake <= 0.0:
        bt.logging.warning("[CONSENSUS] Total stake is zero after filtering.")
        return {}, {}

    for k in list(aggregated.keys()):
        aggregated[k] /= total_stake

    meta = {
        "validators": len(selected),
        "total_stake": total_stake,
        "round_start_block": start_block,
        "round_target_block": target_block,
    }
    return aggregated, meta
