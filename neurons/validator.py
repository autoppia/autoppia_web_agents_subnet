from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import time
from pathlib import Path

import bittensor as bt

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - validator can still rely on process env

    def load_dotenv(*_args, **_kwargs):
        return False


def _init_validator_entrypoint_env() -> None:
    """
    Load the validator entrypoint environment from the subnet repo root.

    The validator process belongs to `autoppia_web_agents_subnet`, so its
    authoritative `.env` must be resolved from this repo, not from the sibling
    `autoppia_iwa` package.
    """

    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / ".env", override=True)


_init_validator_entrypoint_env()

from autoppia_iwa.src.bootstrap import AppBootstrap

from autoppia_web_agents_subnet import SUBNET_IWA_VERSION
from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.bittensor_config import config
from autoppia_web_agents_subnet.opensource.sandbox_manager import SandboxManager
from autoppia_web_agents_subnet.platform.validator_mixin import ValidatorPlatformMixin
from autoppia_web_agents_subnet.validator import config as validator_config
from autoppia_web_agents_subnet.validator.config import (
    BURN_UID,
    ROUND_SIZE_EPOCHS,
)
from autoppia_web_agents_subnet.validator.evaluation.mixin import ValidatorEvaluationMixin
from autoppia_web_agents_subnet.validator.models import AgentInfo
from autoppia_web_agents_subnet.validator.round_manager import RoundManager, RoundPhase
from autoppia_web_agents_subnet.validator.round_start.mixin import ValidatorRoundStartMixin
from autoppia_web_agents_subnet.validator.round_start.types import RoundStartResult
from autoppia_web_agents_subnet.validator.season_manager import SeasonManager
from autoppia_web_agents_subnet.validator.settlement.mixin import ValidatorSettlementMixin


class Validator(
    ValidatorRoundStartMixin,
    ValidatorEvaluationMixin,
    ValidatorSettlementMixin,
    ValidatorPlatformMixin,
    BaseValidatorNeuron,
):
    def __init__(self, config=None):
        super().__init__(config=config)

        self.version: str = SUBNET_IWA_VERSION

        self.agents_queue: queue.Queue[AgentInfo] = queue.Queue()
        self.agents_dict: dict[int, AgentInfo] = {}
        self.agents_on_first_handshake: list[int] = []
        self.should_update_weights: bool = False
        self._season_repo_owners: dict[str, set[str]] = {}
        self._season_competition_history: dict[int, dict] = {}

        try:
            self.sandbox_manager = SandboxManager()
            self.sandbox_manager.deploy_gateway()
        except Exception as e:
            import sys

            bt.logging.error(f"Sandbox manager failed to initialize/deploy gateway: {e}")
            sys.exit(1)

        # Season manager for task generation
        self.season_manager = SeasonManager()
        try:
            self.season_manager.TASKS_DIR = self._state_summary_root()
            self.season_manager.TASKS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Round manager for round timing and boundaries
        self.round_manager = RoundManager()

        bt.logging.info("load_state()")
        self.load_state()

    def _state_summary_root(self) -> Path:
        """Root path for validator local season/round artifacts."""
        root = os.getenv("IWAP_BACKUP_DIR")
        if root:
            base = Path(root)
        else:
            try:
                base = Path(self.config.neuron.full_path).parent.parent
            except Exception:
                base = Path(".")
            base = base / "data"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _season_dir_path(self, season_number: int) -> Path:
        season_dir = self._state_summary_root() / f"season_{int(season_number)}"
        season_dir.mkdir(parents=True, exist_ok=True)
        return season_dir

    def _round_dir_path(self, season_number: int, round_number: int) -> Path:
        round_dir = self._season_dir_path(season_number) / f"round_{int(round_number)}"
        round_dir.mkdir(parents=True, exist_ok=True)
        return round_dir

    def _artifact_context_metadata_path(self) -> Path:
        return self._state_summary_root() / "evaluation_context.json"

    def _artifact_context_payload(self) -> dict[str, object]:
        try:
            round_size_epochs = float(getattr(validator_config, "ROUND_SIZE_EPOCHS", ROUND_SIZE_EPOCHS) or ROUND_SIZE_EPOCHS)
        except Exception:
            round_size_epochs = float(ROUND_SIZE_EPOCHS or 0.0)
        try:
            season_size_epochs = float(getattr(validator_config, "SEASON_SIZE_EPOCHS", 0.0) or 0.0)
        except Exception:
            season_size_epochs = 0.0
        try:
            blocks_per_epoch = int(getattr(getattr(self, "round_manager", None), "BLOCKS_PER_EPOCH", None) or getattr(validator_config, "BLOCKS_PER_EPOCH", None) or 360)
        except Exception:
            blocks_per_epoch = 360
        try:
            minimum_start_block = int(getattr(validator_config, "MINIMUM_START_BLOCK", 0) or 0)
        except Exception:
            minimum_start_block = 0
        minimum_validator_version = str(getattr(self, "version", "") or "")
        context_without_hash = {
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

    def _load_saved_artifact_context(self) -> dict[str, object] | None:
        target = self._artifact_context_metadata_path()
        if not target.exists():
            return None
        try:
            with target.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _persist_artifact_context(self) -> None:
        target = self._artifact_context_metadata_path()
        payload = self._artifact_context_payload()
        with target.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

    def _normalize_artifact_context_mapping(self, payload: object) -> dict[str, object] | None:
        if not isinstance(payload, dict):
            return None
        try:
            round_size_epochs = float(payload.get("round_size_epochs"))
            season_size_epochs = float(payload.get("season_size_epochs"))
            blocks_per_epoch = int(payload.get("blocks_per_epoch"))
            minimum_start_block = int(payload.get("minimum_start_block"))
        except Exception:
            return None
        minimum_validator_version = str(payload.get("minimum_validator_version", "") or "").strip()
        context_without_hash = {
            "round_size_epochs": round_size_epochs,
            "season_size_epochs": season_size_epochs,
            "blocks_per_epoch": blocks_per_epoch,
            "minimum_start_block": minimum_start_block,
            "minimum_validator_version": minimum_validator_version,
        }
        context_json = json.dumps(context_without_hash, sort_keys=True, separators=(",", ":"))
        saved_hash = str(payload.get("evaluation_context_hash", "") or "").strip()
        return {
            **context_without_hash,
            "evaluation_context_hash": saved_hash or f"sha256:{hashlib.sha256(context_json.encode('utf-8')).hexdigest()}",
        }

    def _iter_artifact_context_candidates(self, payload: object):
        stack = [payload]
        visited: set[int] = set()
        while stack:
            node = stack.pop()
            node_id = id(node)
            if node_id in visited:
                continue
            visited.add(node_id)

            normalized = self._normalize_artifact_context_mapping(node)
            if normalized is not None:
                yield normalized

            if isinstance(node, dict):
                evaluation_context = node.get("evaluation_context")
                normalized_eval = self._normalize_artifact_context_mapping(evaluation_context)
                if normalized_eval is not None:
                    yield normalized_eval

                for key in (
                    "payload",
                    "payloads",
                    "miners",
                    "best_run",
                    "current_run",
                    "best_run_consensus",
                    "current_run_consensus",
                    "local_evaluation",
                ):
                    child = node.get(key)
                    if child is not None:
                        stack.append(child)
            elif isinstance(node, list):
                stack.extend(node)

    def _infer_saved_artifact_context_from_existing_artifacts(self) -> dict[str, object] | None:
        base = self._state_summary_root()
        if not base.exists():
            return None

        candidate_files: list[Path] = []
        for season_dir in sorted(base.glob("season_*")):
            if not season_dir.is_dir():
                continue
            for round_dir in sorted(season_dir.glob("round_*")):
                if not round_dir.is_dir():
                    continue
                for filename in ("ipfs_uploaded.json", "ipfs_downloaded.json", "post_consensus.json"):
                    candidate = round_dir / filename
                    if candidate.exists() and candidate.is_file():
                        candidate_files.append(candidate)

        for candidate in candidate_files:
            try:
                with candidate.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue
            for normalized in self._iter_artifact_context_candidates(payload):
                bt.logging.warning(
                    f"Recovered missing evaluation_context.json from artifact {candidate.name}; "
                    f"saved_version={normalized.get('minimum_validator_version') or '<missing>'}, "
                    f"saved_start_block={normalized.get('minimum_start_block')}"
                )
                return normalized
        return None

    def _find_stale_artifact_context_against_current(self, current_context: dict[str, object]) -> dict[str, object] | None:
        base = self._state_summary_root()
        if not base.exists():
            return None

        current_hash = str(current_context.get("evaluation_context_hash", "") or "").strip()
        current_version = str(current_context.get("minimum_validator_version", "") or "").strip()
        current_start_block = int(current_context.get("minimum_start_block", 0) or 0)

        candidate_files: list[Path] = []
        for season_dir in sorted(base.glob("season_*")):
            if not season_dir.is_dir():
                continue
            for round_dir in sorted(season_dir.glob("round_*")):
                if not round_dir.is_dir():
                    continue
                for filename in ("ipfs_uploaded.json", "ipfs_downloaded.json", "post_consensus.json"):
                    candidate = round_dir / filename
                    if candidate.exists() and candidate.is_file():
                        candidate_files.append(candidate)

        for candidate in candidate_files:
            try:
                with candidate.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue
            for normalized in self._iter_artifact_context_candidates(payload):
                artifact_hash = str(normalized.get("evaluation_context_hash", "") or "").strip()
                artifact_version = str(normalized.get("minimum_validator_version", "") or "").strip()
                try:
                    artifact_start_block = int(normalized.get("minimum_start_block", 0) or 0)
                except Exception:
                    artifact_start_block = 0

                mismatched = artifact_hash != current_hash if current_hash and artifact_hash else artifact_version != current_version or artifact_start_block != current_start_block
                if not mismatched:
                    continue

                bt.logging.warning(
                    f"Detected stale validator artifact context in {candidate.name}; "
                    f"artifact_version={artifact_version or '<missing>'}, "
                    f"artifact_start_block={artifact_start_block}, "
                    f"current_version={current_version or '<missing>'}, "
                    f"current_start_block={current_start_block}"
                )
                return normalized
        return None

    def _clear_round_artifacts_preserving_tasks(self) -> None:
        base = self._state_summary_root()
        removed_round_dirs = 0
        for season_dir in sorted(base.glob("season_*")):
            if not season_dir.is_dir():
                continue
            for round_dir in sorted(season_dir.glob("round_*")):
                if not round_dir.is_dir():
                    continue
                try:
                    shutil.rmtree(round_dir)
                    removed_round_dirs += 1
                except Exception as exc:
                    bt.logging.warning(f"Could not remove round artifact directory {round_dir}: {exc}")
        self._season_competition_history = {}
        self._evaluated_commits_by_miner = {}
        bt.logging.warning(f"Evaluation context changed; cleared {removed_round_dirs} round artifact directories and reset local competition/reuse state while preserving season tasks.")

    def _clear_all_artifacts_preserving_tasks(self) -> None:
        base = self._state_summary_root()
        removed_entries = 0
        for entry in sorted(base.iterdir()):
            if entry.name == "season_tasks":
                continue
            if entry.is_dir() and entry.name.startswith("season_"):
                for child in sorted(entry.iterdir()):
                    if child.name == "tasks.json" and child.is_file():
                        continue
                    try:
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                        removed_entries += 1
                    except Exception as exc:
                        bt.logging.warning(f"Could not remove validator state entry {child}: {exc}")
                continue
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
                removed_entries += 1
            except Exception as exc:
                bt.logging.warning(f"Could not remove validator state entry {entry}: {exc}")
        self._season_competition_history = {}
        self._evaluated_commits_by_miner = {}
        bt.logging.warning(f"Validator version bump detected without major change; cleared {removed_entries} validator state entries while preserving season tasks.")

    def _clear_all_artifacts_including_tasks(self) -> None:
        base = self._state_summary_root()
        removed_entries = 0
        for entry in sorted(base.iterdir()):
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
                removed_entries += 1
            except Exception as exc:
                bt.logging.warning(f"Could not remove validator state entry {entry}: {exc}")
        self._season_competition_history = {}
        self._evaluated_commits_by_miner = {}
        bt.logging.warning(f"Major validator version change detected; cleared {removed_entries} validator state entries, including season tasks and root metadata.")

    @staticmethod
    def _version_major(version: object) -> int | None:
        try:
            text = str(version or "").strip()
            if not text:
                return None
            head = text.split(".", 1)[0]
            return int(head)
        except Exception:
            return None

    @staticmethod
    def _version_tuple(version: object) -> tuple[int, ...] | None:
        try:
            text = str(version or "").strip()
            if not text:
                return None
            parts = []
            for piece in text.split("."):
                digits = "".join(ch for ch in piece if ch.isdigit())
                if not digits:
                    break
                parts.append(int(digits))
            return tuple(parts) if parts else None
        except Exception:
            return None

    def _invalidate_round_artifacts_if_context_changed(self) -> None:
        current_context = self._artifact_context_payload()
        saved_context = self._load_saved_artifact_context()
        stale_artifact_context = self._find_stale_artifact_context_against_current(current_context)
        if isinstance(stale_artifact_context, dict):
            saved_context = stale_artifact_context
        if not isinstance(saved_context, dict):
            saved_context = self._infer_saved_artifact_context_from_existing_artifacts()
            if not isinstance(saved_context, dict):
                self._persist_artifact_context()
                return
        saved_hash = str(saved_context.get("evaluation_context_hash", "") or "")
        current_hash = str(current_context.get("evaluation_context_hash", "") or "")
        if saved_hash and current_hash and saved_hash != current_hash:
            saved_version = str(saved_context.get("minimum_validator_version", "") or "").strip()
            current_version = str(current_context.get("minimum_validator_version", "") or "").strip()
            saved_version_tuple = self._version_tuple(saved_version)
            current_version_tuple = self._version_tuple(current_version)
            saved_major = self._version_major(saved_context.get("minimum_validator_version"))
            current_major = self._version_major(current_context.get("minimum_validator_version"))
            bt.logging.warning(f"Detected validator evaluation-context change (saved={saved_hash}, current={current_hash}).")
            version_bumped = False
            if saved_version_tuple is not None and current_version_tuple is not None:
                version_bumped = current_version_tuple > saved_version_tuple
            elif saved_version and current_version and saved_version != current_version:
                # If we cannot compare semantically, fail safe and invalidate all local artifacts.
                version_bumped = True

            if version_bumped:
                if saved_major is not None and current_major is not None and saved_major != current_major:
                    bt.logging.warning(f"Major validator version bump detected (saved={saved_version or '<missing>'}, current={current_version or '<missing>'}); clearing all local artifacts.")
                    self._clear_all_artifacts_including_tasks()
                else:
                    bt.logging.warning(
                        f"Validator version bump detected (saved={saved_version or '<missing>'}, current={current_version or '<missing>'}); clearing local artifacts but preserving season tasks."
                    )
                    self._clear_all_artifacts_preserving_tasks()
            elif saved_major is not None and current_major is not None and saved_major != current_major:
                self._clear_all_artifacts_including_tasks()
            else:
                self._clear_round_artifacts_preserving_tasks()
        self._persist_artifact_context()

    def _save_competition_state(self) -> None:
        """Persist canonical post-consensus artifacts under season/round folders."""
        state = getattr(self, "_season_competition_history", None)
        if not isinstance(state, dict):
            return
        for season, season_data in state.items():
            try:
                season_i = int(season)
            except Exception:
                continue
            if not isinstance(season_data, dict):
                continue
            rounds_in = season_data.get("rounds", {})
            if isinstance(rounds_in, dict):
                for round_key, round_data in rounds_in.items():
                    try:
                        round_i = int(round_key)
                    except Exception:
                        continue
                    if not isinstance(round_data, dict):
                        continue
                    post_consensus_json_in = round_data.get("post_consensus_json")
                    if isinstance(post_consensus_json_in, dict):
                        round_dir = self._round_dir_path(season_i, round_i)
                        target = round_dir / "post_consensus.json"
                        with target.open("w", encoding="utf-8") as f:
                            json.dump(post_consensus_json_in, f, indent=2, sort_keys=True)

    @staticmethod
    def _winner_snapshot_from_post_consensus(post_consensus_json: dict) -> dict | None:
        miners = post_consensus_json.get("miners")
        if not isinstance(miners, list):
            return None
        winner: dict | None = None
        winner_reward = float("-inf")
        for miner_entry in miners:
            if not isinstance(miner_entry, dict):
                continue
            try:
                uid_i = int(miner_entry.get("uid"))
            except Exception:
                continue
            if uid_i == int(BURN_UID):
                continue
            best_run = miner_entry.get("best_run_consensus")
            if not isinstance(best_run, dict):
                continue
            try:
                reward_f = float(best_run.get("reward", 0.0) or 0.0)
            except Exception:
                reward_f = 0.0
            if reward_f < winner_reward:
                continue
            winner_reward = reward_f
            winner = {
                "uid": uid_i,
                "reward": reward_f,
                "score": float(best_run.get("score", 0.0) or 0.0),
                "time": float(best_run.get("time", 0.0) or 0.0),
                "cost": float(best_run.get("cost", 0.0) or 0.0),
            }
        return winner

    @classmethod
    def _resolve_loaded_round_leadership(
        cls,
        *,
        previous_leader: dict | None,
        post_consensus_json: dict,
        required_improvement_pct: float,
    ) -> tuple[dict | None, dict | None, dict | None, bool]:
        winner = cls._winner_snapshot_from_post_consensus(post_consensus_json)
        if not isinstance(previous_leader, dict):
            return None, winner, winner, False

        leader_before = dict(previous_leader)
        miners = post_consensus_json.get("miners")
        candidate: dict | None = None
        if isinstance(miners, list):
            ranked: list[tuple[float, float, float, int, dict]] = []
            for miner_entry in miners:
                if not isinstance(miner_entry, dict):
                    continue
                try:
                    uid_i = int(miner_entry.get("uid"))
                except Exception:
                    continue
                if uid_i == int(leader_before.get("uid")):
                    continue
                best_run = miner_entry.get("best_run_consensus")
                if not isinstance(best_run, dict):
                    continue
                try:
                    reward_f = float(best_run.get("reward", 0.0) or 0.0)
                    score_f = float(best_run.get("score", 0.0) or 0.0)
                    time_f = float(best_run.get("time", 0.0) or 0.0)
                except Exception:
                    continue
                if reward_f <= 0.0:
                    continue
                ranked.append(
                    (
                        reward_f,
                        score_f,
                        -time_f,
                        -uid_i,
                        {
                            "uid": uid_i,
                            "reward": reward_f,
                            "score": score_f,
                            "time": time_f,
                            "cost": float(best_run.get("cost", 0.0) or 0.0),
                        },
                    )
                )
            if ranked:
                ranked.sort(reverse=True)
                candidate = dict(ranked[0][4])

        try:
            leader_before_reward = float(leader_before.get("reward", 0.0) or 0.0)
        except Exception:
            leader_before_reward = 0.0

        if not isinstance(candidate, dict):
            return leader_before, None, leader_before, False

        try:
            candidate_reward = float(candidate.get("reward", 0.0) or 0.0)
        except Exception:
            candidate_reward = 0.0

        threshold = leader_before_reward * (1.0 + float(required_improvement_pct))
        dethroned = bool(candidate_reward > threshold)
        leader_after = dict(candidate if dethroned else leader_before)
        return leader_before, candidate, leader_after, dethroned

    @classmethod
    def _coerce_loaded_leader_after_snapshot(cls, post_consensus_json: dict) -> dict | None:
        """
        Repair impossible persisted leader snapshots before they are rehydrated.

        This protects restarts from stale local `post_consensus.json` files where
        `leader_after_round` disagrees with the actual winner of the round.
        """
        summary = post_consensus_json.get("summary")
        if not isinstance(summary, dict):
            return cls._winner_snapshot_from_post_consensus(post_consensus_json)

        winner = cls._winner_snapshot_from_post_consensus(post_consensus_json)
        leader_after = summary.get("leader_after_round")
        leader_before = summary.get("leader_before_round")
        candidate = summary.get("candidate_this_round")

        if not isinstance(leader_after, dict):
            return winner

        if not isinstance(leader_before, dict):
            return winner or leader_after

        try:
            required_improvement_pct = float(summary.get("percentage_to_dethrone", 0.0) or 0.0)
        except Exception:
            required_improvement_pct = 0.0

        if not isinstance(candidate, dict):
            return leader_after

        try:
            candidate_uid = int(candidate.get("uid")) if candidate.get("uid") is not None else None
        except Exception:
            candidate_uid = None
        try:
            leader_before_uid = int(leader_before.get("uid")) if leader_before.get("uid") is not None else None
        except Exception:
            leader_before_uid = None
        try:
            candidate_reward = float(candidate.get("reward", 0.0) or 0.0)
        except Exception:
            candidate_reward = 0.0
        try:
            leader_before_reward = float(leader_before.get("reward", 0.0) or 0.0)
        except Exception:
            leader_before_reward = 0.0

        threshold = leader_before_reward * (1.0 + required_improvement_pct)
        candidate_should_dethrone = candidate_uid is not None and candidate_uid != leader_before_uid and candidate_reward > threshold
        if candidate_should_dethrone:
            return winner or candidate
        return leader_after

    def _load_competition_state(self) -> None:
        """Rebuild season competition history from saved round post_consensus artifacts."""
        loaded: dict[int, dict] = {}
        base = self._state_summary_root()
        for season_dir in sorted(base.glob("season_*")):
            if not season_dir.is_dir():
                continue
            try:
                season_i = int(str(season_dir.name).split("_", 1)[1])
            except Exception:
                continue
            rounds_loaded: dict[int, dict] = {}
            summary_loaded: dict = {
                "current_winner_uid": None,
                "current_winner_reward": 0.0,
                "required_improvement_pct": 0.0,
                "best_by_miner": {},
                "best_round_by_miner": {},
                "best_snapshot_by_miner": {},
                "last_eligible_uids": [],
            }
            for round_dir in sorted(season_dir.glob("round_*")):
                if not round_dir.is_dir():
                    continue
                try:
                    round_i = int(str(round_dir.name).split("_", 1)[1])
                except Exception:
                    continue
                post_consensus_path = round_dir / "post_consensus.json"
                if not post_consensus_path.exists():
                    continue
                try:
                    with post_consensus_path.open("r", encoding="utf-8") as f:
                        post_consensus_json = json.load(f)
                except Exception:
                    continue
                if not isinstance(post_consensus_json, dict):
                    continue

                rounds_loaded[round_i] = {"post_consensus_json": dict(post_consensus_json)}

                miners = post_consensus_json.get("miners", [])
                if isinstance(miners, list):
                    eligible_uids: list[int] = []
                    for miner_entry in miners:
                        if not isinstance(miner_entry, dict):
                            continue
                        try:
                            uid_i = int(miner_entry.get("uid"))
                        except Exception:
                            continue
                        if uid_i != int(BURN_UID):
                            eligible_uids.append(uid_i)
                        best_run = miner_entry.get("best_run_consensus")
                        if not isinstance(best_run, dict):
                            continue
                        try:
                            reward_f = float(best_run.get("reward", 0.0) or 0.0)
                        except Exception:
                            reward_f = 0.0
                        current_best = float(summary_loaded["best_by_miner"].get(uid_i, float("-inf")) or float("-inf"))
                        if reward_f >= current_best:
                            summary_loaded["best_by_miner"][uid_i] = reward_f
                            summary_loaded["best_round_by_miner"][uid_i] = round_i
                            summary_loaded["best_snapshot_by_miner"][uid_i] = {
                                "uid": uid_i,
                                "reward": reward_f,
                                "score": float(best_run.get("score", 0.0) or 0.0),
                                "time": float(best_run.get("time", 0.0) or 0.0),
                                "cost": float(best_run.get("cost", 0.0) or 0.0),
                            }
                    summary_loaded["last_eligible_uids"] = sorted(set(eligible_uids))

                summary = post_consensus_json.get("summary")
                if isinstance(summary, dict):
                    try:
                        required_improvement_pct = float(summary.get("percentage_to_dethrone", 0.0) or 0.0)
                    except Exception:
                        required_improvement_pct = 0.0
                    summary_loaded["required_improvement_pct"] = required_improvement_pct

                    previous_leader = summary_loaded.get("current_winner_snapshot")
                    if not isinstance(previous_leader, dict):
                        previous_leader = None

                    (
                        leader_before,
                        candidate,
                        leader_after,
                        dethroned,
                    ) = self._resolve_loaded_round_leadership(
                        previous_leader=previous_leader,
                        post_consensus_json=post_consensus_json,
                        required_improvement_pct=required_improvement_pct,
                    )

                    repaired_summary = dict(summary)
                    repaired_summary["leader_before_round"] = leader_before
                    repaired_summary["candidate_this_round"] = candidate
                    repaired_summary["leader_after_round"] = leader_after
                    repaired_summary["dethroned"] = dethroned
                    post_consensus_json["summary"] = repaired_summary
                    rounds_loaded[round_i]["post_consensus_json"] = dict(post_consensus_json)

                    if isinstance(leader_after, dict):
                        try:
                            summary_loaded["current_winner_uid"] = int(leader_after.get("uid")) if leader_after.get("uid") is not None else None
                        except Exception:
                            summary_loaded["current_winner_uid"] = None
                        try:
                            summary_loaded["current_winner_reward"] = float(leader_after.get("reward", 0.0) or 0.0)
                        except Exception:
                            summary_loaded["current_winner_reward"] = 0.0
                        summary_loaded["current_winner_snapshot"] = {k: v for k, v in dict(leader_after).items() if k != "weight"}

            loaded[season_i] = {
                "rounds": rounds_loaded,
                "summary": summary_loaded,
            }

        self._season_competition_history = loaded

    def _load_evaluated_commit_history(self) -> None:
        """Rebuild evaluated commit index from saved IPFS upload artifacts."""
        rebuilt: dict[int, dict[str, dict]] = {}
        base = self._state_summary_root()
        for season_dir in sorted(base.glob("season_*")):
            if not season_dir.is_dir():
                continue
            for round_dir in sorted(season_dir.glob("round_*")):
                if not round_dir.is_dir():
                    continue
                ipfs_uploaded_path = round_dir / "ipfs_uploaded.json"
                if not ipfs_uploaded_path.exists():
                    continue
                try:
                    with ipfs_uploaded_path.open("r", encoding="utf-8") as f:
                        ipfs_uploaded = json.load(f)
                except Exception:
                    continue
                if not isinstance(ipfs_uploaded, dict):
                    continue
                payload = ipfs_uploaded.get("payload")
                if not isinstance(payload, dict):
                    continue
                miners = payload.get("miners")
                if not isinstance(miners, list):
                    continue
                for miner_entry in miners:
                    if not isinstance(miner_entry, dict):
                        continue
                    try:
                        uid_i = int(miner_entry.get("uid"))
                    except Exception:
                        continue
                    for run_key in ("best_run", "current_run"):
                        run_payload = miner_entry.get(run_key)
                        if not isinstance(run_payload, dict):
                            continue
                        github_url = run_payload.get("github_url")
                        normalized_repo = run_payload.get("normalized_repo")
                        commit_sha = run_payload.get("commit_sha")
                        if not isinstance(github_url, str) or not github_url.strip():
                            continue
                        if not isinstance(normalized_repo, str) or not normalized_repo.strip():
                            continue
                        if not isinstance(commit_sha, str) or not commit_sha.strip():
                            continue
                        try:
                            tasks_received = int(run_payload.get("tasks_received", 0) or 0)
                        except Exception:
                            tasks_received = 0
                        if tasks_received <= 0:
                            continue
                        stats = {
                            "agent_run_id": f"artifact:{season_dir.name}:{round_dir.name}:{uid_i}:{run_key}",
                            "average_reward": float(run_payload.get("reward", 0.0) or 0.0),
                            "average_score": float(run_payload.get("score", 0.0) or 0.0),
                            "average_execution_time": float(run_payload.get("time", 0.0) or 0.0),
                            "average_cost": float(run_payload.get("cost", 0.0) or 0.0),
                            "total_tasks": tasks_received,
                            "success_tasks": int(run_payload.get("tasks_success", 0) or 0),
                            "failed_tasks": max(tasks_received - int(run_payload.get("tasks_success", 0) or 0), 0),
                            "zero_reason": run_payload.get("zero_reason"),
                            "github_url": github_url,
                            "normalized_repo": normalized_repo,
                            "commit_sha": commit_sha,
                            "evaluated_season": run_payload.get("season"),
                            "evaluated_round": run_payload.get("round"),
                            "last_evaluated_season": run_payload.get("season"),
                            "last_evaluated_round": run_payload.get("round"),
                            "first_evaluated_season": run_payload.get("season"),
                            "first_evaluated_round": run_payload.get("round"),
                        }
                        evaluation_context = run_payload.get("evaluation_context")
                        if isinstance(evaluation_context, dict):
                            stats["evaluation_context"] = dict(evaluation_context)
                        target_map = rebuilt.setdefault(uid_i, {})
                        commit_key = f"{normalized_repo.strip()}|{commit_sha.strip()}"
                        target_map[commit_key] = stats
                        target_map[github_url.strip()] = stats
        self._evaluated_commits_by_miner = rebuilt

    def save_state(self):
        """Save base validator state + season/round artifacts."""
        super().save_state()
        try:
            self._save_competition_state()
        except Exception as exc:
            bt.logging.warning(f"Failed to save competition state: {exc}")
        try:
            self._persist_artifact_context()
        except Exception as exc:
            bt.logging.warning(f"Failed to persist evaluation context metadata: {exc}")

    def load_state(self):
        """Load base validator state + season/round artifacts."""
        try:
            super().load_state()
        except Exception as exc:
            bt.logging.warning(f"Could not load base state.npz (starting fresh): {exc}")
        try:
            self._invalidate_round_artifacts_if_context_changed()
        except Exception as exc:
            bt.logging.warning(f"Could not validate/reset round artifacts for changed evaluation context: {exc}")
        try:
            self._load_competition_state()
        except Exception as exc:
            bt.logging.warning(f"Could not load season/round artifacts (starting fresh): {exc}")
        try:
            self._load_evaluated_commit_history()
        except Exception as exc:
            bt.logging.warning(f"Could not rebuild evaluated commit history from round artifacts: {exc}")

    async def forward(self) -> None:
        """
        Forward pass for the validator.
        """
        if await self._wait_for_minimum_start_block():
            return
        try:
            round_size_epochs = float(getattr(self.round_manager, "round_size_epochs", ROUND_SIZE_EPOCHS) or ROUND_SIZE_EPOCHS)
            bt.logging.info(f"🚀 Starting round-based forward (epochs per round: {round_size_epochs:.1f})")
            start_result: RoundStartResult = await self._start_round()

            if not start_result.continue_forward:
                bt.logging.info(f"Round start skipped ({start_result.reason}); waiting for next boundary")
                await self._wait_until_specific_block(
                    target_block=self.round_manager.target_block,
                    target_description="round boundary block",
                )
                return

            # 1) Handshake & agent discovery
            await self._perform_handshake()

            # Late-start guard: if handshake consumed too much time and the round is
            # already at/near end, skip participation entirely for this round.
            try:
                current_block_after_handshake = self.block
                target_block = int(getattr(self.round_manager, "target_block", 0) or 0)
                remaining_blocks = max(target_block - current_block_after_handshake, 0)
                min_blocks_to_participate = int(
                    getattr(
                        self.round_manager,
                        "SKIP_ROUND_MIN_BLOCKS_AFTER_HANDSHAKE",
                        10,
                    )
                    or 10
                )
                if target_block > 0 and remaining_blocks < min_blocks_to_participate:
                    bt.logging.warning(
                        "Skipping round participation after handshake: "
                        f"remaining_blocks={remaining_blocks} < min_required={min_blocks_to_participate} "
                        f"(current_block={current_block_after_handshake}, target_block={target_block})"
                    )
                    self.round_manager.enter_phase(
                        RoundPhase.COMPLETE,
                        block=current_block_after_handshake,
                        note="Round skipped (late start after handshake)",
                        force=True,
                    )
                    await self._wait_until_specific_block(
                        target_block=target_block,
                        target_description="round boundary block",
                    )
                    return
            except Exception as exc:
                bt.logging.warning(f"Late-start guard check failed (continuing): {exc}")

            # Initialize IWAP round after handshake (we now know how many miners participate)
            current_block = self.block
            season_tasks = await self.round_manager.get_round_tasks(current_block, self.season_manager)
            n_tasks = len(season_tasks)

            # Build IWAP tasks before starting round
            if season_tasks and self.current_round_id:
                self.current_round_tasks = self._build_iwap_tasks(validator_round_id=self.current_round_id, tasks=season_tasks)

            await self._iwap_start_round(current_block=current_block, n_tasks=n_tasks)
            await self._try_upload_round_log_checkpoint(
                reason="forward_round_started",
                force=True,
                min_interval_seconds=0.0,
                phase="Validator",
            )

            # Register miners in IWAP (creates validator_round_miners records)
            await self._iwap_register_miners()
            await self._try_upload_round_log_checkpoint(
                reason="forward_miners_registered",
                force=False,
                min_interval_seconds=0.0,
                phase="Validator",
            )

            # 2) Evaluation phase
            agents_evaluated = await self._run_evaluation_phase()

            # 3) Settlement / weight update
            await self._run_settlement_phase(agents_evaluated=agents_evaluated)
        except Exception as exc:
            await self._try_upload_round_log_checkpoint(
                reason=f"forward_exception:{type(exc).__name__}",
                force=True,
                min_interval_seconds=0.0,
                phase="Validator",
            )
            raise


if __name__ == "__main__":
    # Initialize IWA with default logging (best-effort)
    AppBootstrap()

    with Validator(config=config(role="validator")) as validator:
        heartbeat_seconds = 120
        sync_interval_seconds = max(60, int(os.getenv("HEARTBEAT_SYNC_INTERVAL_SECONDS", "1800")))
        last_sync_ts = time.monotonic()
        while True:
            bt.logging.debug(f"Heartbeat — validator running... {time.time()}")
            now = time.monotonic()
            if now - last_sync_ts >= sync_interval_seconds:
                try:
                    bt.logging.info(f"Heartbeat sync triggered (interval={sync_interval_seconds}s)")
                    validator.sync()
                    bt.logging.info("Heartbeat sync completed")
                except Exception as exc:
                    bt.logging.error(f"Heartbeat sync failed: {exc}")
                finally:
                    last_sync_ts = time.monotonic()
            time.sleep(heartbeat_seconds)
