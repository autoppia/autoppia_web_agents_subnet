from __future__ import annotations

from typing import Any, Dict, Optional

import bittensor as bt
from bittensor import AsyncSubtensor  # type: ignore

from autoppia_web_agents_subnet.validator.config import (
    ENABLE_DISTRIBUTED_CONSENSUS,
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO,
    IPFS_API_URL,
    CONSENSUS_VERIFICATION_ENABLED,
    CONSENSUS_VERIFICATION_SAMPLE_FRACTION,
    CONSENSUS_VERIFY_SAMPLE_MIN,
    CONSENSUS_VERIFY_SAMPLE_TOLERANCE,
    CONSENSUS_VERIFY_SAMPLE_MAX_CONCURRENCY,
    CONSENSUS_DATASET_EMBED,
)
from autoppia_web_agents_subnet.utils.commitments import (
    read_all_plain_commitments,
    write_plain_commitment_json,
)
from autoppia_web_agents_subnet.utils.ipfs_client import aadd_json, aget_json
from autoppia_web_agents_subnet.utils.log_colors import ipfs_tag, consensus_tag
from autoppia_web_agents_subnet.validator.dataset import RoundDatasetCollector
from autoppia_web_agents_subnet.validator.evaluation.eval import evaluate_task_solutions

# IWA domain types
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.demo_webs.config import demo_web_projects
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.execution.actions.base import BaseAction


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


async def _publish_snapshot(
    *,
    validator,
    st: AsyncSubtensor,
    round_number: Optional[int],
    tasks_completed: int,
    scores: Dict[int, float],
    phase: str,
) -> Optional[str]:
    """Shared implementation for mid-round and final consensus publishing."""
    if not ENABLE_DISTRIBUTED_CONSENSUS:
        bt.logging.warning(consensus_tag(f"Disabled - skipping publish ({phase})"))
        return None

    boundaries = validator.round_manager.get_current_boundaries()
    start_epoch = float(boundaries["round_start_epoch"])
    target_epoch = float(boundaries["target_epoch"])
    start_block = int(boundaries["round_start_block"])
    target_block = int(boundaries["target_block"])

    try:
        participants = len(
            [u for u, arr in (validator.round_manager.round_rewards or {}).items() if arr]
        )
    except Exception:
        participants = len(getattr(validator, "active_miner_uids", []) or [])

    payload = {
        "v": 1,
        "phase": phase,
        "r": int(round_number) if round_number is not None else None,
        "round_number": int(round_number) if round_number is not None else None,
        "es": start_epoch,
        "et": target_epoch,
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
        "scores": {str(int(uid)): float(score) for uid, score in (scores or {}).items()},
    }

    data_cid = None
    data_sha = None
    data_size = None
    try:
        collector: RoundDatasetCollector | None = getattr(validator, "dataset_collector", None)
        if isinstance(collector, RoundDatasetCollector):
            try:
                round_meta = {
                    "r": payload["r"],
                    "epoch_start": payload["es"],
                    "epoch_end": payload["et"],
                }
                vmeta = {
                    "uid": payload["uid"],
                    "hotkey": payload["hk"],
                    "version": payload.get("validator_version"),
                    "validator_round_id": payload.get("validator_round_id"),
                }
                dataset = collector.build_dataset(round_meta=round_meta, validator_meta=vmeta)
            except Exception as e:  # pragma: no cover - defensive
                dataset = None
                bt.logging.warning(consensus_tag(f"Dataset build failed: {e}"))
            if isinstance(dataset, dict):
                try:
                    data_cid, data_sha, data_size = await aadd_json(
                        dataset,
                        filename=f"autoppia_dataset_r{payload['r'] or 'X'}.json",
                        api_url=IPFS_API_URL,
                        pin=True,
                        sort_keys=True,
                    )
                    bt.logging.success(ipfs_tag("UPLOAD", f"✅ DATASET - CID: {data_cid} size={data_size} bytes"))
                    if CONSENSUS_DATASET_EMBED:
                        # Optional: embed a tiny manifest into the payload itself
                        payload["dataset"] = {
                            "cid": data_cid,
                            "sha256": data_sha,
                            "size": int(data_size or 0),
                        }
                    else:
                        payload["data_cid"] = data_cid
                        payload["data_sha256"] = data_sha
                        payload["data_size"] = int(data_size or 0)
                except Exception as e:  # pragma: no cover - IPFS upload failure should not abort
                    bt.logging.error(ipfs_tag("UPLOAD", f"❌ DATASET upload failed: {type(e).__name__}: {e}"))
        else:
            bt.logging.info(consensus_tag("No dataset collector attached; publishing scores-only payload"))
    except Exception as e:
        bt.logging.debug(consensus_tag(f"Dataset attach failed: {e}"))

    try:
        # 🔍 LOG: Show FULL payload being uploaded
        import json
        bt.logging.info("=" * 80)
        bt.logging.info(
            ipfs_tag(
                "UPLOAD",
                f"Round {payload.get('r')} | {len(payload.get('scores', {}))} miners | "
                f"Validator UID {payload['uid']} ({phase})",
            )
        )
        bt.logging.info(
            ipfs_tag(
                "UPLOAD",
                f"Payload:\n{json.dumps(payload, indent=2, sort_keys=True)}",
            )
        )

        cid, sha_hex, byte_len = await aadd_json(
            payload,
            filename=f"autoppia_commit_r{payload['r'] or 'X'}_{phase}.json",
            api_url=IPFS_API_URL,
            pin=True,
            sort_keys=True,
        )

        bt.logging.success(ipfs_tag("UPLOAD", f"✅ SUCCESS - CID: {cid}"))
        bt.logging.info(ipfs_tag("UPLOAD", f"Size: {byte_len} bytes | SHA256: {sha_hex[:16]}..."))
        bt.logging.info("=" * 80)
    except Exception as e:
        bt.logging.error("=" * 80)
        bt.logging.error(ipfs_tag("UPLOAD", f"❌ FAILED | Error: {type(e).__name__}: {e}"))
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
        "phase": phase,
    }

    try:
        bt.logging.info(
            "📮 CONSENSUS COMMIT START | "
            f"blocks {start_block}→{target_block} | "
            f"e={commit_v4['e']}→pe={commit_v4['pe']} "
            f"r={commit_v4.get('r')} cid={commit_v4['c']} phase={phase}"
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
        if ok:
            return str(cid)
        bt.logging.warning(ipfs_tag("BLOCKCHAIN", "⚠️ Commitment failed - write returned false"))
        return None
    except Exception as e:
        bt.logging.error("=" * 80)
        bt.logging.error(ipfs_tag("BLOCKCHAIN", f"❌ Commitment failed | Error: {type(e).__name__}: {e}"))
        import traceback
        bt.logging.error(ipfs_tag("BLOCKCHAIN", f"Traceback:\n{traceback.format_exc()}"))
        bt.logging.error("=" * 80)
        return None


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
    scores = validator.round_manager.get_average_rewards()
    return await _publish_snapshot(
        validator=validator,
        st=st,
        round_number=round_number,
        tasks_completed=tasks_completed,
        scores=scores,
        phase="mid",
    )


async def publish_scores_snapshot(
    *,
    validator,
    st: AsyncSubtensor,
    round_number: Optional[int],
    tasks_completed: int,
    scores: Dict[int, float],
) -> Optional[str]:
    """
    Publish an explicit scores snapshot to IPFS and commit CID on-chain.

    Same shape as publish_round_snapshot, but uses provided scores mapping.
    """
    return await _publish_snapshot(
        validator=validator,
        st=st,
        round_number=round_number,
        tasks_completed=tasks_completed,
        scores=scores,
        phase="final",
    )


async def aggregate_scores_from_commitments(
    *,
    validator,
    st: AsyncSubtensor,
    start_epoch: Optional[float] = None,
    target_epoch: Optional[float] = None,
    start_block: Optional[int] = None,
    target_block: Optional[int] = None,
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
        return {}, {}

    if start_epoch is None or target_epoch is None:
        if start_block is None or target_block is None:
            bounds = validator.round_manager.get_current_boundaries()
            start_epoch = float(bounds["round_start_epoch"])
            target_epoch = float(bounds["target_epoch"])
        else:
            start_epoch = validator.round_manager.block_to_epoch(int(start_block))
            target_epoch = validator.round_manager.block_to_epoch(int(target_block))
    else:
        start_epoch = float(start_epoch)
        target_epoch = float(target_epoch)

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
    skipped_verification_fail = 0
    skipped_wrong_epoch_list: list[tuple[str, int, int]] = []  # (hk, e, pe)
    skipped_missing_cid_list: list[str] = []
    skipped_low_stake_list: list[tuple[str, float]] = []  # (hk, stake)
    skipped_ipfs_list: list[tuple[str, str]] = []  # (hk, cid)
    skipped_verify_list: list[tuple[str, str]] = []  # (hk, reason)

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

        # Verification step always runs for logging/debug; only enforced if enabled.
        verified_ok, vreason = await _verify_payload_sample(
            payload=payload,
            sample_fraction=float(CONSENSUS_VERIFICATION_SAMPLE_FRACTION),
            min_samples=int(CONSENSUS_VERIFY_SAMPLE_MIN),
            tolerance=float(CONSENSUS_VERIFY_SAMPLE_TOLERANCE),
        )
        if not verified_ok:
            # Always log
            bt.logging.warning(consensus_tag(f"🔎 Verification failed for {hk[:10]}… ({vreason})"))
            # Enforce exclusion only if enabled
            if bool(CONSENSUS_VERIFICATION_ENABLED):
                skipped_verification_fail += 1
                skipped_verify_list.append((hk, vreason or "mismatch"))
                bt.logging.warning(consensus_tag(f"⏭️ Excluding validator {hk[:10]}… by verification policy"))
                continue
        else:
            bt.logging.info(consensus_tag(f"🔎 Verification OK for {hk[:10]}…"))

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
            f"[CONSENSUS] Skipped | Wrong epoch: {skipped_wrong_epoch} | Missing CID: {skipped_missing_cid} | Low stake: {skipped_low_stake} | IPFS fail: {skipped_ipfs} | Verify fail: {skipped_verification_fail}"
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
            f"[CONSENSUS] Reasons | Wrong epoch: {skipped_wrong_epoch} | Missing CID: {skipped_missing_cid} | Low stake: {skipped_low_stake} | IPFS fail: {skipped_ipfs} | Verify fail: {skipped_verification_fail} | Total commits: {len(commits or {})}"
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
            "verify_fail": skipped_verify_list,
        },
        "round_start_epoch": start_epoch,
        "round_target_epoch": target_epoch,
    }

    return result, details


async def _verify_payload_sample(
    *,
    payload: Dict[str, Any],
    sample_fraction: float,
    min_samples: int,
    tolerance: float,
) -> tuple[bool, Optional[str]]:
    """
    Download dataset for a validator payload and re-evaluate a random sample of solutions.

    Returns (ok, reason). If dataset is missing or invalid and CONSENSUS_VERIFICATION_ENABLED is true,
    returns (False, reason).
    """
    try:
        # Obtain dataset manifest
        ds_ref = None
        if isinstance(payload.get("dataset"), dict):
            ds_ref = payload.get("dataset", {})
        elif isinstance(payload.get("data_cid"), str):
            ds_ref = {"cid": payload.get("data_cid"), "sha256": payload.get("data_sha256")}

        if not ds_ref or not isinstance(ds_ref.get("cid"), str):
            # Return ok if dataset is missing and enforcement disabled
            return (False, "no_dataset") if CONSENSUS_VERIFICATION_ENABLED else (True, None)

        cid = str(ds_ref.get("cid"))
        expected_sha = ds_ref.get("sha256")
        dataset, _norm, _h = await aget_json(cid, api_url=IPFS_API_URL, expected_sha256_hex=expected_sha)

        if not isinstance(dataset, dict):
            return False, "invalid_dataset"

        tasks_list = dataset.get("tasks") or []
        solutions_list = dataset.get("solutions") or []
        evals_list = dataset.get("evals") or []
        if not isinstance(tasks_list, list) or not isinstance(solutions_list, list) or not isinstance(evals_list, list):
            return False, "bad_schema"

        # Build task map {task_id: Task}
        task_map: Dict[str, Task] = {}
        project_map: Dict[str, Any] = {getattr(p, "id", None): p for p in demo_web_projects if getattr(p, "id", None)}
        for tj in tasks_list:
            try:
                tid = str(tj.get("id"))
                t = Task.deserialize(tj)
                task_map[tid] = t
            except Exception:
                # Skip malformed task
                continue

        # Build eval index {(task_id, miner_uid): eval_score}
        expected_scores: Dict[tuple[str, int], float] = {}
        for e in evals_list:
            try:
                tid = str(e.get("task_id"))
                uid = int(e.get("miner_uid"))
                expected_scores[(tid, uid)] = float(e.get("eval_score", 0.0))
            except Exception:
                continue

        total = len(expected_scores)
        if total <= 0:
            # Nothing to verify; treat as failure when dataset is required
            return (False, "no_evals") if CONSENSUS_VERIFICATION_ENABLED else (True, None)

        # Sample pairs deterministically
        import random, hashlib
        seed_src = f"{payload.get('validator_hotkey') or payload.get('hk')}|{payload.get('r')}|{payload.get('es')}|{payload.get('et')}"
        seed_hex = hashlib.md5(seed_src.encode()).hexdigest()
        rng = random.Random(int(seed_hex[:8], 16))
        sample_size = max(int(total * max(min(sample_fraction, 1.0), 0.0)), int(min_samples))
        pairs = list(expected_scores.keys())
        if sample_size < total:
            sample_pairs = rng.sample(pairs, sample_size)
        else:
            sample_pairs = pairs

        # Group by task for efficient evaluation
        by_task: Dict[str, List[int]] = {}
        for tid, uid in sample_pairs:
            by_task.setdefault(tid, []).append(uid)

        # Map solutions by (task_id, miner_uid)
        sol_index: Dict[tuple[str, int], Dict[str, Any]] = {}
        for s in solutions_list:
            try:
                tid = str(s.get("task_id"))
                uid = int(s.get("miner_uid"))
                sol_index[(tid, uid)] = s
            except Exception:
                continue

        # Verify per task
        for tid, uids in by_task.items():
            t = task_map.get(str(tid))
            if t is None:
                return False, "missing_task"

            # WebProject lookup (may be used by evaluator)
            proj_id = None
            try:
                for tj in tasks_list:
                    if str(tj.get("id")) == str(tid):
                        proj_id = tj.get("web_project_id")
                        break
            except Exception:
                proj_id = None
            project = project_map.get(proj_id) if proj_id is not None else None
            if project is None:
                # If not found by id, fallback to first project; evaluator may not always need it for static checks
                try:
                    project = demo_web_projects[0]
                except Exception:
                    project = None
            if project is None:
                return False, "missing_project"

            # Rebuild TaskSolution list
            sols: List[TaskSolution] = []
            for uid in uids:
                sj = sol_index.get((str(tid), int(uid)))
                if not sj:
                    return False, "missing_solution"
                actions_json = sj.get("actions") or []
                actions = []
                try:
                    for a in actions_json:
                        try:
                            act = BaseAction.create_action(a)
                        except Exception:
                            act = None
                        if act is not None:
                            actions.append(act)
                except Exception:
                    actions = []
                sols.append(TaskSolution(task_id=str(tid), actions=actions, web_agent_id=str(uid)))

            # Evaluate subset
            exec_times = [0.0] * len(sols)
            eval_scores, _trs, _ers = await evaluate_task_solutions(
                web_project=project,
                task=t,
                task_solutions=sols,
                execution_times=exec_times,
                normalize_scores=True,
            )

            # Compare
            for i, uid in enumerate(uids):
                ref = float(expected_scores.get((str(tid), int(uid)), 0.0))
                got = float(eval_scores[i]) if i < len(eval_scores) else 0.0
                if abs(ref - got) > tolerance:
                    return False, f"diff@{tid}:{uid}:{ref:.6f}!={got:.6f}"

        return True, None
    except Exception as e:
        bt.logging.warning(consensus_tag(f"Verification exception: {type(e).__name__}: {e}"))
        return (False, "exception") if CONSENSUS_VERIFICATION_ENABLED else (True, None)
