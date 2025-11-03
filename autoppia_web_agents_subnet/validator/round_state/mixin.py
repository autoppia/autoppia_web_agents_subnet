from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import bittensor as bt

from autoppia_web_agents_subnet.validator.round_state.state_manager import RoundStateManager
from autoppia_web_agents_subnet.validator.config import (
    DZ_STARTING_BLOCK,
    ENABLE_CHECKPOINT_SYSTEM,
)
from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase


class RoundStateValidatorMixin:
    """Shared checkpoint / resume helpers for round lifecycle."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_resume_info: Dict[str, Any] = {"status": "init", "reason": ""}
        self.state_manager = RoundStateManager(self)

    async def _wait_for_minimum_start_block(self, current_block: int) -> bool:
        """
        Block until the chain height reaches the configured launch gate.

        Returns True when a wait occurred so callers can short-circuit their flow.
        """
        rm = getattr(self, "round_manager", None)
        if rm is None:
            raise RuntimeError("Round manager not initialized; cannot enforce minimum start block")

        if rm.can_start_round(current_block):
            return False

        blocks_remaining = rm.blocks_until_allowed(current_block)
        seconds_remaining = blocks_remaining * rm.SECONDS_PER_BLOCK
        minutes_remaining = seconds_remaining / 60
        hours_remaining = minutes_remaining / 60

        current_epoch = rm.block_to_epoch(current_block)
        target_epoch = rm.block_to_epoch(DZ_STARTING_BLOCK)

        eta = f"~{hours_remaining:.1f}h" if hours_remaining >= 1 else f"~{minutes_remaining:.0f}m"
        bt.logging.warning(
            f"🔒 Locked until block {DZ_STARTING_BLOCK:,} (epoch {target_epoch:.2f}) | "
            f"now {current_block:,} (epoch {current_epoch:.2f}) | ETA {eta}"
        )

        wait_seconds = min(max(seconds_remaining, 30), 600)
        rm.enter_phase(
            RoundPhase.WAITING,
            block=current_block,
            note=f"Waiting for minimum start block {DZ_STARTING_BLOCK}",
        )
        bt.logging.warning(f"💤 Rechecking in {wait_seconds:.0f}s...")

        await asyncio.sleep(wait_seconds)
        return True

    def _save_round_state(self, *, tasks: Optional[List[TaskWithProject]] = None) -> None:
        if not ENABLE_CHECKPOINT_SYSTEM:
            bt.logging.debug("Checkpoint save skipped: checkpoint system disabled")
            return
        self.state_manager.save_checkpoint(tasks=tasks)

    def _load_round_state(self, *, current_block: Optional[int] = None) -> Optional[Dict[str, Any]]:
        if not ENABLE_CHECKPOINT_SYSTEM:
            self._last_resume_info = {"status": "disabled", "reason": "checkpoint system disabled"}
            bt.logging.info("Resume disabled by config (ENABLE_CHECKPOINT_SYSTEM=false); starting fresh")
            return None

        ckpt = self.state_manager.load_checkpoint()
        if ckpt is None:
            self._last_resume_info = {"status": "skipped", "reason": "checkpoint not found"}
            return None

        rm = getattr(self, "round_manager", None)
        if current_block is not None and rm is None:
            raise RuntimeError("Round manager not initialized; cannot validate checkpoint state")

        if (
            current_block is not None
            and rm is not None
            and getattr(rm, "ROUND_BLOCK_LENGTH", 0)
            and getattr(ckpt, "rm_start_block", None) is not None
        ):
            round_length = int(getattr(rm, "ROUND_BLOCK_LENGTH", 0)) or 0
            base_block = int(getattr(rm, "minimum_start_block", 0) or 0)

            def _round_for_block(block: int) -> int:
                if block <= base_block:
                    return 0
                return int(((block - base_block) // round_length) + 1)

            checkpoint_round = _round_for_block(int(ckpt.rm_start_block))
            current_round = _round_for_block(int(current_block))

            if checkpoint_round != current_round:
                bt.logging.warning(
                    f"State checkpoint discarded: stored round {checkpoint_round} (start_block={ckpt.rm_start_block}) "
                    f"!= current round {current_round} (block={current_block})"
                )
                self._reset_iwap_round_state()
                reset_consensus = getattr(self, "_reset_consensus_state", None)
                if callable(reset_consensus):
                    reset_consensus()
                self.state_manager.cleanup()
                self._last_resume_info = {
                    "status": "discarded",
                    "reason": "stale_round",
                    "checkpoint_round": checkpoint_round,
                    "current_round": current_round,
                }
                return None

        self._last_resume_info = {
            "status": "loaded",
            "reason": "checkpoint loaded",
            "tasks_in_file": len(ckpt.all_tasks or []),
            "active_miners": len(getattr(self, "active_miner_uids", []) or []),
            "agent_runs": len(getattr(self, "current_agent_runs", {}) or {}),
            "completed_pairs": len(getattr(self, "_completed_pairs", set()) or set()),
        }
        return {"validator_round_id": ckpt.validator_round_id}

    def _remove_round_state(self) -> None:
        self.state_manager.cleanup()


class RoundPhaseValidatorMixin:
    """
    Phase-specific helpers for validator resume/rebuild.
    Holds logic that reconstructs accumulators and round aggregates
    from saved evaluation records after a crash.
    """

    def _rebuild_from_saved_evaluations(self) -> None:
        records = list(getattr(self, "_eval_records", []) or [])
        if not records:
            return
        bt.logging.info(f"Resume rebuild: restoring {len(records)} evaluation records")

        for rec in records:
            uid = int(rec.get("miner_uid")) if rec.get("miner_uid") is not None else None
            if uid is None:
                continue
            reward = float(rec.get("reward") or 0.0)
            score = float(rec.get("final_score") or 0.0)
            exec_time = float(rec.get("exec_time") or 0.0)

            acc = self.agent_run_accumulators.setdefault(
                uid, {"reward": 0.0, "score": 0.0, "execution_time": 0.0, "tasks": 0}
            )
            acc["reward"] += reward
            acc["score"] += score
            acc["execution_time"] += exec_time
            acc["tasks"] += 1

            run = getattr(self, "current_agent_runs", {}).get(uid)
            if run is not None:
                run.total_tasks = acc["tasks"]
                run.completed_tasks = acc["tasks"]
                run.total_reward = acc["reward"]
                run.average_reward = acc["reward"] / acc["tasks"] if acc["tasks"] else None
                run.average_score = acc["score"] / acc["tasks"] if acc["tasks"] else None
                run.average_execution_time = (
                    acc["execution_time"] / acc["tasks"] if acc["tasks"] else None
                )

            rr = self.round_manager.round_rewards.setdefault(uid, [])
            rs = self.round_manager.round_eval_scores.setdefault(uid, [])
            rt = self.round_manager.round_times.setdefault(uid, [])
            rr.append(reward)
            rs.append(score)
            rt.append(exec_time)
