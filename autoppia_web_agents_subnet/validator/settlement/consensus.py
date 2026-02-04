from __future__ import annotations

from typing import Any, Dict, Optional

import bittensor as bt
from bittensor import AsyncSubtensor  # type: ignore

from autoppia_web_agents_subnet.validator.config import (
    CONSENSUS_VERSION,
    ENABLE_DISTRIBUTED_CONSENSUS,
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO,
    IPFS_API_URL,
)
from autoppia_web_agents_subnet.utils.commitments import (
    read_all_plain_commitments,
    write_plain_commitment_json,
)
from autoppia_web_agents_subnet.utils.ipfs_client import add_json_async, get_json_async
from autoppia_web_agents_subnet.utils.log_colors import ipfs_tag, consensus_tag
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase


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
    self,
    *,
    st: AsyncSubtensor,
    scores: Dict[int, float],
) -> Optional[str]:
    """
    Publish round snapshot to IPFS and commit CID on-chain.

    Returns the CID if successful, else None.
    """
    if not ENABLE_DISTRIBUTED_CONSENSUS:
        bt.logging.warning(consensus_tag("Disabled - skipping publish"))
        return None

    self.round_manager.enter_phase(
        RoundPhase.CONSENSUS,
        block=self.block,
        note=f"Publishing consensus snapshot",
    )

    current_block = self.block
    consensus_version = CONSENSUS_VERSION
    season_number = self.season_manager.get_season_number(current_block)
    round_number = self.round_manager.calculate_round(current_block)
    boundaries = self.round_manager.get_current_boundaries()
    start_epoch = int(boundaries["round_start_epoch"])
    target_epoch = int(boundaries["round_target_epoch"])    
    
    payload = {
        "v": int(consensus_version),
        "s": int(season_number),
        "r": int(round_number),
        "es": start_epoch,
        "et": target_epoch,
        "uid": int(self.uid),
        "validator_uid": int(self.uid),
        "hk": self.wallet.hotkey.ss58_address,
        "validator_hotkey": self.wallet.hotkey.ss58_address,
        "validator_round_id": getattr(self, "current_round_id", None),
        "validator_version": getattr(self, "version", None),
        "scores": scores,
    }

    try:
        import json

        payload_json = json.dumps(payload, indent=2, sort_keys=True)

        bt.logging.info("=" * 80)
        bt.logging.info(ipfs_tag("UPLOAD", f"Round {payload.get('r')} | {len(payload.get('scores', {}))} miners"))
        bt.logging.info(ipfs_tag("UPLOAD", f"Payload:\n{payload_json}"))

        cid, sha_hex, byte_len = await add_json_async(
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

    commit_v5 = {
        "v": 5,
        "r": int(round_number),
        "se": start_epoch,
        "te": target_epoch,
        "c": str(cid),
    }

    try:
        bt.logging.info(
            f"📮 CONSENSUS COMMIT START | round {commit_v5['r']} | "
            f"start_epoch {commit_v5['se']} | target_epoch {commit_v5['te']} | cid={commit_v5['c']}"
        )
        ok = await write_plain_commitment_json(
            st,
            wallet=self.wallet,
            data=commit_v5,
            netuid=self.config.netuid,
        )
        if ok:
            try:
                commit_block = self.subtensor.get_current_block()
            except Exception:
                commit_block = None
            else:
                try:
                    self._consensus_commit_block = commit_block
                    self._consensus_commit_cid = str(cid)
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
    self,
    *,
    st: AsyncSubtensor,  
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
    # Build hotkey->uid and stake map
    hk_to_uid = _hotkey_to_uid_map(self.metagraph)
    stake_list = getattr(self.metagraph, "stake", None)

    def stake_for_hk(hk: str) -> float:
        try:
            uid = hk_to_uid.get(hk)
            if uid is None:
                return 0.0
            return _stake_to_float(stake_list[uid]) if stake_list is not None else 0.0  # type: ignore[index]
        except Exception:
            return 0.0

    current_block = self.block
    consensus_version = CONSENSUS_VERSION
    season_number = self.season_manager.get_season_number(current_block)
    round_number = self.round_manager.calculate_round(current_block)

    # Fetch all plain commitments and select those for this round (v5 with CID)
    try:
        commits = await read_all_plain_commitments(st, netuid=self.config.netuid, block=None)
        bt.logging.info(
            consensus_tag(f"Aggregate | Expected round {round_number} | Commitments found: {len(commits or {})}")
        )
        if commits:
            bt.logging.info(consensus_tag(f"Found {len(commits)} validator commitments:"))
            for hk, entry in list(commits.items())[:5]:
                bt.logging.info(
                    consensus_tag(f"  - {hk[:12]}... | Round {entry.get('r')} | Phase {entry.get('p')} | CID {str(entry.get('c', 'N/A'))[:24]}...")
                )
    except Exception as e:
        bt.logging.error(f"❌ Failed to read commitments from blockchain: {e}")
        commits = {}

    bt.logging.info(f"[CONSENSUS] Filtering commitments for current round: {round_number}")

    weighted_sum: Dict[int, float] = {}
    weight_total: Dict[int, float] = {}

    included = 0
    skipped_legacy_consensus_version = 0
    skipped_wrong_season = 0
    skipped_wrong_round = 0
    skipped_missing_cid = 0
    skipped_low_stake = 0
    skipped_ipfs = 0
    skipped_verification_fail = 0
    skipped_legacy_consensus_version_list: list[tuple[str, int]] = []  # (hk, version)
    skipped_wrong_season_list: list[tuple[str, int]] = []  # (hk, season_number)
    skipped_wrong_round_list: list[tuple[str, int]] = []  # (hk, round_number)
    skipped_missing_cid_list: list[str] = []
    skipped_low_stake_list: list[tuple[str, float]] = []  # (hk, stake)
    skipped_ipfs_list: list[tuple[str, str]] = []  # (hk, cid)
    skipped_verification_fail_list: list[tuple[str, str]] = []  # (hk, reason)

    fetched: list[tuple[str, str, float]] = []
    scores_by_validator: Dict[str, Dict[int, float]] = {}

    for hk, entry in (commits or {}).items():
        if not isinstance(entry, dict):
            bt.logging.info(f"[CONSENSUS] Skip {hk[:12]}... | Reason: entry is not dict")
            continue

        entry_consensus_version = int(entry.get("v", -1))
        if entry_consensus_version != consensus_version:
            skipped_legacy_consensus_version += 1
            skipped_legacy_consensus_version_list.append((hk, entry_consensus_version))
            bt.logging.debug(
                f"⏭️ Skip {hk[:10]}…: legacy consensus version (has v={entry_consensus_version}, need v={consensus_version})"
            )
            continue

        entry_season_number = int(entry.get("s", -1))
        if entry_season_number != season_number:
            skipped_wrong_season += 1
            skipped_wrong_season_list.append((hk, entry_season_number))
            bt.logging.debug(
                f"⏭️ Skip {hk[:10]}…: wrong season (has s={entry_season_number}, need s={season_number})"
            )
            continue

        entry_round_number = int(entry.get("r", -1))
        if entry_round_number != round_number:
            skipped_wrong_round += 1
            skipped_wrong_round_list.append((hk, entry_round_number))
            bt.logging.debug(
                f"⏭️ Skip {hk[:10]}…: wrong round (has r={entry_round_number}, need r={round_number})"
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
            payload, _norm, _h = await get_json_async(cid, api_url=IPFS_API_URL)
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
            f"[CONSENSUS] Skipped | "
            f"Legacy consensus version: {skipped_legacy_consensus_version} | "
            f"Wrong season: {skipped_wrong_season} | "
            f"Wrong round: {skipped_wrong_round} | "
            f"Missing CID: {skipped_missing_cid} | "
            f"Low stake: {skipped_low_stake} | "
            f"IPFS fail: {skipped_ipfs} | "
            f"Verify fail: {skipped_verification_fail} | "
        )

        # Extra verbose logs to diagnose stake/epoch filtering
        try:
            if skipped_low_stake_list:
                low_str = ", ".join([f"{hk[:10]}…({stake:.0f}τ)" for hk, stake in skipped_low_stake_list])
                bt.logging.debug(f"   ⏭️ Low-stake excluded: {low_str}")
            if skipped_legacy_consensus_version_list:
                legacy_str = ", ".join([f"{hk[:10]}…(v={vv})" for hk, vv in skipped_legacy_consensus_version_list])
                bt.logging.debug(f"   ⏭️ Legacy-version excluded: {legacy_str}")
            if skipped_wrong_season_list:
                season_str = ", ".join([f"{hk[:10]}…(s={ss})" for hk, ss in skipped_wrong_season_list])
                bt.logging.debug(f"   ⏭️ Wrong-season excluded: {season_str}")
            if skipped_wrong_round_list:
                wrong_str = ", ".join([f"{hk[:10]}…(r={rr})" for hk, rr in skipped_wrong_round_list])
                bt.logging.debug(f"   ⏭️ Wrong-round excluded: {wrong_str}")
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
            f"[CONSENSUS] Reasons | "
            f"Legacy consensus version: {skipped_legacy_consensus_version} | "
            f"Wrong season: {skipped_wrong_season} | "
            f"Wrong round: {skipped_wrong_round} | "
            f"Missing CID: {skipped_missing_cid} | "
            f"Low stake: {skipped_low_stake} | "
            f"IPFS fail: {skipped_ipfs} | "
            f"Verify fail: {skipped_verification_fail} | "
            f"Total commits: {len(commits or {})}"
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
            "legacy_consensus_version": skipped_legacy_consensus_version_list,
            "wrong_season": skipped_wrong_season_list,
            "wrong_round": skipped_wrong_round_list,
            "missing_cid": skipped_missing_cid_list,
            "low_stake": skipped_low_stake_list,
            "ipfs_fail": skipped_ipfs_list,
            "verify_fail": skipped_verification_fail_list,
        },
    }

    return result, details