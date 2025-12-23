from __future__ import annotations

import asyncio
import copy
import time
from typing import Dict, Optional

import bittensor as bt
import numpy as np

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.utils.log_colors import consensus_tag
from autoppia_web_agents_subnet.validator.config import (
    BURN_AMOUNT_PERCENTAGE,
    BURN_UID,
    ENABLE_DISTRIBUTED_CONSENSUS,
    FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION,
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
        self._agg_meta_cache = None
        # FASE 2/3: Also clear IPFS payload data to avoid stale data between rounds
        for attr in ("_consensus_commit_block", "_consensus_commit_cid", 
                     "_local_avg_rewards_at_publish", "_ipfs_uploaded_payload", 
                     "_ipfs_upload_cid", "_consensus_publish_timestamp"):
            if hasattr(self, attr):
                setattr(self, attr, None)

    async def _publish_final_snapshot(self, *, tasks_completed: int, total_tasks: int) -> None:
        """Emit final consensus snapshot once all tasks complete, then finalize weights."""
        bt.logging.info("=" * 80)
        bt.logging.info("📤 ALL TASKS DONE - PUBLISHING TO IPFS NOW 📤")
        bt.logging.info(f"📦 Tasks completed: {tasks_completed}/{total_tasks}")
        bt.logging.info("=" * 80)

        bt.logging.info("=" * 80)
        bt.logging.info(consensus_tag(f"All tasks done ({tasks_completed}/{total_tasks}) - Publishing to IPFS now..."))
        bt.logging.info("=" * 80)

        self.round_manager.enter_phase(
            RoundPhase.CONSENSUS,
            block=self.block,
            note="All tasks completed; publishing snapshot",
        )

        current_block = self.block
        bt.logging.info(f"[CONSENSUS] Attempting to publish snapshot - current_block: {current_block}")
        
        # 🔍 VALIDATION: Ensure we have a valid block number
        if current_block is None:
            bt.logging.error("=" * 80)
            bt.logging.error("[CONSENSUS] ❌ CRITICAL: self.block is None - cannot get current block from blockchain!")
            bt.logging.error("[CONSENSUS] This usually means:")
            bt.logging.error("[CONSENSUS]   1. Subtensor connection failed")
            bt.logging.error("[CONSENSUS]   2. Network issues")
            bt.logging.error("[CONSENSUS]   3. Blockchain RPC endpoint unavailable")
            bt.logging.error("=" * 80)
            return
        
        try:
            round_number = await self.round_manager.calculate_round(current_block)
            
            # Additional validation: round_number should NEVER be None or < 1
            if round_number is None or round_number < 1:
                bt.logging.error("=" * 80)
                bt.logging.error(f"[CONSENSUS] ❌ Invalid round_number: {round_number} (block: {current_block})")
                bt.logging.error("[CONSENSUS] Attempting to use stored _current_round_number as fallback...")
                # Try to use stored value as fallback
                round_number = getattr(self, "_current_round_number", None)
                if round_number is None or round_number < 1:
                    bt.logging.error("[CONSENSUS] ❌ Cannot publish: no valid round_number available")
                    bt.logging.error("=" * 80)
                    return
                else:
                    bt.logging.warning(f"[CONSENSUS] ⚠️ Using fallback round_number: {round_number}")
                    bt.logging.error("=" * 80)
            else:
                bt.logging.info(f"[CONSENSUS] ✅ Valid round_number: {round_number} (block: {current_block})")
            
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
            bt.logging.error(f"[CONSENSUS] ❌ IPFS publish failed | Error: {type(exc).__name__}: {exc}")
            bt.logging.error(f"[CONSENSUS] Traceback:\n{traceback.format_exc()}")
            bt.logging.error("=" * 80)
            raise

        self._consensus_published = bool(cid) or self._consensus_published
        if not cid:
            bt.logging.warning("Consensus publish returned no CID; will retry later if window allows.")
        else:
            # Record consensus published in report (NEW)
            self._report_consensus_published(ipfs_cid=cid)

        # NO finalizar aquí - esperar hasta FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION (95%) para calcular consenso

    async def _run_settlement_phase(self, *, tasks_completed: int, total_tasks: int) -> None:
        """
        Complete the round:
        - Publish consensus snapshot if pending.
        - Wait until 95% progress (if not already reached) before calculating consensus.
        - Calculate and broadcast final weights.
        - Wait for the next round boundary before exiting to the scheduler loop.
        """
        if ENABLE_DISTRIBUTED_CONSENSUS and (not self._consensus_published):
            await self._publish_final_snapshot(
                tasks_completed=tasks_completed,
                total_tasks=total_tasks,
            )

        # Esperar hasta el 95% antes de calcular consenso (si aún no se alcanzó)
        if not self._finalized_this_round:
            import asyncio
            
            fetch_fraction = float(FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION)
            max_wait_iterations = 1000  # Límite de seguridad (evitar bucle infinito)
            wait_interval_seconds = 2.0  # Verificar progreso cada 2 segundos
            
            iteration = 0
            while iteration < max_wait_iterations:
                # Use subtensor.get_current_block() for accurate block reading (not metagraph.block which can be stale)
                try:
                    current_block_now = self.subtensor.get_current_block()
                except Exception as e:
                    bt.logging.warning(f"[CONSENSUS] Failed to get current block from subtensor: {e}, using metagraph.block as fallback")
                    block_tensor = getattr(self.metagraph, "block", None)
                    current_block_now = int(block_tensor.item()) if block_tensor is not None else 0
                
                bounds_now = self.round_manager.get_round_boundaries(
                    current_block_now,
                    log_debug=False,
                )
                rsb = bounds_now["round_start_block"]
                tb = bounds_now["target_block"]
                progress_now = min(max((current_block_now - rsb) / max(tb - rsb, 1), 0.0), 1.0)
                
                # Calcular si se alcanzó el 95% o el round terminó (progress >= 1.0)
                if progress_now >= fetch_fraction or progress_now >= 1.0:
                    bt.logging.info(
                        f"[CONSENSUS] Progress {progress_now:.2%} >= {fetch_fraction:.0%} - "
                        "Calculating consensus and final weights"
                    )
                    await self._calculate_final_weights(tasks_completed)
                    self._finalized_this_round = True
                    break
                
                # Si aún no se alcanzó, esperar y verificar de nuevo
                if iteration == 0:
                    bt.logging.info(
                        f"[CONSENSUS] Progress {progress_now:.2%} < {fetch_fraction:.0%} - "
                        f"Waiting until {fetch_fraction:.0%} before calculating consensus"
                    )
                
                await asyncio.sleep(wait_interval_seconds)
                iteration += 1
            
            # Si salimos del bucle sin calcular (límite alcanzado), calcular de todas formas
            if not self._finalized_this_round:
                bt.logging.warning(
                    f"[CONSENSUS] Max wait iterations reached - calculating weights anyway"
                )
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

        # Finalize and send round report (NEW) - ALWAYS, even if there are errors
        try:
            current_block = self.subtensor.get_current_block()
            current_epoch = self.round_manager.block_to_epoch(current_block)
            self._finalize_round_report(end_block=current_block, end_epoch=current_epoch, tasks_completed=tasks_completed)
        except Exception as exc:
            bt.logging.error(f"Failed to finalize round report: {exc}")
            # Try to send email anyway with whatever data we have
            try:
                report = self.round_manager.current_round_report
                if report:
                    report.add_error(f"Failed to finalize report: {exc}")
                    report.completed = False
                    from autoppia_web_agents_subnet.validator.reporting.email_sender import send_round_report_email

                    email_sent = send_round_report_email(report, codex_analysis=None)
                    if email_sent:
                        bt.logging.warning("⚠️ Sent partial report via email despite finalization error")
                    else:
                        bt.logging.error("❌ Failed to send partial report email - check SMTP configuration")
                else:
                    bt.logging.error("❌ No round report available to send emergency email")
            except Exception as email_exc:
                bt.logging.error(f"❌ Exception while trying to send emergency email: {email_exc}", exc_info=True)

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
                minutes_remaining = (blocks_remaining * self.round_manager.SECONDS_PER_BLOCK) / 60

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

        final_weights = {uid: float(weights[uid]) for uid in range(len(weights)) if float(weights[uid]) > 0.0}

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
            bt.logging.warning(f"IWAP finish_round failed during burn-all ({reason}); continuing without remote acknowledgement.")
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
        bt.logging.info(f"[CONSENSUS] Distributed consensus: {str(ENABLE_DISTRIBUTED_CONSENSUS).lower()}")
        bt.logging.info("=" * 80)

        avg_rewards: Dict[int, float] = {}
        burn_reason: Optional[str] = None

        if not self.active_miner_uids:
            ColoredLogger.error("🔥 No active miners: burning all weights", ColoredLogger.RED)
            burn_reason = "burn (no active miners)"
        else:
            avg_rewards = self.round_manager.get_average_rewards()
            if BURN_AMOUNT_PERCENTAGE >= 1.0:
                ColoredLogger.warning(
                    f"🔥 BURN_AMOUNT_PERCENTAGE={BURN_AMOUNT_PERCENTAGE:.2f} (≥1.0): forcing full burn and skipping consensus",
                    ColoredLogger.RED,
                )
                burn_reason = "burn (forced by BURN_AMOUNT_PERCENTAGE=1.0)"

        if burn_reason:
            await self._burn_all(
                avg_rewards=avg_rewards,
                tasks_completed=tasks_completed,
                reason=burn_reason,
            )
            return

        # NOTE: Removed duplicate re-fetch here - we only do the final re-fetch before calculating weights
        # This simplifies the code and avoids duplicate IPFS/chain calls
        if ENABLE_DISTRIBUTED_CONSENSUS:
            # Use cached consensus scores if available, otherwise will be fetched in final re-fetch
            # cached_consensus_scores: Dict[miner_uid -> stake_weighted_avg_reward] from previous fetch
            cached_consensus_scores = self._agg_scores_cache or {}
            # cached_consensus_metadata: Dict with validators info, participation stats, downloaded payloads
            cached_consensus_metadata = self._agg_meta_cache
            
            if cached_consensus_scores:
                ColoredLogger.info(
                    f"🤝 Using cached aggregated consensus scores from commitments ({len(cached_consensus_scores)} miners)",
                    ColoredLogger.CYAN,
                )
                avg_rewards = cached_consensus_scores
                self._consensus_last_details = cached_consensus_metadata or {}

                # Record consensus validators in report (NEW)
                validators_info = cached_consensus_metadata.get("validators", []) if cached_consensus_metadata else []
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
                self._report_set_final_scores(cached_consensus_scores)
            else:
                # No cache available - will use local scores or fetch in final re-fetch
                ColoredLogger.warning(
                    "⚠️ No cached consensus scores available, will use local scores or fetch in final re-fetch",
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

        # Re-fetch final justo antes de calcular pesos WTA para asegurar todos los commits
        # CRITICAL: After this re-fetch, we create an immutable snapshot that will be used
        # for BOTH weight calculation AND IWAP submission to guarantee consistency
        if ENABLE_DISTRIBUTED_CONSENSUS:
            # Use subtensor.get_current_block() for accurate block reading (not metagraph.block which can be stale)
            try:
                current_block_final = self.subtensor.get_current_block()
            except Exception as e:
                bt.logging.warning(consensus_tag(f"Failed to get current block from subtensor: {e}, using metagraph.block as fallback"))
                block_tensor = getattr(self.metagraph, "block", None)
                current_block_final = int(block_tensor.item()) if block_tensor is not None else 0
            
            bounds_final = self.round_manager.get_round_boundaries(
                current_block_final,
                log_debug=False,
            )
            rsb_final = bounds_final["round_start_block"]
            tb_final = bounds_final["target_block"]
            progress_final = min(max((current_block_final - rsb_final) / max(tb_final - rsb_final, 1), 0.0), 1.0)
            
            # Si progreso >= 95%, hacer un último re-fetch antes de calcular pesos
            # Si progreso < 95% pero no hay cache, también hacer re-fetch (caso edge: llamado antes de tiempo)
            should_do_final_refetch = (
                progress_final >= float(FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION) or
                (not self._agg_scores_cache and progress_final > 0.5)  # Si no hay cache y ya pasamos 50%, hacer fetch
            )
            
            if should_do_final_refetch:
                boundaries = self.round_manager.get_current_boundaries()
                if progress_final >= float(FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION):
                    bt.logging.info(consensus_tag("🔄 Final re-fetch before calculating weights (95% reached)"))
                else:
                    bt.logging.info(consensus_tag(f"🔄 Re-fetch before calculating weights (progress {progress_final:.1%}, no cache available)"))
                
                st = await self._get_async_subtensor()
                # final_aggregated_consensus_scores: Dict[miner_uid -> stake_weighted_avg_reward] from all validators
                # final_aggregated_consensus_metadata: Dict with validators info, participation stats, downloaded payloads
                final_aggregated_consensus_scores, final_aggregated_consensus_metadata = await aggregate_scores_from_commitments(
                    validator=self,
                    st=st,
                    start_block=boundaries["round_start_block"],
                    target_block=boundaries["target_block"],
                )
                if final_aggregated_consensus_scores:
                    self._agg_scores_cache = final_aggregated_consensus_scores
                    self._agg_meta_cache = final_aggregated_consensus_metadata
                    avg_rewards = final_aggregated_consensus_scores
                    self._consensus_last_details = final_aggregated_consensus_metadata or {}
                    bt.logging.info(consensus_tag(f"✅ Updated consensus with {len(final_aggregated_consensus_scores)} miners from final fetch"))
                else:
                    bt.logging.warning(consensus_tag("⚠️ Final re-fetch returned no consensus data, will use local scores"))
                    
                    # Log quorum participation report
                    if final_aggregated_consensus_metadata and isinstance(final_aggregated_consensus_metadata, dict):
                        downloaded_payloads = final_aggregated_consensus_metadata.get("downloaded_payloads", [])
                        validators_participated = len(downloaded_payloads)
                        
                        # Get active validators count
                        active_validators_count = 0
                        try:
                            validator_permit = getattr(self.metagraph, "validator_permit", None)
                            if validator_permit is not None:
                                active_validators_count = int(validator_permit.sum().item())
                        except Exception:
                            pass
                        
                        bt.logging.info("=" * 80)
                        bt.logging.info(consensus_tag("📊 CONSENSUS PARTICIPATION REPORT (Final Fetch)"))
                        bt.logging.info(consensus_tag(f"Validators active (metagraph): {active_validators_count}"))
                        bt.logging.info(consensus_tag(f"Validators participated: {validators_participated}"))
                        
                        if active_validators_count > 0:
                            participation_rate = (validators_participated / active_validators_count) * 100
                            bt.logging.info(consensus_tag(f"Participation rate: {participation_rate:.1f}%"))
                            
                            if validators_participated < active_validators_count:
                                missing = active_validators_count - validators_participated
                                bt.logging.warning(
                                    consensus_tag(
                                        f"⚠️ QUORUM PARTIAL: {missing} validator(s) missing from consensus"
                                    )
                                )
                        bt.logging.info("=" * 80)

        # Create immutable snapshot of consensus data to ensure IWAP receives EXACTLY
        # the same data used for weight calculation (prevents race conditions)
        if ENABLE_DISTRIBUTED_CONSENSUS and isinstance(avg_rewards, dict):
            final_consensus_scores = copy.deepcopy(avg_rewards)
        else:
            # If not distributed consensus or not a dict, use as-is (but ensure it's a dict)
            final_consensus_scores = avg_rewards if isinstance(avg_rewards, dict) else {}
        
        final_consensus_meta = copy.deepcopy(self._agg_meta_cache) if ENABLE_DISTRIBUTED_CONSENSUS and self._agg_meta_cache else self._agg_meta_cache
        
        # Use the immutable snapshot for weight calculation
        if not final_consensus_scores:
            bt.logging.warning(consensus_tag("⚠️ No consensus scores available for weight calculation"))
            final_consensus_scores = {}
        
        uids = list(final_consensus_scores.keys())
        scores_array = np.array([final_consensus_scores[uid] for uid in uids], dtype=np.float32)
        final_rewards_array = wta_rewards(scores_array)
        final_rewards_dict = {uid: float(reward) for uid, reward in zip(uids, final_rewards_array)}

        try:
            agg_scores = final_consensus_scores if isinstance(final_consensus_scores, dict) else None
            active_set = set(self.active_miner_uids or [])
            consensus_meta = final_consensus_meta
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
            hotkey = self.metagraph.hotkeys[winner_uid] if winner_uid < len(self.metagraph.hotkeys) else "<unknown>"
            bt.logging.info(f"🏆 Winner uid={winner_uid}, hotkey={hotkey[:10]}..., weight={final_rewards_dict[winner_uid]:.4f}")
        else:
            bt.logging.info("❌ No miners evaluated.")

        winner_uid = max(final_rewards_dict, key=final_rewards_dict.get) if final_rewards_dict else None
        all_uids = list(range(self.metagraph.n))
        wta_full = np.zeros(self.metagraph.n, dtype=np.float32)

        if winner_uid is not None and 0 <= int(winner_uid) < self.metagraph.n:
            # Validar y clampar el porcentaje de burn
            burn_percentage = float(max(0.0, min(1.0, BURN_AMOUNT_PERCENTAGE)))
            winner_percentage = 1.0 - burn_percentage

            burn_idx = int(BURN_UID) if 0 <= int(BURN_UID) < self.metagraph.n else min(5, self.metagraph.n - 1)

            # Asignar pesos según el split configurado
            wta_full[int(winner_uid)] = winner_percentage
            if burn_percentage > 0.0:
                wta_full[burn_idx] = burn_percentage

            bt.logging.info("=" * 80)
            bt.logging.info("🎯 WEIGHT DISTRIBUTION (on-chain)")
            bt.logging.info(f"   Winner UID {winner_uid}: {winner_percentage:.1%} ({winner_percentage:.6f})")
            bt.logging.info(f"   Burn UID {burn_idx}: {burn_percentage:.1%} ({burn_percentage:.6f})")
            bt.logging.info(f"   Total: {winner_percentage + burn_percentage:.6f}")
            bt.logging.info(f"   Config: BURN_AMOUNT_PERCENTAGE={BURN_AMOUNT_PERCENTAGE}")
            bt.logging.info("=" * 80)
        else:
            bt.logging.warning("❌ No valid winner found, weights remain zero")

        # Record winner and weights in report (NEW)
        if winner_uid is not None:
            self._report_set_winner(winner_uid, is_local=False)
        # Report the actual on-chain distribution (after burn applied)
        weights_for_finish = {
            idx: float(val) for idx, val in enumerate(wta_full) if float(val) > 0.0
        }
        self._report_set_weights(weights_for_finish)

        self.update_scores(rewards=wta_full, uids=all_uids)
        self.set_weights()

        # Use the SAME immutable snapshot for IWAP submission to guarantee consistency
        # between weight calculation and IWAP data
        finish_success = await self._finish_iwap_round(
            avg_rewards=final_consensus_scores,
            final_weights=weights_for_finish,
            tasks_completed=tasks_completed,
        )
        completion_color = ColoredLogger.GREEN if finish_success else ColoredLogger.YELLOW
        completion_reason = None

        if not finish_success:
            bt.logging.warning("IWAP finish_round failed during final weight submission; continuing without remote acknowledgement.")
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
