from __future__ import annotations

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
    
    async def _wait_for_minimum_start_block(self) -> bool:
        """
        Block until the chain height reaches the configured launch gate.

        Returns True when a wait occurred so callers can short-circuit their flow.
        """
        rm = getattr(self, "round_manager", None)
        if rm is None:
            raise RuntimeError("Round manager not initialized; cannot enforce minimum start block")

        current_block = self.block
        if rm.can_start_round(current_block):
            return False
        
        blocks_remaining = rm.blocks_until_allowed(current_block)
        seconds_remaining = blocks_remaining * rm.SECONDS_PER_BLOCK
        minutes_remaining = seconds_remaining / 60
        hours_remaining = minutes_remaining / 60

        current_epoch = rm.block_to_epoch(current_block)
        target_epoch = rm.block_to_epoch(MINIMUM_START_BLOCK)

        eta = f"~{hours_remaining:.1f}h" if hours_remaining >= 1 else f"~{minutes_remaining:.0f}m"
        bt.logging.warning(
            f"🔒 Locked until block {MINIMUM_START_BLOCK:,} (epoch {target_epoch:.2f}) | "
            f"now {current_block:,} (epoch {current_epoch:.2f}) | ETA {eta}"
        )

        wait_seconds = min(max(seconds_remaining, 30), 600)
        rm.enter_phase(
            RoundPhase.WAITING,
            block=current_block,
            note=f"Waiting for minimum start block {MINIMUM_START_BLOCK}",
        )
        bt.logging.warning(f"💤 Rechecking in {wait_seconds:.0f}s...")

        await asyncio.sleep(wait_seconds)
        return True

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
        """Aggregate screening scores from all miners."""
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
        """Aggregate final scores from all miners."""
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

    async def _run_settlement_phase(self, *, tasks_completed: int, total_tasks: int) -> None:
        """
        Complete the round:
        - Publish consensus snapshot if pending.
        - Calculate and broadcast final weights (if not already done).
        - Wait for the next round boundary before exiting to the scheduler loop.
        """
        try:
            self.state_manager.save_checkpoint()
        except Exception as exc:
            bt.logging.warning(f"Checkpoint save before settlement finalization failed: {exc}")

        if ENABLE_DISTRIBUTED_CONSENSUS and (not self._consensus_published):
            await self._publish_final_snapshot(
                tasks_completed=tasks_completed,
                total_tasks=total_tasks,
            )

        if not self._finalized_this_round:
            await self._calculate_final_weights(tasks_completed)
            self._finalized_this_round = True

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

    async def _burn_all(
        self,
        *,
        avg_rewards: Dict[int, float] | None,
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
            avg_rewards=avg_rewards or {},
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

        self.round_manager.enter_phase(
            RoundPhase.FINALIZING,
            block=self.block,
            note=f"Calculating final weights (tasks_completed={tasks_completed})",
        )

        bt.logging.info("=" * 80)
        bt.logging.info("[CONSENSUS] Phase: SetWeights - Calculating final weights")
        bt.logging.info(
            f"[CONSENSUS] Distributed consensus: {str(ENABLE_DISTRIBUTED_CONSENSUS).lower()}"
        )
        bt.logging.info("=" * 80)

        avg_rewards: Dict[int, float] = {}
        burn_reason: Optional[str] = None

        if not self.active_miner_uids:
            ColoredLogger.error("🔥 No active miners: burning all weights", ColoredLogger.RED)
            burn_reason = "burn (no active miners)"
        else:
            avg_rewards = self.round_manager.get_average_rewards()
            if BURN_ALL:
                ColoredLogger.warning(
                    "🔥 BURN_ALL enabled: forcing burn and skipping consensus",
                    ColoredLogger.RED,
                )
                burn_reason = "burn (forced)"

        if burn_reason:
            await self._burn_all(
                avg_rewards=avg_rewards,
                tasks_completed=tasks_completed,
                reason=burn_reason,
            )
            return

        if ENABLE_DISTRIBUTED_CONSENSUS:
            await self._wait_for_commit_propagation()
            boundaries = self.round_manager.get_current_boundaries()
            bt.logging.info("[CONSENSUS] Aggregating scores from other validators...")
            agg = self._agg_scores_cache or {}
            agg_meta = None
            if not agg:
                block_tensor = getattr(self.metagraph, "block", None)
                current_block_now = int(block_tensor.item()) if block_tensor is not None else 0
                bounds_now = self.round_manager.get_round_boundaries(
                    current_block_now,
                    log_debug=False,
                )
                rsb = bounds_now["round_start_block"]
                tb = bounds_now["target_block"]
                progress_now = min(max((current_block_now - rsb) / max(tb - rsb, 1), 0.0), 1.0)

                bt.logging.info("=" * 80)
                bt.logging.info(
                    consensus_tag(
                        f"📥 FETCH COMMITS @ {FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION:.0%}"
                    )
                )
                bt.logging.info(consensus_tag(f"Progress: {progress_now:.2f}"))
                bt.logging.info(consensus_tag(f"Current Block: {current_block_now:,}"))
                bt.logging.info(consensus_tag("Fetching commitments from IPFS to aggregate scores"))
                bt.logging.info("=" * 80)

                st = await self._get_async_subtensor()
                agg, agg_meta = await aggregate_scores_from_commitments(
                    validator=self,
                    st=st,
                    start_block=boundaries["round_start_block"],
                    target_block=boundaries["target_block"],
                )
                self._agg_scores_cache = agg

            if agg:
                ColoredLogger.info(
                    f"🤝 Using aggregated scores from commitments ({len(agg)} miners)",
                    ColoredLogger.CYAN,
                )
                avg_rewards = agg
                self._consensus_last_details = agg_meta or {}

        if not avg_rewards:
            ColoredLogger.warning("No rewards to apply; burning weights", ColoredLogger.YELLOW)
            await self._burn_all(
                avg_rewards=avg_rewards,
                tasks_completed=tasks_completed,
                reason="burn (no rewards)",
            )
            return

        avg_rewards_array = np.zeros(self.metagraph.n, dtype=np.float32)
        for uid, score in avg_rewards.items():
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
            avg_rewards=avg_rewards,
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
