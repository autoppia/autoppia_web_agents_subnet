from __future__ import annotations

import time
import asyncio
from typing import Dict, Optional

import bittensor as bt
import numpy as np

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator import config as validator_config
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.visualization.round_table import (
    render_round_summary_table,
)
from autoppia_web_agents_subnet.validator.settlement.consensus import (
    publish_round_snapshot,
    aggregate_scores_from_commitments,
)
from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards


class ValidatorSettlementMixin:
    """Consensus and weight-finalization helpers shared across phases."""

    async def _run_settlement_phase(self, *, agents_evaluated: int = 0) -> None:
        """
        Complete the round:
        - Publish consensus snapshot if pending.
        - Calculate and broadcast final weights (if not already done).
        - Wait for the next round boundary before exiting to the scheduler loop.
        """
        agents_dict = getattr(self, "agents_dict", None)
        if not isinstance(agents_dict, dict):
            agents_dict = {}

        handshake_uids = getattr(self, "agents_on_first_handshake", [])
        try:
            if isinstance(handshake_uids, (str, bytes, dict)):
                handshake_uids = []
            else:
                handshake_uids = list(handshake_uids)
        except Exception:
            handshake_uids = []

        self.should_update_weights = all(
            bool(getattr(agents_dict.get(uid), "evaluated", False)) for uid in handshake_uids
        )

        if not self.should_update_weights:
            ColoredLogger.info(
                "Not all agents from first handshake were evaluated; keeping original weights.",
                ColoredLogger.CYAN,
            )
            self.set_weights()
            self.round_manager.enter_phase(
                RoundPhase.COMPLETE,
                block=self.block,
                note=f"Round finalized without weight update",
                force=True,
            )
        else:
            st = await self._get_async_subtensor()
            await publish_round_snapshot(
                self, 
                st=st, 
                scores={str(int(uid)): float(agent.score) for uid, agent in (self.agents_dict or {}).items()}
            )

            await self._wait_until_specific_block(
                target_block=self.round_manager.settlement_block,
                target_description="round settlement block",
            )

            try:
                scores, _ = await aggregate_scores_from_commitments(self, st=st)
            except Exception as e:
                ColoredLogger.error(f"Error aggregating scores from commitments: {e}", ColoredLogger.RED)
                scores = {}
                
            await self._calculate_final_weights(scores=scores)
            self.round_manager.enter_phase(
                RoundPhase.COMPLETE,
                block=self.block,
                note=f"Round finalized with weight update",
                force=True,
            )

        await self._wait_until_specific_block(
            target_block=self.round_manager.target_block,
            target_description="round end block",
        )

        self.round_manager.log_phase_history()  

    async def _wait_until_specific_block(self, target_block: int, target_description: str) -> None:
        current_block = self.block
        if current_block >= target_block:
            return

        self.round_manager.enter_phase(
            RoundPhase.WAITING,
            block=current_block,
            note=f"Waiting for target {target_description} to reach block {target_block}",
        )
        last_log_time = time.time()
        while True:
            try:
                current_block = self.subtensor.get_current_block()
                if current_block >= target_block:
                    ColoredLogger.success(
                        f"🎯 Target {target_description} reached at block {target_block}",
                        ColoredLogger.GREEN,
                    )
                    break

                blocks_remaining = max(target_block - current_block, 0)
                minutes_remaining = (blocks_remaining * self.round_manager.SECONDS_PER_BLOCK) / 60

                if time.time() - last_log_time >= 12:
                    ColoredLogger.info(
                        (
                            f"Waiting — {target_description} — ~{minutes_remaining:.1f}m left — holding until block {target_block}"
                        ),
                        ColoredLogger.BLUE,
                    )
                    last_log_time = time.time()
            except Exception as exc:
                bt.logging.debug(f"Failed to read current block during finalize wait: {exc}")

            await asyncio.sleep(12)

    async def _burn_all(
        self,
        *,
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
            try:
                burn_uid = int(getattr(validator_config, "BURN_UID", 5))
            except Exception:
                burn_uid = 5
            burn_idx = burn_uid if 0 <= burn_uid < n else min(5, n - 1)
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

        # final_weights = {
        #     uid: float(weights[uid]) for uid in range(len(weights)) if float(weights[uid]) > 0.0
        # }

        # finish_success = await self._finish_iwap_round(
        #     avg_rewards=self.round_manager.final_aggregated_rewards or {},
        #     final_weights=final_weights,
        # )

        # round_reason = reason
        # log_color = success_color if finish_success else ColoredLogger.YELLOW
        # if finish_success:
        #     ColoredLogger.success(success_message, success_color)
        # else:
        #     bt.logging.warning(
        #         f"IWAP finish_round failed during burn-all ({reason}); continuing without remote acknowledgement."
        #     )
        #     ColoredLogger.warning(
        #         "⚠️ IWAP finish_round did not complete; proceeding locally.",
        #         ColoredLogger.YELLOW,
        #     )
        #     round_reason = f"{reason} — IWAP finish failed"

        # self._log_round_completion(
        #     color=log_color,
        #     reason=round_reason,
        # )

    async def _calculate_final_weights(self, scores: Dict[int, float]):
        """Calculate averages, apply WTA, and set final on-chain weights."""
        round_number = getattr(self, "_current_round_number", None)

        if round_number is not None:
            ColoredLogger.info(f"🏁 Finishing Round: {int(round_number)}", ColoredLogger.GOLD)
        else:
            ColoredLogger.info("🏁 Finishing current round", ColoredLogger.GOLD)

        burn_reason: Optional[str] = None

        if bool(getattr(validator_config, "BURN_ALL", False)):
            ColoredLogger.warning(
                "🔥 BURN_ALL enabled: forcing burn and skipping consensus",
                ColoredLogger.RED,
            )
            burn_reason = "burn (forced)"

        valid_scores = {uid: score for uid, score in scores.items() if score > 0.0}
        if (not valid_scores) or burn_reason:
            self._last_round_winner_uid = None
            await self._burn_all(
                reason=burn_reason or "burn (no rewards)",
            )
            return

        avg_rewards_array = np.zeros(self.metagraph.n, dtype=np.float32)
        for uid, score in valid_scores.items():
            if 0 <= int(uid) < self.metagraph.n:
                avg_rewards_array[int(uid)] = float(score)

        try:
            bonus_pct = max(float(getattr(validator_config, "LAST_WINNER_BONUS_PCT", 0.0)), 0.0)
        except Exception:
            bonus_pct = 0.0
        if bonus_pct > 0.0 and getattr(self, "_last_round_winner_uid", None) is not None:
            prev = int(self._last_round_winner_uid)
            if 0 <= prev < avg_rewards_array.shape[0]:
                avg_rewards_array[prev] *= 1.0 + bonus_pct
                ColoredLogger.info(
                    f"🏆 Applying previous-winner bonus to UID {prev}: x{1.0 + bonus_pct:.3f}",
                    ColoredLogger.GOLD,
                )

        final_rewards_array = wta_rewards(avg_rewards_array)
        final_rewards_dict = {
            uid: float(final_rewards_array[uid])
            for uid in range(len(final_rewards_array))
            if float(final_rewards_array[uid]) > 0.0
        }

        if final_rewards_dict:
            winner_uid = next(iter(final_rewards_dict.keys()))
            self._last_round_winner_uid = winner_uid
        else:
            self._last_round_winner_uid = None

        render_round_summary_table(
            self.round_manager,
            final_rewards_dict,
            self.metagraph,
            to_console=True,
        )

        self.update_scores(rewards=final_rewards_array, uids=list(range(self.metagraph.n)))
        self.set_weights()

        # Send final results to IWAP
        try:
            # Count tasks completed (from agents_dict)
            tasks_completed = 0
            for agent in self.agents_dict.values():
                if hasattr(agent, 'score') and agent.score > 0:
                    tasks_completed += 1
            
            finish_success = await self._finish_iwap_round(
                avg_rewards=valid_scores,
                final_weights={
                    uid: float(final_rewards_array[uid])
                    for uid in range(len(final_rewards_array))
                    if float(final_rewards_array[uid]) > 0.0
                },
                tasks_completed=tasks_completed,
            )
            
            if finish_success:
                ColoredLogger.success("✅ Final weights submitted to IWAP successfully", ColoredLogger.GREEN)
            else:
                ColoredLogger.warning(
                    "⚠️ IWAP finish_round failed; weights set on-chain but dashboard not updated.",
                    ColoredLogger.YELLOW,
                )
        except Exception as exc:
            ColoredLogger.error(f"Error finishing IWAP round: {exc}", ColoredLogger.RED)
            finish_success = False

        self._log_round_completion(
            color=ColoredLogger.GREEN if finish_success else ColoredLogger.YELLOW,
            reason="completed",
        )

        # Tear down any per-miner sandboxes to keep footprint low between rounds.
        try:
            manager = getattr(self, "sandbox_manager", None)
            if manager is not None:
                manager.cleanup_all_agents()
        except Exception:
            pass


    def _log_round_completion(self, *, color: str, reason: str) -> None:
        """Small helper for consistent round completion logs."""
        ColoredLogger.info(
            f"Round completion | reason={reason}",
            color,
        )


# Backward-compat alias expected by tests
SettlementMixin = ValidatorSettlementMixin
