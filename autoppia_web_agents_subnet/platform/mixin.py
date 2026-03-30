from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import bittensor as bt
import httpx

from autoppia_web_agents_subnet.platform import client as iwa_main, models as iwa_models
from autoppia_web_agents_subnet.platform.utils.iwa_core import (
    build_iwap_auth_headers,
    build_iwap_tasks as _utils_build_iwap_tasks,
    build_validator_identity as _utils_build_validator_identity,
    build_validator_snapshot as _utils_build_validator_snapshot,
    extract_gif_bytes as _utils_extract_gif_bytes,
    log_iwap_phase,
    metagraph_numeric as _metrics_metagraph_numeric,
    normalized_stake_tao as _metrics_normalized_stake_tao,
    validator_vtrust as _metrics_validator_vtrust,
)
from autoppia_web_agents_subnet.platform.utils.round_flow import (
    finish_round_flow as _utils_finish_round_flow,
    register_participating_miners_in_iwap as _utils_register_participating_miners_in_iwap,
    start_round_flow as _utils_start_round_flow,
)
from autoppia_web_agents_subnet.platform.utils.task_flow import (
    submit_task_results as _utils_submit_task_results,
)
from autoppia_web_agents_subnet.validator import config as validator_config
from autoppia_web_agents_subnet.validator.config import (
    IWAP_API_BASE_URL,
    IWAP_VALIDATOR_AUTH_MESSAGE,
)
from autoppia_web_agents_subnet.validator.models import TaskWithProject


class ValidatorPlatformMixin:
    """Shared IWAP integration helpers extracted from the validator loop."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Unify all validator local artifacts under the bittensor neuron path tree.
        # This avoids splitting state between repo ./data and ~/.bittensor/...
        try:
            default_backup_dir = Path(str(self.config.neuron.full_path)).parent.parent / "data"
        except Exception:
            default_backup_dir = Path("data")
        os.environ.setdefault("IWAP_BACKUP_DIR", str(default_backup_dir))
        backup_dir = Path(os.environ.get("IWAP_BACKUP_DIR", str(default_backup_dir)))
        self._IWAP_VALIDATOR_AUTH_MESSAGE = IWAP_VALIDATOR_AUTH_MESSAGE or "I am a honest validator"
        self._auth_warning_emitted = False
        self.iwap_client = iwa_main.IWAPClient(
            base_url=IWAP_API_BASE_URL,
            backup_dir=backup_dir,
            auth_provider=self._build_iwap_auth_headers,
        )
        self.current_round_id: str | None = None
        self.current_round_tasks: dict[str, iwa_models.TaskIWAP] = {}
        self.current_agent_runs: dict[int, iwa_models.AgentRunIWAP] = {}
        self.current_miner_snapshots: dict[int, iwa_models.MinerSnapshotIWAP] = {}
        self._iwap_shadow_mode = False
        self.round_handshake_payloads: dict[int, Any] = {}
        self.eligibility_status_by_uid: dict[int, str] = {}
        self.round_start_timestamp: float = 0.0
        self.agent_run_accumulators: dict[int, dict[str, float]] = {}
        # (repo, commit) already evaluated per miner -> persisted best-run candidate data.
        self._evaluated_commits_by_miner: dict[int, dict[str, dict[str, Any]]] = {}  # uid -> "repo|commit" -> {agent_run_id, ...stats}
        self._disable_reuse_until: dict[str, Any] | None = None
        self._pending_all_zero_round_policy: dict[str, Any] | None = None
        self._last_all_zero_round_policy: dict[str, Any] | None = None
        # Track completed (miner_uid, task_id) to avoid duplicates
        self._completed_pairs: set[tuple[int, str]] = set()
        # Round-log periodic upload state (best effort, no hard dependency).
        self._round_log_last_upload_ts: float = 0.0
        self._round_log_last_uploaded_size: int = -1
        self._round_log_last_uploaded_url: str | None = None
        self._round_log_last_upload_round_id: str | None = None
        # Phase flags for IWAP steps (p1=start_round, p2=set_tasks)
        self._phases: dict[str, Any] = {"p1_done": False, "p2_done": False}

    def _evaluation_context_payload(self) -> dict[str, Any]:
        season_number, _round_number = self._current_round_numbers()
        try:
            round_size_epochs = float(getattr(getattr(self, "round_manager", None), "round_size_epochs", 0.0) or 0.0)
        except Exception:
            round_size_epochs = 0.0
        try:
            season_size_epochs = float(getattr(getattr(self, "season_manager", None), "season_size_epochs", 0.0) or 0.0)
        except Exception:
            season_size_epochs = 0.0
        try:
            round_manager = getattr(self, "round_manager", None)
            blocks_per_epoch = int(getattr(round_manager, "BLOCKS_PER_EPOCH", None) or getattr(round_manager, "blocks_per_epoch", None) or 360)
        except Exception:
            blocks_per_epoch = 360
        try:
            minimum_start_block = int(getattr(validator_config, "MINIMUM_START_BLOCK", 0) or 0)
        except Exception:
            minimum_start_block = 0
        minimum_validator_version = str(getattr(self, "version", "") or "")

        context_without_hash = {
            "season_number": season_number,
            "round_size_epochs": round_size_epochs,
            "season_size_epochs": season_size_epochs,
            "blocks_per_epoch": blocks_per_epoch,
            "minimum_start_block": minimum_start_block,
            "minimum_validator_version": minimum_validator_version,
        }
        context_json = json.dumps(context_without_hash, sort_keys=True, separators=(",", ":"))
        return {
            **context_without_hash,
            "evaluation_context_hash": f"sha256:{hashlib.sha256(context_json.encode('utf-8')).hexdigest()}",
        }

    def _is_same_evaluation_context(self, stats: dict[str, Any] | None) -> bool:
        if not isinstance(stats, dict):
            return False
        saved_context = stats.get("evaluation_context")
        if not isinstance(saved_context, dict):
            return False
        current_context = self._evaluation_context_payload()
        return str(saved_context.get("evaluation_context_hash", "") or "") == str(current_context.get("evaluation_context_hash", "") or "")

    def _find_reusable_commit_stats(
        self,
        *,
        uid: int,
        github_url: str | None,
        normalized_repo: str | None,
        commit_sha: str | None,
    ) -> dict[str, Any] | None:
        reuse_guard = getattr(self, "_disable_reuse_until", None)
        if isinstance(reuse_guard, dict):
            season_number, round_number = self._current_round_numbers()
            try:
                guard_season = int(reuse_guard.get("season"))
                guard_round = int(reuse_guard.get("round"))
            except Exception:
                guard_season = None
                guard_round = None
            if guard_season is not None and guard_round is not None and int(season_number) == guard_season and int(round_number) <= guard_round:
                return None

        stored_map = (getattr(self, "_evaluated_commits_by_miner", None) or {}).get(uid) or {}
        if not isinstance(stored_map, dict):
            return None

        github_key = str(github_url or "").strip()
        repo_key = str(normalized_repo or "").strip()
        commit_key_raw = str(commit_sha or "").strip()
        candidates: list[dict[str, Any]] = []

        if github_key:
            entry = stored_map.get(github_key)
            if isinstance(entry, dict):
                candidates.append(entry)
        if repo_key and commit_key_raw:
            entry = stored_map.get(f"{repo_key}|{commit_key_raw}")
            if isinstance(entry, dict):
                candidates.append(entry)

        valid_candidates: list[dict[str, Any]] = []
        for entry in candidates:
            if not entry.get("agent_run_id"):
                continue
            if not self._is_same_evaluation_context(entry):
                continue
            try:
                total_tasks = int(entry.get("total_tasks", 0) or 0)
            except Exception:
                total_tasks = 0
            if total_tasks <= 0:
                continue
            valid_candidates.append(entry)

        if not valid_candidates:
            return None

        def _candidate_key(entry: dict[str, Any]) -> tuple[float, float, float, int]:
            try:
                reward = float(entry.get("average_reward", entry.get("reward", 0.0)) or 0.0)
            except Exception:
                reward = 0.0
            try:
                score = float(entry.get("average_score", entry.get("score", 0.0)) or 0.0)
            except Exception:
                score = 0.0
            try:
                exec_time = float(entry.get("average_execution_time", entry.get("time", 0.0)) or 0.0)
            except Exception:
                exec_time = 0.0
            try:
                total_tasks = int(entry.get("total_tasks", 0) or 0)
            except Exception:
                total_tasks = 0
            return (reward, score, -exec_time, total_tasks)

        return max(valid_candidates, key=_candidate_key)

    def _purge_evaluated_commits_for_round(
        self,
        *,
        season_number: int,
        round_number: int,
        miner_uids: set[int] | None = None,
    ) -> int:
        commits_by_miner = getattr(self, "_evaluated_commits_by_miner", None)
        if not isinstance(commits_by_miner, dict):
            return 0

        target_uids = {int(uid) for uid in (miner_uids or set())}
        removed = 0
        for uid, entries in list(commits_by_miner.items()):
            try:
                uid_i = int(uid)
            except Exception:
                uid_i = uid
            if target_uids and uid_i not in target_uids:
                continue
            if not isinstance(entries, dict):
                continue
            kept_entries: dict[str, dict[str, Any]] = {}
            for key, stats in entries.items():
                if not isinstance(stats, dict):
                    kept_entries[key] = stats
                    continue
                try:
                    stats_season = int(stats.get("evaluated_season", -1) or -1)
                    stats_round = int(stats.get("evaluated_round", -1) or -1)
                except Exception:
                    stats_season = -1
                    stats_round = -1
                if stats_season == int(season_number) and stats_round == int(round_number):
                    removed += 1
                    continue
                kept_entries[key] = stats
            if kept_entries:
                commits_by_miner[uid] = kept_entries
            else:
                commits_by_miner.pop(uid, None)
        return removed

    def _current_round_all_runs_zero(self) -> bool:
        active_uids = {int(uid) for uid in (set(getattr(self, "active_miner_uids", None) or set()) | set((getattr(self, "current_agent_runs", None) or {}).keys()))}
        if not active_uids:
            return False

        miners_reused = {int(uid) for uid in (getattr(self, "miners_reused_this_round", None) or set())}
        inspected_uids: set[int] = set()
        for uid_i in sorted(active_uids):
            if uid_i in miners_reused:
                continue
            payload = self._current_round_run_payload(uid_i)
            if not isinstance(payload, dict):
                inspected_uids.add(uid_i)
                continue
            zero_reason = str(payload.get("zero_reason", "") or "")
            if zero_reason == "round_window_exceeded":
                continue
            inspected_uids.add(uid_i)
            try:
                reward = float(payload.get("reward", 0.0) or 0.0)
            except Exception:
                reward = 0.0
            if reward > 0.0:
                return False

        return bool(inspected_uids)

    def _effective_signal_all_runs_zero(self) -> bool:
        """
        Returns True only when the validator has no positive effective signal for any active miner.

        Effective signal is what consensus should care about:
        - current round run if it improved the miner
        - otherwise the best historical run carried in the snapshot

        This intentionally differs from `_current_round_all_runs_zero()`, which is still used for
        local re-evaluation policy when the freshly evaluated round itself looks suspicious.
        """
        active_uids = {int(uid) for uid in (set(getattr(self, "active_miner_uids", None) or set()) | set((getattr(self, "current_agent_runs", None) or {}).keys()))}
        if not active_uids:
            return False

        for uid_i in sorted(active_uids):
            best_payload = self._best_run_payload_for_miner(uid_i)
            if not isinstance(best_payload, dict):
                continue
            try:
                reward = float(best_payload.get("reward", 0.0) or 0.0)
            except Exception:
                reward = 0.0
            if reward > 0.0:
                return False

        return True

    def _mark_all_zero_round_for_re_evaluation(self) -> bool:
        season_number, round_number = self._current_round_numbers()
        if season_number is None or round_number is None:
            return False

        is_all_zero = self._current_round_all_runs_zero()
        if not is_all_zero:
            return False

        current_runs = getattr(self, "current_agent_runs", None) or {}
        miners_reused = {int(uid) for uid in (getattr(self, "miners_reused_this_round", None) or set())}
        inspected_uids: set[int] = set()
        for uid in list(current_runs.keys()):
            try:
                uid_i = int(uid)
            except Exception:
                continue
            if uid_i in miners_reused:
                continue
            payload = self._current_round_run_payload(uid_i)
            if not isinstance(payload, dict):
                continue
            if str(payload.get("zero_reason", "") or "") == "round_window_exceeded":
                continue
            inspected_uids.add(uid_i)

        if not inspected_uids:
            return False

        self._pending_all_zero_round_policy = {
            "season": int(season_number),
            "round": int(round_number),
            "miner_uids": sorted(inspected_uids),
        }
        self._last_all_zero_round_policy = {
            "season": int(season_number),
            "round": int(round_number),
            "miner_uids": sorted(inspected_uids),
            "purged_entries": 0,
            "reuse_preserved": None,
            "status": "pending_consensus",
        }
        return True

    def _apply_post_consensus_reuse_policy(self, details: dict[str, Any] | None) -> bool:
        pending = getattr(self, "_pending_all_zero_round_policy", None)
        if not isinstance(pending, dict):
            return False

        try:
            season_number = int(pending.get("season"))
            round_number = int(pending.get("round"))
        except Exception:
            self._pending_all_zero_round_policy = None
            return False

        miner_uids_raw = pending.get("miner_uids") or []
        miner_uids: set[int] = set()
        for uid_raw in miner_uids_raw:
            try:
                miner_uids.add(int(uid_raw))
            except Exception:
                continue

        skips = {}
        if isinstance(details, dict):
            raw_skips = details.get("skips")
            if isinstance(raw_skips, dict):
                skips = raw_skips

        excluded_all_zero = skips.get("all_zero_when_others_positive") or []
        validator_hotkey = str(getattr(getattr(getattr(self, "wallet", None), "hotkey", None), "ss58_address", "") or "")
        excluded_by_consensus = False
        if validator_hotkey and isinstance(excluded_all_zero, list):
            for entry in excluded_all_zero:
                if not isinstance(entry, tuple | list) or not entry:
                    continue
                hotkey = str(entry[0] or "")
                if hotkey == validator_hotkey:
                    excluded_by_consensus = True
                    break

        purged_entries = 0
        if excluded_by_consensus:
            purged_entries = self._purge_evaluated_commits_for_round(
                season_number=season_number,
                round_number=round_number,
                miner_uids=miner_uids,
            )
            self._disable_reuse_until = {
                "season": int(season_number),
                "round": int(round_number) + 1,
                "reason": "all_zero_excluded_by_consensus",
                "miner_uids": sorted(miner_uids),
            }

        self._last_all_zero_round_policy = {
            "season": int(season_number),
            "round": int(round_number),
            "miner_uids": sorted(miner_uids),
            "purged_entries": int(purged_entries),
            "reuse_preserved": not excluded_by_consensus,
            "status": "excluded_by_consensus" if excluded_by_consensus else "preserved_after_consensus",
        }
        self._pending_all_zero_round_policy = None
        return excluded_by_consensus

    def _log_iwap_phase(self, phase: str, message: str, *, level: str = "info", exc_info: bool = False) -> None:
        # Delegate to logging utility (keeps test compatibility with monkeypatching this method)
        log_iwap_phase(phase, message, level=level, exc_info=exc_info)

    def _round_checkpoint_path(self, round_id: str | None = None) -> Path | None:
        target_round_id = str(round_id or getattr(self, "current_round_id", "") or "").strip()
        if not target_round_id:
            return None

        season_number, round_number = self._extract_round_numbers_from_round_id(target_round_id)
        root_getter = getattr(self, "_state_summary_root", None)
        try:
            base = root_getter() if callable(root_getter) else Path(os.getenv("IWAP_BACKUP_DIR", "data"))
        except Exception:
            base = Path(os.getenv("IWAP_BACKUP_DIR", "data"))

        base = Path(base)
        if season_number is not None and round_number is not None:
            base = base / f"season_{int(season_number)}" / f"round_{int(round_number)}"
        base.mkdir(parents=True, exist_ok=True)
        return base / "round_checkpoint.json"

    def _persist_round_checkpoint(
        self,
        *,
        reason: str,
        status: str = "in_progress",
        round_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Path | None:
        checkpoint_path = self._round_checkpoint_path(round_id)
        if checkpoint_path is None:
            return None

        target_round_id = str(round_id or getattr(self, "current_round_id", "") or "").strip()
        season_number, round_number = self._extract_round_numbers_from_round_id(target_round_id)
        round_log_file = None
        round_log_exists = False
        round_log_size = 0
        try:
            from autoppia_web_agents_subnet.utils.logging import ColoredLogger

            round_log_file = ColoredLogger.get_round_log_file()
        except Exception:
            round_log_file = None

        if round_log_file:
            try:
                round_log_path = Path(round_log_file)
                round_log_exists = round_log_path.exists()
                if round_log_exists:
                    round_log_size = int(round_log_path.stat().st_size)
            except Exception:
                round_log_exists = False
                round_log_size = 0

        phase_history_payload: list[dict[str, Any]] = []
        round_manager = getattr(self, "round_manager", None)
        for item in list(getattr(round_manager, "phase_history", []) or [])[-20:]:
            phase = getattr(item, "phase", None)
            phase_history_payload.append(
                {
                    "phase": getattr(phase, "name", str(phase)) if phase is not None else None,
                    "block": getattr(item, "block", None),
                    "note": getattr(item, "note", None),
                    "entered_at": getattr(item, "entered_at", None),
                }
            )

        current_agent_run_ids: dict[str, str] = {}
        for uid, run in (getattr(self, "current_agent_runs", None) or {}).items():
            agent_run_id = getattr(run, "agent_run_id", None)
            if not agent_run_id:
                continue
            current_agent_run_ids[str(uid)] = str(agent_run_id)

        payload = {
            "version": 1,
            "validator_round_id": target_round_id,
            "season_number": season_number,
            "round_number_in_season": round_number,
            "validator_uid": getattr(self, "uid", None),
            "validator_hotkey": getattr(getattr(getattr(self, "wallet", None), "hotkey", None), "ss58_address", None),
            "status": str(status or "in_progress"),
            "reason": str(reason or "unknown"),
            "timestamp": time.time(),
            "current_block": int(getattr(self, "block", 0) or 0),
            "current_phase": getattr(getattr(round_manager, "current_phase", None), "name", str(getattr(round_manager, "current_phase", None) or "")),
            "phase_history": phase_history_payload,
            "active_miner_uids": sorted(int(uid) for uid in (getattr(self, "active_miner_uids", None) or [])),
            "miners_reused_this_round": sorted(int(uid) for uid in (getattr(self, "miners_reused_this_round", None) or [])),
            "eligibility_status_by_uid": {str(uid): status for uid, status in (getattr(self, "eligibility_status_by_uid", None) or {}).items()},
            "current_agent_runs": current_agent_run_ids,
            "round_log_file": round_log_file,
            "round_log_exists": round_log_exists,
            "round_log_size": round_log_size,
            "last_round_log_upload_url": getattr(self, "_round_log_last_uploaded_url", None),
            "last_round_log_upload_ts": getattr(self, "_round_log_last_upload_ts", 0.0),
            "last_round_log_uploaded_size": getattr(self, "_round_log_last_uploaded_size", -1),
            "extra": extra or {},
        }

        try:
            checkpoint_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            bt.logging.warning(f"IWAP | Could not persist round checkpoint for {target_round_id}")
            return None
        return checkpoint_path

    async def _try_upload_round_log_checkpoint(
        self,
        *,
        reason: str,
        force: bool = False,
        min_interval_seconds: float | None = None,
        phase: str = "Phase 5",
    ) -> str | None:
        """
        Best-effort wrapper around round-log uploads.

        Settlement and forward paths should never crash just because the
        observability snapshot could not be uploaded.
        """
        persist_checkpoint = getattr(self, "_persist_round_checkpoint", None)
        if callable(persist_checkpoint):
            with contextlib.suppress(Exception):
                persist_checkpoint(
                    reason=reason,
                    status="checkpoint_requested",
                    extra={
                        "force": bool(force),
                        "min_interval_seconds": float(min_interval_seconds) if min_interval_seconds is not None else None,
                        "phase": phase,
                    },
                )
        uploader = getattr(self, "_upload_round_log_snapshot", None)
        if not callable(uploader):
            return None
        try:
            url = await uploader(
                reason=reason,
                force=force,
                min_interval_seconds=min_interval_seconds,
            )
            if callable(persist_checkpoint):
                with contextlib.suppress(Exception):
                    persist_checkpoint(
                        reason=reason,
                        status="checkpoint_uploaded",
                        extra={
                            "phase": phase,
                            "round_log_url": url,
                        },
                    )
            return url
        except Exception as exc:
            if callable(persist_checkpoint):
                with contextlib.suppress(Exception):
                    persist_checkpoint(
                        reason=reason,
                        status="checkpoint_upload_failed",
                        extra={
                            "phase": phase,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        },
                    )
            self._log_iwap_phase(
                phase,
                f"round-log checkpoint upload failed ({reason}): {type(exc).__name__}: {exc}",
                level="warning",
                exc_info=False,
            )
            return None

    def _generate_validator_round_id(self, *, current_block: int) -> str:
        """
        Generate a unique validator round ID with season and round information.

        Format: validator_round_{season}_{round_in_season}_{hash}
        Example: validator_round_4_6_abc123def456
        """
        rm = getattr(self, "round_manager", None)
        if rm is None or not getattr(rm, "round_block_length", 0):
            raise RuntimeError("Round manager is not initialized; cannot derive validator round id")

        round_length = int(rm.round_block_length)
        if round_length <= 0:
            raise RuntimeError("round_block_length must be a positive integer")

        reference_block = current_block
        try:
            start_block = getattr(rm, "start_block", None)
            if start_block is not None:
                reference_block = int(start_block)
            else:
                boundaries = rm.get_round_boundaries(current_block, log_debug=False)
                reference_block = int(boundaries.get("round_start_block", current_block) or current_block)
        except Exception:
            reference_block = current_block

        # Calculate season and round within season using the canonical round start block.
        season_number = iwa_main.compute_season_number(reference_block)
        round_number_in_season = iwa_main.compute_round_number_in_season(reference_block, round_length)

        return iwa_main.generate_validator_round_id(season_number=season_number, round_number_in_season=round_number_in_season)

    def _build_iwap_auth_headers(self) -> dict[str, str]:
        hotkey = getattr(self.wallet.hotkey, "ss58_address", None)
        if not hotkey:
            raise RuntimeError("Validator hotkey is unavailable for IWAP authentication")

        message = self._IWAP_VALIDATOR_AUTH_MESSAGE
        if not message:
            self._log_iwap_phase(
                "Auth",
                "Validator auth message not configured; aborting IWAP request signing",
                level="error",
            )
            raise RuntimeError("Validator auth message not configured; cannot sign IWAP requests")

        return build_iwap_auth_headers(self.wallet, message)

    def _build_validator_identity(self) -> iwa_models.ValidatorIdentityIWAP:
        return _utils_build_validator_identity(self)

    def _metagraph_numeric(self, attribute: str, uid: int) -> float | None:
        return _metrics_metagraph_numeric(self.metagraph, attribute, uid)

    def _normalized_stake_tao(self, uid: int) -> float | None:
        return _metrics_normalized_stake_tao(self.metagraph, uid)

    def _validator_vtrust(self, uid: int) -> float | None:
        return _metrics_validator_vtrust(self.metagraph, uid)

    def _build_validator_snapshot(self, validator_round_id: str) -> iwa_models.ValidatorSnapshotIWAP:
        return _utils_build_validator_snapshot(self, validator_round_id)

    def _build_iwap_tasks(
        self,
        *,
        validator_round_id: str,
        tasks: list[TaskWithProject],
    ) -> dict[str, iwa_models.TaskIWAP]:
        return _utils_build_iwap_tasks(validator_round_id=validator_round_id, tasks=tasks)

    async def _iwap_start_round(self, *, current_block: int, n_tasks: int) -> None:
        await _utils_start_round_flow(self, current_block=current_block, n_tasks=n_tasks)

    @staticmethod
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

    async def _upload_round_log_snapshot(
        self,
        *,
        reason: str,
        force: bool = False,
        min_interval_seconds: float | None = None,
    ) -> str | None:
        """
        Best-effort upload of the current round log file to IWAP/S3.
        Safe to call frequently; throttled by interval and no-change checks.
        """
        if getattr(self, "_iwap_offline_mode", False):
            return None

        round_id = getattr(self, "current_round_id", None)
        if not round_id:
            return None

        if self._round_log_last_upload_round_id != round_id:
            self._round_log_last_upload_round_id = round_id
            self._round_log_last_upload_ts = 0.0
            self._round_log_last_uploaded_size = -1
            self._round_log_last_uploaded_url = None

        try:
            interval_cfg = float(getattr(validator_config, "ROUND_LOG_UPLOAD_INTERVAL_SECONDS", 120) or 120)
        except Exception:
            interval_cfg = 120.0
        interval = float(min_interval_seconds) if min_interval_seconds is not None else interval_cfg
        interval = max(0.0, interval)

        now = time.time()
        if not force and self._round_log_last_upload_ts > 0 and (now - self._round_log_last_upload_ts) < interval:
            return self._round_log_last_uploaded_url

        from autoppia_web_agents_subnet.utils.logging import ColoredLogger

        round_log_file = ColoredLogger.get_round_log_file()
        if not round_log_file:
            return self._round_log_last_uploaded_url

        round_log_path = Path(round_log_file)
        if not round_log_path.exists():
            return self._round_log_last_uploaded_url

        try:
            content = round_log_path.read_text(encoding="utf-8", errors="replace")
            content_size = len(content.encode("utf-8"))
        except Exception as exc:
            self._log_iwap_phase(
                "Phase 5",
                f"round-log upload skipped ({reason}): read failed ({type(exc).__name__}: {exc})",
                level="warning",
                exc_info=False,
            )
            return self._round_log_last_uploaded_url

        if not force and content_size == self._round_log_last_uploaded_size:
            return self._round_log_last_uploaded_url

        season_number, round_number_in_season = self._extract_round_numbers_from_round_id(round_id)
        if season_number is None:
            try:
                season_number = int(getattr(getattr(self, "season_manager", None), "season_number", 0) or 0)
            except Exception:
                season_number = 0
        if round_number_in_season is None:
            try:
                round_number_in_season = int(getattr(getattr(self, "round_manager", None), "round_number", 0) or 0)
            except Exception:
                round_number_in_season = 0

        validator_uid = getattr(self, "uid", None)
        validator_hotkey = None
        try:
            validator_hotkey_obj = getattr(getattr(self, "wallet", None), "hotkey", None)
            validator_hotkey = getattr(validator_hotkey_obj, "ss58_address", None)
        except Exception:
            validator_hotkey = None

        upload_variants = ColoredLogger.build_round_log_upload_variants(content)
        url: str | None = None
        upload_exc: Exception | None = None
        for variant_label, variant_content in upload_variants:
            try:
                url = await self.iwap_client.upload_round_log(
                    validator_round_id=round_id,
                    content=variant_content,
                    season_number=season_number if isinstance(season_number, int) else None,
                    round_number_in_season=round_number_in_season if isinstance(round_number_in_season, int) else None,
                    validator_uid=validator_uid if isinstance(validator_uid, int) else None,
                    validator_hotkey=validator_hotkey,
                )
                if variant_label != "full":
                    self._log_iwap_phase(
                        "Phase 5",
                        f"round-log upload succeeded with truncated payload ({variant_label}) for {round_id}",
                        level="warning",
                        exc_info=False,
                    )
                break
            except httpx.HTTPStatusError as exc:
                upload_exc = exc
                status_code = exc.response.status_code if exc.response is not None else None
                has_smaller_variant = variant_label != upload_variants[-1][0]
                if status_code == 413 and has_smaller_variant:
                    self._log_iwap_phase(
                        "Phase 5",
                        f"round-log upload hit 413 ({variant_label}) for {round_id}; retrying with a smaller tail payload",
                        level="warning",
                        exc_info=False,
                    )
                    continue
                break
            except Exception as exc:
                upload_exc = exc
                break

        if upload_exc is not None and not isinstance(url, str):
            persist_checkpoint = getattr(self, "_persist_round_checkpoint", None)
            if callable(persist_checkpoint):
                with contextlib.suppress(Exception):
                    persist_checkpoint(
                        reason=reason,
                        status="round_log_upload_failed",
                        extra={
                            "error_type": type(upload_exc).__name__,
                            "error_message": str(upload_exc),
                        },
                    )
            self._log_iwap_phase(
                "Phase 5",
                f"round-log upload failed ({reason}) for {round_id}: {type(upload_exc).__name__}: {upload_exc}",
                level="warning",
                exc_info=False,
            )
            return self._round_log_last_uploaded_url

        self._round_log_last_upload_ts = now
        self._round_log_last_uploaded_size = content_size
        if isinstance(url, str) and url.strip():
            self._round_log_last_uploaded_url = url.strip()
            persist_checkpoint = getattr(self, "_persist_round_checkpoint", None)
            if callable(persist_checkpoint):
                with contextlib.suppress(Exception):
                    persist_checkpoint(
                        reason=reason,
                        status="round_log_uploaded",
                        extra={
                            "round_log_url": self._round_log_last_uploaded_url,
                            "round_log_size": content_size,
                        },
                    )
            self._log_iwap_phase(
                "Phase 5",
                f"round-log uploaded ({reason}) for {round_id}",
                level="success",
                exc_info=False,
            )
        return self._round_log_last_uploaded_url

    async def _iwap_register_miners(self) -> None:
        """
        Register all participating miners in IWAP dashboard after handshake.

        Creates records for each miner that responded to handshake:
        - validator_round_miners (miner identity and snapshot)
        - miner_evaluation_runs (agent run for this round)
        """
        await _utils_register_participating_miners_in_iwap(self)

    async def _iwap_submit_task_results(
        self,
        *,
        task_item: TaskWithProject,
        task_solutions,
        eval_scores,
        test_results_list,
        evaluation_results,
        execution_times,
        rewards: list[float],
    ) -> None:
        await _utils_submit_task_results(
            self,
            task_item=task_item,
            task_solutions=task_solutions,
            eval_scores=eval_scores,
            test_results_list=test_results_list,
            evaluation_results=evaluation_results,
            execution_times=execution_times,
            rewards=rewards,
        )

    @staticmethod
    def _extract_gif_bytes(payload: object | None) -> bytes | None:
        return _utils_extract_gif_bytes(payload)

    async def _finish_iwap_round(
        self,
        *,
        avg_rewards: dict[int, float],
        final_weights: dict[int, float],
        tasks_completed: int,
    ) -> bool:
        return await _utils_finish_round_flow(
            self,
            avg_rewards=avg_rewards,
            final_weights=final_weights,
            tasks_completed=tasks_completed,
        )

    def _reset_iwap_round_state(self) -> None:
        current_runs = getattr(self, "current_agent_runs", None) or {}
        if current_runs:
            self.prev_round_agent_run_ids = {uid: run.agent_run_id for uid, run in current_runs.items()}
            self.prev_round_run_stats = {}
            for uid, run in current_runs.items():
                acc = getattr(self, "agent_run_accumulators", {}).get(uid, {})
                attempted_tasks = int(acc.get("tasks", 0) or 0)
                expected_total_tasks = int(getattr(run, "total_tasks", 0) or attempted_tasks)
                total_tasks_for_run = max(expected_total_tasks, attempted_tasks)
                reward_sum = float(acc.get("reward", 0.0) or 0.0)
                eval_sum = float(acc.get("eval_score", 0.0) or 0.0)
                time_sum = float(acc.get("execution_time", 0.0) or 0.0)
                avg_score = (eval_sum / total_tasks_for_run) if total_tasks_for_run else (getattr(run, "average_score", None) or 0.0)
                avg_reward = (reward_sum / total_tasks_for_run) if total_tasks_for_run else (getattr(run, "average_reward", None) or 0.0)
                avg_time = (time_sum / attempted_tasks) if attempted_tasks else (getattr(run, "average_execution_time", None) or 0.0)
                round_rewards = getattr(getattr(self, "round_manager", None), "round_rewards", {}) or {}
                miner_rewards = round_rewards.get(uid, []) or []
                success_tasks = len([r for r in miner_rewards if float(r) >= 0.5])
                agent_for_uid = getattr(self, "agents_dict", {}).get(uid)
                self.prev_round_run_stats[uid] = {
                    "agent_run_id": run.agent_run_id,
                    "average_score": avg_score,
                    "average_reward": avg_reward,
                    "average_execution_time": avg_time,
                    "total_tasks": total_tasks_for_run or len(miner_rewards),
                    "tasks_attempted": attempted_tasks,
                    "success_tasks": success_tasks,
                    "failed_tasks": max((total_tasks_for_run or len(miner_rewards)) - success_tasks, 0),
                    "zero_reason": getattr(agent_for_uid, "zero_reason", None) if agent_for_uid else None,
                    "early_stop_reason": getattr(agent_for_uid, "early_stop_reason", None) if agent_for_uid else None,
                    "early_stop_message": getattr(agent_for_uid, "early_stop_message", None) if agent_for_uid else None,
                }
        self.current_round_id = None
        self.current_round_tasks = {}
        self.current_agent_runs = {}
        self.current_miner_snapshots = {}
        self.round_handshake_payloads = {}
        self.eligibility_status_by_uid = {}
        self.round_start_timestamp = 0.0
        self.agent_run_accumulators = {}
        self._completed_pairs = set()
        self._phases = {"p1_done": False, "p2_done": False}
        self._s3_task_log_urls = []
        self._round_log_last_upload_ts = 0.0
        self._round_log_last_uploaded_size = -1
        self._round_log_last_uploaded_url = None
        self._round_log_last_upload_round_id = None
        self._iwap_shadow_mode = False
        try:
            from autoppia_web_agents_subnet.utils.logging import ColoredLogger

            ColoredLogger.clear_round_log_file()
        except Exception:
            pass
        # Reset round number to force recalculation on next round start
        # This prevents reusing stale values when discarding old round state
        self._current_round_number = None

    @staticmethod
    def _derive_early_stop_fields(
        *,
        tasks_attempted: int,
        tasks_received: int,
        zero_reason: Any,
        early_stop_reason: Any,
        early_stop_message: Any,
    ) -> tuple[str | None, str | None]:
        derived_reason = str(early_stop_reason) if isinstance(early_stop_reason, str) and early_stop_reason.strip() else None
        derived_message = str(early_stop_message) if isinstance(early_stop_message, str) and early_stop_message.strip() else None
        if derived_reason or derived_message:
            return derived_reason, derived_message
        if zero_reason == "over_cost_limit" and tasks_attempted > 0 and tasks_received > tasks_attempted:
            return (
                "over_cost_limit",
                (f"Stopped early after {tasks_attempted}/{tasks_received} tasks: too many tasks exceeded the per-task cost limit."),
            )
        return None, None

    @classmethod
    def _round_metrics_payload_from_stats(cls, stats: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(stats, dict):
            return None
        try:
            reward = float(stats.get("average_reward", 0.0) or 0.0)
            score = float(stats.get("average_score", 0.0) or 0.0)
            avg_time = float(stats.get("average_execution_time", 0.0) or 0.0)
            avg_cost = float(stats.get("average_cost", 0.0) or 0.0)
            tasks_received = int(stats.get("total_tasks", 0) or 0)
            tasks_attempted = int(stats.get("tasks_attempted", tasks_received) or 0)
            tasks_success = int(stats.get("success_tasks", 0) or 0)
        except Exception:
            return None
        zero_reason = stats.get("zero_reason")
        early_stop_reason, early_stop_message = cls._derive_early_stop_fields(
            tasks_attempted=tasks_attempted,
            tasks_received=tasks_received,
            zero_reason=zero_reason,
            early_stop_reason=stats.get("early_stop_reason"),
            early_stop_message=stats.get("early_stop_message"),
        )
        payload = {
            "reward": reward,
            "score": score,
            "time": avg_time,
            "cost": avg_cost,
            "tasks_received": tasks_received,
            "tasks_attempted": tasks_attempted,
            "tasks_success": tasks_success,
            "github_url": stats.get("github_url"),
            "normalized_repo": stats.get("normalized_repo"),
            "commit_sha": stats.get("commit_sha"),
            "season": (int(stats["evaluated_season"]) if stats.get("evaluated_season") is not None else None),
            "round": (int(stats["evaluated_round"]) if stats.get("evaluated_round") is not None else None),
            "zero_reason": zero_reason,
            "early_stop_reason": early_stop_reason,
            "early_stop_message": early_stop_message,
        }
        evaluation_context = stats.get("evaluation_context")
        if isinstance(evaluation_context, dict):
            payload["evaluation_context"] = dict(evaluation_context)
        return payload

    def _current_round_numbers(self) -> tuple[int | None, int | None]:
        season_number, round_number_in_season = self._extract_round_numbers_from_round_id(getattr(self, "current_round_id", None))
        if season_number is None:
            try:
                season_number = int(getattr(getattr(self, "season_manager", None), "season_number", 0) or 0)
            except Exception:
                season_number = None
        if round_number_in_season is None:
            try:
                round_number_in_season = int(getattr(getattr(self, "round_manager", None), "round_number", 0) or 0)
            except Exception:
                round_number_in_season = None
        return season_number, round_number_in_season

    def _current_round_run_payload(self, uid: int) -> dict[str, Any] | None:
        run = (getattr(self, "current_agent_runs", None) or {}).get(uid)
        if run is None:
            return None
        acc = (getattr(self, "agent_run_accumulators", None) or {}).get(uid, {})
        round_rewards = getattr(getattr(self, "round_manager", None), "round_rewards", {}) or {}
        miner_rewards = round_rewards.get(uid, []) or []
        attempted_tasks = int(acc.get("tasks", 0) or len(miner_rewards))
        expected_total_tasks = int(getattr(run, "total_tasks", 0) or attempted_tasks)
        total_tasks = max(expected_total_tasks, attempted_tasks)
        success_tasks = int(getattr(run, "completed_tasks", 0) or len([reward for reward in miner_rewards if float(reward) >= 0.5]))
        failed_tasks = int(getattr(run, "failed_tasks", 0) or max(total_tasks - success_tasks, 0))
        if total_tasks > 0:
            avg_reward = float(acc.get("reward", 0.0) or 0.0) / float(total_tasks)
            avg_score = float(acc.get("eval_score", 0.0) or 0.0) / float(total_tasks)
            avg_time = float(acc.get("execution_time", 0.0) or 0.0) / float(attempted_tasks) if attempted_tasks > 0 else 0.0
            avg_cost = float(acc.get("cost", 0.0) or 0.0) / float(attempted_tasks) if attempted_tasks > 0 else 0.0
        else:
            avg_reward = float(getattr(run, "average_reward", 0.0) or 0.0)
            avg_score = float(getattr(run, "average_score", 0.0) or 0.0)
            avg_time = float(getattr(run, "average_execution_time", 0.0) or 0.0)
            run_meta = getattr(run, "metadata", {}) or {}
            avg_cost = float(run_meta.get("average_cost", 0.0) or 0.0) if isinstance(run_meta, dict) else 0.0
        agent_info = (getattr(self, "agents_dict", None) or {}).get(uid)
        season_number, round_number_in_season = self._current_round_numbers()
        zero_reason = getattr(run, "zero_reason", None)
        early_stop_reason, early_stop_message = ValidatorPlatformMixin._derive_early_stop_fields(
            tasks_attempted=attempted_tasks,
            tasks_received=total_tasks,
            zero_reason=zero_reason,
            early_stop_reason=getattr(run, "early_stop_reason", None),
            early_stop_message=getattr(run, "early_stop_message", None),
        )
        return {
            "reward": avg_reward,
            "score": avg_score,
            "time": avg_time,
            "cost": avg_cost,
            "tasks_received": total_tasks,
            "tasks_attempted": attempted_tasks,
            "tasks_success": success_tasks,
            "failed_tasks": failed_tasks,
            "github_url": getattr(agent_info, "github_url", None) if agent_info is not None else None,
            "normalized_repo": getattr(agent_info, "normalized_repo", None) if agent_info is not None else None,
            "commit_sha": getattr(agent_info, "git_commit", None) if agent_info is not None else None,
            "season": season_number,
            "round": round_number_in_season,
            "zero_reason": zero_reason,
            "early_stop_reason": early_stop_reason,
            "early_stop_message": early_stop_message,
            "evaluation_context": self._evaluation_context_payload(),
        }

    def _best_run_payload_for_miner(self, uid: int) -> dict[str, Any] | None:
        best_payload: dict[str, Any] | None = None
        best_key: tuple[float, float, float] | None = None
        commits_by_miner = (getattr(self, "_evaluated_commits_by_miner", None) or {}).get(uid, {})
        if isinstance(commits_by_miner, dict):
            for stats in commits_by_miner.values():
                payload = self._round_metrics_payload_from_stats(stats)
                if payload is None:
                    continue
                key = (
                    float(payload.get("reward", 0.0) or 0.0),
                    float(payload.get("score", 0.0) or 0.0),
                    -float(payload.get("time", 0.0) or 0.0),
                )
                if best_key is None or key > best_key:
                    best_key = key
                    best_payload = payload
        current_payload = self._current_round_run_payload(uid)
        if current_payload is not None:
            current_key = (
                float(current_payload.get("reward", 0.0) or 0.0),
                float(current_payload.get("score", 0.0) or 0.0),
                -float(current_payload.get("time", 0.0) or 0.0),
            )
            if best_key is None or current_key > best_key:
                best_payload = {k: v for k, v in current_payload.items() if k != "failed_tasks" and k != "zero_reason"}
        return best_payload

    def _register_evaluated_commit(
        self,
        uid: int,
        normalized_repo: str,
        commit_sha: str,
        agent_run_id: str,
        stats: dict[str, Any] | None = None,
    ) -> None:
        """Record that we evaluated (repo, commit) for this miner so we don't re-evaluate on resubmit."""
        if not normalized_repo or not commit_sha or not agent_run_id:
            return
        github_url = None
        if isinstance(stats, dict):
            github_url = stats.get("github_url")
        commit_key = f"{normalized_repo.strip()}|{commit_sha.strip()}"
        github_key = str(github_url).strip() if isinstance(github_url, str) and str(github_url).strip() else None
        if not isinstance(getattr(self, "_evaluated_commits_by_miner", None), dict):
            self._evaluated_commits_by_miner = {}
        existing_map = self._evaluated_commits_by_miner.get(uid) or {}
        existing = existing_map.get(github_key) if github_key else None
        if not isinstance(existing, dict):
            existing = existing_map.get(commit_key)
        incoming = {"agent_run_id": agent_run_id, **(stats or {})}
        if not isinstance(incoming.get("evaluation_context"), dict):
            incoming["evaluation_context"] = self._evaluation_context_payload()
        # Keep explicit first/last evaluated round metadata per commit key.
        season_val = incoming.get("evaluated_season")
        round_val = incoming.get("evaluated_round")
        if season_val is not None and "last_evaluated_season" not in incoming:
            incoming["last_evaluated_season"] = season_val
        if round_val is not None and "last_evaluated_round" not in incoming:
            incoming["last_evaluated_round"] = round_val
        if season_val is not None and "first_evaluated_season" not in incoming:
            incoming["first_evaluated_season"] = season_val
        if round_val is not None and "first_evaluated_round" not in incoming:
            incoming["first_evaluated_round"] = round_val

        # Do not downgrade a good reusable source with an empty/incomplete run.
        # Keep first meaningful evaluated run as anchor for reuse.
        if isinstance(existing, dict):
            if not self._is_same_evaluation_context(existing):
                target_map = self._evaluated_commits_by_miner.setdefault(uid, {})
                target_map[commit_key] = incoming
                if github_key:
                    target_map[github_key] = incoming
                return
            # Preserve first evaluation markers forever for this commit.
            if existing.get("first_evaluated_season") is not None:
                incoming["first_evaluated_season"] = existing.get("first_evaluated_season")
            if existing.get("first_evaluated_round") is not None:
                incoming["first_evaluated_round"] = existing.get("first_evaluated_round")
            try:
                existing_total = int(existing.get("total_tasks", 0) or 0)
            except Exception:
                existing_total = 0
            try:
                incoming_total = int(incoming.get("total_tasks", 0) or 0)
            except Exception:
                incoming_total = 0

            if existing_total > 0 and incoming_total <= 0:
                # Never overwrite a good evaluation with a failed one (deploy error, 0 tasks).
                return
            if existing_total > 0 and incoming_total > 0:
                # Keep the first successful evaluation as the canonical reuse anchor.
                return
            if existing_total <= 0 and incoming_total > 0:
                # Upgrade: replace a previously failed evaluation with a good one.
                target_map = self._evaluated_commits_by_miner.setdefault(uid, {})
                target_map[commit_key] = incoming
                if github_key:
                    target_map[github_key] = incoming
                return
            # Both existing and incoming have total_tasks=0: nothing useful to store.
            return

        # No existing entry. Only register evaluations that actually produced tasks;
        # skip failed evaluations (deploy error, short SHA, etc.) so that the same
        # commit is re-evaluated next round instead of being frozen with 0 tasks.
        try:
            incoming_total = int(incoming.get("total_tasks", 0) or 0)
        except Exception:
            incoming_total = 0
        if incoming_total <= 0:
            return

        target_map = self._evaluated_commits_by_miner.setdefault(uid, {})
        target_map[commit_key] = incoming
        if github_key:
            target_map[github_key] = incoming

    # ──────────────────────────────────────────────────────────────────────────
    # Async subtensor provider for consensus (single instance per validator)
    # ──────────────────────────────────────────────────────────────────────────
    async def _get_async_subtensor(self):
        """
        Return a shared AsyncSubtensor instance for this validator.

        - If an async subtensor is already attached (e.g., self.async_subtensor or cached), reuse it.
        - Otherwise, create one using safe constructor (without chain_endpoint), and initialize if needed.
        """
        # Reuse if already present on the instance (external init)
        existing = getattr(self, "async_subtensor", None) or getattr(self, "_async_subtensor", None)
        if existing is not None:
            return existing

        # Lazy-create and cache
        try:
            from bittensor import AsyncSubtensor  # type: ignore
        except Exception as e:
            bt.logging.warning(f"AsyncSubtensor import failed: {e}")
            raise

        network = getattr(getattr(self.config, "subtensor", None), "network", None)

        st = None
        try:
            # Avoid chain_endpoint argument for broad compatibility
            st = AsyncSubtensor(network=network)  # type: ignore[arg-type]
        except Exception:
            st = AsyncSubtensor()  # type: ignore[call-arg]

        # Initialize if supported
        init = getattr(st, "initialize", None)
        if callable(init):
            try:
                await init()
            except Exception as exc:
                bt.logging.warning(f"AsyncSubtensor initialize() failed: {exc}")

        self._async_subtensor = st
        return st

    async def _close_async_subtensor(self):
        """
        Properly close the AsyncSubtensor WebSocket connection to avoid pending tasks.
        This method handles the internal async_substrate_interface websocket cleanup.
        """
        import asyncio

        try:
            async_subtensor = getattr(self, "_async_subtensor", None) or getattr(self, "async_subtensor", None)
            if async_subtensor is None:
                return

            bt.logging.debug("Starting AsyncSubtensor cleanup...")

            # Step 1: Access the substrate interface
            substrate = getattr(async_subtensor, "substrate", None)
            if substrate is not None:
                bt.logging.debug("Found substrate interface")

                # Step 2: Access the websocket connection
                websocket = getattr(substrate, "websocket", None)
                if websocket is not None:
                    bt.logging.debug("Found websocket connection, cancelling background tasks...")

                    # Step 3: Cancel all websocket background tasks
                    task_attrs = ["_sending_task", "_receiving_task", "_start_sending", "_ws_send_task"]
                    for task_attr in task_attrs:
                        task = getattr(websocket, task_attr, None)
                        if task is not None and isinstance(task, asyncio.Task) and not task.done():
                            bt.logging.debug(f"Cancelling {task_attr}...")
                            task.cancel()
                            try:
                                await asyncio.wait_for(task, timeout=1.0)
                            except (TimeoutError, asyncio.CancelledError):
                                bt.logging.debug(f"{task_attr} cancelled/timeout")
                            except Exception as e:
                                bt.logging.debug(f"{task_attr} cancel error: {e}")

                    # Step 4: Close the websocket
                    try:
                        if hasattr(websocket, "close") and callable(websocket.close):
                            await websocket.close()
                            bt.logging.debug("Websocket closed")
                    except Exception as e:
                        bt.logging.debug(f"Websocket close error: {e}")

                # Step 5: Close the substrate interface
                try:
                    if hasattr(substrate, "close") and callable(substrate.close):
                        await substrate.close()
                        bt.logging.debug("Substrate interface closed")
                except Exception as e:
                    bt.logging.debug(f"Substrate close error: {e}")

            # Step 6: Try high-level close methods
            try:
                if hasattr(async_subtensor, "close") and callable(async_subtensor.close):
                    await async_subtensor.close()
                    bt.logging.debug("AsyncSubtensor.close() called")
                elif hasattr(async_subtensor, "disconnect") and callable(async_subtensor.disconnect):
                    await async_subtensor.disconnect()
                    bt.logging.debug("AsyncSubtensor.disconnect() called")
            except Exception as e:
                bt.logging.debug(f"High-level close error: {e}")

            # Step 7: Small delay to allow cleanup
            await asyncio.sleep(0.1)

            bt.logging.debug("AsyncSubtensor cleanup complete")

        except Exception as e:
            bt.logging.debug(f"Error during AsyncSubtensor cleanup: {e}")
        finally:
            # Always clear the reference
            try:
                if hasattr(self, "_async_subtensor"):
                    self._async_subtensor = None
                if hasattr(self, "async_subtensor"):
                    self.async_subtensor = None
            except Exception:
                pass
