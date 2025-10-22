from __future__ import annotations

import os
import pickle
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import bittensor as bt


@dataclass
class RoundCheckpoint:
    """
    Pickle-friendly snapshot of a validator round mid-flight.

    Stores objects directly so we can resume without re-hydration logic,
    keeping IDs stable across crashes.
    """

    schema_version: int = 1

    # Core identifiers and timing
    validator_round_id: Optional[str] = None
    round_number: Optional[int] = None
    round_start_timestamp: float = 0.0

    # Tasks
    all_tasks: List[Any] = field(default_factory=list)  # List[TaskWithProject]
    current_round_tasks: Dict[str, Any] = field(default_factory=dict)  # task_id -> TaskIWAP

    # Participants and metadata
    active_miner_uids: List[int] = field(default_factory=list)
    miner_hotkeys: Dict[int, Optional[str]] = field(default_factory=dict)
    round_handshake_payloads: Dict[int, Dict[str, Any]] = field(default_factory=dict)  # minimal dicts

    # Agent runs and accumulators
    current_agent_runs: Dict[int, Any] = field(default_factory=dict)  # uid -> AgentRunIWAP
    current_miner_snapshots: Dict[int, Any] = field(default_factory=dict)
    agent_run_accumulators: Dict[int, Dict[str, float]] = field(default_factory=dict)

    # Progress bookkeeping
    completed_pairs: Set[Tuple[int, str]] = field(default_factory=set)
    eval_records: List[Dict[str, Any]] = field(default_factory=list)
    phases: Dict[str, Any] = field(default_factory=lambda: {"p1_done": False, "p2_done": False})

    # Round manager aggregates
    rm_start_block: Optional[int] = None
    rm_round_rewards: Dict[int, List[float]] = field(default_factory=dict)
    rm_round_eval_scores: Dict[int, List[float]] = field(default_factory=dict)
    rm_round_times: Dict[int, List[float]] = field(default_factory=dict)

    # Consensus flags
    consensus_published: bool = False


class RoundStateManager:
    """
    Minimal pickle-based checkpoint manager. Thread-safe writes, atomic replace.
    """

    def __init__(self, validator: Any) -> None:
        self._validator = validator
        self._lock = threading.Lock()

    # ──────────────────────────────────────────────────────────────────────
    # Path resolution
    # ──────────────────────────────────────────────────────────────────────
    def _checkpoint_path(self) -> Path:
        """
        Resolve a stable path for checkpoints under /data by default.

        Priority:
        1) Env IWA_STATE_DIR or VALIDATOR_STATE_DIR (/<base>/state)
        2) /data/state (created if needed)
        """
        env_base = os.getenv("IWA_STATE_DIR") or os.getenv("VALIDATOR_STATE_DIR")
        if env_base:
            base = Path(env_base).expanduser().resolve()
            if base.name != "state":
                base = base / "state"
        else:
            base = Path("/data/state")

        # Determine netuid and hotkey
        try:
            netuid = getattr(self._validator.metagraph, "netuid", None)
        except Exception:
            netuid = None
        try:
            hotkey = getattr(getattr(self._validator.wallet, "hotkey", None), "ss58_address", None)
        except Exception:
            hotkey = None
        netuid_part = f"netuid_{netuid}" if netuid is not None else "netuid_unknown"
        hotkey_part = hotkey or "hotkey_unknown"
        return Path(base) / netuid_part / f"{hotkey_part}.pkl"

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────
    def save_checkpoint(self, *, tasks: Optional[List[Any]] = None) -> None:
        """
        Capture current validator in-memory state and persist to disk atomically.
        """
        with self._lock:
            # Keep tasks cached on the validator for subsequent saves without tasks new param
            if tasks is not None:
                try:
                    self._validator._all_tasks_cache = list(tasks)
                except Exception:
                    self._validator._all_tasks_cache = tasks
            ckpt = self._build_checkpoint(tasks=tasks)
            path = self._checkpoint_path()
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            tmp = path.with_suffix(path.suffix + ".tmp")
            data = pickle.dumps(ckpt, protocol=pickle.HIGHEST_PROTOCOL)
            with tmp.open("wb") as fh:
                fh.write(data)
                try:
                    fh.flush()
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            tmp.replace(path)
            bt.logging.info(
                f"💾 Checkpoint saved at {path} (tasks={len(ckpt.all_tasks)} uids={len(ckpt.active_miner_uids)} bytes={len(data)})"
            )

    def load_checkpoint(self) -> Optional[RoundCheckpoint]:
        """
        Load and apply a prior checkpoint if present. Returns the checkpoint or None.
        """
        path = self._checkpoint_path()
        candidates = [path, path.with_suffix(path.suffix + ".tmp")]
        blob: Optional[bytes] = None
        chosen: Optional[Path] = None
        for p in candidates:
            try:
                if p.exists() and p.is_file():
                    blob = p.read_bytes()
                    chosen = p
                    break
            except Exception:
                continue
        if blob is None:
            return None
        try:
            ckpt: RoundCheckpoint = pickle.loads(blob)
        except Exception as exc:
            bt.logging.warning(f"Checkpoint load failed at {chosen}: {exc}")
            return None

        self._apply_checkpoint(ckpt)
        bt.logging.info(
            f"♻️ Checkpoint loaded from {chosen} (tasks={len(ckpt.all_tasks)} runs={len(ckpt.current_agent_runs)} completed={len(ckpt.completed_pairs)})"
        )
        return ckpt

    def cleanup(self) -> None:
        """Remove checkpoint files (final + temp)."""
        with self._lock:
            path = self._checkpoint_path()
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────
    def _build_checkpoint(self, *, tasks: Optional[List[Any]] = None) -> RoundCheckpoint:
        v = self._validator
        # Build minimal handshake dicts to ensure picklability
        handshake_dict: Dict[int, Dict[str, Any]] = {}
        for uid, payload in (getattr(v, "round_handshake_payloads", {}) or {}).items():
            handshake_dict[int(uid)] = {
                "agent_name": getattr(payload, "agent_name", None),
                "agent_image": getattr(payload, "agent_image", None),
                "github_url": getattr(payload, "github_url", None),
                "agent_version": getattr(payload, "agent_version", None),
                "note": getattr(payload, "note", None),
            }

        # Miner hotkeys at time of save (stabilize identity)
        miner_hotkeys: Dict[int, Optional[str]] = {}
        try:
            uids = list(getattr(v, "active_miner_uids", []) or [])
            for uid in uids:
                try:
                    miner_hotkeys[int(uid)] = v.metagraph.hotkeys[uid]
                except Exception:
                    miner_hotkeys[int(uid)] = None
        except Exception:
            pass

        rm = getattr(v, "round_manager", None)
        ckpt = RoundCheckpoint(
            validator_round_id=getattr(v, "current_round_id", None),
            round_number=None,  # Not strictly needed; can be recomputed
            round_start_timestamp=float(getattr(v, "round_start_timestamp", 0.0) or 0.0),
            all_tasks=list(tasks if tasks is not None else getattr(v, "_all_tasks_cache", []) or []),
            current_round_tasks=dict(getattr(v, "current_round_tasks", {}) or {}),
            active_miner_uids=list(getattr(v, "active_miner_uids", []) or []),
            miner_hotkeys=miner_hotkeys,
            round_handshake_payloads=handshake_dict,
            current_agent_runs=dict(getattr(v, "current_agent_runs", {}) or {}),
            current_miner_snapshots=dict(getattr(v, "current_miner_snapshots", {}) or {}),
            agent_run_accumulators=dict(getattr(v, "agent_run_accumulators", {}) or {}),
            completed_pairs=set(getattr(v, "_completed_pairs", set()) or set()),
            eval_records=list(getattr(v, "_eval_records", []) or []),
            phases=dict(getattr(v, "_phases", {"p1_done": False, "p2_done": False}) or {}),
            rm_start_block=getattr(rm, "start_block", None) if rm is not None else None,
            rm_round_rewards=dict(getattr(rm, "round_rewards", {}) or {}) if rm is not None else {},
            rm_round_eval_scores=dict(getattr(rm, "round_eval_scores", {}) or {}) if rm is not None else {},
            rm_round_times=dict(getattr(rm, "round_times", {}) or {}) if rm is not None else {},
            consensus_published=bool(getattr(v, "_consensus_published", False)),
        )
        return ckpt

    def _apply_checkpoint(self, ckpt: RoundCheckpoint) -> None:
        v = self._validator
        # Core IDs
        v.current_round_id = ckpt.validator_round_id
        v.round_start_timestamp = float(ckpt.round_start_timestamp or 0.0)

        # Tasks
        v._all_tasks_cache = list(ckpt.all_tasks or [])  # internal helper cache
        v.current_round_tasks = dict(ckpt.current_round_tasks or {})

        # Participants/metadata
        v.active_miner_uids = list(ckpt.active_miner_uids or [])
        v.round_handshake_payloads = {}
        for uid, payload in (ckpt.round_handshake_payloads or {}).items():
            # Convert dicts back to SimpleNamespace-like objects
            try:
                from types import SimpleNamespace

                v.round_handshake_payloads[int(uid)] = SimpleNamespace(**(payload or {}))
            except Exception:
                v.round_handshake_payloads[int(uid)] = payload

        # Agent runs and accumulators
        v.current_agent_runs = dict(ckpt.current_agent_runs or {})
        v.current_miner_snapshots = dict(ckpt.current_miner_snapshots or {})
        v.agent_run_accumulators = dict(ckpt.agent_run_accumulators or {})

        # Progress
        v._completed_pairs = set(ckpt.completed_pairs or set())
        v._eval_records = list(ckpt.eval_records or [])
        v._phases = dict(ckpt.phases or {"p1_done": False, "p2_done": False})

        # Consensus
        try:
            v._consensus_published = bool(ckpt.consensus_published)
        except Exception:
            v._consensus_published = False

        # Round manager aggregates
        rm = getattr(v, "round_manager", None)
        if rm is not None:
            try:
                rm.start_block = ckpt.rm_start_block
                rm.round_rewards = dict(ckpt.rm_round_rewards or {})
                rm.round_eval_scores = dict(ckpt.rm_round_eval_scores or {})
                rm.round_times = dict(ckpt.rm_round_times or {})
            except Exception:
                pass
