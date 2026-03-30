from __future__ import annotations

import asyncio
import contextlib
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import bittensor as bt
import httpx

from autoppia_web_agents_subnet.platform import client as iwa_main, models as iwa_models
from autoppia_web_agents_subnet.validator import config as validator_config

from .iwa_core import (
    build_validator_identity,
    build_validator_snapshot,
    log_iwap_phase,
)


def _eligibility_status_is_valid(status: object) -> bool:
    return str(status or "").strip().lower() in {"handshake_valid", "reused", "evaluated"}


def _eligible_uids_from_status_map(raw_statuses: object) -> set[int]:
    eligible: set[int] = set()
    if not isinstance(raw_statuses, dict):
        return eligible
    for uid_raw, status_raw in raw_statuses.items():
        if not _eligibility_status_is_valid(status_raw):
            continue
        try:
            eligible.add(int(uid_raw))
        except Exception:
            continue
    return eligible


def _eligible_uids_from_downloaded_payloads(raw_payloads: object) -> set[int]:
    eligible: set[int] = set()
    if not isinstance(raw_payloads, list):
        return eligible
    for payload_entry in raw_payloads:
        if not isinstance(payload_entry, dict):
            continue
        payload = payload_entry.get("payload")
        if not isinstance(payload, dict):
            continue
        miners = payload.get("miners")
        if isinstance(miners, list):
            for miner_raw in miners:
                if not isinstance(miner_raw, dict):
                    continue
                uid_raw = miner_raw.get("uid", miner_raw.get("miner_uid"))
                try:
                    eligible.add(int(uid_raw))
                except Exception:
                    continue
            continue

        miner_metrics = payload.get("miner_metrics")
        if isinstance(miner_metrics, dict):
            for uid_raw, metric_raw in miner_metrics.items():
                if not isinstance(metric_raw, dict):
                    continue
                if metric_raw.get("eligible_this_round") is True or _eligibility_status_is_valid(metric_raw.get("eligibility_status")):
                    try:
                        eligible.add(int(metric_raw.get("miner_uid", uid_raw)))
                    except Exception:
                        continue

        rewards = payload.get("rewards")
        if not isinstance(rewards, dict):
            rewards = payload.get("scores")
        if not isinstance(rewards, dict):
            continue
        for uid_raw in rewards:
            try:
                eligible.add(int(uid_raw))
            except Exception:
                continue
    return eligible


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

    detail = payload.get("detail", payload) if isinstance(payload, dict) else payload

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


def _get_start_retry_policy() -> tuple[int, int]:
    """
    Return (max_retries, retry_interval_sec) for recoverable start_round retries.
    Config keys:
      - validator_config.START_ROUND_MAX_RETRIES
      - validator_config.START_ROUND_RETRY_SECONDS
    """
    try:
        max_retries = int(getattr(validator_config, "START_ROUND_MAX_RETRIES", 3))
    except Exception:
        max_retries = 3
    try:
        retry_interval_sec = int(getattr(validator_config, "START_ROUND_RETRY_SECONDS", 15))
    except Exception:
        retry_interval_sec = 15

    max_retries = max(0, max_retries)
    retry_interval_sec = max(1, retry_interval_sec)
    return max_retries, retry_interval_sec


def _parse_round_window_not_active(exc: httpx.HTTPStatusError) -> tuple[int | None, int | None, int | None] | None:
    response = exc.response
    if response is None or response.status_code not in (400, 409):
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
    if not isinstance(detail, dict) or detail.get("error") != "round window not active":
        return None

    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return (
        _coerce_int(detail.get("currentBlock")),
        _coerce_int(detail.get("startBlock")),
        _coerce_int(detail.get("endBlock")),
    )


def _extract_round_numbers_from_round_id(round_id: str | None) -> tuple[int | None, int | None]:
    if not isinstance(round_id, str) or not round_id:
        return None, None

    pattern = re.match(r"^validator_round_(\d+)_(\d+)_.*$", round_id)
    if not pattern:
        return None, None

    try:
        return int(pattern.group(1)), int(pattern.group(2))
    except Exception:
        return None, None


def _require_ctx_method(ctx, name: str):
    method = getattr(ctx, name, None)
    if not callable(method):
        raise AttributeError(f"Context is missing required callable: {name}")
    return method


def _load_validator_state_json(ctx) -> dict[str, Any] | None:
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


def _extract_round_summary_v2(*, season_history: dict[Any, Any], season_number: int, round_number_in_season: int) -> dict[str, Any] | None:
    season_state = season_history.get(int(season_number), {}) if isinstance(season_history, dict) else {}
    if not isinstance(season_state, dict):
        return None
    rounds_state = season_state.get("rounds", {})
    if not isinstance(rounds_state, dict):
        return None
    round_entry = rounds_state.get(int(round_number_in_season)) or rounds_state.get(str(int(round_number_in_season)))
    if not isinstance(round_entry, dict):
        return None
    post_consensus_json = round_entry.get("post_consensus_json")
    if not isinstance(post_consensus_json, dict):
        return None
    summary = post_consensus_json.get("summary")
    if isinstance(summary, dict):
        return dict(summary)
    legacy_summary_keys = {
        "season",
        "round",
        "percentage_to_dethrone",
        "dethroned",
        "leader_before_round",
        "candidate_this_round",
        "leader_after_round",
    }
    if legacy_summary_keys.intersection(post_consensus_json.keys()):
        return dict(post_consensus_json)
    return None


def _extract_previous_round_leader_after(
    *,
    season_history: dict[Any, Any],
    season_number: int,
    round_number_in_season: int,
) -> dict[str, Any] | None:
    previous_round = int(round_number_in_season) - 1
    if previous_round <= 0:
        return None
    previous_summary = _extract_round_summary_v2(
        season_history=season_history,
        season_number=season_number,
        round_number_in_season=previous_round,
    )
    if not isinstance(previous_summary, dict):
        return None
    leader_after = previous_summary.get("leader_after_round")
    return dict(leader_after) if isinstance(leader_after, dict) else None


def _canonicalize_consensus_snapshot(
    snapshot: dict[str, Any] | None,
    *,
    best_run_by_uid: dict[int, dict[str, Any]],
    preserve_reward: bool = False,
) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None

    normalized = dict(snapshot)
    try:
        uid = int(normalized.get("uid"))
    except Exception:
        return normalized

    normalized["uid"] = uid
    if preserve_reward:
        return normalized

    best_run = best_run_by_uid.get(uid)
    if not isinstance(best_run, dict):
        return normalized

    for key in ("reward", "score", "time", "cost", "weight"):
        if best_run.get(key) is not None:
            normalized[key] = float(best_run.get(key) or 0.0)
    return normalized


def _top_consensus_snapshot(
    best_run_by_uid: dict[int, dict[str, Any]],
    *,
    exclude_uid: int | None = None,
) -> dict[str, Any] | None:
    ranked: list[tuple[float, float, float, int, dict[str, Any]]] = []
    for uid_raw, best_run in best_run_by_uid.items():
        if not isinstance(best_run, dict):
            continue
        try:
            uid = int(uid_raw)
        except Exception:
            continue
        if exclude_uid is not None and uid == int(exclude_uid):
            continue
        try:
            reward = float(best_run.get("reward", 0.0) or 0.0)
            score = float(best_run.get("score", 0.0) or 0.0)
            time_s = float(best_run.get("time", 0.0) or 0.0)
        except Exception:
            continue
        if reward <= 0.0:
            continue
        ranked.append((reward, score, -time_s, -uid, {"uid": uid, **{k: v for k, v in best_run.items() if v is not None}}))

    if not ranked:
        return None

    ranked.sort(reverse=True)
    top = dict(ranked[0][4])
    top["uid"] = int(top["uid"])
    return top


def _normalize_post_consensus_leadership_summary(
    summary: dict[str, Any] | None,
    *,
    best_run_by_uid: dict[int, dict[str, Any]],
    previous_leader_after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = dict(summary) if isinstance(summary, dict) else {}
    try:
        required_improvement_pct = float(normalized.get("percentage_to_dethrone", 0.05) or 0.05)
    except Exception:
        required_improvement_pct = 0.05

    leader_before = (
        dict(previous_leader_after)
        if isinstance(previous_leader_after, dict)
        else _canonicalize_consensus_snapshot(
            normalized.get("leader_before_round"),
            best_run_by_uid=best_run_by_uid,
            preserve_reward=True,
        )
    )
    candidate = _canonicalize_consensus_snapshot(
        normalized.get("candidate_this_round"),
        best_run_by_uid=best_run_by_uid,
    )
    leader_after_existing = _canonicalize_consensus_snapshot(
        normalized.get("leader_after_round"),
        best_run_by_uid=best_run_by_uid,
    )

    if leader_before is None:
        top_snapshot = candidate or leader_after_existing or _top_consensus_snapshot(best_run_by_uid)
        normalized["leader_before_round"] = None
        normalized["candidate_this_round"] = dict(top_snapshot) if isinstance(top_snapshot, dict) else None
        normalized["leader_after_round"] = dict(top_snapshot) if isinstance(top_snapshot, dict) else None
        normalized["required_reward_to_dethrone"] = None
        normalized["dethroned"] = False
        return normalized

    try:
        leader_before_uid = int(leader_before.get("uid")) if leader_before.get("uid") is not None else None
    except Exception:
        leader_before_uid = None

    if candidate is None:
        candidate = _top_consensus_snapshot(best_run_by_uid, exclude_uid=leader_before_uid)

    try:
        leader_before_reward = float(leader_before.get("reward", 0.0) or 0.0)
    except Exception:
        leader_before_reward = 0.0
    threshold = float(leader_before_reward * (1.0 + required_improvement_pct))

    dethroned = False
    if isinstance(candidate, dict):
        try:
            candidate_reward = float(candidate.get("reward", 0.0) or 0.0)
        except Exception:
            candidate_reward = 0.0
        dethroned = bool(candidate_reward > threshold)

    normalized["leader_before_round"] = dict(leader_before)
    normalized["candidate_this_round"] = dict(candidate) if isinstance(candidate, dict) else None
    normalized["leader_after_round"] = dict(candidate if dethroned and isinstance(candidate, dict) else leader_before)
    normalized["required_reward_to_dethrone"] = threshold
    normalized["dethroned"] = dethroned
    return normalized


def _persist_round_summary_file(
    *,
    ctx,
    season_number: int,
    round_number: int,
    post_consensus: dict[str, Any] | None,
    ipfs_uploaded: dict[str, Any] | None,
    ipfs_downloaded: dict[str, Any] | None,
    s3_logs_url: str | None,
) -> None:
    if season_number <= 0 or round_number <= 0:
        return

    try:
        root_getter = getattr(ctx, "_state_summary_root", None)
        base = root_getter() if callable(root_getter) else Path("data")
        target_dir = Path(base) / f"season_{season_number}" / f"round_{round_number}"
        target_dir.mkdir(parents=True, exist_ok=True)
        legacy_summary = target_dir / "summary_round.json"
        if legacy_summary.exists():
            legacy_summary.unlink()
        if isinstance(ipfs_uploaded, dict):
            with (target_dir / "ipfs_uploaded.json").open("w", encoding="utf-8") as fh:
                json.dump(ipfs_uploaded, fh, indent=2, sort_keys=True)
        if isinstance(ipfs_downloaded, dict):
            with (target_dir / "ipfs_downloaded.json").open("w", encoding="utf-8") as fh:
                json.dump(ipfs_downloaded, fh, indent=2, sort_keys=True)
        if isinstance(post_consensus, dict):
            with (target_dir / "post_consensus.json").open("w", encoding="utf-8") as fh:
                json.dump(post_consensus, fh, indent=2, sort_keys=True)
    except Exception:
        from autoppia_web_agents_subnet.utils.logging import ColoredLogger

        ColoredLogger.warning(f"IWAP | Could not persist round artifacts for season={season_number} round={round_number}")


def _pending_finish_dir(ctx) -> Path:
    root_getter = getattr(ctx, "_state_summary_root", None)
    base = root_getter() if callable(root_getter) else Path("data")
    target = Path(base) / "pending_finish"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _round_checkpoint_files(ctx) -> list[Path]:
    root_getter = getattr(ctx, "_state_summary_root", None)
    base = root_getter() if callable(root_getter) else Path("data")
    base = Path(base)
    return sorted(base.glob("season_*/round_*/round_checkpoint.json"))


async def _flush_pending_round_log_replays(ctx) -> None:
    if getattr(ctx, "_iwap_offline_mode", False):
        return

    checkpoint_files = _round_checkpoint_files(ctx)
    if not checkpoint_files:
        return

    from autoppia_web_agents_subnet.utils.logging import ColoredLogger

    for checkpoint_file in checkpoint_files:
        try:
            payload = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        status = str(payload.get("status", "") or "").strip().lower()
        if status == "completed":
            continue

        validator_round_id = str(payload.get("validator_round_id", "") or "").strip()
        if not validator_round_id:
            continue

        round_log_file = str(payload.get("round_log_file", "") or "").strip()
        round_log_path = Path(round_log_file) if round_log_file else checkpoint_file.with_name("round.log")
        if not round_log_path.exists():
            continue

        try:
            content = round_log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        content_size = len(content.encode("utf-8", errors="replace"))
        last_uploaded_size = int(payload.get("last_round_log_uploaded_size", -1) or -1)
        if content_size > 0 and last_uploaded_size == content_size and str(payload.get("last_round_log_upload_url", "") or "").strip():
            continue

        variants = ColoredLogger.build_round_log_upload_variants(content)
        replay_url: str | None = None
        replay_exc: Exception | None = None
        for variant_label, variant_content in variants:
            try:
                replay_url = await ctx.iwap_client.upload_round_log(
                    validator_round_id=validator_round_id,
                    content=variant_content,
                    season_number=payload.get("season_number"),
                    round_number_in_season=payload.get("round_number_in_season"),
                    validator_uid=payload.get("validator_uid"),
                    validator_hotkey=payload.get("validator_hotkey"),
                )
                if variant_label != "full":
                    log_iwap_phase(
                        "Phase 5",
                        f"pending round-log replay succeeded with truncated payload ({variant_label}) for {validator_round_id}",
                        level="warning",
                        exc_info=False,
                    )
                break
            except httpx.HTTPStatusError as exc:
                replay_exc = exc
                status_code = exc.response.status_code if exc.response is not None else None
                has_smaller_variant = variant_label != variants[-1][0]
                if status_code == 413 and has_smaller_variant:
                    log_iwap_phase(
                        "Phase 5",
                        f"pending round-log replay hit 413 ({variant_label}) for {validator_round_id}; retrying with a smaller tail payload",
                        level="warning",
                        exc_info=False,
                    )
                    continue
                break
            except Exception as exc:
                replay_exc = exc
                break

        if replay_url:
            payload["last_round_log_upload_url"] = replay_url
            payload["last_round_log_uploaded_size"] = content_size
            payload["replayed_at"] = time.time()
            payload["replayed_from_startup"] = True
            checkpoint_file.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            log_iwap_phase(
                "Phase 5",
                f"pending round-log replay flushed for round_id={validator_round_id}",
                level="success",
                exc_info=False,
            )
            continue

        if replay_exc is not None:
            bt.logging.warning(f"IWAP | pending round-log replay failed for {validator_round_id}: {type(replay_exc).__name__}: {replay_exc}")


def _finish_request_to_jsonable(finish_request: Any) -> dict[str, Any]:
    if hasattr(finish_request, "to_payload"):
        payload = finish_request.to_payload()
        if isinstance(payload, dict):
            return payload
    if hasattr(finish_request, "model_dump"):
        return finish_request.model_dump(mode="json")
    if hasattr(finish_request, "dict"):
        return finish_request.dict()
    raise TypeError("finish_request is not serializable")


class _PendingFinishRequest:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = dict(payload)
        self.summary = self._payload.get("summary")

    def to_payload(self) -> dict[str, Any]:
        return dict(self._payload)


def _persist_pending_finish_request(*, ctx, validator_round_id: str, finish_request: Any) -> None:
    try:
        payload = {
            "validator_round_id": str(validator_round_id),
            "finish_request": _finish_request_to_jsonable(finish_request),
            "persisted_at": time.time(),
        }
        target = _pending_finish_dir(ctx) / f"{validator_round_id}.json"
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        bt.logging.warning(f"IWAP | Could not persist pending finish payload for {validator_round_id}")


async def _flush_pending_finish_requests(ctx) -> None:
    if getattr(ctx, "_iwap_offline_mode", False):
        return
    pending_dir = _pending_finish_dir(ctx)
    files = sorted(pending_dir.glob("*.json"))
    if not files:
        return

    for pending_file in files:
        try:
            payload = json.loads(pending_file.read_text(encoding="utf-8"))
            validator_round_id = str(payload.get("validator_round_id") or "").strip()
            finish_request_payload = payload.get("finish_request")
            if not validator_round_id or not isinstance(finish_request_payload, dict):
                pending_file.unlink(missing_ok=True)
                continue
            finish_request = _PendingFinishRequest(finish_request_payload)
            await ctx.iwap_client.finish_round(
                validator_round_id=validator_round_id,
                finish_request=finish_request,
            )
            pending_file.unlink(missing_ok=True)
            log_iwap_phase("Phase 5", f"pending finish_round flushed for round_id={validator_round_id}", level="success", exc_info=False)
        except Exception as exc:
            if isinstance(exc, httpx.HTTPStatusError) and _is_main_authority_or_grace_error(exc):
                log_iwap_phase(
                    "Phase 5",
                    f"pending finish_round still blocked for {pending_file.stem}; will retry later",
                    level="warning",
                    exc_info=False,
                )
                continue
            bt.logging.warning(f"IWAP | pending finish replay failed for {pending_file.stem}: {type(exc).__name__}: {exc}")


async def start_round_flow(ctx, *, current_block: int, n_tasks: int) -> None:
    with contextlib.suppress(Exception):
        await _flush_pending_round_log_replays(ctx)
    with contextlib.suppress(Exception):
        await _flush_pending_finish_requests(ctx)
    # Gate for downstream IWAP writes (start_agent_run/registration). Only set true once
    # round creation + set_tasks completed (or duplicate/idempotent equivalent).
    ctx._iwap_round_ready = False

    if not ctx.current_round_id:
        return

    ctx._s3_task_log_urls = []

    # 🔍 FIX: Fetch a fresh block height to avoid TTL-cached values around round boundaries
    # self.block is cached with 12s TTL. If block advances within that TTL, we send a stale round
    # and backend returns "round_number mismatch". Always use fresh block for round calculation.
    original_block = current_block
    try:
        latest_block = ctx.get_current_block(fresh=True) if hasattr(ctx, "get_current_block") else ctx.subtensor.get_current_block()
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
    max_epochs = max(1, round(validator_config.ROUND_SIZE_EPOCHS)) if validator_config.ROUND_SIZE_EPOCHS else 1
    start_epoch_raw = boundaries["round_start_epoch"]
    start_epoch = math.floor(start_epoch_raw)
    round_metadata: dict[str, Any] = {
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

    # Bootstrap DB config_season_round from validator runtime config.
    # Backend applies it only for main validator; non-main calls are ignored safely.
    try:
        sync_resp = await ctx.iwap_client.sync_runtime_config(
            validator_identity=validator_identity,
            validator_snapshot=validator_snapshot,
        )
        updated = bool(sync_resp.get("updated")) if isinstance(sync_resp, dict) else False
        if updated:
            log_iwap_phase("Config", "runtime-config synced to IWAP (main validator update applied)", level="success")
        else:
            log_iwap_phase("Config", "runtime-config sync acknowledged (non-main/no-op)", level="info")
    except Exception as exc:
        # Non-fatal: round flow should still continue.
        log_iwap_phase("Config", f"runtime-config sync failed (continuing): {type(exc).__name__}: {exc}", level="warning")

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

    def _apply_start_round_response(resp: Any) -> tuple[bool, bool]:
        vrid = _extract_validator_round_id(resp)
        if vrid != ctx.current_round_id:
            ctx.current_round_id = vrid
        response_shadow_mode = bool(resp.get("shadow_mode")) if isinstance(resp, dict) else False
        if response_shadow_mode:
            ctx._iwap_shadow_mode = True
            log_iwap_phase(
                "Phase 1",
                (f"start_round accepted in SHADOW mode for round_id={ctx.current_round_id}; continuing idempotent IWAP writes with non-authoritative close semantics"),
                level="warning",
            )
        return True, response_shadow_mode

    def _is_recoverable_start_error(exc: httpx.HTTPStatusError) -> bool:
        return _is_main_authority_or_grace_error(exc) or _parse_round_window_not_active(exc) is not None

    start_round_ok = False
    shadow_mode = False
    try:
        resp = await ctx.iwap_client.start_round(
            validator_identity=validator_identity,
            validator_round=validator_round,
            validator_snapshot=validator_snapshot,
        )
        start_round_ok, shadow_mode = _apply_start_round_response(resp)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else None
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
            if _is_recoverable_start_error(exc):
                max_retries, retry_interval_sec = _get_start_retry_policy()
                last_exc: Exception = exc
                initial_window = _parse_round_window_not_active(exc)
                if initial_window is not None:
                    current_block_seen, start_block_seen, end_block_seen = initial_window
                    log_iwap_phase(
                        "Phase 1",
                        (
                            f"start_round returned {status} because the round window is not active "
                            f"(current_block={current_block_seen}, start_block={start_block_seen}, end_block={end_block_seen}); "
                            f"retrying up to {max_retries} time(s) every {retry_interval_sec}s before degrading to local-only mode"
                        ),
                        level="warning",
                        exc_info=False,
                    )
                else:
                    log_iwap_phase(
                        "Phase 1",
                        (
                            f"start_round returned {status} due to main-validator authority/grace guard; "
                            f"retrying up to {max_retries} time(s) every {retry_interval_sec}s before degrading to shadow/local-only mode"
                        ),
                        level="warning",
                        exc_info=False,
                    )

                retried_success = False
                for attempt in range(1, max_retries + 1):
                    log_iwap_phase(
                        "Phase 1",
                        f"start_round retry {attempt}/{max_retries} for round_id={ctx.current_round_id} in {retry_interval_sec}s",
                        level="warning",
                        exc_info=False,
                    )
                    await asyncio.sleep(retry_interval_sec)
                    try:
                        retry_resp = await ctx.iwap_client.start_round(
                            validator_identity=validator_identity,
                            validator_round=validator_round,
                            validator_snapshot=validator_snapshot,
                        )
                    except httpx.HTTPStatusError as retry_exc:
                        if _is_duplicate_like_error(retry_exc):
                            start_round_ok = True
                            retried_success = True
                            break
                        mismatch = _parse_round_mismatch(retry_exc)
                        if mismatch is not None:
                            expected, got = mismatch
                            log_iwap_phase(
                                "Phase 1",
                                (f"start_round retry rejected due to round_number mismatch (expected={expected}, got={got}); continuing without IWAP sync"),
                                level="error",
                            )
                            ctx._iwap_offline_mode = True
                            return
                        last_exc = retry_exc
                        if _is_recoverable_start_error(retry_exc):
                            continue
                        exc = retry_exc
                        break
                    except Exception as retry_exc:
                        last_exc = retry_exc
                        exc = retry_exc
                        break
                    else:
                        start_round_ok, shadow_mode = _apply_start_round_response(retry_resp)
                        retried_success = True
                        log_iwap_phase(
                            "Phase 1",
                            f"start_round succeeded on retry for round_id={ctx.current_round_id}",
                            level="success",
                        )
                        break

                if retried_success:
                    pass
                elif isinstance(last_exc, httpx.HTTPStatusError) and _is_main_authority_or_grace_error(last_exc):
                    log_iwap_phase(
                        "Phase 1",
                        (
                            f"start_round still blocked by main-validator authority/grace after retries for round_id={ctx.current_round_id}; "
                            "keeping validator online in SHADOW/local-only mode for this round"
                        ),
                        level="warning",
                        exc_info=False,
                    )
                    ctx._iwap_shadow_mode = True
                    return
                elif isinstance(last_exc, httpx.HTTPStatusError) and _parse_round_window_not_active(last_exc) is not None:
                    current_block_seen, start_block_seen, end_block_seen = _parse_round_window_not_active(last_exc) or (None, None, None)
                    log_iwap_phase(
                        "Phase 1",
                        (
                            f"start_round still outside the active window after retries for round_id={ctx.current_round_id} "
                            f"(current_block={current_block_seen}, start_block={start_block_seen}, end_block={end_block_seen}); "
                            "keeping validator online and skipping IWAP writes for this round"
                        ),
                        level="warning",
                        exc_info=False,
                    )
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
            else:
                log_iwap_phase(
                    "Phase 1",
                    f"start_round failed for round_id={ctx.current_round_id}",
                    level="error",
                    exc_info=False,
                )
                ctx._iwap_offline_mode = True
                return
    except Exception as exc:
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
    if (not hasattr(ctx, "current_round_tasks") or not ctx.current_round_tasks) and hasattr(ctx, "season_manager") and hasattr(ctx.season_manager, "season_tasks"):
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
    ctx._iwap_round_ready = True

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

    if not bool(getattr(ctx, "_iwap_round_ready", False)):
        log_iwap_phase(
            "Register Miners",
            "Skipping miner registration: IWAP round is not ready (start_round/set_tasks not completed)",
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
        with contextlib.suppress(Exception):
            miner_hotkey = ctx.metagraph.hotkeys[miner_uid]

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
        is_historical_only = miner_uid in miners_reused

        if is_historical_only:
            ctx.current_miner_snapshots[miner_uid] = miner_snapshot
            ctx.agent_run_accumulators.setdefault(
                miner_uid,
                {"reward": 0.0, "eval_score": 0.0, "execution_time": 0.0, "cost": 0.0, "tasks": 0},
            )
            persist_checkpoint = getattr(ctx, "_persist_round_checkpoint", None)
            if callable(persist_checkpoint):
                with contextlib.suppress(Exception):
                    persist_checkpoint(
                        reason="start_agent_run_skipped_reuse",
                        status="registering_miners",
                        extra={
                            "miner_uid": int(miner_uid),
                            "agent_run_id": str(agent_run_id),
                            "reuse": True,
                        },
                    )
            log_iwap_phase(
                "Phase 3",
                f"Skipping start_agent_run for miner_uid={miner_uid}; keeping best historical run for this round",
                level="info",
            )
            continue

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
            total_tasks=int(len(getattr(ctx, "season_tasks", []) or []) or 0),
            metadata={"handshake_note": getattr(handshake_payload, "note", None)},
        )

        try:
            start_agent_run_message = f"Calling start_agent_run for miner_uid={miner_uid}, agent_run_id={agent_run_id}"
            persist_checkpoint = getattr(ctx, "_persist_round_checkpoint", None)
            if callable(persist_checkpoint):
                with contextlib.suppress(Exception):
                    persist_checkpoint(
                        reason="start_agent_run_started",
                        status="registering_miners",
                        extra={
                            "miner_uid": int(miner_uid),
                            "agent_run_id": str(agent_run_id),
                            "reuse": False,
                        },
                    )
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
                ctx.agent_run_accumulators.setdefault(
                    miner_uid,
                    {"reward": 0.0, "eval_score": 0.0, "execution_time": 0.0, "cost": 0.0, "tasks": 0},
                )
            else:
                start_agent_run_error = f"start_agent_run failed for miner_uid={miner_uid}, agent_run_id={agent_run_id}"
                if callable(persist_checkpoint):
                    with contextlib.suppress(Exception):
                        persist_checkpoint(
                            reason="start_agent_run_failed",
                            status="registering_miners",
                            extra={
                                "miner_uid": int(miner_uid),
                                "agent_run_id": str(agent_run_id),
                            },
                        )
                log_iwap_phase(
                    "Phase 3",
                    start_agent_run_error,
                    level="error",
                    exc_info=False,
                )
                continue
        except Exception:
            start_agent_run_error = f"start_agent_run failed for miner_uid={miner_uid}, agent_run_id={agent_run_id}"
            if callable(persist_checkpoint):
                with contextlib.suppress(Exception):
                    persist_checkpoint(
                        reason="start_agent_run_failed",
                        status="registering_miners",
                        extra={
                            "miner_uid": int(miner_uid),
                            "agent_run_id": str(agent_run_id),
                        },
                    )
            log_iwap_phase("Phase 3", start_agent_run_error, level="error", exc_info=False)
            continue
        else:
            start_agent_run_success = f"start_agent_run completed for miner_uid={miner_uid}, agent_run_id={agent_run_id}"
            if callable(persist_checkpoint):
                with contextlib.suppress(Exception):
                    persist_checkpoint(
                        reason="start_agent_run_completed",
                        status="registering_miners",
                        extra={
                            "miner_uid": int(miner_uid),
                            "agent_run_id": str(agent_run_id),
                        },
                    )
            log_iwap_phase("Phase 3", start_agent_run_success, level="success")
            # Update local state for bookkeeping
            ctx.current_agent_runs[miner_uid] = agent_run
            ctx.current_miner_snapshots[miner_uid] = miner_snapshot
            ctx.agent_run_accumulators.setdefault(
                miner_uid,
                {"reward": 0.0, "eval_score": 0.0, "execution_time": 0.0, "cost": 0.0, "tasks": 0},
            )


async def finish_round_flow(
    ctx,
    *,
    avg_rewards: dict[int, float],
    final_weights: dict[int, float],
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
        persist_checkpoint = getattr(ctx, "_persist_round_checkpoint", None)
        if callable(persist_checkpoint):
            with contextlib.suppress(Exception):
                persist_checkpoint(reason="finish_round_offline", status="completed")
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
    # Upload the full round log first; if the gateway rejects it for size,
    # fall back to a truncated tail snapshot so we still persist something useful.
    round_log_file: str | None = None
    round_log_url: str | None = None
    round_log_error: str | None = None
    try:
        # Prefer shared periodic uploader when available (keeps single source of truth
        # for throttling and retry behavior). Force upload at finish.
        uploader = getattr(ctx, "_upload_round_log_snapshot", None)
        if callable(uploader):
            round_log_url = await uploader(
                reason="finish_round",
                force=True,
                min_interval_seconds=0.0,
            )
        if round_log_url is None:
            from autoppia_web_agents_subnet.utils.logging import ColoredLogger

            round_log_file = ColoredLogger.get_round_log_file()
            if round_log_file:
                round_log_path = Path(round_log_file)
                if round_log_path.exists():
                    round_log_contents = round_log_path.read_text(encoding="utf-8", errors="replace")
                    validator_uid = getattr(ctx, "uid", None)
                    validator_hotkey = None
                    try:
                        validator_hotkey = getattr(ctx.wallet, "hotkey", None)
                        if validator_hotkey is not None:
                            validator_hotkey = getattr(validator_hotkey, "ss58_address", None)
                    except Exception:
                        pass
                    upload_variants = ColoredLogger.build_round_log_upload_variants(round_log_contents)
                    for variant_label, variant_content in upload_variants:
                        try:
                            round_log_url = await ctx.iwap_client.upload_round_log(
                                validator_round_id=round_id,
                                content=variant_content,
                                season_number=season_for_round,
                                round_number_in_season=round_for_round,
                                validator_uid=validator_uid if isinstance(validator_uid, int) else None,
                                validator_hotkey=validator_hotkey,
                            )
                            if round_log_url is not None:
                                break
                        except httpx.HTTPStatusError as exc:
                            status_code = exc.response.status_code if exc.response is not None else None
                            has_smaller_variant = variant_label != upload_variants[-1][0]
                            if status_code == 413 and has_smaller_variant:
                                bt.logging.warning(f"Round log upload hit 413 for {round_id} ({variant_label}); retrying with a smaller tail payload")
                                continue
                            raise
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
            season_number_for_summary = int(ctx.season_manager.season_number)
        except Exception:
            season_number_for_summary = 0
        try:
            round_number_for_summary = int(ctx.round_manager.round_number)
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

    local_avg_costs: dict[int, float] = {}
    for uid, acc in (getattr(ctx, "agent_run_accumulators", {}) or {}).items():
        if not isinstance(acc, dict):
            continue
        try:
            total_tasks = int(acc.get("tasks", 0) or 0)
        except Exception:
            total_tasks = 0
        try:
            total_cost = float(acc.get("cost", 0.0) or 0.0)
        except Exception:
            total_cost = 0.0
        local_avg_costs[int(uid)] = float(total_cost / total_tasks) if total_tasks > 0 else 0.0

    round_times = getattr(ctx.round_manager, "round_times", {}) or {}
    participant_uids = sorted({int(uid) for uid in (getattr(ctx, "active_miner_uids", []) or [])} | {int(uid) for uid in (getattr(ctx, "current_agent_runs", {}) or {})})
    local_reward_candidates: list[tuple[int, float, float]] = []
    local_evaluation_miners = []
    local_stats_by_miner: dict[int, dict[str, Any]] = {}

    best_run_getter = _require_ctx_method(ctx, "_best_run_payload_for_miner")
    current_run_getter = _require_ctx_method(ctx, "_current_round_run_payload")

    for miner_uid in participant_uids:
        best_run = best_run_getter(miner_uid)
        current_run = current_run_getter(miner_uid)
        effective_run = best_run or current_run
        if effective_run is None:
            effective_run = {
                "reward": float(local_avg_rewards.get(miner_uid, 0.0) or 0.0),
                "score": float(local_avg_eval_scores.get(miner_uid, 0.0) or 0.0),
                "time": 0.0,
                "cost": float(local_avg_costs.get(miner_uid, 0.0) or 0.0),
                "tasks_received": 0,
                "tasks_success": 0,
                "season": season_number_for_summary,
                "round": round_number_for_summary,
            }

        try:
            reward_value = float(effective_run.get("reward", 0.0) or 0.0)
        except Exception:
            reward_value = 0.0
        try:
            avg_time = float(effective_run.get("time", 0.0) or 0.0)
        except Exception:
            times = round_times.get(miner_uid, []) or []
            avg_time = sum(times) / len(times) if times else 999999.0
        local_reward_candidates.append((miner_uid, reward_value, avg_time))

    sorted_miners_local = sorted(local_reward_candidates, key=lambda item: (-item[1], item[2], item[0]))
    rank_map_local = {uid: rank for rank, (uid, _score, _time) in enumerate(sorted_miners_local, start=1)}

    for miner_uid in participant_uids:
        best_run = best_run_getter(miner_uid)
        current_run = current_run_getter(miner_uid)
        effective_run = best_run or current_run or {}
        rank_value = rank_map_local.get(miner_uid)

        miner_name = None
        try:
            agent_info = getattr(ctx, "agents_dict", {}).get(miner_uid)
            miner_name = getattr(agent_info, "agent_name", None)
        except Exception:
            miner_name = None
        if not miner_name:
            miner_name = f"Miner {miner_uid}"

        miner_hotkey = None
        try:
            miner_snapshot = ctx.current_miner_snapshots.get(miner_uid)
            if miner_snapshot and hasattr(miner_snapshot, "miner_hotkey"):
                miner_hotkey = miner_snapshot.miner_hotkey
            if not miner_hotkey:
                miner_hotkey = ctx.metagraph.hotkeys[miner_uid] if miner_uid < len(ctx.metagraph.hotkeys) else None
        except Exception:
            pass

        tasks_received = int(effective_run.get("tasks_received", 0) or 0)
        tasks_attempted = int(effective_run.get("tasks_attempted", tasks_received) or 0)
        tasks_success = int(effective_run.get("tasks_success", 0) or 0)
        tasks_failed = int(max(tasks_received - tasks_success, 0))
        avg_time = float(effective_run.get("time", 0.0) or 0.0)
        avg_cost = float(effective_run.get("cost", 0.0) or 0.0)
        avg_reward_value = float(effective_run.get("reward", 0.0) or 0.0)
        avg_eval_score = float(effective_run.get("score", 0.0) or 0.0)

        local_stats_by_miner[miner_uid] = {
            "avg_eval_time": avg_time,
            "avg_cost": avg_cost,
            "tasks_sent": tasks_received,
            "tasks_attempted": tasks_attempted,
            "tasks_success": tasks_success,
            "tasks_failed": tasks_failed,
            "github_url": effective_run.get("github_url"),
            "normalized_repo": effective_run.get("normalized_repo"),
            "commit_sha": effective_run.get("commit_sha"),
            "evaluation_context": effective_run.get("evaluation_context"),
        }

        miner_payload = {
            "rank": rank_value,
            "avg_reward": avg_reward_value,
            "avg_eval_score": avg_eval_score,
            "avg_evaluation_time": avg_time,
            "avg_cost": avg_cost,
            "miner_uid": miner_uid,
            "miner_hotkey": miner_hotkey,
            "miner_name": miner_name,
            "tasks_attempted": tasks_attempted,
            "tasks_completed": tasks_success,
            "tasks_failed": tasks_failed,
            "best_run": best_run,
            "current_run": current_run,
        }
        if current_run and current_run.get("zero_reason") is not None:
            miner_payload["zero_reason"] = current_run.get("zero_reason")
        if current_run and current_run.get("early_stop_reason") is not None:
            miner_payload["early_stop_reason"] = current_run.get("early_stop_reason")
        if current_run and current_run.get("early_stop_message") is not None:
            miner_payload["early_stop_message"] = current_run.get("early_stop_message")
        local_evaluation_miners.append(miner_payload)

    agent_run_summaries: list[iwa_models.FinishRoundAgentRunIWAP] = []
    for miner_uid, agent_run in (ctx.current_agent_runs or {}).items():
        current_run = current_run_getter(miner_uid)
        if current_run is None:
            continue
        miner_name = None
        try:
            agent_info = getattr(ctx, "agents_dict", {}).get(miner_uid)
            miner_name = getattr(agent_info, "agent_name", None)
        except Exception:
            miner_name = None
        agent_run_summaries.append(
            iwa_models.FinishRoundAgentRunIWAP(
                agent_run_id=agent_run.agent_run_id,
                rank=rank_map_local.get(miner_uid),
                miner_name=miner_name or f"Miner {miner_uid}",
                avg_reward=float(current_run.get("reward", 0.0) or 0.0),
                avg_evaluation_time=float(current_run.get("time", 0.0) or 0.0),
                tasks_attempted=int(current_run.get("tasks_attempted", current_run.get("tasks_received", 0)) or 0),
                tasks_completed=int(current_run.get("tasks_success", 0) or 0),
                tasks_failed=int(current_run.get("failed_tasks", 0) or 0),
                zero_reason=current_run.get("zero_reason"),
                early_stop_reason=current_run.get("early_stop_reason"),
                early_stop_message=current_run.get("early_stop_message"),
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
    from autoppia_web_agents_subnet.validator.config import BURN_AMOUNT_PERCENTAGE, BURN_UID

    burn_percentage = float(BURN_AMOUNT_PERCENTAGE)

    emission_info = {
        "burn_percentage": float(burn_percentage) * 100,  # Convert to percentage
        "burn_recipient_uid": int(BURN_UID),
    }

    # Include round/season config so backend can persist to config_season_round (main validator only)
    round_manager = getattr(ctx, "round_manager", None)
    round_size_epochs = float(round_manager.round_size_epochs) if round_manager else getattr(validator_config, "ROUND_SIZE_EPOCHS", None)
    season_size_epochs = float(round_manager.season_size_epochs) if round_manager else getattr(validator_config, "SEASON_SIZE_EPOCHS", None)
    minimum_start_block = (
        int(round_manager.minimum_start_block) if round_manager and getattr(round_manager, "minimum_start_block", None) is not None else getattr(validator_config, "MINIMUM_START_BLOCK", None)
    )
    blocks_per_epoch = int(getattr(round_manager, "BLOCKS_PER_EPOCH", 360) if round_manager else 360)

    tasks_total_for_round = 0
    tasks_completed_for_round = 0
    for miner_uid in ctx.current_agent_runs or {}:
        current_run = current_run_getter(miner_uid)
        if not isinstance(current_run, dict):
            continue
        tasks_total_for_round += int(current_run.get("tasks_received", 0) or 0)
        tasks_completed_for_round += int(current_run.get("tasks_success", 0) or 0)

    round_metadata = iwa_models.RoundMetadataIWAP(
        round_number=int(round_num or 0),
        started_at=float(getattr(ctx, "round_start_time", ended_at - 3600) or (ended_at - 3600)),
        ended_at=float(ended_at),
        start_block=int(boundaries.get("round_start_block", 0) or 0),
        end_block=int(boundaries.get("target_block", 0) or 0),
        start_epoch=float(boundaries.get("round_start_epoch", 0.0) or 0.0),
        end_epoch=float(boundaries.get("target_epoch", 0.0) or 0.0),
        tasks_total=int(tasks_total_for_round or 0),
        tasks_completed=int(tasks_completed_for_round or 0),
        miners_responded_handshake=len(getattr(ctx, "active_miner_uids", []) or []),
        miners_evaluated=len(local_evaluation_miners),
        emission=emission_info,
        round_size_epochs=round_size_epochs,
        season_size_epochs=season_size_epochs,
        minimum_start_block=minimum_start_block,
        blocks_per_epoch=blocks_per_epoch,
    )

    local_eligibility_statuses_raw = getattr(ctx, "eligibility_status_by_uid", None) or {}
    local_eligibility_statuses = {str(uid): str(status) for uid, status in local_eligibility_statuses_raw.items()}

    # local_evaluation should match what this validator actually uploaded to IPFS.
    local_evaluation = getattr(ctx, "_ipfs_uploaded_payload", None)
    if not isinstance(local_evaluation, dict):
        local_evaluation = {
            "season": int(season_number_for_summary or 0),
            "round": int(round_number_for_summary or 0),
            "miners": local_evaluation_miners,
            "summary": None,
        }

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

    # Get consensus rewards (from agg cache if available, otherwise use avg_rewards as fallback).
    # consensus_rewards: Dict[uid -> consensus_reward], where consensus_reward is the stake-weighted
    # average of each validator's published avg_reward for that miner. The companion metrics
    # avg_eval_score, avg_eval_time and avg_cost are also aggregated with the same stake weights.
    consensus_rewards = getattr(ctx, "_agg_scores_cache", None)
    if not consensus_rewards:
        # Fallback 1: if aggregation returned nothing, keep observability by reusing
        # the exact reward map this validator published to IPFS.
        published_rewards: dict[int, float] = {}
        try:
            published_payload = getattr(ctx, "_ipfs_uploaded_payload", None)
            published_rewards_raw = None
            if isinstance(published_payload, dict):
                published_rewards_raw = published_payload.get("rewards")
                if not isinstance(published_rewards_raw, dict):
                    published_rewards_raw = published_payload.get("scores")
                if not isinstance(published_rewards_raw, dict):
                    for miner_entry in published_payload.get("miners", []) if isinstance(published_payload.get("miners", []), list) else []:
                        if not isinstance(miner_entry, dict):
                            continue
                        best_run = miner_entry.get("best_run")
                        if not isinstance(best_run, dict):
                            continue
                        try:
                            published_rewards[int(miner_entry.get("uid"))] = float(best_run.get("reward", 0.0) or 0.0)
                        except Exception:
                            continue
            if isinstance(published_rewards_raw, dict):
                for uid_raw, reward_raw in published_rewards_raw.items():
                    try:
                        published_rewards[int(uid_raw)] = float(reward_raw)
                    except Exception:
                        continue
        except Exception:
            published_rewards = {}

        # Fallback 2: use local evaluated rewards if no published (may be empty if no valid miners).
        consensus_rewards = published_rewards or avg_rewards

    stats_by_miner = {}
    current_stats_by_miner = {}
    if agg_meta and isinstance(agg_meta, dict):
        stats_by_miner = agg_meta.get("stats_by_miner", {}) or {}
        current_stats_by_miner = agg_meta.get("current_stats_by_miner", {}) or {}

    if consensus_rewards and isinstance(consensus_rewards, dict):
        # Calculate ranks from consensus rewards.
        sorted_consensus = sorted(consensus_rewards.items(), key=lambda item: item[1], reverse=True)
        rank_map_consensus = {uid: rank for rank, (uid, _consensus_reward) in enumerate(sorted_consensus, start=1)}

        # Build post_consensus miners list - include all miners with weight > 0 (including burn_uid)
        # BURN_AMOUNT_PERCENTAGE and BURN_UID are already imported above

        post_consensus_miners = []
        # First, add all miners from consensus_rewards
        for miner_uid, consensus_reward in consensus_rewards.items():
            weight = final_weights.get(miner_uid, 0.0)
            rank = rank_map_consensus.get(miner_uid)

            # Obtener stats: current-round stake-weighted first, then best-run consensus, then local fallback.
            current_stats = current_stats_by_miner.get(miner_uid) or {}
            consensus_stats = stats_by_miner.get(miner_uid) or {}
            local_stats = local_stats_by_miner.get(miner_uid) or {}
            best_run_payload = best_run_getter(miner_uid)
            current_run_payload = current_run_getter(miner_uid)
            current_run_dict = current_run_payload if isinstance(current_run_payload, dict) else {}
            best_run_dict = best_run_payload if isinstance(best_run_payload, dict) else {}

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

            # Prefer current-round aggregated stats (stake-weighted via aggregate_scores_from_commitments
            # using current_run data) over the historical best-run consensus stats.
            # This ensures time/cost/score reflect the actual round, not a cached prior round.
            post_consensus_avg_eval_score = current_stats.get("avg_eval_score") or consensus_stats.get("avg_eval_score") or local_avg_eval_scores.get(miner_uid, 0.0)
            avg_eval_time = current_stats.get("avg_eval_time") or consensus_stats.get("avg_eval_time") or local_stats.get("avg_eval_time", 0.0)
            avg_cost = current_stats.get("avg_cost") or consensus_stats.get("avg_cost") or local_stats.get("avg_cost", 0.0)
            # IMPORTANT:
            # best_run_consensus must describe the consensus view of THIS round,
            # not the miner's historical best run. Use current-round payload and
            # aggregated round stats first, and only fall back to best_run for
            # identity fields when there is no round-local data.
            if "tasks_received" in current_run_dict:
                tasks_sent = int(current_run_dict.get("tasks_received", 0) or 0)
            else:
                tasks_sent = int(current_stats.get("tasks_sent") or 0) or int(consensus_stats.get("tasks_sent") or 0) or int(local_stats.get("tasks_sent", 0) or 0)
            if "tasks_success" in current_run_dict:
                tasks_success = int(current_run_dict.get("tasks_success", 0) or 0)
            else:
                tasks_success = int(current_stats.get("tasks_success") or 0) or int(consensus_stats.get("tasks_success") or 0) or int(local_stats.get("tasks_success", 0) or 0)
            github_url = current_run_dict.get("github_url") or local_stats.get("github_url") or best_run_dict.get("github_url")
            normalized_repo = current_run_dict.get("normalized_repo") or local_stats.get("normalized_repo") or best_run_dict.get("normalized_repo")
            commit_sha = current_run_dict.get("commit_sha") or local_stats.get("commit_sha") or best_run_dict.get("commit_sha")
            evaluation_context = current_run_dict.get("evaluation_context") if isinstance(current_run_dict.get("evaluation_context"), dict) else local_stats.get("evaluation_context")
            if not isinstance(evaluation_context, dict):
                fallback_context = best_run_dict.get("evaluation_context")
                evaluation_context = dict(fallback_context) if isinstance(fallback_context, dict) else local_stats.get("evaluation_context")

            current_run_consensus = None
            if (isinstance(current_stats, dict) and current_stats) or current_run_dict:
                current_run_consensus = {
                    "reward": float(current_stats.get("avg_reward", 0.0) if isinstance(current_stats, dict) and current_stats else current_run_dict.get("reward", 0.0) or 0.0),
                    "score": float(current_stats.get("avg_eval_score", 0.0) if isinstance(current_stats, dict) and current_stats else current_run_dict.get("score", 0.0) or 0.0),
                    "time": float(current_stats.get("avg_eval_time", 0.0) if isinstance(current_stats, dict) and current_stats else current_run_dict.get("time", 0.0) or 0.0),
                    "cost": float(current_stats.get("avg_cost", 0.0) if isinstance(current_stats, dict) and current_stats else current_run_dict.get("cost", 0.0) or 0.0),
                    "tasks_received": int(current_run_dict.get("tasks_received", 0) or 0) if current_run_dict else int(current_stats.get("tasks_sent", 0) or 0),
                    "tasks_success": int(current_run_dict.get("tasks_success", 0) or 0) if current_run_dict else int(current_stats.get("tasks_success", 0) or 0),
                    "github_url": current_run_dict.get("github_url") if current_run_dict else github_url,
                    "normalized_repo": current_run_dict.get("normalized_repo") if current_run_dict else normalized_repo,
                    "commit_sha": current_run_dict.get("commit_sha") if current_run_dict else commit_sha,
                }
                current_context = current_run_dict.get("evaluation_context") if current_run_dict else None
                if isinstance(current_context, dict):
                    current_run_consensus["evaluation_context"] = dict(current_context)
                elif isinstance(evaluation_context, dict):
                    current_run_consensus["evaluation_context"] = dict(evaluation_context)

            post_consensus_miners.append(
                {
                    "uid": miner_uid,
                    "hotkey": miner_hotkey,
                    "github_url": github_url,
                    "best_run_consensus": {
                        "reward": float(consensus_reward),
                        "score": float(post_consensus_avg_eval_score),
                        "time": float(avg_eval_time),
                        "cost": float(avg_cost),
                        "tasks_received": int(tasks_sent),
                        "tasks_success": int(tasks_success),
                        "github_url": github_url,
                        "normalized_repo": normalized_repo,
                        "commit_sha": commit_sha,
                        "rank": rank,
                        "weight": float(weight),
                    },
                    "current_run_consensus": current_run_consensus,
                }
            )
            if isinstance(evaluation_context, dict):
                post_consensus_miners[-1]["best_run_consensus"]["evaluation_context"] = dict(evaluation_context)

        # Add burn_uid if it has weight > 0 but is not in consensus_rewards
        burn_uid = int(BURN_UID)
        burn_weight = final_weights.get(burn_uid, 0.0)
        if burn_weight > 0.0 and burn_uid not in consensus_rewards:
            # Burn UID gets a rank after all consensus miners
            max_rank = max(rank_map_consensus.values()) if rank_map_consensus else 0
            # Obtener miner_hotkey para burn_uid
            burn_miner_hotkey = None
            with contextlib.suppress(Exception):
                burn_miner_hotkey = ctx.metagraph.hotkeys[burn_uid] if burn_uid < len(ctx.metagraph.hotkeys) else None

            post_consensus_miners.append(
                {
                    "uid": burn_uid,
                    "hotkey": burn_miner_hotkey,
                    "best_run_consensus": {
                        "reward": 0.0,
                        "score": 0.0,
                        "time": 0.0,
                        "cost": 0.0,
                        "tasks_received": 0,
                        "tasks_success": 0,
                        "rank": max_rank + 1,
                        "weight": float(burn_weight),
                    },
                    "current_run_consensus": None,
                }
            )

        post_consensus_json_summary = _extract_round_summary_v2(
            season_history=getattr(ctx, "_season_competition_history", {}) or {},
            season_number=int(season_number_for_summary or 0),
            round_number_in_season=int(round_number_for_summary or 0),
        )
        previous_leader_after = _extract_previous_round_leader_after(
            season_history=getattr(ctx, "_season_competition_history", {}) or {},
            season_number=int(season_number_for_summary or 0),
            round_number_in_season=int(round_number_for_summary or 0),
        )
        best_run_by_uid = {
            int(miner_payload.get("uid")): dict(miner_payload.get("best_run_consensus") or {})
            for miner_payload in post_consensus_miners
            if isinstance(miner_payload, dict) and miner_payload.get("uid") is not None
        }

        if isinstance(post_consensus_json_summary, dict):
            post_consensus_json_summary = _normalize_post_consensus_leadership_summary(
                post_consensus_json_summary,
                best_run_by_uid=best_run_by_uid,
                previous_leader_after=previous_leader_after,
            )

        post_consensus_evaluation = {
            "season": int(season_number_for_summary or 0),
            "round": int(round_number_for_summary or 0),
            "consensus_type": "stake_weighted",
            "validators_participated": len(_downloaded_payloads_raw) if _downloaded_payloads_raw else 0,
            "total_stake": float(sum(float(p.get("stake", 0.0) or 0.0) for p in _downloaded_payloads_raw if isinstance(p, dict))) if _downloaded_payloads_raw else 0.0,
            "miners": post_consensus_miners,
            "timestamp": ended_at,
            "summary": post_consensus_json_summary,
        }

        # NOTA: post_consensus_evaluation NO se sube a IPFS
        # Se calcula DESPUÉS de descargar todos los IPFS de otros validadores
        # Solo se guarda para enviarlo al backend en finish_round
        try:
            season_history = getattr(ctx, "_season_competition_history", None) or {}
            if isinstance(season_history, dict):
                season_key = int(season_number_for_summary or 0)
                round_key = int(round_number_for_summary or 0)
                season_state = season_history.get(season_key)
                if not isinstance(season_state, dict):
                    season_state = {}
                rounds_state = season_state.get("rounds")
                if not isinstance(rounds_state, dict):
                    rounds_state = {}
                round_entry = rounds_state.get(round_key)
                if not isinstance(round_entry, dict):
                    round_entry = {}
                round_entry["post_consensus_json"] = dict(post_consensus_evaluation)
                rounds_state[round_key] = round_entry
                season_state["rounds"] = rounds_state
                season_history[season_key] = season_state
                ctx._season_competition_history = season_history
                persist_fn = getattr(ctx, "_save_competition_state", None)
                if callable(persist_fn):
                    persist_fn()
        except Exception:
            bt.logging.warning("IWAP | Could not persist full post_consensus_json into local season history")

    # Build ipfs_downloaded with the raw downloaded payloads plus the shared post-consensus object.
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
    # validator_summary: observability object kept in backend, separate from IPFS raw payloads.
    handshake_results_raw = getattr(ctx, "handshake_results", None) or {}
    handshake_results = {str(uid): status for uid, status in handshake_results_raw.items()}

    post_consensus_payload = post_consensus_evaluation if isinstance(post_consensus_evaluation, dict) else None

    validator_summary = {
        "round": round_metadata.to_payload() if hasattr(round_metadata, "to_payload") else (round_metadata if isinstance(round_metadata, dict) else None),
        "s3_logs_url": round_log_url,
        "ipfs_uploaded": ipfs_uploaded,
        "ipfs_downloaded": ipfs_downloaded,
        "evaluation_post_consensus": post_consensus_payload,
        "handshake_results": handshake_results,
        "eligibility_statuses": local_eligibility_statuses,
    }
    validator_state_json = _load_validator_state_json(ctx)

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
    )

    _persist_round_summary_file(
        ctx=ctx,
        season_number=int(season_number_for_summary or 0),
        round_number=int(round_number_for_summary or 0),
        post_consensus=post_consensus_payload,
        ipfs_uploaded=ipfs_uploaded,
        ipfs_downloaded=ipfs_downloaded,
        s3_logs_url=round_log_url,
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
    except Exception as exc:
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
                except Exception as retry_exc:
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
                persist_checkpoint = getattr(ctx, "_persist_round_checkpoint", None)
                if callable(persist_checkpoint):
                    with contextlib.suppress(Exception):
                        persist_checkpoint(reason="finish_round_completed", status="completed")
                success = True
                return success

            # If retries exhausted and still authority/grace blocked, keep local completion and continue.
            if isinstance(last_exc, httpx.HTTPStatusError) and _is_main_authority_or_grace_error(last_exc):
                _persist_pending_finish_request(
                    ctx=ctx,
                    validator_round_id=round_id,
                    finish_request=finish_request,
                )
                log_iwap_phase(
                    "Phase 5",
                    (f"finish_round still blocked after retries for round_id={round_id}; persisted pending finish payload and continuing without IWAP close for this validator round"),
                    level="warning",
                    exc_info=False,
                )
                persist_checkpoint = getattr(ctx, "_persist_round_checkpoint", None)
                if callable(persist_checkpoint):
                    with contextlib.suppress(Exception):
                        persist_checkpoint(reason="finish_round_pending", status="pending_finish")
                success = False
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
            persist_checkpoint = getattr(ctx, "_persist_round_checkpoint", None)
            if callable(persist_checkpoint):
                with contextlib.suppress(Exception):
                    persist_checkpoint(reason="finish_round_fallback_completed", status="completed")
            log_iwap_phase(
                "Phase 5",
                f"finish_round fallback succeeded for round_id={round_id}",
                level="success",
            )
        except Exception as fallback_exc:
            _persist_pending_finish_request(
                ctx=ctx,
                validator_round_id=round_id,
                finish_request=finish_request,
            )
            log_iwap_phase(
                "Phase 5",
                f"finish_round fallback also failed for round_id={round_id}: {type(fallback_exc).__name__}: {fallback_exc}. Pending finish payload persisted for retry.",
                level="error",
            )
    else:
        persist_checkpoint = getattr(ctx, "_persist_round_checkpoint", None)
        if callable(persist_checkpoint):
            with contextlib.suppress(Exception):
                persist_checkpoint(reason="finish_round_completed", status="completed")
        log_iwap_phase(
            "Phase 5",
            f"finish_round completed for round_id={round_id}",
            level="success",
        )
        success = True
    finally:
        ctx._reset_iwap_round_state()
    return success
