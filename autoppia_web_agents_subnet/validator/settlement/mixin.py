from __future__ import annotations

import time
import asyncio
from typing import Dict, Optional

import bittensor as bt
import numpy as np

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.utils.log_colors import consensus_tag
from autoppia_web_agents_subnet.validator.config import (
    BURN_ALL,
    BURN_UID,
    MINIMUM_START_BLOCK,
    ENABLE_DISTRIBUTED_CONSENSUS,
    FINAL_TOP_K,
)
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.visualization.round_table import (
    render_round_summary_table,
)
from autoppia_web_agents_subnet.validator.settlement.consensus import (
    publish_phase_snapshot,
    aggregate_scores_from_commitments,
)
from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards


class ValidatorSettlementMixin:
    """Consensus and weight-finalization helpers shared across phases."""

    async def _wait_until_specific_block(self, target_block: int, target_discription: str) -> None:
        current_block = self.block
        if current_block >= target_block:
            return

        self.round_manager.enter_phase(
            RoundPhase.WAITING,
            block=current_block,
            note=f"Waiting for target {target_discription} to reach block {target_block}",
        )
        last_log_time = time.time()
        while True:
            try:
                current_block = self.subtensor.get_current_block()
                if current_block >= target_block:
                    ColoredLogger.success(
                        f"🎯 Target {target_discription} reached at block {target_block}",
                        ColoredLogger.GREEN,
                    )
                    break

                blocks_remaining = max(target_block - current_block, 0)
                minutes_remaining = (blocks_remaining * self.round_manager.SECONDS_PER_BLOCK) / 60

                if time.time() - last_log_time >= 12:
                    ColoredLogger.info(
                        (
                            f"Waiting — {target_discription} — ~{minutes_remaining:.1f}m left — holding until block {target_block}"
                        ),
                        ColoredLogger.BLUE,
                    )
                    last_log_time = time.time()
            except Exception as exc:
                bt.logging.debug(f"Failed to read current block during finalize wait: {exc}")

            await asyncio.sleep(12)

    async def _publish_screening_snapshot(self, *, tasks_completed: int) -> None:
        """Publish screening consensus snapshot to IPFS."""
        ColoredLogger.error(
            "📤📤📤 PUBLISHING SCREENING CONSENSUS SNAPSHOT TO IPFS NOW 📤📤📤",
            ColoredLogger.RED,
        )
        ColoredLogger.error(
            f"📦 Screening tasks completed: {tasks_completed}/{len(self.screening_tasks)}",
            ColoredLogger.RED,
        )

        st = await self._get_async_subtensor()
        avg_rewards = self.round_manager.get_screening_average_rewards()
        await publish_phase_snapshot(
            self,
            st=st,
            phase=RoundPhase.SCREENING_CONSENSUS,
            tasks_completed=tasks_completed,
            scores=avg_rewards,
        )

    async def _publish_final_snapshot(self, *, tasks_completed: int) -> None:
        """Publish final consensus snapshot to IPFS."""
        ColoredLogger.error(
            "📤📤📤 PUBLISHING FINAL CONSENSUS SNAPSHOT TO IPFS NOW 📤📤📤",
            ColoredLogger.RED,
        )
        ColoredLogger.error(
            f"📦 Final tasks completed: {tasks_completed}/{len(self.final_tasks)}",
            ColoredLogger.RED,
        )

        st = await self._get_async_subtensor()
        avg_rewards = self.round_manager.get_final_average_rewards()
        await publish_phase_snapshot(
            self,
            st=st,
            phase=RoundPhase.FINAL_CONSENSUS,
            tasks_completed=tasks_completed,
            scores=avg_rewards,
        )

    async def _aggregate_screening_scores(self) -> None:
        """Aggregate screening scores from all commitments."""
        if not ENABLE_DISTRIBUTED_CONSENSUS:
            self.round_manager.get_screening_average_rewards()
            return

        ColoredLogger.error("\n" + "=" * 80, ColoredLogger.RED)
        ColoredLogger.error(
            f"📦 Aggregating screening scores from IPFS commitments",
            ColoredLogger.RED,
        )
        ColoredLogger.error("=" * 80 + "\n", ColoredLogger.RED)
        st = await self._get_async_subtensor()
        scores, _ = await aggregate_scores_from_commitments(
            self,
            st=st, 
            phase=RoundPhase.SCREENING_CONSENSUS
        )
        self.round_manager.screening_aggregated_rewards = scores

    async def _aggregate_final_scores(self) -> None:
        """Aggregate final scores from all commitments."""
        if not ENABLE_DISTRIBUTED_CONSENSUS:
            self.round_manager.get_final_average_rewards()
            return

        ColoredLogger.error("\n" + "=" * 80, ColoredLogger.RED)
        ColoredLogger.error(
            f"📦 Aggregating final scores from IPFS commitments",
            ColoredLogger.RED,
        )
        ColoredLogger.error("=" * 80 + "\n", ColoredLogger.RED)
        st = await self._get_async_subtensor()
        scores, _ = await aggregate_scores_from_commitments(
            self,
            st=st, 
            phase=RoundPhase.FINAL_CONSENSUS
        )
        self.round_manager.final_aggregated_rewards = scores

    async def _select_final_top_k_uids(self) -> None:
        """Select top K UIDs from screening and final scores."""
        screening_scores = self.round_manager.screening_aggregated_rewards
        screening_uids = list(screening_scores.keys())
        sorted_miner_uids = sorted(screening_uids, key=lambda x: screening_scores[x], reverse=True)
        final_uid_limit = max(FINAL_TOP_K, len(sorted_miner_uids))
        self.final_top_k_uids = sorted_miner_uids[:final_uid_limit]
        ColoredLogger.info(
            f"🏁 Selected final top {final_uid_limit} UIDs: {self.final_top_k_uids}",
            ColoredLogger.GREEN,
        )

    async def _run_settlement_phase(self, *, tasks_completed: int) -> None:
        """
        Complete the round:
        - Publish consensus snapshot if pending.
        - Calculate and broadcast final weights (if not already done).
        - Wait for the next round boundary before exiting to the scheduler loop.
        """
        self.round_manager.enter_phase(
            RoundPhase.FINAL_CONSENSUS,
            block=self.block,
            note="Starting final consensus phase",
        )
        await self._aggregate_final_scores()
        await self._calculate_final_weights()

        self.round_manager.enter_phase(
            RoundPhase.WAITING,
            block=self.block,
            note="Awaiting end-of-round boundary",
        )

        try:
            await self._wait_until_next_round_boundary()
        except Exception as exc:
            bt.logging.warning(f"Wait-until-boundary failed, proceeding to next loop: {exc}")

        self.round_manager.enter_phase(
            RoundPhase.COMPLETE,
            block=self.block,
            note=f"Round finalized with {tasks_completed} tasks",
            force=True,
        )
        self.round_manager.log_phase_history()   

        self._wait_until_specific_block(
            target_block=self.round_manager.target_block,
            target_discription="round boundary block",
        )

    async def _burn_all(
        self,
        *,
        tasks_completed: int,
        reason: str,
        weights: Optional[np.ndarray] = None,
        success_message: Optional[str] = None,
        success_color: str = ColoredLogger.RED,
    ) -> None:
        """Override on-chain weights with burn-style weights and finalize the round."""
        n = self.metagraph.n
        self.round_manager.enter_phase(
            RoundPhase.FINALIZING,
            block=self.block,
            note=f"Burn all triggered ({reason})",
        )

        if weights is None:
            burn_idx = int(BURN_UID) if 0 <= int(BURN_UID) < n else min(5, n - 1)
            weights = np.zeros(n, dtype=np.float32)
            weights[burn_idx] = 1.0
            success_message = success_message or f"✅ Burn complete (weight to UID {burn_idx})"
        else:
            if not isinstance(weights, np.ndarray):
                weights = np.asarray(weights, dtype=np.float32)
            elif weights.dtype != np.float32:
                weights = weights.astype(np.float32)
            success_message = success_message or "✅ Burn complete"

        all_uids = list(range(n))
        self.update_scores(rewards=weights, uids=all_uids)
        self.set_weights()

        final_weights = {
            uid: float(weights[uid]) for uid in range(len(weights)) if float(weights[uid]) > 0.0
        }

        finish_success = await self._finish_iwap_round(
            avg_rewards=self.round_manager.final_aggregated_rewards or {},
            final_weights=final_weights,
            tasks_completed=tasks_completed,
        )

        round_reason = reason
        log_color = success_color if finish_success else ColoredLogger.YELLOW
        if finish_success:
            ColoredLogger.success(success_message, success_color)
            ColoredLogger.info(f"Tasks attempted: {tasks_completed}", success_color)
        else:
            bt.logging.warning(
                f"IWAP finish_round failed during burn-all ({reason}); continuing without remote acknowledgement."
            )
            ColoredLogger.warning(
                "⚠️ IWAP finish_round did not complete; proceeding locally.",
                ColoredLogger.YELLOW,
            )
            ColoredLogger.info(f"Tasks attempted: {tasks_completed}", ColoredLogger.YELLOW)
            round_reason = f"{reason} — IWAP finish failed"

        self._log_round_completion(
            tasks_completed,
            color=log_color,
            reason=round_reason,
        )

    async def _calculate_final_weights(self, tasks_completed: int):
        """Calculate averages, apply WTA, and set final on-chain weights."""
        round_number = getattr(self, "_current_round_number", None)

        if round_number is not None:
            ColoredLogger.info(f"🏁 Finishing Round: {int(round_number)}", ColoredLogger.GOLD)
        else:
            ColoredLogger.info("🏁 Finishing current round", ColoredLogger.GOLD)

        burn_reason: Optional[str] = None

        if not self.final_top_k_uids:
            ColoredLogger.error("🔥 No final top K UIDs: burning all weights", ColoredLogger.RED)
            burn_reason = "burn (no final top K UIDs)"
        else:
            if BURN_ALL:
                ColoredLogger.warning(
                    "🔥 BURN_ALL enabled: forcing burn and skipping consensus",
                    ColoredLogger.RED,
                )
                burn_reason = "burn (forced)"

        if burn_reason:
            await self._burn_all(
                tasks_completed=tasks_completed,
                reason=burn_reason,
            )
            return

        if not self.round_manager.final_aggregated_rewards:
            ColoredLogger.warning("No rewards to apply; burning weights", ColoredLogger.YELLOW)
            await self._burn_all(
                tasks_completed=tasks_completed,
                reason="burn (no rewards)",
            )
            return

        avg_rewards_array = np.zeros(self.metagraph.n, dtype=np.float32)
        for uid, score in self.round_manager.final_aggregated_rewards.items():
            if 0 <= int(uid) < self.metagraph.n:
                avg_rewards_array[int(uid)] = float(score)

        final_rewards_array = wta_rewards(avg_rewards_array)
        final_rewards_dict = {
            uid: float(final_rewards_array[uid])
            for uid in range(len(final_rewards_array))
            if float(final_rewards_array[uid]) > 0.0
        }

        render_round_summary_table(
            self.round_manager,
            final_rewards_dict,
            self.metagraph,
            to_console=True,
        )

        self.update_scores(rewards=final_rewards_array, uids=list(range(self.metagraph.n)))
        self.set_weights()

        finish_success = await self._finish_iwap_round(
            avg_rewards=self.round_manager.final_aggregated_rewards or {},
            final_weights={
                uid: float(final_rewards_array[uid])
                for uid in range(len(final_rewards_array))
                if float(final_rewards_array[uid]) > 0.0
            },
            tasks_completed=tasks_completed,
        )

        if finish_success:
            ColoredLogger.success("✅ Final weights submitted successfully", ColoredLogger.GREEN)
        else:
            ColoredLogger.warning(
                "⚠️ IWAP finish_round failed; continuing locally.",
                ColoredLogger.YELLOW,
            )

        self._log_round_completion(
            tasks_completed,
            color=ColoredLogger.GREEN if finish_success else ColoredLogger.YELLOW,
            reason="completed",
        )

    async def _finish_iwap_round(
        self,
        *,
        avg_rewards: Dict[int, float],
        final_weights: Dict[int, float],
        tasks_completed: int,
    ) -> bool:
        """Bridge to IWAP client finish_round flow."""
        try:
            return await super()._finish_iwap_round(  # type: ignore[misc]
                avg_rewards=avg_rewards,
                final_weights=final_weights,
                tasks_completed=tasks_completed,
            )
        except Exception as exc:
            bt.logging.warning(f"IWAP finish_round failed: {exc}")
            return False

    def _log_round_completion(self, tasks_completed: int, *, color: str, reason: str) -> None:
        """Small helper for consistent round completion logs."""
        ColoredLogger.info(
            f"Round completion | tasks_completed={tasks_completed} | reason={reason}",
            color,
        )
