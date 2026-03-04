from __future__ import annotations

import asyncio
import re
import math
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import bittensor as bt

from autoppia_web_agents_subnet.validator import config as validator_config
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


def _extract_error_detail(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    if response is None:
        return ""
    try:
        payload = response.json()
    except Exception:
        try:
            return str(response.text or "")
        except Exception:
            return ""

    if isinstance(payload, dict):
        detail = payload.get("detail", payload)
    else:
        detail = payload

    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail)
    except Exception:
        return str(detail)


def _is_duplicate_like_error(exc: httpx.HTTPStatusError) -> bool:
    """Return True only for explicit idempotent/duplicate conflicts."""
    status = exc.response.status_code if exc.response is not None else None
    detail = _extract_error_detail(exc).lower()
    duplicate_markers = (
        "already exists",
        "already registered",
        "duplicate",
        "unique constraint",
        "duplicate key value",
    )
    if status == 409:
        return any(marker in detail for marker in duplicate_markers)
    if status != 500:
        return False

    return any(marker in detail for marker in duplicate_markers)


def _is_main_authority_or_grace_error(exc: httpx.HTTPStatusError) -> bool:
    """Return True for expected backend guardrails where non-main validator must not write."""
    status = exc.response.status_code if exc.response is not None else None
    if status not in (400, 409):
        return False

    detail = _extract_error_detail(exc).lower()
    markers = (
        "only main validator can open a new season/round",
        "fallback finish denied",
        "main validator still within finish grace",
        "validator is not the highest-stake backup",
    )
    return any(marker in detail for marker in markers)


def _get_finish_retry_policy() -> tuple[int, int]:
    """
    Return (max_retries, retry_interval_sec) for finish_round authority/grace retries.
    Config keys:
      - validator_config.FINISH_ROUND_MAX_RETRIES
      - validator_config.FINISH_ROUND_RETRY_SECONDS
    """
    try:
        max_retries = int(getattr(validator_config, "FINISH_ROUND_MAX_RETRIES", 3))
    except Exception:
        max_retries = 3
    try:
        retry_interval_sec = int(getattr(validator_config, "FINISH_ROUND_RETRY_SECONDS", 180))
    except Exception:
        retry_interval_sec = 180

    max_retries = max(0, max_retries)
    retry_interval_sec = max(10, retry_interval_sec)
    return max_retries, retry_interval_sec


def _extract_round_numbers_from_round_id(round_id: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    if not isinstance(round_id, str) or not round_id:
        return None, None

    pattern = re.match(r"^validator_round_(\d+)_(\d+)_.*$", round_id)
    if not pattern:
        return None, None

    try:
        return int(pattern.group(1)), int(pattern.group(2))
    except Exception:
        return None, None


def _load_validator_state_json(ctx) -> Optional[Dict[str, Any]]:
    """Read validator local state.npz and return a JSON-safe payload."""
    try:
        full_path = Path(str(getattr(ctx.config.neuron, "full_path", ".")))
        state_path = full_path / "state.npz"
        if not state_path.exists():
            return None

        import numpy as np

        with np.load(state_path, allow_pickle=False) as state:
            step_val = state.get("step")
            scores_val = state.get("scores")
            hotkeys_val = state.get("hotkeys")

            step = int(step_val.reshape(-1)[0]) if step_val is not None else None
            scores_list = scores_val.tolist() if scores_val is not None else []
            hotkeys_list = hotkeys_val.tolist() if hotkeys_val is not None else []

            # Ensure all entries are JSON-safe primitive strings/floats.
            scores_json = [float(x) for x in scores_list]
            hotkeys_json = [str(x) for x in hotkeys_list]

            return {
                "path": str(state_path),
                "step": step,
                "scores": scores_json,
                "hotkeys": hotkeys_json,
                "scores_non_zero": int(sum(1 for x in scores_json if float(x) != 0.0)),
                "scores_sum": float(sum(scores_json)),
                "saved_at_utc": datetime.utcnow().isoformat(timespec="microseconds") + "Z",
            }
    except Exception as exc:
        bt.logging.warning(f"IWAP | Could not load validator state.npz: {exc}")
        return {"error": str(exc)}


def _load_validator_iwap_prev_round_json(ctx) -> Optional[Dict[str, Any]]:
    """Read validator local iwap_prev_round.json and return parsed JSON."""
    try:
        path_getter = getattr(ctx, "_iwap_prev_round_path", None)
        if callable(path_getter):
            prev_path = Path(path_getter())
        else:
            full_path = Path(str(getattr(ctx.config.neuron, "full_path", ".")))
            prev_path = full_path / "iwap_prev_round.json"
        if not prev_path.exists():
            return None

        data = json.loads(prev_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = dict(data)
            data["path"] = str(prev_path)
            data["saved_at_utc"] = datetime.utcnow().isoformat(timespec="microseconds") + "Z"
            return data
        return {"path": str(prev_path), "content": data}
    except Exception as exc:
        bt.logging.warning(f"IWAP | Could not load iwap_prev_round.json: {exc}")
        return {"error": str(exc)}


def _build_consensus_summary_payload(
    *,
    season_number: Optional[int],
    round_number_in_season: Optional[int],
    miner_scores: Dict[int, float],
    season_history: Dict[Any, Any],
) -> Dict[str, Any]:
    season_i = int(season_number) if season_number is not None else 0
    round_i = int(round_number_in_season) if round_number_in_season is not None else 0
    if season_i <= 0:
        season_i = 0
    if round_i <= 0:
        round_i = 0

    try:
        required_improvement_pct = max(float(validator_config.LAST_WINNER_BONUS_PCT), 0.0)
    except Exception:
        required_improvement_pct = 0.0

    normalized_scores: Dict[int, float] = {}
    for uid_raw, score_raw in (miner_scores or {}).items():
        try:
            uid_i = int(uid_raw)
            score_f = float(score_raw)
        except Exception:
            continue
        normalized_scores[uid_i] = float(score_f)

    season_state = season_history.get(season_i, {})
    if not isinstance(season_state, dict):
        season_state = {}

    summary_state = season_state.get("summary", {})
    if not isinstance(summary_state, dict):
        summary_state = {}

    best_by_miner_raw = summary_state.get("best_by_miner", {})
    if isinstance(best_by_miner_raw, dict):
        best_by_miner = {}
        for uid_raw, score_raw in best_by_miner_raw.items():
            if uid_raw is None:
                continue
            try:
                uid_i = int(uid_raw)
                score_f = float(score_raw)
            except Exception:
                continue
            best_by_miner[uid_i] = score_f
    else:
        best_by_miner = {}

    round_scores_for_summary: Dict[int, float] = dict(best_by_miner)
    # Always carry current-round scores into the summary map, even if they are 0.0.
    # This guarantees post-consensus observability for rounds where all miners score zero.
    for uid, score in normalized_scores.items():
        prev_best = round_scores_for_summary.get(uid)
        if prev_best is None or score > prev_best:
            round_scores_for_summary[uid] = score

    best_uid: Optional[int] = None
    best_score = float("-inf")
    for uid, score in round_scores_for_summary.items():
        try:
            uid_i = int(uid)
            score_f = float(score)
        except Exception:
            continue
        if score_f > best_score or (score_f == best_score and best_uid is not None and uid_i < best_uid):
            best_score = score_f
            best_uid = uid_i
    if best_score == float("-inf"):
        best_score = 0.0

    reigning_uid_raw = summary_state.get("current_winner_uid")
    try:
        reigning_uid: Optional[int] = int(reigning_uid_raw) if reigning_uid_raw is not None else None
    except Exception:
        reigning_uid = None

    reigning_score = 0.0
    if reigning_uid is not None:
        try:
            reigning_score = float(summary_state.get("current_winner_score", 0.0) or 0.0)
        except Exception:
            reigning_score = 0.0
        if reigning_score <= 0.0:
            reigning_score = float(round_scores_for_summary.get(reigning_uid, 0.0) or 0.0)

    winner_uid: Optional[int] = None
    winner_score = 0.0
    dethroned = False
    required_score_to_dethrone: Optional[float] = None

    # Keep winner UID explicit when possible, even if score is 0.0.
    if reigning_uid is not None:
        winner_uid = reigning_uid
        winner_score = reigning_score
        if best_uid is not None and best_uid != reigning_uid:
            required_score_to_dethrone = float(reigning_score * (1.0 + required_improvement_pct))
            if best_score > required_score_to_dethrone:
                dethroned = True
                winner_uid = best_uid
                winner_score = best_score
    elif best_uid is not None:
        winner_uid = best_uid
        winner_score = best_score

    return {
        "schema_version": 1,
        "season_number": season_i,
        "round_number_in_season": round_i,
        "saved_at_utc": datetime.utcnow().isoformat(),
        "round_summary": {
            "winner": {
                "miner_uid": int(winner_uid) if winner_uid is not None else None,
                "score": float(winner_score),
            },
            "miner_scores": {int(uid): float(score) for uid, score in normalized_scores.items()},
            "decision": {
                "top_candidate_uid": int(best_uid) if best_uid is not None else None,
                "top_candidate_score": float(best_score),
                "reigning_uid_before_round": int(reigning_uid) if reigning_uid is not None else None,
                "reigning_score_before_round": float(reigning_score),
                "required_improvement_pct": float(required_improvement_pct),
                "required_score_to_dethrone": float(required_score_to_dethrone) if required_score_to_dethrone is not None else None,
                "dethroned": bool(dethroned),
            },
        },
        "season_summary": {
            "current_winner_uid": int(winner_uid) if winner_uid is not None else None,
            "current_winner_score": float(winner_score),
            "required_improvement_pct": float(required_improvement_pct),
        },
    }


def _persist_round_summary_file(
    *,
    ctx,
    season_number: int,
    round_number: int,
    pre_consensus: Optional[Dict[str, Any]],
    post_consensus: Optional[Dict[str, Any]],
    ipfs_uploaded: Optional[Dict[str, Any]],
    ipfs_downloaded: Optional[Dict[str, Any]],
    s3_logs: Optional[Dict[str, Any]],
) -> None:
    if season_number <= 0 or round_number <= 0:
        return

    pre_summary = pre_consensus if isinstance(pre_consensus, dict) else None
    post_summary = post_consensus if isinstance(post_consensus, dict) else None

    payload: Dict[str, Any] = {
        "schema_version": 1,
        "season_number": season_number,
        "round_number_in_season": round_number,
        "saved_at_utc": datetime.utcnow().isoformat(),
        "pre_consensus": pre_summary,
        "post_consensus": post_summary,
        "ipfs_uploaded": ipfs_uploaded if isinstance(ipfs_uploaded, dict) else None,
        "ipfs_downloaded": ipfs_downloaded if isinstance(ipfs_downloaded, dict) else None,
        "s3_logs": s3_logs if isinstance(s3_logs, dict) else None,
        "round_summary": pre_summary.get("round_summary", {}) if isinstance(pre_summary, dict) else {},
        "season_summary": pre_summary.get("season_summary", {}) if isinstance(pre_summary, dict) else {},
    }

    try:
        root_getter = getattr(ctx, "_state_summary_root", None)
        base = root_getter() if callable(root_getter) else Path("data")
        target_dir = Path(base) / f"season_{season_number}" / f"round_{round_number}"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "logs").mkdir(parents=True, exist_ok=True)
        target = target_dir / "summary_round.json"
        with target.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
    except Exception:
        from autoppia_web_agents_subnet.utils.logging import ColoredLogger

        ColoredLogger.warning(f"IWAP | Could not persist summary_round file for season={season_number} round={round_number}")


async def start_round_flow(ctx, *, current_block: int, n_tasks: int) -> None:
    if not ctx.current_round_id:
        return

    ctx._s3_task_log_urls = []

    # 🔍 FIX: Fetch a fresh block height to avoid TTL-cached values around round boundaries
    # self.block is cached with 12s TTL. If block advances within that TTL, we send a stale round
    # and backend returns "round_number mismatch". Always use fresh block for round calculation.
    original_block = current_block
    try:
        if hasattr(ctx, "get_current_block"):
            latest_block = ctx.get_current_block(fresh=True)
        else:
            latest_block = ctx.subtensor.get_current_block()
        if latest_block is not None:
            current_block = int(latest_block)
            if current_block != original_block:
                bt.logging.info(f"[IWAP] Block refresh: using fresh_block={current_block:,} (was {original_block:,}, diff={current_block - original_block})")
    except Exception:
        # If refresh fails, use the passed block (fallback)
        pass

    validator_identity = build_validator_identity(ctx)
    validator_snapshot = build_validator_snapshot(ctx, ctx.current_round_id)

    # 🔍 IMPORTANT: Recalculate boundaries with refreshed block to ensure consistency
    # get_current_boundaries() uses self.start_block (from original block), but we need
    # boundaries consistent with the refreshed current_block for round_number calculation
    boundaries = ctx.round_manager.get_round_boundaries(current_block, log_debug=False)
    max_epochs = max(1, int(round(validator_config.ROUND_SIZE_EPOCHS))) if validator_config.ROUND_SIZE_EPOCHS else 1
    start_epoch_raw = boundaries["round_start_epoch"]
    start_epoch = math.floor(start_epoch_raw)
    round_metadata: Dict[str, Any] = {
        "round_start_epoch_raw": start_epoch_raw,
        "target_epoch": boundaries.get("target_epoch"),
    }

    # Use round_start_block from boundaries (not current_block) for consistency
    round_start_block = int(boundaries.get("round_start_block", current_block) or current_block)

    # 🔍 Calculate season and round within season using round_start_block
    # CRITICAL: Must use round_start_block (not current_block) so backend validation passes
    # The backend validates season_number against start_block, so they must match
    from autoppia_web_agents_subnet.platform import client as iwa_main

    round_blocks = int(ctx.round_manager.round_block_length)

    season_number = iwa_main.compute_season_number(round_start_block)
    round_number_in_season = iwa_main.compute_round_number_in_season(round_start_block, round_blocks)

    bt.logging.info(
        f"[IWAP] Season calculation: round_start_block={round_start_block:,} | season_number={season_number} | round_number_in_season={round_number_in_season} | round_blocks={round_blocks}"
    )

    miner_count = len(getattr(ctx, "active_miner_uids", []))

    start_round_message = f"Calling start_round with season={season_number}, round_in_season={round_number_in_season}, tasks={n_tasks}, miners={miner_count}, round_id={ctx.current_round_id}"
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

    start_round_ok = False
    shadow_mode = False
    try:
        resp = await ctx.iwap_client.start_round(
            validator_identity=validator_identity,
            validator_round=validator_round,
            validator_snapshot=validator_snapshot,
        )
        vrid = _extract_validator_round_id(resp)
        if vrid != ctx.current_round_id:
            ctx.current_round_id = vrid
        shadow_mode = bool(resp.get("shadow_mode")) if isinstance(resp, dict) else False
        if shadow_mode:
            setattr(ctx, "_iwap_shadow_mode", True)
            log_iwap_phase(
                "Phase 1",
                (f"start_round accepted in SHADOW mode for round_id={ctx.current_round_id}; continuing idempotent IWAP writes with non-authoritative close semantics"),
                level="warning",
            )
        start_round_ok = True
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if _is_main_authority_or_grace_error(exc):
            log_iwap_phase(
                "Phase 1",
                (f"start_round returned {status} due to main-validator authority/grace guard; enabling SHADOW mode and continuing on-chain"),
                level="warning",
                exc_info=False,
            )
            setattr(ctx, "_iwap_shadow_mode", True)
            return
        if _is_duplicate_like_error(exc):
            detail = _extract_error_detail(exc).lower()
            season_conflict = "cannot start season" in detail and "still active" in detail
            if season_conflict:
                log_iwap_phase(
                    "Phase 1",
                    "start_round rejected due to active previous season; disabling IWAP sync for this round",
                    level="error",
                    exc_info=False,
                )
                ctx._iwap_offline_mode = True
                return
            log_iwap_phase("Phase 1", f"start_round returned {status} (already exists); continuing idempotently", level="warning")
            start_round_ok = True
        else:
            mismatch = _parse_round_mismatch(exc)
            if mismatch is not None:
                expected, got = mismatch
                log_iwap_phase(
                    "Phase 1",
                    (f"start_round rejected due to round_number mismatch (expected={expected}, got={got}); continuing without IWAP sync"),
                    level="error",
                )
                ctx._iwap_offline_mode = True
                return
            else:
                log_iwap_phase(
                    "Phase 1",
                    f"start_round failed for round_id={ctx.current_round_id}",
                    level="error",
                    exc_info=False,
                )
                ctx._iwap_offline_mode = True
                return
    except Exception as exc:  # noqa: BLE001
        log_iwap_phase(
            "Phase 1",
            f"start_round failed for round_id={ctx.current_round_id}: {exc}; continuing without IWAP sync",
            level="error",
        )
        ctx._iwap_offline_mode = True
        return
    else:
        log_iwap_phase(
            "Phase 1",
            f"start_round completed for round_id={ctx.current_round_id}",
            level="success",
        )

    if not start_round_ok:
        ctx._iwap_offline_mode = True
        return

    if shadow_mode:
        log_iwap_phase(
            "Phase 1",
            (f"shadow_mode active for round_id={ctx.current_round_id}; continuing with set_tasks/start_agent_run/evaluations using idempotent writes"),
            level="warning",
        )

    # Build IWAP tasks from season tasks
    # Get season tasks from the validator (they should be available after get_round_tasks was called)
    if not hasattr(ctx, "current_round_tasks") or not ctx.current_round_tasks:
        # Try to get tasks from season_manager if available
        if hasattr(ctx, "season_manager") and hasattr(ctx.season_manager, "season_tasks"):
            season_tasks = ctx.season_manager.season_tasks
            if season_tasks:
                from autoppia_web_agents_subnet.platform.utils.iwa_core import build_iwap_tasks

                ctx.current_round_tasks = build_iwap_tasks(validator_round_id=ctx.current_round_id, tasks=season_tasks)

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
        if _is_duplicate_like_error(exc):
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

    # Note: register_participating_miners_in_iwap is called separately in validator.py
    # after handshake to avoid duplication


async def register_participating_miners_in_iwap(ctx) -> None:
    """
    Register all miners that responded to handshake in IWAP dashboard.

    For each active miner:
    - Sends miner identity (uid, hotkey, coldkey)
    - Sends miner snapshot (agent_name, github_url, image_url)
    - Creates agent_run record (agent_run_id, started_at)

    Creates records in:
    - validator_round_miners (miner info)
    - miner_evaluation_runs (agent_evaluation_runs)

    Skips registration if IWAP is in offline mode.
    """
    if not ctx.current_round_id:
        return

    if getattr(ctx, "_iwap_offline_mode", False):
        log_iwap_phase(
            "Register Miners",
            "⚠️ OFFLINE MODE: Skipping miner registration",
            level="warning",
        )
        return

    if not hasattr(ctx, "active_miner_uids") or not ctx.active_miner_uids:
        log_iwap_phase(
            "Register Miners",
            "No active miners to register",
            level="info",
        )
        return

    validator_identity = build_validator_identity(ctx)
    coldkeys = getattr(ctx.metagraph, "coldkeys", [])
    now_ts = time.time()

    for miner_uid in ctx.active_miner_uids:
        # CRITICAL: Check if agent_run already exists for this miner in this round
        # An agent run should be unique per (validator_round_id, miner_uid)
        # If it already exists in current_agent_runs, skip creating a new one
        existing_agent_run = ctx.current_agent_runs.get(miner_uid)
        if existing_agent_run and existing_agent_run.validator_round_id == ctx.current_round_id:
            log_iwap_phase(
                "Register Miners",
                f"Agent run already exists for miner_uid={miner_uid} in round {ctx.current_round_id}. Existing agent_run_id={existing_agent_run.agent_run_id}. Skipping registration.",
                level="warning",
            )
            continue

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
        miners_reused = getattr(ctx, "miners_reused_this_round", None) or set()
        prev_run_ids = getattr(ctx, "prev_round_agent_run_ids", None) or {}
        prev_stats = getattr(ctx, "prev_round_run_stats", None) or {}
        # Always use the FIRST evaluated run as reused_from (handshake sets this from _evaluated_commits_by_miner).
        # prev_run_ids is only fallback (e.g. after restart before handshake); handshake ensures all reused runs point to the same origin.
        reused_from_id = getattr(ctx, "reused_from_agent_run_id_by_uid", None) or {}
        reused_from_id = reused_from_id.get(miner_uid) or prev_run_ids.get(miner_uid)
        reused_stats = getattr(ctx, "reused_stats_by_uid", None) or {}
        prev_s = reused_stats.get(miner_uid) or prev_stats.get(miner_uid)
        is_reused = miner_uid in miners_reused and reused_from_id

        if is_reused and reused_from_id and prev_s:
            agent_run = iwa_models.AgentRunIWAP(
                agent_run_id=agent_run_id,
                validator_round_id=ctx.current_round_id,
                validator_uid=int(ctx.uid),
                validator_hotkey=validator_identity.hotkey,
                miner_uid=miner_uid,
                miner_hotkey=miner_hotkey,
                is_sota=False,
                version=None,
                started_at=now_ts,
                metadata={"handshake_note": "reused", "reused_from_round": reused_from_id},
                is_reused=True,
                reused_from_agent_run_id=reused_from_id,
                average_score=prev_s.get("average_score"),
                average_execution_time=prev_s.get("average_execution_time"),
                average_reward=prev_s.get("average_reward"),
                total_tasks=prev_s.get("total_tasks", 0),
                completed_tasks=prev_s.get("success_tasks", 0),
                failed_tasks=prev_s.get("failed_tasks", 0),
                zero_reason=prev_s.get("zero_reason"),
            )
        else:
            agent_run = iwa_models.AgentRunIWAP(
                agent_run_id=agent_run_id,
                validator_round_id=ctx.current_round_id,
                validator_uid=int(ctx.uid),
                validator_hotkey=validator_identity.hotkey,
                miner_uid=miner_uid,
                miner_hotkey=miner_hotkey,
                is_sota=False,
                version=None,
                started_at=now_ts,
                metadata={"handshake_note": getattr(handshake_payload, "note", None)},
            )

        try:
            if is_reused and reused_from_id:
                start_agent_run_message = f"Calling start_agent_run for miner_uid={miner_uid}, agent_run_id={agent_run_id} (reused from {reused_from_id})"
            else:
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
                # If validator_round is missing on backend (e.g., after API reset), skip retry
                # The round should have been created in _iwap_start_round() before this
                if status == 400 and "Validator round" in body and "not found" in body:
                    log_iwap_phase(
                        "Register Miners",
                        f"start_agent_run failed for miner_uid={miner_uid}: validator round not found. Skipping.",
                        level="error",
                    )
                    continue
                else:
                    raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if _is_duplicate_like_error(exc):
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
            if is_reused and reused_from_id:
                start_agent_run_success = f"start_agent_run completed for miner_uid={miner_uid} (reused from {reused_from_id})"
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

    # Upload round log as early as possible so we always persist it even if something
    # fails later (consensus, summary, finish_round API). You get the same logs the
    # validator saw.
    round_id = ctx.current_round_id
    season_for_round, round_for_round = _extract_round_numbers_from_round_id(round_id)
    if season_for_round is None:
        season_for_round = 0
    if round_for_round is None:
        round_for_round = 0
    # Upload full round log (append-only file: all logs from round start; never truncated on error)
    round_log_file: Optional[str] = None
    round_log_url: Optional[str] = None
    round_log_size = 0
    round_log_error: Optional[str] = None
    try:
        from autoppia_web_agents_subnet.utils.logging import ColoredLogger

        round_log_file = ColoredLogger.get_round_log_file()
        if round_log_file:
            round_log_path = Path(round_log_file)
            if round_log_path.exists():
                round_log_contents = round_log_path.read_text(encoding="utf-8", errors="replace")
                round_log_size = len(round_log_contents.encode("utf-8"))
                validator_uid = getattr(ctx, "uid", None)
                validator_hotkey = None
                try:
                    validator_hotkey = getattr(ctx.wallet, "hotkey", None)
                    if validator_hotkey is not None:
                        validator_hotkey = getattr(validator_hotkey, "ss58_address", None)
                except Exception:
                    pass
                round_log_url = await ctx.iwap_client.upload_round_log(
                    validator_round_id=round_id,
                    content=round_log_contents,
                    season_number=season_for_round,
                    round_number_in_season=round_for_round,
                    validator_uid=validator_uid if isinstance(validator_uid, int) else None,
                    validator_hotkey=validator_hotkey,
                )
                if round_log_url is None:
                    round_log_error = "upload rejected: no url returned"
            else:
                round_log_error = f"round log file not found: {round_log_file}"
    except Exception as exc:
        round_log_error = f"upload failed: {type(exc).__name__}: {exc}"
        bt.logging.warning(f"Failed to upload round log for round_id={round_id}: {round_log_error}")

    ended_at = time.time()
    for agent_run in ctx.current_agent_runs.values():
        agent_run.ended_at = ended_at
        agent_run.elapsed_sec = max(0.0, ended_at - agent_run.started_at)

    summary = {
        "tasks_completed": tasks_completed,
        "active_miners": len(avg_rewards),
    }

    season_number_for_summary, round_number_for_summary = _extract_round_numbers_from_round_id(ctx.current_round_id)
    if season_number_for_summary is None or round_number_for_summary is None:
        try:
            season_number_for_summary = int(getattr(ctx, "season_manager").season_number)
        except Exception:
            season_number_for_summary = 0
        try:
            round_number_for_summary = int(getattr(ctx, "round_manager").round_number)
        except Exception:
            round_number_for_summary = 0

    # Get local scores (pre-consensus) if they were saved during IPFS publish
    # If not available, use current avg_rewards (backward compatible)
    local_avg_rewards = getattr(ctx, "_local_avg_rewards_at_publish", None) or avg_rewards

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
        is_reused = getattr(agent_run, "is_reused", False)

        if is_reused:
            # Reused run: no evaluations this round; use stats from the source run (agent_run was filled from reused_stats)
            avg_reward_value = getattr(agent_run, "average_reward", None) or local_avg_rewards.get(miner_uid, 0.0)
            miner_tasks_attempted = getattr(agent_run, "total_tasks", 0) or 0
            miner_tasks_completed = getattr(agent_run, "completed_tasks", 0) or getattr(agent_run, "success_tasks", 0) or 0
            miner_tasks_failed = getattr(agent_run, "failed_tasks", 0) or max(0, miner_tasks_attempted - miner_tasks_completed)
            avg_time = getattr(agent_run, "average_execution_time", None) or 0.0
        else:
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

        # Get local avg_eval_score (for reused runs, agent_run.average_score reflects source run)
        local_avg_eval_score = getattr(agent_run, "average_score", None) if is_reused else local_avg_eval_scores.get(miner_uid, 0.0)
        if local_avg_eval_score is None:
            local_avg_eval_score = local_avg_eval_scores.get(miner_uid, 0.0)
        zero_reason = getattr(agent_run, "zero_reason", None)
        reused_from_agent_run_id = getattr(agent_run, "reused_from_agent_run_id", None)

        local_evaluation_miners.append(
            {
                "rank": rank_value,
                "avg_reward": float(avg_reward_value),  # Average of all rewards for this miner (pre-consensus, local to this validator)
                "avg_eval_score": float(local_avg_eval_score),  # Average of all eval_scores for this miner (pure evaluation score, 0-1)
                "miner_uid": miner_uid,
                "miner_hotkey": miner_hotkey,  # Miner hotkey for identification
                "miner_name": miner_name,
                "agent_run_id": agent_run.agent_run_id,
                "zero_reason": zero_reason,
                "is_reused": is_reused,
                "reused_from_agent_run_id": reused_from_agent_run_id,
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
                zero_reason=miner_data.get("zero_reason"),
                is_reused=miner_data.get("is_reused", False),
                reused_from_agent_run_id=miner_data.get("reused_from_agent_run_id"),
            )
        )

    # Build round metadata (safe access to all fields)
    try:
        boundaries = ctx.round_manager.get_current_boundaries() if hasattr(ctx, "round_manager") else {}
    except Exception:
        boundaries = {}

    # IMPORTANT: freeze boundaries to the round being finalized.
    # If finalization runs near/after target block, round_manager may already be on
    # the next round and get_current_boundaries() would drift to round N+1.
    round_start_block_frozen = getattr(ctx, "_settlement_round_start_block", None)
    round_target_block_frozen = getattr(ctx, "_settlement_round_target_block", None)
    if round_start_block_frozen is not None:
        boundaries["round_start_block"] = int(round_start_block_frozen)
    if round_target_block_frozen is not None:
        boundaries["target_block"] = int(round_target_block_frozen)

    # Keep epoch values consistent with frozen blocks.
    if hasattr(ctx, "round_manager"):
        try:
            if boundaries.get("round_start_block") is not None:
                boundaries["round_start_epoch"] = float(ctx.round_manager.block_to_epoch(int(boundaries["round_start_block"])))
            if boundaries.get("target_block") is not None:
                boundaries["target_epoch"] = float(ctx.round_manager.block_to_epoch(int(boundaries["target_block"])))
        except Exception:
            pass

    # Round number for finish payload must match the round being finalized,
    # not a potentially advanced current block.
    round_num = int(round_number_for_summary or 0)
    if round_num <= 0 and hasattr(ctx, "round_manager"):
        try:
            round_num = int(getattr(ctx.round_manager, "round_number", 0) or 0)
        except Exception:
            round_num = int(getattr(ctx, "_current_round_number", 0) or getattr(ctx, "current_round_number", 0) or 0)

    # Build emission info (will be added to round_metadata)
    # alpha_price will be calculated by backend
    from autoppia_web_agents_subnet.validator.config import BURN_UID, BURN_AMOUNT_PERCENTAGE

    burn_percentage = float(BURN_AMOUNT_PERCENTAGE)

    emission_info = {
        "burn_percentage": float(burn_percentage) * 100,  # Convert to percentage
        "burn_recipient_uid": int(BURN_UID),
    }

    miners_reused = list(getattr(ctx, "miners_reused_this_round", None) or [])

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
        miners_evaluated=len(avg_rewards or {}),
        emission=emission_info,
        miners_reused_same_commit=miners_reused if miners_reused else None,
    )

    # Build local_evaluation (what THIS validator evaluated - pre-consensus)
    local_evaluation = {
        "timestamp": ended_at,
        "miners": local_evaluation_miners,
        "summary": _build_consensus_summary_payload(
            season_number=season_number_for_summary,
            round_number_in_season=round_number_for_summary,
            miner_scores=local_avg_rewards,
            season_history=getattr(ctx, "_season_competition_history", {}),
        ),
    }

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

    # FASE 3: IPFS downloaded data (shape built after post_consensus_evaluation so we can add evaluation_post_consensus)
    ipfs_downloaded = None
    agg_meta = getattr(ctx, "_agg_meta_cache", None)
    _downloaded_payloads_raw = []
    if agg_meta and isinstance(agg_meta, dict):
        _downloaded_payloads_raw = agg_meta.get("downloaded_payloads", [])

    # Build post_consensus_evaluation (after consensus)
    # NOTE: emission is now in round_metadata, not here
    post_consensus_evaluation = None

    # Get consensus scores (from agg cache if available, otherwise use avg_rewards as fallback)
    # consensus_scores: Dict[uid -> consensus_reward] where consensus_reward = stake-weighted average of avg_rewards from all validators
    consensus_scores = getattr(ctx, "_agg_scores_cache", None)
    if not consensus_scores:
        # Fallback 1: if aggregation returned nothing, keep observability by reusing
        # the exact score map this validator published to IPFS.
        published_scores: Dict[int, float] = {}
        try:
            published_payload = getattr(ctx, "_ipfs_uploaded_payload", None)
            published_scores_raw = published_payload.get("scores") if isinstance(published_payload, dict) else None
            if isinstance(published_scores_raw, dict):
                for uid_raw, score_raw in published_scores_raw.items():
                    try:
                        published_scores[int(uid_raw)] = float(score_raw)
                    except Exception:
                        continue
        except Exception:
            published_scores = {}

        if published_scores:
            consensus_scores = published_scores
        else:
            # Fallback 2: use local evaluated rewards (may be empty if no valid miners).
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
            "summary": _build_consensus_summary_payload(
                season_number=season_number_for_summary,
                round_number_in_season=round_number_for_summary,
                miner_scores=consensus_scores,
                season_history=getattr(ctx, "_season_competition_history", {}),
            ),
        }

        # NOTA: post_consensus_evaluation NO se sube a IPFS
        # Se calcula DESPUÉS de descargar todos los IPFS de otros validadores
        # Solo se guarda para enviarlo al backend en finish_round

    # Enrich ipfs_uploaded.payload with explicit evaluation keys (no duplication in validator_summary)
    if ipfs_uploaded and isinstance(ipfs_uploaded.get("payload"), dict):
        p = ipfs_uploaded["payload"]
        p["evaluation_pre_consensus"] = local_evaluation
        p["evaluation_post_consensus"] = post_consensus_evaluation

    # Build ipfs_downloaded with one entry per validator: cid, payload with evaluation_pre_consensus and evaluation_post_consensus
    if _downloaded_payloads_raw:
        total_stake = sum(p.get("stake", 0.0) for p in _downloaded_payloads_raw)
        payloads = []
        for p in _downloaded_payloads_raw:
            if not isinstance(p, dict):
                continue
            payloads.append(
                {
                    "validator_uid": p.get("uid"),
                    "validator_hotkey": p.get("validator_hotkey") or p.get("hk"),
                    "cid": p.get("cid"),
                    "evaluation_pre_consensus": p.get("local_evaluation"),
                    "evaluation_post_consensus": post_consensus_evaluation,
                    "payload": p,
                }
            )
        ipfs_downloaded = {
            "timestamp": ended_at,
            "validators_participated": len(payloads),
            "total_stake": total_stake,
            "payloads": payloads,
        }

    round_id = ctx.current_round_id
    season_for_round = int(season_number_for_summary or 0)
    round_for_round = int(round_number_for_summary or 0)
    # round_log_* were set at the start of this flow so we always upload even if something failed later
    s3_logs: Dict[str, Any] = {
        "schema_version": 1,
        "season_number": season_for_round,
        "round_number_in_season": round_for_round,
        "saved_at_utc": datetime.utcnow().isoformat(timespec="microseconds") + "Z",
        "round_log": {
            "file": round_log_file,
            "uploaded": round_log_url is not None,
            "url": round_log_url,
            "size_bytes": round_log_size,
            "upload_error": round_log_error,
        },
    }

    # validator_summary: single object with round, s3_logs_url, ipfs_uploaded, ipfs_downloaded,
    # evaluation_pre_consensus, evaluation_post_consensus, handshake_results
    handshake_results_raw = getattr(ctx, "handshake_results", None) or {}
    handshake_results = {str(uid): status for uid, status in handshake_results_raw.items()}

    pre_consensus_summary = local_evaluation.get("summary") if isinstance(local_evaluation, dict) else None
    post_consensus_summary = post_consensus_evaluation.get("summary") if isinstance(post_consensus_evaluation, dict) else None

    validator_summary = {
        "round": round_metadata.to_payload() if hasattr(round_metadata, "to_payload") else (round_metadata if isinstance(round_metadata, dict) else None),
        "s3_logs_url": round_log_url,
        # Keep legacy object for old readers; backend prioritizes s3_logs_url.
        "s3_logs": s3_logs,
        "ipfs_uploaded": ipfs_uploaded,
        "ipfs_downloaded": ipfs_downloaded,
        "evaluation_pre_consensus": pre_consensus_summary,
        "evaluation_post_consensus": post_consensus_summary,
        "handshake_results": handshake_results,
    }
    validator_state_json = _load_validator_state_json(ctx)
    validator_iwap_prev_round_json = _load_validator_iwap_prev_round_json(ctx)

    finish_request = iwa_models.FinishRoundIWAP(
        status="completed",
        ended_at=ended_at,
        summary=summary,
        agent_runs=agent_run_summaries,
        round_metadata=round_metadata,
        local_evaluation=local_evaluation,
        post_consensus_evaluation=post_consensus_evaluation,
        validator_summary=validator_summary,
        ipfs_uploaded=ipfs_uploaded,
        ipfs_downloaded=ipfs_downloaded,
        s3_logs_url=round_log_url,
        validator_state=validator_state_json,
        validator_iwap_prev_round_json=validator_iwap_prev_round_json,
    )

    _persist_round_summary_file(
        ctx=ctx,
        season_number=int(season_number_for_summary or 0),
        round_number=int(round_number_for_summary or 0),
        pre_consensus=pre_consensus_summary,
        post_consensus=post_consensus_summary,
        ipfs_uploaded=ipfs_uploaded,
        ipfs_downloaded=ipfs_downloaded,
        s3_logs=s3_logs,
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
        if isinstance(exc, httpx.HTTPStatusError) and _is_main_authority_or_grace_error(exc):
            max_retries, retry_interval_sec = _get_finish_retry_policy()
            log_iwap_phase(
                "Phase 5",
                (f"finish_round blocked by main-validator grace/authority for round_id={round_id}; retrying up to {max_retries} time(s) every {retry_interval_sec}s"),
                level="warning",
                exc_info=False,
            )

            retried_success = False
            last_exc: Exception = exc
            for attempt in range(1, max_retries + 1):
                log_iwap_phase(
                    "Phase 5",
                    (f"finish_round retry {attempt}/{max_retries} for round_id={round_id} in {retry_interval_sec}s"),
                    level="warning",
                    exc_info=False,
                )
                await asyncio.sleep(retry_interval_sec)
                try:
                    await ctx.iwap_client.finish_round(
                        validator_round_id=round_id,
                        finish_request=finish_request,
                    )
                except Exception as retry_exc:  # noqa: BLE001
                    last_exc = retry_exc
                    if isinstance(retry_exc, httpx.HTTPStatusError) and _is_main_authority_or_grace_error(retry_exc):
                        continue
                    # Non-authority error: stop retrying and fall through to generic handling.
                    break
                else:
                    retried_success = True
                    log_iwap_phase(
                        "Phase 5",
                        f"finish_round succeeded on retry for round_id={round_id}",
                        level="success",
                    )
                    break

            if retried_success:
                success = True
                ctx._reset_iwap_round_state()
                return success

            # If retries exhausted and still authority/grace blocked, keep local completion and continue.
            if isinstance(last_exc, httpx.HTTPStatusError) and _is_main_authority_or_grace_error(last_exc):
                log_iwap_phase(
                    "Phase 5",
                    (f"finish_round still blocked after retries for round_id={round_id}; continuing without IWAP close for this validator round"),
                    level="warning",
                    exc_info=False,
                )
                success = False
                ctx._reset_iwap_round_state()
                return success

            # Replace original exception so generic handler logs the real non-authority failure.
            exc = last_exc
        error_msg = f"finish_round failed for round_id={round_id} ({type(exc).__name__}: {exc})"
        log_iwap_phase("Phase 5", error_msg, level="error", exc_info=False)
        bt.logging.error(f"IWAP finish_round failed for round_id={round_id}: {exc}")
        success = False
        # Even if the primary finish call fails, persist the best-effort round summary
        # to keep traceability of what happened in this round.
        try:
            error_summary = dict(summary) if isinstance(summary, dict) else {}
            error_summary.setdefault("round_closure_error", {})
            error_summary["round_closure_error"] = {
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "status": "failed_on_finish_round",
            }
            finish_request.summary = error_summary
            await ctx.iwap_client.finish_round(
                validator_round_id=round_id,
                finish_request=finish_request,
            )
            success = True
            log_iwap_phase(
                "Phase 5",
                f"finish_round fallback succeeded for round_id={round_id}",
                level="success",
            )
        except Exception as fallback_exc:  # noqa: BLE001
            log_iwap_phase(
                "Phase 5",
                f"finish_round fallback also failed for round_id={round_id}: {type(fallback_exc).__name__}: {fallback_exc}",
                level="error",
            )
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
