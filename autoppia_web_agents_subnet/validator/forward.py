# autoppia_web_agents_subnet/validator/forward.py
from __future__ import annotations

import asyncio
import time
from typing import Dict, List

import bittensor as bt
import numpy as np

from autoppia_web_agents_subnet.config import (
    TIMEOUT,
    EVAL_SCORE_WEIGHT,
    TIME_WEIGHT,
    ROUND_SIZE_EPOCHS,
    AVG_TASK_DURATION_SECONDS,
    SAFETY_BUFFER_EPOCHS,
    PROMPTS_PER_USECASE,
    PRE_GENERATED_TASKS,
)
from autoppia_web_agents_subnet.validator.tasks import get_task_plan
from autoppia_web_agents_subnet.validator.communication import send_feedback_synapse_to_miners
from autoppia_web_agents_subnet.synapses import StartRoundSynapse
from autoppia_web_agents_subnet.validator.rewards import reduce_rewards_to_averages, wta_rewards
from autoppia_web_agents_subnet.validator.models import TaskPlan, ScoredTask
from autoppia_web_agents_subnet.validator.leaderboard import Phase
from autoppia_web_agents_subnet.utils.random import get_random_uids
from autoppia_web_agents_subnet.validator.round_calculator import RoundCalculator


class ForwardHandler:
    """
    Handles the forward loop logic for the validator.

    This forward spans the ENTIRE round (~24h):
    1. Pre-generates all tasks at the beginning
    2. Dynamic loop: sends tasks one by one based on time remaining
    3. Accumulates scores from all miners
    4. When finished, WAIT until target epoch
    5. Calculates averages, applies WTA, sets weights
    """

    def __init__(self, validator):
        self.validator = validator

        # ⭐ Round calculator: dynamic task system
        self.round_calculator = RoundCalculator(
            round_size_epochs=ROUND_SIZE_EPOCHS,
            avg_task_duration_seconds=AVG_TASK_DURATION_SECONDS,
            safety_buffer_epochs=SAFETY_BUFFER_EPOCHS,
        )

    async def execute_forward(self) -> None:
        """
        Execute the main forward loop (= 1 round completo).
        Dura aproximadamente ROUND_SIZE_EPOCHS epochs (~24h por defecto).
        """
        try:
            self.validator.forward_count += 1
            round_id = f"Round-{self.validator.forward_count}"

            # ═══════════════════════════════════════════════════════
            # INICIO DEL ROUND
            # ═══════════════════════════════════════════════════════
            start_block = self.validator.block
            boundaries = self.round_calculator.get_round_boundaries(start_block)

            bt.logging.warning("=" * 80)
            bt.logging.warning(f"🚀 STARTING ROUND #{self.validator.forward_count}")
            bt.logging.warning(f"   Round ID: {round_id}")
            bt.logging.warning(f"   Start epoch: {boundaries['round_start_epoch']} (block {start_block})")
            bt.logging.warning(f"   Target epoch: {boundaries['target_epoch']} (block {boundaries['target_block']})")
            bt.logging.warning(f"   Validator version: {self.validator.version}")
            bt.logging.warning("=" * 80)

            t0 = time.time()

            # Log evento: round start
            self.validator.lb.log_event_simple(
                validator_uid=int(self.validator.uid),
                round_id=round_id,
                phase=Phase.ROUND_START,
                message=f"Round starting at epoch {boundaries['round_start_epoch']}",
                extra={
                    "version": self.validator.version,
                    "start_epoch": boundaries['round_start_epoch'],
                    "target_epoch": boundaries['target_epoch'],
                }
            )

            # ⭐ Log dynamic system configuration
            self.round_calculator.log_calculation_summary()

            # ═══════════════════════════════════════════════════════
            # SETUP: Full miners roster
            # ═══════════════════════════════════════════════════════
            full_uid_array = get_random_uids(self.validator, k=self.validator.metagraph.n.item())
            full_uids: List[int] = full_uid_array.tolist()
            full_axons = [self.validator.metagraph.axons[uid] for uid in full_uids]
            n_miners = len(full_uids)

            if not full_uids:
                bt.logging.warning("⚠️ No miners in metagraph; aborting round.")
                return

            bt.logging.info(f"📋 Full miner roster: {n_miners} miners")

            # Inicializar acumuladores para TODO el round
            rewards_sum = np.zeros(n_miners, dtype=np.float32)
            counts = np.zeros(n_miners, dtype=np.int32)

            # ═══════════════════════════════════════════════════════
            # PHASE 0: Initial notify - Descubrir miners activos
            # ═══════════════════════════════════════════════════════
            self.validator.lb.log_event_simple(
                validator_uid=int(self.validator.uid),
                round_id=round_id,
                phase=Phase.INITIALIZING,
                message="Discovering active miners"
            )

            responders: Dict[int, StartRoundSynapse] = {}
            try:
                responders = await self.validator.notify_start_round(
                    miner_uids=full_uids,
                    axons=full_axons,
                    round_id=round_id,
                    note="Round starting - dynamic task system",
                    timeout=12
                )
            except Exception as e:
                bt.logging.warning(f"notify_start_round failed: {e}")

            active_mask = [uid in responders for uid in full_uids]
            active_uids = [uid for uid, ok in zip(full_uids, active_mask) if ok]
            active_axons = [ax for ax, ok in zip(full_axons, active_mask) if ok]

            if not active_uids:
                bt.logging.error("❌ No active miners responded; burning all and aborting.")
                self.validator.burn_all(uids=full_uids)
                self.validator.lb.log_event_simple(
                    validator_uid=int(self.validator.uid),
                    round_id=round_id,
                    phase=Phase.ERROR,
                    message="No active miners; burn_all executed"
                )
                return

            bt.logging.info(f"✅ Active miners: {len(active_uids)}/{n_miners}")

            # Metadata de miners activos
            active_hotkeys = [self.validator.metagraph.hotkeys[uid] for uid in active_uids]
            active_coldkeys = [self.validator.metagraph.coldkeys[uid] for uid in active_uids]

            # ═══════════════════════════════════════════════════════
            # PRE-GENERATION: Generar todas las tasks al inicio
            # ═══════════════════════════════════════════════════════
            bt.logging.warning("")
            bt.logging.warning("🔄 PRE-GENERATING TASKS")
            bt.logging.warning("=" * 80)

            pre_generation_start = time.time()
            all_tasks = []

            # Generar todas las tasks en batches
            tasks_generated = 0
            while tasks_generated < PRE_GENERATED_TASKS:
                batch_start = time.time()

                # Generar un batch de tasks
                task_plan: TaskPlan = await get_task_plan(prompts_per_use_case=PROMPTS_PER_USECASE)

                # Extraer tasks individuales del plan
                for project_task_batch in task_plan.batches:
                    for task in project_task_batch.tasks:
                        if tasks_generated >= PRE_GENERATED_TASKS:
                            break
                        all_tasks.append((project_task_batch.project, task))
                        tasks_generated += 1

                batch_elapsed = time.time() - batch_start
                bt.logging.info(f"   Generated batch: {len(task_plan.batches)} projects in {batch_elapsed:.1f}s (total: {tasks_generated}/{PRE_GENERATED_TASKS})")

            pre_generation_elapsed = time.time() - pre_generation_start
            bt.logging.warning(f"✅ Pre-generation complete: {len(all_tasks)} tasks in {pre_generation_elapsed:.1f}s")
            bt.logging.warning("=" * 80)

            # ═══════════════════════════════════════════════════════
            # MAIN LOOP: Dynamic system with pre-generated tasks
            # ═══════════════════════════════════════════════════════
            tasks_completed = 0
            all_scored_tasks: List[ScoredTask] = []
            task_index = 0

            bt.logging.warning(f"🎯 Starting dynamic task execution with {len(all_tasks)} pre-generated tasks")

            # Dynamic loop: consume pre-generated tasks and check AFTER evaluation
            while task_index < len(all_tasks):
                iteration_start = time.time()

                # Progress logging
                current_block = self.validator.block
                current_epoch = self.round_calculator.block_to_epoch(current_block)
                wait_info = self.round_calculator.get_wait_info(current_block, start_block)

                bt.logging.info("")
                bt.logging.info("━" * 80)
                bt.logging.info(
                    f"📍 TASK {task_index + 1}/{len(all_tasks)} | "
                    f"Epoch {current_epoch}/{boundaries['target_epoch']} | "
                    f"Time remaining: {wait_info['minutes_remaining']:.0f} min"
                )
                bt.logging.info("━" * 80)

                # ─────────────────────────────────────────────────
                # 1. Coger siguiente task pre-generada
                # ─────────────────────────────────────────────────
                project, task = all_tasks[task_index]

                # Crear TaskPlan con una sola task
                from autoppia_web_agents_subnet.validator.models import ProjectTaskBatch
                single_task_batch = ProjectTaskBatch(project=project, tasks=[task])
                task_plan = TaskPlan(batches=[single_task_batch])

                self.validator.lb.log_event_simple(
                    validator_uid=int(self.validator.uid),
                    round_id=round_id,
                    phase=Phase.GENERATING_TASKS,
                    message=f"Processing pre-generated task {task_index + 1}/{len(all_tasks)}"
                )

                # ─────────────────────────────────────────────────
                # 2. Send task to miners
                # ─────────────────────────────────────────────────
                self.validator.lb.log_event_simple(
                    validator_uid=int(self.validator.uid),
                    round_id=round_id,
                    phase=Phase.SENDING_TASKS,
                    message=f"Sending task {task_index + 1} to {len(active_uids)} miners"
                )

                # Enviar solo esta task
                per_task_results = await self.validator.send_tasks(
                    task_plan=task_plan,
                    miner_uids=active_uids,
                    miner_axons=active_axons,
                    max_tasks=1,  # Solo 1 task
                    timeout=TIMEOUT,
                )

                # ─────────────────────────────────────────────────
                # 3. Evaluate task
                # ─────────────────────────────────────────────────
                self.validator.lb.log_event_simple(
                    validator_uid=int(self.validator.uid),
                    round_id=round_id,
                    phase=Phase.EVALUATING_TASKS,
                    message=f"Evaluating task {task_index + 1}"
                )

                eval_outputs = await self.validator.evaluate_tasks(
                    per_task_results=per_task_results,
                    n_miners=len(active_uids)
                )

                # ─────────────────────────────────────────────────
                # 4. Calculate rewards for this batch
                # ─────────────────────────────────────────────────
                rewards_active, scored_tasks = await self.validator.calculate_rewards(
                    per_task_results=per_task_results,
                    eval_outputs=eval_outputs,
                    miner_uids=active_uids,
                    eval_score_weight=EVAL_SCORE_WEIGHT,
                    time_weight=TIME_WEIGHT,
                )

                # ⭐ ACUMULAR rewards (alinear active_uids → full_uids)
                uid_to_idx_active = {uid: i for i, uid in enumerate(active_uids)}
                for i_full, uid in enumerate(full_uids):
                    idx_active = uid_to_idx_active.get(uid)
                    if idx_active is not None:
                        rewards_sum[i_full] += rewards_active[idx_active]
                        counts[i_full] += 1

                all_scored_tasks.extend(scored_tasks)

                # ─────────────────────────────────────────────────
                # 5. Send feedback to miners (opcional)
                # ─────────────────────────────────────────────────
                try:
                    await self.validator.send_feedback(
                        scored_tasks=scored_tasks,
                        miner_uids=active_uids,
                        miner_axons=active_axons,
                    )
                except Exception as e:
                    bt.logging.warning(f"Feedback failed: {e}")

                # Update counters
                tasks_completed += 1
                task_index += 1

                iteration_elapsed = time.time() - iteration_start
                bt.logging.info(f"✅ Completed task {task_index}/{len(all_tasks)} in {iteration_elapsed:.1f}s")

                # Log top 3 miners every 10 tasks
                if tasks_completed % 10 == 0:
                    avg_so_far = reduce_rewards_to_averages(rewards_sum, counts)
                    top_3 = np.argsort(avg_so_far)[-3:][::-1]
                    bt.logging.info(f"   Current top 3: {[(full_uids[i], f'{avg_so_far[i]:.3f}') for i in top_3]}")

                # ⚡ DYNAMIC CHECK: Is there time for another task AFTER evaluation?
                current_block = self.validator.block
                if not self.round_calculator.should_send_next_task(current_block, start_block):
                    current_epoch = self.round_calculator.block_to_epoch(current_block)
                    wait_info = self.round_calculator.get_wait_info(current_block, start_block)
                    bt.logging.warning("")
                    bt.logging.warning("🛑 STOPPING TASK EXECUTION")
                    bt.logging.warning(f"   Reason: Insufficient time remaining for another task")
                    bt.logging.warning(f"   Current epoch: {current_epoch}")
                    bt.logging.warning(f"   Time remaining: {wait_info['seconds_remaining']}s")
                    bt.logging.warning(f"   Safety buffer: {self.round_calculator.safety_buffer_epochs} epochs")
                    bt.logging.warning(f"   Tasks completed: {tasks_completed}/{len(all_tasks)}")
                    break

            # ═══════════════════════════════════════════════════════
            # WAIT PHASE: Esperar al target epoch
            # ═══════════════════════════════════════════════════════
            bt.logging.warning("")
            bt.logging.warning("=" * 80)
            bt.logging.warning(f"✅ ALL {tasks_completed}/{len(all_tasks)} TASKS COMPLETED!")
            bt.logging.warning("=" * 80)

            wait_start = time.time()

            while True:
                current_block = self.validator.block
                wait_info = self.round_calculator.get_wait_info(current_block, start_block)

                if wait_info["reached_target"]:
                    bt.logging.warning(
                        f"🎯 Target epoch {wait_info['target_epoch']} REACHED! "
                        f"(current: {wait_info['current_epoch']})"
                    )
                    break

                bt.logging.info(
                    f"⏳ Waiting for target epoch... "
                    f"Current: {wait_info['current_epoch']}, "
                    f"Target: {wait_info['target_epoch']}, "
                    f"Remaining: {wait_info['epochs_remaining']} epochs "
                    f"(~{wait_info['minutes_remaining']:.0f} min)"
                )

                # Esperar 2 minutos y volver a checkear
                await asyncio.sleep(120)

            wait_elapsed = time.time() - wait_start
            bt.logging.info(f"   Waited {wait_elapsed/60:.1f} minutes for target epoch")

            # ═══════════════════════════════════════════════════════
            # FINALIZATION: Promedios, WTA, SET WEIGHTS
            # ═══════════════════════════════════════════════════════
            bt.logging.warning("")
            bt.logging.warning("=" * 80)
            bt.logging.warning("🏁 FINALIZING ROUND - CALCULATING WINNER & SETTING WEIGHTS")
            bt.logging.warning("=" * 80)

            self.validator.lb.log_event_simple(
                validator_uid=int(self.validator.uid),
                round_id=round_id,
                phase=Phase.UPDATING_WEIGHTS,
                message="Finalizing round: calculating averages and applying WTA"
            )

            # Calcular promedios del round completo
            avg_rewards = reduce_rewards_to_averages(rewards_sum, counts)

            # Log top 10 miners
            top_10_indices = np.argsort(avg_rewards)[-10:][::-1]
            bt.logging.info("")
            bt.logging.info("📊 TOP 10 MINERS (by average score):")
            bt.logging.info("-" * 80)
            for rank, idx in enumerate(top_10_indices, 1):
                uid = full_uids[idx]
                score = avg_rewards[idx]
                task_count = counts[idx]
                bt.logging.info(f"   {rank:2d}. UID {uid:3d}: {score:.4f} ({task_count} tasks evaluated)")
            bt.logging.info("-" * 80)

            # ⚡ Aplicar Winner Takes All
            rewards_wta = wta_rewards(avg_rewards)
            winner_idx = int(np.argmax(rewards_wta))
            winner_uid = full_uids[winner_idx]
            winner_score = avg_rewards[winner_idx]

            bt.logging.warning("")
            bt.logging.warning("🏆" * 40)
            bt.logging.warning(
                f"   WINNER: UID {winner_uid} "
                f"(avg score: {winner_score:.4f}, tasks: {counts[winner_idx]})"
            )
            bt.logging.warning("🏆" * 40)

            # ⚡ SET WEIGHTS ON-CHAIN
            self.validator.update_scores(rewards_wta, full_uids)
            self.validator.set_weights()
            self.validator.last_rewards = avg_rewards

            elapsed_total = time.time() - t0
            bt.logging.warning("")
            bt.logging.warning(
                f"✅ WEIGHTS SET ON-CHAIN! "
                f"Round duration: {elapsed_total/3600:.2f}h"
            )

            # ═══════════════════════════════════════════════════════
            # POST RESULTS al leaderboard
            # ═══════════════════════════════════════════════════════
            self.validator._build_and_post_round_results(
                round_id=round_id,
                started_at=t0,
                full_uids=full_uids,
                active_uids=active_uids,
                active_hotkeys=active_hotkeys,
                active_coldkeys=active_coldkeys,
                scored_tasks=all_scored_tasks[:50],  # Solo las primeras 50 para no saturar
                rewards_full_avg=avg_rewards,
                rewards_full_wta=rewards_wta,
            )

            # Log evento: round end
            self.validator.lb.log_event_simple(
                validator_uid=int(self.validator.uid),
                round_id=round_id,
                phase=Phase.ROUND_END,
                message=f"Round finished successfully in {elapsed_total/3600:.2f}h",
                extra={
                    "elapsed_hours": round(elapsed_total / 3600, 2),
                    "tasks_completed": tasks_completed,
                    "winner_uid": int(winner_uid),
                    "winner_score": float(winner_score),
                    "active_miners": len(active_uids),
                    "total_miners": n_miners,
                }
            )

            self.validator.lb.log_event_simple(
                validator_uid=int(self.validator.uid),
                round_id=round_id,
                phase=Phase.DONE,
                message="Round complete - ready for next round"
            )

            bt.logging.warning("=" * 80)
            bt.logging.info("")
            bt.logging.info(f"🔄 Round complete. Next round will start at next epoch boundary.")
            bt.logging.info("")

        except Exception as err:
            bt.logging.error(f"❌ Error in forward: {err}")
            import traceback
            bt.logging.error(traceback.format_exc())

            try:
                round_id = f"Round-{self.validator.forward_count}"
                self.validator.lb.log_event_simple(
                    validator_uid=int(self.validator.uid),
                    round_id=round_id,
                    phase=Phase.ERROR,
                    message=f"Round crashed: {err}"
                )
            except Exception:
                pass
