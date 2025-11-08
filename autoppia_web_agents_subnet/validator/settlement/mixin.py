from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional

import bittensor as bt
import numpy as np

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.utils.log_colors import consensus_tag
from autoppia_web_agents_subnet.validator.config import (
    BURN_ALL,
    BURN_UID,
    ENABLE_DISTRIBUTED_CONSENSUS,
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION,
    PROPAGATION_BLOCKS_SLEEP,
)
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.visualization.round_table import (
    render_round_summary_table,
)
from autoppia_web_agents_subnet.validator.settlement.consensus import (
    aggregate_scores_from_commitments,
    publish_round_snapshot,
)
from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards


class SettlementMixin:
    """Consensus and weight-finalization helpers shared across phases."""

    def _reset_consensus_state(self) -> None:
        """Clear cached consensus state so a fresh round can publish again."""
        self._consensus_published = False
        self._consensus_mid_fetched = False
        self._agg_scores_cache = None
        for attr in ("_consensus_commit_block", "_consensus_commit_cid"):
            if hasattr(self, attr):
                setattr(self, attr, None)

    async def _wait_for_commit_propagation(self) -> None:
        """Wait for the most recent commitment to settle a few blocks deep."""
        if not ENABLE_DISTRIBUTED_CONSENSUS:
            return
        blocks_to_wait = max(int(PROPAGATION_BLOCKS_SLEEP or 0), 0)
        if blocks_to_wait <= 0:
            return
        commit_block = getattr(self, "_consensus_commit_block", None)
        if commit_block is None:
            return

        target_block = int(commit_block) + blocks_to_wait
        seconds_per_block = getattr(self.round_manager, "SECONDS_PER_BLOCK", 12)
        wait_logged = False
        consecutive_failures = 0

        while True:
            try:
                current_block = int(self.subtensor.get_current_block())
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                current_block = None

            if current_block is not None:
                if current_block >= target_block:
                    if wait_logged:
                        ColoredLogger.info(
                            f"✅ Commitment propagation window satisfied at block {current_block}",
                            ColoredLogger.CYAN,
                        )
                    return
                remaining = max(target_block - current_block, 0)
            else:
                remaining = max(blocks_to_wait, 0)

            if consecutive_failures >= 3:
                ColoredLogger.warning(
                    "Propagation wait aborted: unable to read current block height",
                    ColoredLogger.YELLOW,
                )
                return

        if not wait_logged:
            ColoredLogger.info(
                f"⏳ Waiting ~{remaining} blocks for commitment propagation",
                ColoredLogger.CYAN,
            )
            wait_logged = True

        await asyncio.sleep(seconds_per_block)

    async def _publish_final_snapshot(self, *, tasks_completed: int, total_tasks: int) -> None:
        """Emit final consensus snapshot once all tasks complete, then finalize weights."""
        ColoredLogger.error("\n" + "=" * 80, ColoredLogger.RED)
        ColoredLogger.error(
            "📤📤📤 ALL TASKS DONE - PUBLISHING TO IPFS NOW 📤📤📤",
            ColoredLogger.RED,
        )
        ColoredLogger.error(
            f"📦 Tasks completed: {tasks_completed}/{total_tasks}",
            ColoredLogger.RED,
        )
        ColoredLogger.error("=" * 80 + "\n", ColoredLogger.RED)

        bt.logging.info("=" * 80)
        bt.logging.info(
            consensus_tag(
                f"All tasks done ({tasks_completed}/{total_tasks}) - Publishing to IPFS now..."
            )
        )
        bt.logging.info("=" * 80)

        self.round_manager.enter_phase(
            RoundPhase.CONSENSUS,
            block=self.block,
            note="All tasks completed; publishing snapshot",
        )

        current_block = self.block
        try:
            round_number = await self.round_manager.calculate_round(current_block)
            st = await self._get_async_subtensor()
            cid = await publish_round_snapshot(
                validator=self,
                st=st,
                round_number=round_number,
                tasks_completed=tasks_completed,
            )
        except Exception as exc:  # noqa: BLE001
            import traceback

            bt.logging.error("=" * 80)
            bt.logging.error(
                f"[CONSENSUS] ❌ IPFS publish failed | Error: {type(exc).__name__}: {exc}"
            )
            bt.logging.error(f"[CONSENSUS] Traceback:\n{traceback.format_exc()}")
            bt.logging.error("=" * 80)
            raise

        self._consensus_published = bool(cid) or self._consensus_published
        if not cid:
            bt.logging.warning(
                "Consensus publish returned no CID; will retry later if window allows."
            )
        else:
            # Record consensus published in report (NEW)
            self._report_consensus_published(ipfs_cid=cid)

        if not self._finalized_this_round:
            bt.logging.info("[CONSENSUS] Finalizing immediately after all-tasks completion publish")
            await self._calculate_final_weights(tasks_completed)
            self._finalized_this_round = True

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
        
        # Finalize and send round report (NEW)
        try:
            current_block = self.subtensor.get_current_block()
            current_epoch = self.round_manager.block_to_epoch(current_block)
            self._finalize_round_report(end_block=current_block, end_epoch=current_epoch)
        except Exception as exc:
            bt.logging.error(f"Failed to finalize round report: {exc}")

    async def _wait_until_next_round_boundary(self) -> None:
        start_block_snapshot = self.subtensor.get_current_block()
        initial_bounds = self.round_manager.get_round_boundaries(
            start_block_snapshot,
            log_debug=False,
        )
        fixed_start_block = int(initial_bounds["round_start_block"])
        fixed_target_block = int(initial_bounds["target_block"])
        fixed_target_epoch = float(initial_bounds["target_epoch"])

        last_log_time = time.time()
        while True:
            try:
                current_block = self.subtensor.get_current_block()
                if current_block >= fixed_target_block:
                    ColoredLogger.success(
                        f"🎯 Next round boundary reached at epoch {fixed_target_epoch}",
                        ColoredLogger.GREEN,
                    )
                    break

                total = max(fixed_target_block - fixed_start_block, 1)
                done = max(current_block - fixed_start_block, 0)
                progress = min(max((done / total) * 100.0, 0.0), 100.0)

                blocks_remaining = max(fixed_target_block - current_block, 0)
                minutes_remaining = (
                    blocks_remaining * self.round_manager.SECONDS_PER_BLOCK
                ) / 60

                if time.time() - last_log_time >= 30:
                    current_epoch = self.round_manager.block_to_epoch(current_block)
                    ColoredLogger.info(
                        (
                            "Waiting — next round boundary (global) — epoch {cur:.3f}/{target:.3f} "
                            "({pct:.2f}%) | ~{mins:.1f}m left — holding until block {target_blk} "
                            "before carrying scores forward"
                        ).format(
                            cur=current_epoch,
                            target=fixed_target_epoch,
                            pct=progress,
                            mins=minutes_remaining,
                            target_blk=fixed_target_block,
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
                
                # Record consensus validators in report (NEW)
                validators_info = agg_meta.get("validators", []) if agg_meta else []
                for val_info in validators_info:
                    self._report_consensus_validator(
                        uid=val_info.get("uid"),
                        hotkey=val_info.get("hotkey", ""),
                        stake_tao=float(val_info.get("stake", 0.0)),
                        ipfs_cid=val_info.get("cid"),
                        miners_reported=len(val_info.get("scores", {})),
                        miner_scores=val_info.get("scores"),
                    )
                
                self._report_consensus_aggregated()
                self._report_set_final_scores(agg)
            else:
                ColoredLogger.warning(
                    "No aggregated scores available; using local averages.",
                    ColoredLogger.YELLOW,
                )

        has_positive = any(float(score) > 0.0 for score in (avg_rewards or {}).values())

        if not has_positive:
            ColoredLogger.warning("🔥 All miners scored <= 0: burning all weights", ColoredLogger.RED)
            zero_vec = np.zeros(self.metagraph.n, dtype=np.float32)
            await self._burn_all(
                avg_rewards=avg_rewards,
                tasks_completed=tasks_completed,
                reason="burn (no winners)",
                weights=zero_vec,
                success_message="✅ Burn complete (no winners)",
            )
            return

        self.round_manager.log_round_summary()

        uids = list(avg_rewards.keys())
        scores_array = np.array([avg_rewards[uid] for uid in uids], dtype=np.float32)
        final_rewards_array = wta_rewards(scores_array)
        final_rewards_dict = {uid: float(reward) for uid, reward in zip(uids, final_rewards_array)}

        try:
            agg_scores = avg_rewards if isinstance(avg_rewards, dict) else None
            active_set = set(self.active_miner_uids or [])
            consensus_meta = getattr(self, "_consensus_last_details", None)
            render_round_summary_table(
                self.round_manager,
                final_rewards_dict,
                self.metagraph,
                to_console=True,
                agg_scores=agg_scores,
                consensus_meta=consensus_meta,
                active_uids=active_set,
            )
        except Exception as exc:
            bt.logging.debug(f"Round summary table failed: {exc}")

        bt.logging.info("🎯 Final weights (WTA)")
        winner_uid = max(final_rewards_dict, key=final_rewards_dict.get) if final_rewards_dict else None
        if winner_uid is not None:
            hotkey = (
                self.metagraph.hotkeys[winner_uid]
                if winner_uid < len(self.metagraph.hotkeys)
                else "<unknown>"
            )
            bt.logging.info(
                f"🏆 Winner uid={winner_uid}, hotkey={hotkey[:10]}..., weight={final_rewards_dict[winner_uid]:.4f}"
            )
        else:
            bt.logging.info("❌ No miners evaluated.")

        winner_uid = max(final_rewards_dict, key=final_rewards_dict.get) if final_rewards_dict else None
        all_uids = list(range(self.metagraph.n))
        wta_full = np.zeros(self.metagraph.n, dtype=np.float32)
        if winner_uid is not None and 0 <= int(winner_uid) < self.metagraph.n:
            wta_full[int(winner_uid)] = 1.0
        bt.logging.info(f"Updating scores for on-chain WTA winner uid={winner_uid}")
        
        # Record winner and weights in report (NEW)
        if winner_uid is not None:
            self._report_set_winner(winner_uid, is_local=False)
        self._report_set_weights(final_rewards_dict)
        
        self.update_scores(rewards=wta_full, uids=all_uids)
        self.set_weights()

        finish_success = await self._finish_iwap_round(
            avg_rewards=avg_rewards,
            final_weights=final_rewards_dict,
            tasks_completed=tasks_completed,
        )
        completion_color = ColoredLogger.GREEN if finish_success else ColoredLogger.YELLOW
        completion_reason = None

        if not finish_success:
            bt.logging.warning(
                "IWAP finish_round failed during final weight submission; continuing without remote acknowledgement."
            )
            completion_reason = "IWAP finish failed"

        self._log_round_completion(
            tasks_completed,
            color=completion_color,
            reason=completion_reason,
        )

    def _log_round_completion(
        self,
        tasks_completed: int,
        *,
        color: str = ColoredLogger.GREEN,
        reason: Optional[str] = None,
    ) -> None:
        round_finished = getattr(self, "_current_round_number", None)

        if round_finished is not None:
            message = f"✅ Round completed: {int(round_finished)}"
        else:
            message = "✅ Round completed"

        if reason:
            message = f"{message} — {reason}"

        ColoredLogger.success(message, color)
        ColoredLogger.info(f"Tasks completed: {tasks_completed}", color)
