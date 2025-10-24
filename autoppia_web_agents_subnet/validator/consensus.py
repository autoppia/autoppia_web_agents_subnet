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
        bt.logging.info(
            f"📤 CONSENSUS PUBLISH | round={payload['r']} es={payload['es']} et={payload['et']} "
            f"tasks={payload['n']} agents={payload['agents']} active={str(ENABLE_DISTRIBUTED_CONSENSUS).lower()}"
        )

        # 🔍 LOG: Show FULL payload being uploaded
        import json

        payload_json = json.dumps(payload, indent=2, sort_keys=True)
        bt.logging.info("🌐 IPFS UPLOAD START")
        bt.logging.info(f"📍 ENDPOINT: {IPFS_API_URL}")
        bt.logging.info("📦 ========== PAYLOAD BEING UPLOADED TO IPFS ==========")
        bt.logging.info(f"\n{payload_json}")
        bt.logging.info("📦 ======================================================")
        bt.logging.info(
            f"   Summary: Round {payload['r']} | {len(payload.get('scores', {}))} miners | Validator UID {payload['uid']}"
        )

        cid, sha_hex, byte_len = await aadd_json(
            payload,
            filename=f"autoppia_commit_r{payload['r'] or 'X'}.json",
            api_url=IPFS_API_URL,
            pin=True,
            sort_keys=True,
        )

        # 🔍 LOG: IPFS upload success
        bt.logging.info("✅ IPFS UPLOAD SUCCESS")
        bt.logging.info(f"   CID: {cid}")
        bt.logging.info(f"   Size: {byte_len} bytes | SHA256: {sha_hex}")
        bt.logging.info(f"   📍 DOWNLOAD URL: http://ipfs.metahash73.com:5001/api/v0/cat?arg={cid}")
        bt.logging.info(f"   📍 GATEWAY URL: https://ipfs.io/ipfs/{cid}")
    except Exception as e:
        bt.logging.error(f"❌ IPFS UPLOAD FAILED | error={type(e).__name__}: {e}")
        bt.logging.debug(f"IPFS API URL: {IPFS_API_URL}")
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
            else:
                try:
                    validator._consensus_commit_block = commit_block
                    validator._consensus_commit_cid = str(cid)
                except Exception:
                    pass

            bt.logging.info(
                f"📬 CONSENSUS COMMIT | e={commit_v4['e']}→pe={commit_v4['pe']} "
                f"r={commit_v4.get('r')} cid={cid} bytes={byte_len} sha256={sha_hex}"
            )
            if commit_block is not None:
                bt.logging.debug(f"Commit recorded at block {commit_block} (waiting for spread)")
            return str(cid)
        else:
            bt.logging.warning("📮 CONSENSUS COMMIT RESULT | status=failed reason=write_returned_false")
            return None
    except Exception as e:
        bt.logging.warning(f"📮 CONSENSUS COMMIT RESULT | status=failed error={e}")
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
            f"🔎 CONSENSUS AGGREGATE | expected e={int(target_epoch)-1} pe={int(target_epoch)} | commits_seen={len(commits or {})}"
        )
        if commits:
            bt.logging.debug(f"📋 Found commitments from {len(commits)} validators:")
            for hk, entry in list(commits.items())[:5]:
                bt.logging.debug(
                    f"  - {hk[:10]}…: e={entry.get('e')} pe={entry.get('pe')} "
                    f"cid={str(entry.get('c', 'N/A'))[:20]}…"
                )
    except Exception as e:
        bt.logging.error(f"❌ Failed to read commitments from blockchain: {e}")
        commits = {}

    e = int(target_epoch) - 1
    pe = int(target_epoch)

    bt.logging.debug(f"🎯 Filtering for: e={e} pe={pe}")

    weighted_sum: Dict[int, float] = {}
    weight_total: Dict[int, float] = {}

    included = 0
    skipped_wrong_epoch = 0
    skipped_missing_cid = 0
    skipped_low_stake = 0
    skipped_ipfs = 0

    fetched: list[tuple[str, str, float]] = []

    for hk, entry in (commits or {}).items():
        if not isinstance(entry, dict):
            bt.logging.debug(f"⏭️ Skip {hk[:10]}…: entry is not dict")
            continue

        entry_e = int(entry.get("e", -1))
        entry_pe = int(entry.get("pe", -1))
        if entry_e != e or entry_pe != pe:
            skipped_wrong_epoch += 1
            bt.logging.debug(
                f"⏭️ Skip {hk[:10]}…: wrong epoch (has e={entry_e} pe={entry_pe}, need e={e} pe={pe})"
            )
            continue

        cid = entry.get("c")
        if not isinstance(cid, str) or not cid:
            skipped_missing_cid += 1
            bt.logging.debug(f"⏭️ Skip {hk[:10]}…: missing or invalid CID")
            continue

        st_val = stake_for_hk(hk)
        validator_uid = hk_to_uid.get(hk, "?")
        bt.logging.debug(
            f"📊 Validator {hk[:10]}… (UID {validator_uid}): stake={st_val:.2f}τ "
            f"(min required: {float(MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO):.1f}τ)"
        )
        if st_val < float(MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO):
            skipped_low_stake += 1
            bt.logging.debug(
                f"⏭️ Skip {hk[:10]}…: low stake ({st_val:.1f}τ < {float(MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO):.1f}τ)"
            )
            continue

        bt.logging.info(f"🌐 IPFS DOWNLOAD START | validator={hk} cid={cid}")
        try:
            payload, _norm, _h = await aget_json(cid, api_url=IPFS_API_URL)
            import json

            payload_json = json.dumps(payload, indent=2, sort_keys=True)
            bt.logging.info(f"✅ IPFS DOWNLOAD SUCCESS from validator {hk[:20]}…")
            bt.logging.info("📦 ========== PAYLOAD DOWNLOADED FROM IPFS ==========")
            bt.logging.info(f"\n{payload_json}")
            bt.logging.info("📦 ====================================================")
            bt.logging.info(
                f"   Summary: Round {payload.get('r')} | {len(payload.get('scores', {}))} miners "
                f"| Validator UID {payload.get('uid')}"
            )
        except Exception as e:
            skipped_ipfs += 1
            bt.logging.error(f"❌ IPFS DOWNLOAD FAILED | cid={str(cid)[:20]} error={type(e).__name__}: {e}")
            continue
        if not isinstance(payload, dict):
            bt.logging.debug(f"⏭️ Skip {hk[:10]}…: payload is not dict")
            continue

        scores = payload.get("scores")
        if not isinstance(scores, dict):
            continue

        for uid_s, sc in scores.items():
            try:
                uid = int(uid_s)
                val = float(sc)
            except Exception:
                continue
            effective_weight = st_val if st_val > 0.0 else 1.0
            weighted_sum[uid] = weighted_sum.get(uid, 0.0) + effective_weight * val
            weight_total[uid] = weight_total.get(uid, 0.0) + effective_weight
        included += 1
        fetched.append((hk, cid, st_val))

    result: Dict[int, float] = {}
    for uid, wsum in weighted_sum.items():
        denom = weight_total.get(uid, 0.0)
        if denom > 0:
            result[uid] = float(wsum / denom)

    if included > 0:
        all_stakes_zero = all(stake == 0.0 for _, _, stake in fetched)
        consensus_mode = "simple average (all 0τ)" if all_stakes_zero else "stake-weighted"

        hk_list = ", ".join([f"{hk[:10]}…:{cid[:12]}…({stake:.0f}τ)" for hk, cid, stake in fetched])
        bt.logging.info(
            f"🤝 CONSENSUS INCLUDED | validators={included} | miners={len(result)} | mode={consensus_mode} | {hk_list}"
        )
        bt.logging.info(
            f"📊 Skip summary — wrong_epoch={skipped_wrong_epoch} missing_cid={skipped_missing_cid} "
            f"low_stake={skipped_low_stake} ipfs_fail={skipped_ipfs}"
        )
        if len(result) > 0:
            bt.logging.info(f"🎯 CONSENSUS AGGREGATED SCORES ({len(result)} miners):")
            top_sample = list(sorted(result.items(), key=lambda x: x[1], reverse=True))[:10]
            for uid, score in top_sample:
                bt.logging.info(f"   UID {uid}: {score:.4f}")
        else:
            bt.logging.warning("   ⚠️ NO MINERS AGGREGATED (all scores were <= 0 or no common miners)")
        bt.logging.debug(f"Full consensus result: {result}")
    else:
        bt.logging.warning("🤝 CONSENSUS INCLUDED | validators=0 (no aggregated scores)")
        bt.logging.warning(
            "📊 Why no validators? — "
            f"wrong_epoch={skipped_wrong_epoch} missing_cid={skipped_missing_cid} "
            f"low_stake={skipped_low_stake} ipfs_fail={skipped_ipfs} | "
            f"total_commits_seen={len(commits or {})}"
        )

    return result
