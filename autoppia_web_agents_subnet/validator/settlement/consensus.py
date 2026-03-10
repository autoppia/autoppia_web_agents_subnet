from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional

import bittensor as bt
from bittensor import AsyncSubtensor  # type: ignore

from autoppia_web_agents_subnet.validator.config import (
    CONSENSUS_VERSION,
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO,
    IPFS_API_URL,
    LAST_WINNER_BONUS_PCT,
)
from autoppia_web_agents_subnet.utils.commitments import (
    read_all_plain_commitments,
    write_plain_commitment_json,
)
from autoppia_web_agents_subnet.utils.ipfs_client import add_json_async, get_json_async
from autoppia_web_agents_subnet.utils.log_colors import ipfs_tag, consensus_tag
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.platform.client import compute_season_number


def _safe_season_number(self, current_block: int) -> int:
    round_id = str(getattr(self, "current_round_id", "") or "")
    if round_id:
        m = re.match(r"^validator_round_(\d+)_(\d+)_", round_id)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    try:
        sm = getattr(self, "season_manager", None)
        if sm is not None and hasattr(sm, "get_season_number"):
            reference_block = int(getattr(self, "_settlement_round_start_block", 0) or getattr(getattr(self, "round_manager", None), "start_block", 0) or current_block)
            return int(sm.get_season_number(reference_block))
    except Exception:
        pass
    try:
        return int(compute_season_number(current_block))
    except Exception:
        return 0


def _resolve_expected_season_round(self, current_block: int) -> tuple[int, int]:
    """
    Resolve the season/round that is being settled.

    Priority:
    1) `current_round_id` (authoritative for the active round lifecycle)
    2) `_current_round_number` + season from block
    3) block-derived season/round fallback
    """
    round_id = str(getattr(self, "current_round_id", "") or "")
    if round_id:
        m = re.match(r"^validator_round_(\d+)_(\d+)_", round_id)
        if m:
            try:
                return int(m.group(1)), int(m.group(2))
            except Exception:
                pass

    season_number = _safe_season_number(self, current_block)
    try:
        current_round = int(getattr(self, "_current_round_number", 0) or 0)
    except Exception:
        current_round = 0
    if current_round > 0:
        return int(season_number), int(current_round)

    try:
        return int(season_number), int(self.round_manager.calculate_round(current_block))
    except Exception:
        return int(season_number), 0


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


def _payload_log_summary(payload: dict) -> dict:
    """Return a compact payload summary for logs."""
    out = dict(payload)
    rewards = out.get("rewards")
    scores = out.get("scores")
    metrics = out.get("miner_metrics")
    miners = out.get("miners")

    def _summarize_rewards_map(raw: Any) -> str | None:
        if not isinstance(raw, dict):
            return None
        vals = []
        for v in raw.values():
            try:
                vals.append(float(v))
            except Exception:
                continue
        if len(raw) <= 10:
            return None
        nz = sum(1 for v in vals if float(v) > 0.0)
        return f"<{len(raw)} miners, non_zero={nz}, sum={sum(vals):.4f}>"

    rewards_summary = _summarize_rewards_map(rewards)
    if rewards_summary:
        out["rewards"] = rewards_summary

    scores_summary = _summarize_rewards_map(scores)
    if scores_summary:
        out["scores"] = scores_summary

    if isinstance(metrics, dict) and len(metrics) > 10:
        handshake_ok = 0
        for entry in metrics.values():
            if isinstance(entry, dict) and entry.get("handshake_ok") is True:
                handshake_ok += 1
        out["miner_metrics"] = f"<{len(metrics)} miners, handshake_ok={handshake_ok}>"

    if isinstance(miners, list) and len(miners) > 10:
        out["miners"] = f"<{len(miners)} miners>"

    return out


def _normalize_rewards_map(raw_scores: Dict[Any, Any]) -> Dict[str, float]:
    normalized: Dict[str, float] = {}
    for uid_raw, score_raw in (raw_scores or {}).items():
        try:
            uid_i = int(uid_raw)
            score_f = float(score_raw)
        except Exception:
            continue
        normalized[str(uid_i)] = float(score_f)
    return normalized


def _extract_metric_value(entry: dict, *keys: str) -> Optional[float]:
    for key in keys:
        if key not in entry:
            continue
        try:
            return float(entry.get(key))
        except Exception:
            continue
    return None


def _extract_int_metric_value(entry: dict, *keys: str) -> Optional[int]:
    for key in keys:
        if key not in entry:
            continue
        try:
            return int(entry.get(key))
        except Exception:
            continue
    return None


def _eligibility_status_is_valid(status: Any) -> bool:
    return str(status or "").strip().lower() in {"handshake_valid", "reused", "evaluated"}


def _extract_metrics_from_payload(payload: Dict[str, Any]) -> tuple[Dict[int, float], Dict[int, Dict[str, Any]]]:
    rewards: Dict[int, float] = {}
    metrics: Dict[int, Dict[str, Any]] = {}

    miners = payload.get("miners")
    if isinstance(miners, list):
        for miner_entry in miners:
            if not isinstance(miner_entry, dict):
                continue
            miner_uid = miner_entry.get("uid") or miner_entry.get("miner_uid")
            try:
                uid = int(miner_uid)
            except Exception:
                continue
            best_run = miner_entry.get("best_run")
            if not isinstance(best_run, dict):
                best_run = None
            reward = 0.0
            score = 0.0
            avg_time = 0.0
            avg_cost = 0.0
            tasks_received = 0
            tasks_success = 0
            if best_run is not None:
                try:
                    reward = float(best_run.get("reward", 0.0) or 0.0)
                except Exception:
                    reward = 0.0
                try:
                    score = float(best_run.get("score", 0.0) or 0.0)
                except Exception:
                    score = 0.0
                try:
                    avg_time = float(best_run.get("time", 0.0) or 0.0)
                except Exception:
                    avg_time = 0.0
                try:
                    avg_cost = float(best_run.get("cost", 0.0) or 0.0)
                except Exception:
                    avg_cost = 0.0
                try:
                    tasks_received = int(best_run.get("tasks_received", 0) or 0)
                except Exception:
                    tasks_received = 0
                try:
                    tasks_success = int(best_run.get("tasks_success", 0) or 0)
                except Exception:
                    tasks_success = 0
            rewards[uid] = reward
            metrics[uid] = {
                "avg_reward": reward,
                "avg_eval_score": score,
                "avg_eval_time": avg_time,
                "avg_cost": avg_cost,
                "tasks_sent": tasks_received,
                "tasks_success": tasks_success,
            }
        return rewards, metrics

    rewards_raw = payload.get("rewards")
    if not isinstance(rewards_raw, dict):
        rewards_raw = payload.get("scores")
    if isinstance(rewards_raw, dict):
        for uid_raw, value_raw in rewards_raw.items():
            try:
                uid = int(uid_raw)
                rewards[uid] = float(value_raw)
            except Exception:
                continue

    miner_metrics = payload.get("miner_metrics")
    if isinstance(miner_metrics, dict):
        for uid_raw, entry_raw in miner_metrics.items():
            if not isinstance(entry_raw, dict):
                continue
            try:
                uid = int(entry_raw.get("miner_uid", uid_raw))
            except Exception:
                continue
            metrics[uid] = entry_raw
    return rewards, metrics


def _extract_current_run_metrics_from_payload(payload: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    metrics: Dict[int, Dict[str, Any]] = {}
    miners = payload.get("miners")
    if not isinstance(miners, list):
        return metrics
    for miner_entry in miners:
        if not isinstance(miner_entry, dict):
            continue
        current_run = miner_entry.get("current_run")
        if not isinstance(current_run, dict):
            continue
        try:
            uid = int(miner_entry.get("uid", miner_entry.get("miner_uid")))
        except Exception:
            continue
        metrics[uid] = {
            "avg_reward": float(current_run.get("reward", 0.0) or 0.0),
            "avg_eval_score": float(current_run.get("score", 0.0) or 0.0),
            "avg_eval_time": float(current_run.get("time", 0.0) or 0.0),
            "avg_cost": float(current_run.get("cost", 0.0) or 0.0),
            "tasks_sent": int(current_run.get("tasks_received", 0) or 0),
            "tasks_success": int(current_run.get("tasks_success", 0) or 0),
        }
    return metrics


def _summary_snapshot_from_run(uid: Optional[int], run_payload: Optional[Dict[str, Any]], *, weight: Optional[float] = None) -> Optional[Dict[str, Any]]:
    if uid is None:
        return None
    snapshot = {
        "uid": int(uid),
        "reward": 0.0,
        "score": 0.0,
        "time": 0.0,
        "cost": 0.0,
    }
    if isinstance(run_payload, dict):
        try:
            snapshot["reward"] = round(float(run_payload.get("reward", 0.0) or 0.0), 4)
        except Exception:
            pass
        try:
            snapshot["score"] = round(float(run_payload.get("score", 0.0) or 0.0), 4)
        except Exception:
            pass
        try:
            snapshot["time"] = round(float(run_payload.get("time", 0.0) or 0.0), 4)
        except Exception:
            pass
        try:
            snapshot["cost"] = round(float(run_payload.get("cost", 0.0) or 0.0), 4)
        except Exception:
            pass
    if weight is not None:
        snapshot["weight"] = float(weight)
    return snapshot


def _build_local_round_summary(
    self,
    *,
    season_number: int,
    round_number: int,
    miners_payload: list[dict[str, Any]],
) -> Dict[str, Any]:
    try:
        percentage_to_dethrone = max(float(LAST_WINNER_BONUS_PCT), 0.0)
    except Exception:
        percentage_to_dethrone = 0.05

    season_history = getattr(self, "_season_competition_history", None) or {}
    season_state = season_history.get(int(season_number), {}) if isinstance(season_history, dict) else {}
    if not isinstance(season_state, dict):
        season_state = {}
    summary_state = season_state.get("summary", {})
    if not isinstance(summary_state, dict):
        summary_state = {}

    leader_before = None
    reigning_uid_raw = summary_state.get("current_winner_uid")
    try:
        reigning_uid = int(reigning_uid_raw) if reigning_uid_raw is not None else None
    except Exception:
        reigning_uid = None
    if reigning_uid is not None:
        leader_before = summary_state.get("current_winner_snapshot")
        if not isinstance(leader_before, dict):
            best_snapshots = summary_state.get("best_snapshot_by_miner", {})
            if isinstance(best_snapshots, dict):
                leader_before = best_snapshots.get(str(reigning_uid)) or best_snapshots.get(reigning_uid)
        leader_before = _summary_snapshot_from_run(reigning_uid, leader_before)

    ranked_candidates: list[tuple[tuple[float, float, float, int], dict[str, Any], dict[str, Any]]] = []
    for miner in miners_payload:
        if not isinstance(miner, dict):
            continue
        best_run = miner.get("best_run")
        if not isinstance(best_run, dict):
            continue
        try:
            reward = float(best_run.get("reward", 0.0) or 0.0)
            score = float(best_run.get("score", 0.0) or 0.0)
            avg_time = float(best_run.get("time", 0.0) or 0.0)
            uid = int(miner.get("uid"))
        except Exception:
            continue
        key = (reward, score, -avg_time, -uid)
        ranked_candidates.append((key, miner, best_run))

    ranked_candidates.sort(key=lambda item: item[0], reverse=True)

    top_entry = ranked_candidates[0][1] if ranked_candidates else None
    top_run = ranked_candidates[0][2] if ranked_candidates else None
    candidate_entry = None
    candidate_run = None
    if reigning_uid is not None:
        for _key, miner, best_run in ranked_candidates:
            try:
                if int(miner.get("uid")) == int(reigning_uid):
                    continue
            except Exception:
                continue
            candidate_entry = miner
            candidate_run = best_run
            break
    else:
        candidate_entry = top_entry
        candidate_run = top_run

    candidate_snapshot = None
    if isinstance(candidate_entry, dict):
        candidate_snapshot = _summary_snapshot_from_run(candidate_entry.get("uid"), candidate_run)

    top_snapshot = None
    if isinstance(top_entry, dict):
        top_snapshot = _summary_snapshot_from_run(top_entry.get("uid"), top_run)

    leader_after = top_snapshot
    dethroned = False
    if leader_before is not None:
        leader_before_reward = float(leader_before.get("reward", 0.0) or 0.0)
        candidate_reward = float(candidate_snapshot.get("reward", 0.0) or 0.0) if candidate_snapshot else 0.0
        if candidate_snapshot is None:
            leader_after = leader_before
        else:
            threshold = leader_before_reward * (1.0 + percentage_to_dethrone)
            if candidate_reward > threshold:
                dethroned = True
                leader_after = candidate_snapshot
            else:
                leader_after = leader_before

    return {
        "season": int(season_number),
        "round": int(round_number),
        "percentage_to_dethrone": float(percentage_to_dethrone),
        "dethroned": bool(dethroned),
        "leader_before_round": leader_before,
        "candidate_this_round": candidate_snapshot,
        "leader_after_round": leader_after,
    }


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


def _aggregate_scores_for_validators(
    entries: Any,
) -> tuple[Dict[int, float], bool]:
    """
    Aggregate per-validator scores into final miner scores.

    Args:
        entries: Iterable of (stake, scores_dict) where:
            - stake: numeric stake value for the validator (TAO or 0.0)
            - scores_dict: mapping uid -> score in [0, 1]

    Returns:
        (result, all_stakes_zero)
          - result: dict[uid -> aggregated score]
          - all_stakes_zero: True if all original stakes were exactly 0.0
    """
    weighted_sum: Dict[int, float] = {}
    weight_total: Dict[int, float] = {}
    original_stakes: list[float] = []

    try:
        iterator = list(entries)
    except TypeError:
        iterator = []

    for stake_val, scores in iterator:
        try:
            st_val = float(stake_val)
        except Exception:
            st_val = 0.0
        original_stakes.append(st_val)

        # If stake is zero or invalid, treat validator as having unit weight.
        effective_weight = st_val if st_val > 0.0 else 1.0

        if not isinstance(scores, dict):
            continue

        for uid_raw, sc_raw in scores.items():
            try:
                uid = int(uid_raw)
                val = float(sc_raw)
            except Exception:
                continue

            weighted_sum[uid] = weighted_sum.get(uid, 0.0) + effective_weight * val
            weight_total[uid] = weight_total.get(uid, 0.0) + effective_weight

    result: Dict[int, float] = {}
    for uid, wsum in weighted_sum.items():
        denom = weight_total.get(uid, 0.0)
        if denom > 0:
            result[uid] = float(wsum / denom)

    all_stakes_zero = bool(original_stakes) and all(st == 0.0 for st in original_stakes)
    return result, all_stakes_zero


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
    self.round_manager.enter_phase(
        RoundPhase.CONSENSUS,
        block=self.block,
        note="Publishing consensus snapshot",
    )

    current_block = self.block
    consensus_version = CONSENSUS_VERSION
    season_number, round_number = _resolve_expected_season_round(self, current_block)
    boundaries = self.round_manager.get_current_boundaries()
    start_epoch = int(boundaries["round_start_epoch"])
    target_epoch = int(boundaries["round_target_epoch"])
    _ = scores
    miners_payload = []
    active_uids = sorted({int(uid) for uid in (getattr(self, "active_miner_uids", None) or [])} | {int(uid) for uid in (getattr(self, "current_agent_runs", None) or {}).keys()})
    for uid in active_uids:
        miner_hotkey = None
        try:
            miner_hotkey = self.metagraph.hotkeys[uid] if uid < len(self.metagraph.hotkeys) else None
        except Exception:
            miner_hotkey = None
        miner_name = None
        try:
            agent_info = getattr(self, "agents_dict", {}).get(uid)
            miner_name = getattr(agent_info, "agent_name", None)
        except Exception:
            miner_name = None
        miners_payload.append(
            {
                "uid": int(uid),
                "hotkey": miner_hotkey,
                "miner_name": miner_name,
                "best_run": getattr(self, "_best_run_payload_for_miner")(uid),
                "current_run": getattr(self, "_current_round_run_payload")(uid),
            }
        )
    local_summary = _build_local_round_summary(
        self,
        season_number=int(season_number),
        round_number=int(round_number),
        miners_payload=miners_payload,
    )
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
        "miners": miners_payload,
        "summary": local_summary,
    }
    try:
        self._ipfs_uploaded_payload = dict(payload)
    except Exception:
        pass

    try:
        import json

        payload_json = json.dumps(_payload_log_summary(payload), separators=(",", ":"), sort_keys=True)

        bt.logging.info("=" * 80)
        bt.logging.info(ipfs_tag("UPLOAD", f"Round {payload.get('r')} | {len(payload.get('miners', []))} miners"))
        bt.logging.info(ipfs_tag("UPLOAD", f"Payload: {payload_json}"))

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
        try:
            self._ipfs_upload_cid = str(cid)
            self._consensus_publish_timestamp = time.time()
        except Exception:
            pass
    except Exception as exc:
        bt.logging.error("=" * 80)
        bt.logging.error(ipfs_tag("UPLOAD", f"❌ FAILED | Error: {type(exc).__name__}: {exc}"))
        bt.logging.error(ipfs_tag("UPLOAD", f"API URL: {IPFS_API_URL}"))
        import traceback

        bt.logging.error(ipfs_tag("UPLOAD", f"Traceback:\n{traceback.format_exc()}"))
        bt.logging.error("=" * 80)
        return None

    # Keep the on-chain commitment payload small and versioned for compatibility
    # across validators. The IPFS payload holds the verbose metadata.
    commit_payload = {
        "v": int(consensus_version),
        "s": int(season_number),
        "r": int(round_number),
        "c": str(cid),
        "p": 0,  # phase placeholder for future extensions
    }

    try:
        bt.logging.info(f"📮 CONSENSUS COMMIT START | v={commit_payload['v']} s={commit_payload['s']} r={commit_payload['r']} | cid={commit_payload['c']}")
        ok = await write_plain_commitment_json(
            st,
            wallet=self.wallet,
            data=commit_payload,
            netuid=self.config.netuid,
        )
        if ok:
            try:
                commit_block = self.get_current_block(fresh=True)
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
    Read validators' commitments for the current round and compute consensus metrics.

    The consensus winner signal is the stake-weighted average of each validator's
    published per-miner reward. In parallel we also aggregate the observability
    metrics carried in `miner_metrics` using the same stake weights:
    `avg_reward`, `avg_eval_score`, `avg_eval_time`, `avg_cost`, `tasks_sent`,
    and `tasks_success`.

    Returns a tuple: (consensus_rewards, details)
      - consensus_rewards: Dict[uid -> stake-weighted consensus reward]
      - details:
          {
            "validators": [ {"hotkey": str, "uid": int|"?", "stake": float, "cid": str} ],
            "scores_by_validator": { hotkey: { uid: reward } }
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
    season_number, round_number = _resolve_expected_season_round(self, current_block)

    # Fetch all plain commitments and select those for this round (v5 with CID)
    try:
        commits = await read_all_plain_commitments(st, netuid=self.config.netuid, block=None)
        bt.logging.info(consensus_tag(f"Aggregate | Expected round {round_number} | Commitments found: {len(commits or {})}"))
        if commits:
            bt.logging.info(consensus_tag(f"Found {len(commits)} validator commitments:"))
            for hk, entry in list(commits.items())[:5]:
                bt.logging.info(consensus_tag(f"  - {hk[:12]}... | Round {entry.get('r')} | Phase {entry.get('p')} | CID {str(entry.get('c', 'N/A'))[:24]}..."))
    except Exception as e:
        bt.logging.error(f"❌ Failed to read commitments from blockchain: {e}")
        commits = {}

    # Descargado: en el bloque actual se leen los commitments on-chain; solo se aceptan los que
    # cumplen s=season, r=round, v=1 (consensus version) y validator_version compatible; para
    # cada uno se descarga ese CID y se obtiene ese JSON.
    bt.logging.info(f"[CONSENSUS] Filtering commitments for current round: {round_number}")

    weighted_sum: Dict[int, float] = {}
    weight_total: Dict[int, float] = {}
    metric_acc: Dict[int, Dict[str, float]] = {}
    current_metric_acc: Dict[int, Dict[str, float]] = {}

    included = 0
    skipped_legacy_consensus_version = 0
    skipped_wrong_season = 0
    skipped_wrong_round = 0
    skipped_missing_cid = 0
    skipped_low_stake = 0
    skipped_ipfs = 0
    skipped_verification_fail = 0
    skipped_wrong_validator_version = 0
    skipped_legacy_consensus_version_list: list[tuple[str, int]] = []  # (hk, version)
    skipped_wrong_season_list: list[tuple[str, int]] = []  # (hk, season_number)
    skipped_wrong_round_list: list[tuple[str, int]] = []  # (hk, round_number)
    skipped_missing_cid_list: list[str] = []
    skipped_low_stake_list: list[tuple[str, float]] = []  # (hk, stake)
    skipped_ipfs_list: list[tuple[str, str]] = []  # (hk, cid)
    skipped_verification_fail_list: list[tuple[str, str]] = []  # (hk, reason)
    skipped_wrong_validator_version_list: list[tuple[str, str]] = []  # (hk, payload_version)

    fetched: list[tuple[str, str, float]] = []
    scores_by_validator: Dict[str, Dict[int, float]] = {}
    downloaded_payloads: list[Dict[str, Any]] = []

    for hk, entry in (commits or {}).items():
        if not isinstance(entry, dict):
            bt.logging.info(f"[CONSENSUS] Skip {hk[:12]}... | Reason: entry is not dict")
            continue

        # Backward compatible parsing: older commitments may omit v/s.
        raw_v = entry.get("v", None)
        if raw_v is None:
            entry_consensus_version = int(consensus_version)
        else:
            try:
                entry_consensus_version = int(raw_v)
            except Exception:
                entry_consensus_version = -1
        if entry_consensus_version != int(consensus_version):
            skipped_legacy_consensus_version += 1
            skipped_legacy_consensus_version_list.append((hk, entry_consensus_version))
            bt.logging.debug(f"⏭️ Skip {hk[:10]}…: legacy consensus version (has v={entry_consensus_version}, need v={consensus_version})")
            continue

        raw_s = entry.get("s", None)
        if raw_s is None:
            entry_season_number = int(season_number)
        else:
            try:
                entry_season_number = int(raw_s)
            except Exception:
                entry_season_number = -1
        if entry_season_number != int(season_number):
            skipped_wrong_season += 1
            skipped_wrong_season_list.append((hk, entry_season_number))
            bt.logging.debug(f"⏭️ Skip {hk[:10]}…: wrong season (has s={entry_season_number}, need s={season_number})")
            continue

        entry_round_number = int(entry.get("r", -1))
        if entry_round_number != round_number:
            skipped_wrong_round += 1
            skipped_wrong_round_list.append((hk, entry_round_number))
            bt.logging.debug(f"⏭️ Skip {hk[:10]}…: wrong round (has r={entry_round_number}, need r={round_number})")
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
            bt.logging.debug(f"⏭️ Skip {hk[:10]}…: low stake ({st_val:.1f}τ < {float(MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO):.1f}τ)")
            continue

        try:
            payload, _norm, _h = await get_json_async(cid, api_url=IPFS_API_URL)
            import json

            payload_json = json.dumps(_payload_log_summary(payload), separators=(",", ":"), sort_keys=True)

            bt.logging.info("=" * 80)
            bt.logging.info(f"[IPFS] [DOWNLOAD] Validator {hk[:12]}... (UID {validator_uid}) | CID: {cid}")
            bt.logging.info(f"[IPFS] [DOWNLOAD] URL: http://ipfs.metahash73.com:5001/api/v0/cat?arg={cid}")
            bt.logging.info(f"[IPFS] [DOWNLOAD] Payload: {payload_json}")
            payload_rewards, payload_metrics = _extract_metrics_from_payload(payload)
            miner_count = len(payload_rewards)
            bt.logging.success(f"[IPFS] [DOWNLOAD] ✅ SUCCESS - Round {payload.get('r')} | {miner_count} miners | Stake: {st_val:.2f}τ")
            bt.logging.info("=" * 80)
        except Exception as e:
            skipped_ipfs += 1
            skipped_ipfs_list.append((hk, str(cid)))
            bt.logging.error(f"❌ IPFS DOWNLOAD FAILED | cid={str(cid)[:20]} error={type(e).__name__}: {e}")
            continue
        if not isinstance(payload, dict):
            bt.logging.info(f"[CONSENSUS] Skip {hk[:12]}... | Reason: payload is not dict")
            continue

        # También debe coincidir el validator_version del payload con el de este validator.
        expected_validator_version = getattr(self, "version", None)
        if expected_validator_version is not None:
            payload_validator_version = payload.get("validator_version")
            if payload_validator_version != expected_validator_version:
                skipped_wrong_validator_version += 1
                pv_str = str(payload_validator_version) if payload_validator_version is not None else "missing"
                skipped_wrong_validator_version_list.append((hk, pv_str))
                bt.logging.debug(f"⏭️ Skip {hk[:10]}…: wrong validator_version (payload has {pv_str}, need {expected_validator_version})")
                continue

        rewards, miner_metrics = _extract_metrics_from_payload(payload)
        current_run_metrics = _extract_current_run_metrics_from_payload(payload)
        if not isinstance(rewards, dict) or not rewards:
            continue

        # Record each validator's published per-miner reward map (converted to int uid).
        per_val_map: Dict[int, float] = {}
        effective_weight = st_val if st_val > 0.0 else 1.0
        for uid_s, sc in rewards.items():
            try:
                uid = int(uid_s)
                val = float(sc)
            except Exception:
                continue
            weighted_sum[uid] = weighted_sum.get(uid, 0.0) + effective_weight * val
            weight_total[uid] = weight_total.get(uid, 0.0) + effective_weight
            per_val_map[uid] = val

        if isinstance(miner_metrics, dict):
            for uid_raw, entry_raw in miner_metrics.items():
                if not isinstance(entry_raw, dict):
                    continue
                try:
                    metric_uid = int(entry_raw.get("miner_uid", uid_raw))
                except Exception:
                    try:
                        metric_uid = int(uid_raw)
                    except Exception:
                        continue
                acc = metric_acc.setdefault(
                    metric_uid,
                    {
                        "avg_reward_num": 0.0,
                        "avg_reward_den": 0.0,
                        "avg_eval_score_num": 0.0,
                        "avg_eval_score_den": 0.0,
                        "avg_eval_time_num": 0.0,
                        "avg_eval_time_den": 0.0,
                        "avg_cost_num": 0.0,
                        "avg_cost_den": 0.0,
                        "tasks_sent_sum": 0,
                        "tasks_success_sum": 0,
                        "handshake_ok_num": 0.0,
                        "handshake_ok_den": 0.0,
                    },
                )

                avg_reward = _extract_metric_value(entry_raw, "avg_reward", "reward")
                if avg_reward is None and metric_uid in per_val_map:
                    avg_reward = float(per_val_map[metric_uid])
                if avg_reward is not None:
                    acc["avg_reward_num"] += effective_weight * float(avg_reward)
                    acc["avg_reward_den"] += effective_weight

                avg_eval_score = _extract_metric_value(entry_raw, "avg_eval_score")
                if avg_eval_score is not None:
                    acc["avg_eval_score_num"] += effective_weight * float(avg_eval_score)
                    acc["avg_eval_score_den"] += effective_weight

                avg_eval_time = _extract_metric_value(entry_raw, "avg_eval_time")
                if avg_eval_time is None:
                    avg_eval_time = _extract_metric_value(entry_raw, "avg_evaluation_time")
                if avg_eval_time is not None:
                    acc["avg_eval_time_num"] += effective_weight * float(avg_eval_time)
                    acc["avg_eval_time_den"] += effective_weight

                avg_cost = _extract_metric_value(entry_raw, "avg_cost")
                if avg_cost is None:
                    avg_cost = _extract_metric_value(entry_raw, "avg_cost_per_task")
                if avg_cost is not None:
                    acc["avg_cost_num"] += effective_weight * float(avg_cost)
                    acc["avg_cost_den"] += effective_weight

                tasks_sent = _extract_int_metric_value(entry_raw, "tasks_sent", "tasks_attempted")
                if tasks_sent is not None:
                    acc["tasks_sent_sum"] += int(tasks_sent)

                tasks_success = _extract_int_metric_value(entry_raw, "tasks_success", "tasks_completed")
                if tasks_success is not None:
                    acc["tasks_success_sum"] += int(tasks_success)

                handshake_ok = entry_raw.get("handshake_ok")
                if isinstance(handshake_ok, bool):
                    acc["handshake_ok_den"] += effective_weight
                    if handshake_ok:
                        acc["handshake_ok_num"] += effective_weight

        if isinstance(current_run_metrics, dict):
            for metric_uid, entry_raw in current_run_metrics.items():
                if not isinstance(entry_raw, dict):
                    continue
                acc = current_metric_acc.setdefault(
                    int(metric_uid),
                    {
                        "avg_reward_num": 0.0,
                        "avg_reward_den": 0.0,
                        "avg_eval_score_num": 0.0,
                        "avg_eval_score_den": 0.0,
                        "avg_eval_time_num": 0.0,
                        "avg_eval_time_den": 0.0,
                        "avg_cost_num": 0.0,
                        "avg_cost_den": 0.0,
                        "tasks_sent_sum": 0,
                        "tasks_success_sum": 0,
                    },
                )
                avg_reward = _extract_metric_value(entry_raw, "avg_reward", "reward")
                if avg_reward is not None:
                    acc["avg_reward_num"] += effective_weight * float(avg_reward)
                    acc["avg_reward_den"] += effective_weight
                avg_eval_score = _extract_metric_value(entry_raw, "avg_eval_score")
                if avg_eval_score is not None:
                    acc["avg_eval_score_num"] += effective_weight * float(avg_eval_score)
                    acc["avg_eval_score_den"] += effective_weight
                avg_eval_time = _extract_metric_value(entry_raw, "avg_eval_time")
                if avg_eval_time is not None:
                    acc["avg_eval_time_num"] += effective_weight * float(avg_eval_time)
                    acc["avg_eval_time_den"] += effective_weight
                avg_cost = _extract_metric_value(entry_raw, "avg_cost")
                if avg_cost is not None:
                    acc["avg_cost_num"] += effective_weight * float(avg_cost)
                    acc["avg_cost_den"] += effective_weight
                tasks_sent = _extract_int_metric_value(entry_raw, "tasks_sent")
                if tasks_sent is not None:
                    acc["tasks_sent_sum"] += int(tasks_sent)
                tasks_success = _extract_int_metric_value(entry_raw, "tasks_success")
                if tasks_success is not None:
                    acc["tasks_success_sum"] += int(tasks_success)

        included += 1
        fetched.append((hk, cid, st_val))
        scores_by_validator[hk] = per_val_map
        # Keep normalized download metadata for later IWAP finish_round payloads.
        downloaded_payloads.append(
            {
                "uid": (int(validator_uid) if isinstance(validator_uid, int) else validator_uid),
                "validator_hotkey": hk,
                "stake": float(st_val),
                "cid": cid,
                "local_evaluation": payload.get("local_evaluation") if isinstance(payload, dict) else None,
                "payload": payload,
            }
        )

    # Aggregate scores across all included validators using stake weighting.
    aggregation_entries = [(stake, scores_by_validator.get(hk, {})) for hk, _cid, stake in fetched]
    result, all_stakes_zero = _aggregate_scores_for_validators(aggregation_entries)

    stats_by_miner: Dict[int, Dict[str, Any]] = {}
    for uid, acc in metric_acc.items():
        stats_entry: Dict[str, Any] = {}
        if acc.get("avg_reward_den", 0.0) > 0.0:
            stats_entry["avg_reward"] = float(acc["avg_reward_num"] / acc["avg_reward_den"])
        if acc.get("avg_eval_score_den", 0.0) > 0.0:
            stats_entry["avg_eval_score"] = float(acc["avg_eval_score_num"] / acc["avg_eval_score_den"])
        if acc.get("avg_eval_time_den", 0.0) > 0.0:
            stats_entry["avg_eval_time"] = float(acc["avg_eval_time_num"] / acc["avg_eval_time_den"])
        if acc.get("avg_cost_den", 0.0) > 0.0:
            stats_entry["avg_cost"] = float(acc["avg_cost_num"] / acc["avg_cost_den"])
        if acc.get("tasks_sent_sum", 0) > 0:
            stats_entry["tasks_sent"] = int(acc["tasks_sent_sum"])
        if acc.get("tasks_success_sum", 0) > 0:
            stats_entry["tasks_success"] = int(acc["tasks_success_sum"])
        if acc.get("handshake_ok_den", 0.0) > 0.0:
            ratio = float(acc["handshake_ok_num"] / acc["handshake_ok_den"])
            stats_entry["handshake_ok_ratio"] = ratio
            stats_entry["handshake_ok"] = bool(ratio >= 0.5)
        if stats_entry:
            stats_by_miner[int(uid)] = stats_entry

    current_stats_by_miner: Dict[int, Dict[str, Any]] = {}
    for uid, acc in current_metric_acc.items():
        stats_entry: Dict[str, Any] = {}
        if acc.get("avg_reward_den", 0.0) > 0.0:
            stats_entry["avg_reward"] = float(acc["avg_reward_num"] / acc["avg_reward_den"])
        if acc.get("avg_eval_score_den", 0.0) > 0.0:
            stats_entry["avg_eval_score"] = float(acc["avg_eval_score_num"] / acc["avg_eval_score_den"])
        if acc.get("avg_eval_time_den", 0.0) > 0.0:
            stats_entry["avg_eval_time"] = float(acc["avg_eval_time_num"] / acc["avg_eval_time_den"])
        if acc.get("avg_cost_den", 0.0) > 0.0:
            stats_entry["avg_cost"] = float(acc["avg_cost_num"] / acc["avg_cost_den"])
        if acc.get("tasks_sent_sum", 0) > 0:
            stats_entry["tasks_sent"] = int(acc["tasks_sent_sum"])
        if acc.get("tasks_success_sum", 0) > 0:
            stats_entry["tasks_success"] = int(acc["tasks_success_sum"])
        if stats_entry:
            current_stats_by_miner[int(uid)] = stats_entry

    if included > 0:
        consensus_mode = "simple average (all 0τ)" if all_stakes_zero else "stake-weighted"
        bt.logging.success(f"[CONSENSUS] ✅ Aggregation complete | Validators: {included} | Miners: {len(result)} | Mode: {consensus_mode}")
        bt.logging.info(
            f"[CONSENSUS] Skipped | "
            f"Legacy consensus version: {skipped_legacy_consensus_version} | "
            f"Wrong season: {skipped_wrong_season} | "
            f"Wrong round: {skipped_wrong_round} | "
            f"Missing CID: {skipped_missing_cid} | "
            f"Low stake: {skipped_low_stake} | "
            f"IPFS fail: {skipped_ipfs} | "
            f"Wrong validator_version: {skipped_wrong_validator_version} | "
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
            if skipped_wrong_validator_version_list:
                vv_str = ", ".join([f"{hk[:10]}…(payload={pv})" for hk, pv in skipped_wrong_validator_version_list])
                bt.logging.debug(f"   ⏭️ Wrong-validator_version excluded: {vv_str}")
        except Exception:
            pass
        if len(result) > 0:
            top_sample = list(sorted(result.items(), key=lambda x: x[1], reverse=True))[:10]
            top_str = ", ".join(f"UID {uid}={score:.4f}" for uid, score in top_sample)
            bt.logging.info(f"[CONSENSUS] Aggregated scores ({len(result)} miners) top10: {top_str}")
        else:
            bt.logging.warning("[CONSENSUS] ⚠️ No miners aggregated (all scores were <= 0 or no common miners)")
    else:
        bt.logging.warning("[CONSENSUS] ⚠️ No validators included in aggregation")
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
    validators_info = [{"hotkey": hk, "uid": hk_to_uid.get(hk, "?"), "stake": stake, "cid": cid} for hk, cid, stake in fetched]
    details = {
        "validators": validators_info,
        "rewards_by_validator": scores_by_validator,
        "scores_by_validator": scores_by_validator,
        "stats_by_miner": stats_by_miner,
        "current_stats_by_miner": current_stats_by_miner,
        "downloaded_payloads": downloaded_payloads,
        "skips": {
            "legacy_consensus_version": skipped_legacy_consensus_version_list,
            "wrong_season": skipped_wrong_season_list,
            "wrong_round": skipped_wrong_round_list,
            "missing_cid": skipped_missing_cid_list,
            "low_stake": skipped_low_stake_list,
            "ipfs_fail": skipped_ipfs_list,
            "wrong_validator_version": skipped_wrong_validator_version_list,
            "verify_fail": skipped_verification_fail_list,
        },
    }

    return result, details
