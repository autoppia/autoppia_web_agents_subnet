from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import httpx

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.config import (
    IWAP_API_BASE_URL,
    TESTING,
)


class RoundPhase(Enum):
    """Named phases in the validator round lifecycle."""

    IDLE = "idle"
    PREPARING = "preparing"
    HANDSHAKE = "handshake"
    TASK_EXECUTION = "task_execution"
    CONSENSUS = "consensus"
    WAITING = "waiting"
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class PhaseTransition:
    """Record of a phase transition within a round."""

    phase: RoundPhase
    started_at_block: Optional[int] = None
    started_at_epoch: Optional[float] = None
    note: Optional[str] = None
    started_at_time: float = field(default_factory=time.time)


@dataclass
class RoundStatus:
    """Lightweight snapshot of the current round status."""

    phase: RoundPhase
    round_start_block: Optional[int]
    target_block: Optional[int]
    current_block: Optional[int]
    blocks_remaining: Optional[int]
    minutes_remaining: Optional[float]
    note: Optional[str] = None


class RoundManager:
    """
    Manages complete round lifecycle: timing, boundaries, and score accumulation.

    Combines:
    - Round timing and boundaries
    - Score accumulation (screening + final)
    - Phase tracking for observability
    """

    BLOCKS_PER_EPOCH = 360
    SECONDS_PER_BLOCK = 12

    def __init__(
        self,
        round_size_epochs: float,
        avg_task_duration_seconds: float,
        safety_buffer_epochs: float,
        minimum_start_block: Optional[int] = None,
    ):
        self.round_size_epochs = round_size_epochs
        self.avg_task_duration_seconds = avg_task_duration_seconds
        self.safety_buffer_epochs = safety_buffer_epochs
        self.minimum_start_block = minimum_start_block

        self.ROUND_BLOCK_LENGTH = int(self.BLOCKS_PER_EPOCH * max(self.round_size_epochs, 0.01))

        # Screening statistics
        self.round_rewards: Dict[int, List[float]] = {}
        self.round_eval_scores: Dict[int, List[float]] = {}
        self.round_times: Dict[int, List[float]] = {}
        self.round_task_attempts: Dict[int, int] = {}

        # Final-phase statistics
        self.final_round_rewards: Dict[int, List[float]] = {}
        self.final_round_eval_scores: Dict[int, List[float]] = {}
        self.final_round_times: Dict[int, List[float]] = {}

        # Duplicate-solution bookkeeping
        self.round_duplicate_counts: Dict[int, int] = {}

        # Round start block
        self.start_block: int | None = None

        # Phase tracking
        self.current_phase: RoundPhase = RoundPhase.IDLE
        self.phase_history: List[PhaseTransition] = []

    # ──────────────────────────────────────────────────────────────────────────
    # Round timing helpers
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def block_to_epoch(cls, block: int) -> float:
        return block / cls.BLOCKS_PER_EPOCH

    @classmethod
    def epoch_to_block(cls, epoch: float) -> int:
        return int(epoch * cls.BLOCKS_PER_EPOCH)

    def start_new_round(self, current_block: int):
        if not self.can_start_round(current_block):
            blocks_remaining = self.blocks_until_allowed(current_block)
            next_block = self.minimum_start_block if self.minimum_start_block is not None else None
            message = (
                f"Round start blocked. Current block {current_block} has not reached minimum "
                f"{self.minimum_start_block}."
            )
            if next_block is not None:
                message += f" Next allowed block: {next_block} (≈{blocks_remaining} blocks remaining)."
            ColoredLogger.warning(message, ColoredLogger.YELLOW)
            raise RuntimeError("Round cannot start before minimum start block is reached")

        boundaries = self.get_round_boundaries(current_block, log_debug=False)
        self.start_block = int(boundaries["round_start_block"])
        self.reset_round()
        self.enter_phase(
            RoundPhase.PREPARING,
            block=self.start_block,
            note="Round window established",
        )

        blocks_remaining = boundaries["target_block"] - current_block
        estimated_minutes = (blocks_remaining * self.SECONDS_PER_BLOCK) / 60
        ColoredLogger.info(
            (
                "🔄 Starting new round | start_block={start_block} start_epoch={start_epoch:.2f} "
                "-> target_epoch={target_epoch:.2f} target_block={target_block} | ETA ~{eta:.1f}m (~{blocks} blocks)"
            ).format(
                start_block=self.start_block,
                start_epoch=boundaries["round_start_epoch"],
                target_epoch=boundaries["target_epoch"],
                target_block=boundaries["target_block"],
                eta=estimated_minutes,
                blocks=blocks_remaining,
            ),
            ColoredLogger.CYAN,
        )

    def get_round_boundaries(self, current_block: int, *, log_debug: bool = True) -> Dict[str, Any]:
        import bittensor as bt

        rbl = int(self.ROUND_BLOCK_LENGTH)
        base_block = int(self.minimum_start_block) if self.minimum_start_block is not None else 0
        effective_block = max(current_block, base_block)

        if self.minimum_start_block is not None:
            blocks_since_base = effective_block - base_block
            window_index = blocks_since_base // rbl
            round_start_block = int(base_block + window_index * rbl)
        else:
            window_index = effective_block // rbl
            round_start_block = int(window_index * rbl)

        target_block = int(round_start_block + rbl)
        round_start_epoch = round_start_block / self.BLOCKS_PER_EPOCH
        target_epoch = target_block / self.BLOCKS_PER_EPOCH

        if log_debug:
            bt.logging.debug(
                (
                    "🌐 Sync | block={blk:,} | start_epoch={start:.4f} (b{sb:,}) -> target_epoch={end:.4f} (b{tb:,}) | blocks={blocks:,}"
                ).format(
                    blk=current_block,
                    start=round_start_epoch,
                    sb=round_start_block,
                    end=target_epoch,
                    tb=target_block,
                    blocks=(target_block - round_start_block),
                )
            )

        return {
            "round_start_epoch": round_start_epoch,
            "target_epoch": target_epoch,
            "round_start_block": round_start_block,
            "target_block": target_block,
        }

    def get_current_boundaries(self) -> Dict[str, Any]:
        if self.start_block is None:
            raise ValueError("Round not started. Call start_new_round() first.")
        return self.get_round_boundaries(self.start_block, log_debug=False)

    def fraction_elapsed(self, current_block: int) -> float:
        bounds = self.get_round_boundaries(current_block, log_debug=False)
        rsb = int(bounds["round_start_block"])
        tb = int(bounds["target_block"])
        total = max(tb - rsb, 1)
        done = max(current_block - rsb, 0)
        frac = done / total
        return max(0.0, min(1.0, frac))

    def should_send_next_task(self, current_block: int) -> bool:
        if self.start_block is None:
            raise ValueError("Round not started. Call start_new_round() first.")

        boundaries = self.get_round_boundaries(self.start_block, log_debug=False)
        safety_buffer_blocks = self.safety_buffer_epochs * self.BLOCKS_PER_EPOCH
        absolute_limit_block = int(boundaries["target_block"] - safety_buffer_blocks)

        if current_block >= absolute_limit_block:
            return False

        blocks_until_limit = absolute_limit_block - current_block
        seconds_until_limit = blocks_until_limit * self.SECONDS_PER_BLOCK
        return seconds_until_limit >= self.avg_task_duration_seconds

    def get_wait_info(self, current_block: int) -> Dict[str, Any]:
        if self.start_block is None:
            raise ValueError("Round not started. Call start_new_round() first.")

        boundaries = self.get_round_boundaries(self.start_block, log_debug=False)
        target_epoch = boundaries["target_epoch"]
        current_epoch = self.block_to_epoch(current_block)

        blocks_remaining = boundaries["target_block"] - current_block
        seconds_remaining = blocks_remaining * self.SECONDS_PER_BLOCK
        minutes_remaining = seconds_remaining / 60

        return {
            "current_epoch": current_epoch,
            "target_epoch": target_epoch,
            "blocks_remaining": blocks_remaining,
            "seconds_remaining": seconds_remaining,
            "minutes_remaining": minutes_remaining,
            "reached_target": current_epoch >= target_epoch,
        }

    def log_calculation_summary(self) -> None:
        base = (
            f"📊 Round config | size={self.round_size_epochs} epochs | buffer={self.safety_buffer_epochs} epochs | "
            f"avg_task={self.avg_task_duration_seconds}s | b/epoch={self.BLOCKS_PER_EPOCH} | s/block={self.SECONDS_PER_BLOCK}s | "
            f"round_blocks={self.ROUND_BLOCK_LENGTH}"
        )
        if self.minimum_start_block is not None:
            base += f" | min_start_block>{self.minimum_start_block}"
        ColoredLogger.info(base, ColoredLogger.CYAN)

    def can_start_round(self, current_block: int) -> bool:
        if TESTING:
            return True
        if self.minimum_start_block is None:
            return True
        return current_block >= self.minimum_start_block

    def blocks_until_allowed(self, current_block: int) -> int:
        if self.minimum_start_block is None:
            return 0
        return max(self.minimum_start_block - current_block, 0)

    async def calculate_round(self, current_block: int) -> int:
        base_block = self.minimum_start_block or 0
        if current_block < base_block:
            return 0

        blocks_since_start = current_block - base_block
        round_index = blocks_since_start // self.ROUND_BLOCK_LENGTH
        round_number = int(round_index + 1)

        if TESTING:
            try:
                backend_round = await self._calculate_round_from_backend()
                if backend_round is not None:
                    return backend_round
            except Exception:
                pass
        return round_number

    async def _calculate_round_from_backend(self) -> Optional[int]:
        base_url = (IWAP_API_BASE_URL or "").rstrip("/")
        if not base_url:
            return None

        url = f"{base_url}/api/v1/rounds"
        params = {
            "limit": 1,
            "page": 1,
            "sortBy": "round",
            "sortOrder": "desc",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            ColoredLogger.warning(
                f"Unable to fetch rounds from backend ({url}): {exc}",
                ColoredLogger.YELLOW,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            ColoredLogger.warning(
                f"Unexpected error when fetching rounds from backend ({url}): {exc}",
                ColoredLogger.YELLOW,
            )
            return None

        try:
            payload = response.json()
        except ValueError:
            ColoredLogger.warning(
                f"Received non-JSON response from backend rounds endpoint ({url})",
                ColoredLogger.YELLOW,
            )
            return None

        entries = self._extract_round_entries(payload)
        if not entries:
            return 1

        latest_entry = entries[0]
        round_value = self._extract_round_value(latest_entry)
        if round_value is None:
            return None
        return round_value + 1

    @staticmethod
    def _extract_round_entries(payload: Any) -> List[Dict[str, Any]]:
        def _coerce(obj: Any) -> List[Dict[str, Any]]:
            if isinstance(obj, list):
                return [item for item in obj if isinstance(item, dict)]
            if isinstance(obj, dict):
                candidates = []
                for key in ("rounds", "data", "entries"):
                    if key in obj:
                        nested = _coerce(obj[key])
                        if nested:
                            candidates.extend(nested)
                if candidates:
                    return candidates
                if {"round", "roundNumber", "round_number", "id"}.intersection(obj.keys()):
                    return [obj]
            return []

        extracted = _coerce(payload)
        return extracted

    @staticmethod
    def _extract_round_value(entry: Dict[str, Any]) -> Optional[int]:
        for key in ("round", "roundNumber", "round_number", "id"):
            value = entry.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                digits = "".join(ch for ch in value if ch.isdigit())
                if digits:
                    try:
                        return int(digits)
                    except ValueError:
                        continue
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Score accumulation
    # ──────────────────────────────────────────────────────────────────────────
    def accumulate_rewards(
        self,
        miner_uids: List[int],
        rewards: List[float],
        eval_scores: List[float],
        execution_times: List[float],
    ) -> None:
        for i, uid in enumerate(miner_uids):
            uid = int(uid)
            self.round_rewards.setdefault(uid, []).append(rewards[i])
            self.round_eval_scores.setdefault(uid, []).append(eval_scores[i])
            self.round_times.setdefault(uid, []).append(execution_times[i])
            self.round_task_attempts[uid] = int(self.round_task_attempts.get(uid, 0)) + 1

    def accumulate_final_rewards(
        self,
        miner_uids: List[int],
        rewards: List[float],
        eval_scores: List[float],
        execution_times: List[float],
    ) -> None:
        for i, uid in enumerate(miner_uids):
            uid = int(uid)
            self.final_round_rewards.setdefault(uid, []).append(rewards[i])
            self.final_round_eval_scores.setdefault(uid, []).append(eval_scores[i])
            self.final_round_times.setdefault(uid, []).append(execution_times[i])

    def record_duplicate_penalties(self, miner_uids: List[int], groups: List[List[int]]):
        try:
            for group in groups or []:
                for idx in group:
                    if 0 <= idx < len(miner_uids):
                        uid = int(miner_uids[idx])
                        self.round_duplicate_counts[uid] = int(self.round_duplicate_counts.get(uid, 0)) + 1
        except Exception:
            pass

    def get_average_rewards(self) -> Dict[int, float]:
        return {
            uid: (sum(rewards) / len(rewards)) if rewards else 0.0
            for uid, rewards in self.round_rewards.items()
        }

    def get_final_average_rewards(self) -> Dict[int, float]:
        return {
            uid: (sum(rewards) / len(rewards)) if rewards else 0.0
            for uid, rewards in self.final_round_rewards.items()
        }

    def get_round_stats(self) -> Dict[str, Any]:
        total_miners = len(self.round_rewards)
        total_tasks = sum(len(reward) for reward in self.round_rewards.values())
        return {
            "total_miners": total_miners,
            "total_tasks": total_tasks,
            "miners_with_rewards": len([uid for uid, rewards in self.round_rewards.items() if rewards]),
            "round_rewards": self.round_rewards,
            "round_times": self.round_times,
            "round_eval_scores": self.round_eval_scores,
        }

    def reset_round(self) -> None:
        self.round_rewards = {}
        self.round_eval_scores = {}
        self.round_times = {}
        self.round_task_attempts = {}
        self.final_round_rewards = {}
        self.final_round_eval_scores = {}
        self.final_round_times = {}
        self.round_duplicate_counts = {}
        self.reset_phase_tracking()

    def log_round_summary(self) -> None:
        stats = self.get_round_stats()
        ColoredLogger.debug(
            f"Round stats | miners={stats['total_miners']} | tasks={stats['total_tasks']}",
            ColoredLogger.PURPLE,
        )
        if self.round_task_attempts:
            parts = []
            for uid, attempts in self.round_task_attempts.items():
                evals_used = len(self.round_rewards.get(uid, []))
                parts.append(f"{uid}:{evals_used}/{attempts}")
            summary = ", ".join(parts)
            ColoredLogger.info(
                f"Evaluation counts (evaluated/attempted per miner): {summary}",
                ColoredLogger.CYAN,
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Phase tracking utilities
    # ──────────────────────────────────────────────────────────────────────────
    def enter_phase(
        self,
        phase: RoundPhase,
        *,
        block: Optional[int] = None,
        note: Optional[str] = None,
        force: bool = False,
    ) -> PhaseTransition:
        if not force and self.current_phase == phase and self.phase_history:
            transition = self.phase_history[-1]
            if note:
                transition.note = note
            if block is not None and transition.started_at_block is None:
                transition.started_at_block = block
                transition.started_at_epoch = self.block_to_epoch(block)
            return transition

        transition = PhaseTransition(
            phase=phase,
            started_at_block=block,
            started_at_epoch=self.block_to_epoch(block) if block is not None else None,
            note=note,
        )
        self.current_phase = phase
        self.phase_history.append(transition)
        self._log_phase_transition(transition)
        return transition

    def current_phase_state(self) -> PhaseTransition:
        if self.phase_history:
            return self.phase_history[-1]
        return PhaseTransition(phase=self.current_phase)

    def log_phase_history(self) -> None:
        if not self.phase_history:
            return

        lines = []
        for item in self.phase_history:
            block_info = f"block={item.started_at_block}" if item.started_at_block is not None else ""
            note_info = f"note={item.note}" if item.note else ""
            epoch_info = (
                f"epoch={item.started_at_epoch:.2f}"
                if item.started_at_epoch is not None
                else ""
            )
            parts = [part for part in (block_info, epoch_info, note_info) if part]
            suffix = " | ".join(parts)
            lines.append(f"{item.phase.value}: {suffix}" if suffix else item.phase.value)

        ColoredLogger.info("Round phase timeline ➜ " + " → ".join(lines), ColoredLogger.ORANGE)

    def get_status(self, current_block: Optional[int] = None) -> RoundStatus:
        boundaries: Dict[str, Any] = {}
        if self.start_block is not None:
            boundaries = self.get_round_boundaries(self.start_block, log_debug=False)

        target_block = boundaries.get("target_block")
        blocks_remaining: Optional[int] = None
        minutes_remaining: Optional[float] = None
        if current_block is not None and target_block is not None:
            blocks_remaining = max(target_block - current_block, 0)
            minutes_remaining = (blocks_remaining * self.SECONDS_PER_BLOCK) / 60

        transition = self.current_phase_state()
        return RoundStatus(
            phase=self.current_phase,
            round_start_block=self.start_block,
            target_block=target_block,
            current_block=current_block,
            blocks_remaining=blocks_remaining,
            minutes_remaining=minutes_remaining,
            note=transition.note,
        )

    def reset_phase_tracking(self) -> None:
        self.current_phase = RoundPhase.IDLE
        self.phase_history = []

    def _log_phase_transition(self, transition: PhaseTransition) -> None:
        color_map = {
            RoundPhase.PREPARING: ColoredLogger.CYAN,
            RoundPhase.HANDSHAKE: ColoredLogger.MAGENTA,
            RoundPhase.TASK_EXECUTION: ColoredLogger.BLUE,
            RoundPhase.CONSENSUS: ColoredLogger.PURPLE,
            RoundPhase.WAITING: ColoredLogger.GRAY,
            RoundPhase.FINALIZING: ColoredLogger.GOLD,
            RoundPhase.COMPLETE: ColoredLogger.GREEN,
            RoundPhase.ERROR: ColoredLogger.RED,
        }
        color = color_map.get(transition.phase, ColoredLogger.WHITE)

        message = f"🧭 Phase → {transition.phase.value}"
        if transition.started_at_block is not None:
            message += f" | block={transition.started_at_block}"
        if transition.started_at_epoch is not None:
            message += f" | epoch={transition.started_at_epoch:.2f}"
        if transition.note:
            message += f" | {transition.note}"

        ColoredLogger.info(message, color)
