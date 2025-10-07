# file: autoppia_web_agents_subnet/validator/forward.py
"""
Forward handler for validator.
Handles the complete forward loop logic for the round-based system.
"""
from __future__ import annotations

import asyncio
import time
from typing import List, Tuple

import bittensor as bt

from autoppia_web_agents_subnet.config import (
    ROUND_SIZE_EPOCHS,
    AVG_TASK_DURATION_SECONDS,
    SAFETY_BUFFER_EPOCHS,
    PROMPTS_PER_USECASE,
    PRE_GENERATED_TASKS,
)
from autoppia_web_agents_subnet.validator.tasks import get_task_plan, collect_task_solutions_and_execution_times
from autoppia_web_agents_subnet.validator.synapse_handlers import send_feedback_synapse_to_miners
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

        # ⭐ Accumulated scores for the entire round
        self.round_scores = {}  # {miner_uid: [score1, score2, ...]}
        self.round_times = {}   # {miner_uid: [time1, time2, ...]}

    async def execute_forward(self):
        """
        Execute the complete forward loop for the round.
        """
        bt.logging.warning("")
        bt.logging.warning("🚀 STARTING ROUND-BASED FORWARD")
        bt.logging.warning("=" * 80)

        # Get current block and calculate round boundaries
        current_block = self.validator.metagraph.block.item()
        boundaries = self.round_calculator.get_round_boundaries(current_block)

        bt.logging.info(f"Round boundaries: start={boundaries['round_start_epoch']}, target={boundaries['target_epoch']}")

        # Log configuration summary
        self.round_calculator.log_calculation_summary()

        # ═══════════════════════════════════════════════════════
        # PRE-GENERATION: Generate all tasks at the beginning
        # ═══════════════════════════════════════════════════════
        bt.logging.warning("")
        bt.logging.warning("🔄 PRE-GENERATING TASKS")
        bt.logging.warning("=" * 80)

        pre_generation_start = time.time()
        all_tasks = []

        # Generate all tasks in batches
        tasks_generated = 0
        while tasks_generated < PRE_GENERATED_TASKS:
            batch_start = time.time()

            # Generate a batch of tasks
            task_plan: TaskPlan = await get_task_plan(prompts_per_use_case=PROMPTS_PER_USECASE)

            # Extract individual tasks from the plan
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
        # DYNAMIC LOOP: Execute tasks one by one based on time
        # ═══════════════════════════════════════════════════════
        bt.logging.warning("")
        bt.logging.warning("🔄 STARTING DYNAMIC TASK EXECUTION")
        bt.logging.warning("=" * 80)

        start_block = current_block
        task_index = 0
        tasks_completed = 0

        # Dynamic loop: consume pre-generated tasks and check AFTER evaluating
        while task_index < len(all_tasks):
            current_block = self.validator.metagraph.block.item()
            current_epoch = self.round_calculator.block_to_epoch(current_block)
            boundaries = self.round_calculator.get_round_boundaries(start_block)
            wait_info = self.round_calculator.get_wait_info(current_block, start_block)

            bt.logging.info(
                f"📍 TASK {task_index + 1}/{len(all_tasks)} | "
                f"Epoch {current_epoch:.2f}/{boundaries['target_epoch']} | "
                f"Time remaining: {wait_info['minutes_remaining']:.1f} min"
            )

            # 1. Get next pre-generated task
            project, task = all_tasks[task_index]
            # Create TaskPlan with a single task
            from autoppia_web_agents_subnet.validator.models import ProjectTaskBatch
            single_task_batch = ProjectTaskBatch(project=project, tasks=[task])
            task_plan = TaskPlan(batches=[single_task_batch])

            # 2. Send task to miners
            try:
                # Get active miners
                active_uids = get_random_uids(
                    self.validator.metagraph,
                    k=min(5, len(self.validator.metagraph.uids)),
                )
                active_axons = [self.validator.metagraph.axons[uid] for uid in active_uids]

                # Send task
                task_synapse = StartRoundSynapse(
                    version=self.validator.version,
                    round_id=f"round_{boundaries['round_start_epoch']}",
                    validator_id=str(self.validator.uid),
                    total_prompts=1,
                    prompts_per_use_case=PROMPTS_PER_USECASE,
                )

                responses = await self.validator.dendrite(
                    axons=active_axons,
                    synapse=task_synapse,
                    deserialize=True,
                    timeout=60,
                )

                # 3. Process responses and calculate rewards
                task_solutions, execution_times = collect_task_solutions_and_execution_times(
                    task=task,
                    responses=responses,
                    miner_uids=active_uids,
                )

                # 4. Evaluate task solutions
                from autoppia_web_agents_subnet.validator.eval import evaluate_task_solutions
                eval_results = evaluate_task_solutions(task, task_solutions)

                # 5. Calculate rewards
                rewards = [result.score for result in eval_results]

                # 6. Accumulate scores for the round
                for i, uid in enumerate(active_uids):
                    if uid not in self.round_scores:
                        self.round_scores[uid] = []
                        self.round_times[uid] = []
                    self.round_scores[uid].append(rewards[i])
                    self.round_times[uid].append(execution_times[i])

                # 7. Send feedback to miners
                try:
                    await send_feedback_synapse_to_miners(
                        validator=self.validator,
                        miner_axons=active_axons,
                        miner_uids=active_uids,
                        task=task,
                        rewards=rewards,
                        execution_times=execution_times,
                        task_solutions=task_solutions,
                        test_results_matrices=[[result.test_results] for result in eval_results],
                        evaluation_results=[result.evaluation_result for result in eval_results],
                    )
                except Exception as e:
                    bt.logging.warning(f"Feedback failed: {e}")

                # Update counters
                tasks_completed += 1
                task_index += 1

                bt.logging.info(f"✅ Task {task_index} completed. Total: {tasks_completed}")

            except Exception as e:
                bt.logging.error(f"Task execution failed: {e}")
                task_index += 1
                continue

            # 8. Dynamic check: should we send another task?
            if not self.round_calculator.should_send_next_task(current_block, start_block):
                bt.logging.warning("")
                bt.logging.warning("🛑 STOPPING TASK EXECUTION - SAFETY BUFFER REACHED")
                bt.logging.warning(f"   Reason: Insufficient time remaining for another task")
                bt.logging.warning(f"   Current epoch: {current_epoch:.2f}")
                bt.logging.warning(f"   Time remaining: {wait_info['seconds_remaining']:.0f}s")
                bt.logging.warning(f"   Safety buffer: {SAFETY_BUFFER_EPOCHS} epochs")
                bt.logging.warning(f"   Tasks completed: {tasks_completed}/{len(all_tasks)}")
                bt.logging.warning(f"   ⏳ Now waiting for target epoch to set weights...")
                break

        # ═══════════════════════════════════════════════════════
        # WAIT FOR TARGET EPOCH: Wait until the round ends
        # ═══════════════════════════════════════════════════════
        if tasks_completed < len(all_tasks):
            await self._wait_for_target_epoch(start_block)

        # ═══════════════════════════════════════════════════════
        # FINAL WEIGHTS: Calculate averages, apply WTA, set weights
        # ═══════════════════════════════════════════════════════
        bt.logging.warning("")
        bt.logging.warning("🏁 CALCULATING FINAL WEIGHTS")
        bt.logging.warning("=" * 80)

        # Calculate average scores for each miner
        avg_scores = {}
        for uid, scores in self.round_scores.items():
            if scores:
                avg_scores[uid] = sum(scores) / len(scores)
            else:
                avg_scores[uid] = 0.0

        bt.logging.info(f"Round scores: {len(avg_scores)} miners with scores")
        for uid, score in avg_scores.items():
            bt.logging.info(f"  Miner {uid}: {score:.3f} (from {len(self.round_scores[uid])} tasks)")

        # Apply WTA to get final weights
        final_weights = wta_rewards(avg_scores)

        bt.logging.warning("")
        bt.logging.warning("🎯 FINAL WEIGHTS (WTA)")
        bt.logging.warning("=" * 80)
        for uid, weight in final_weights.items():
            if weight > 0:
                bt.logging.warning(f"  🏆 Miner {uid}: {weight:.3f}")
            else:
                bt.logging.info(f"  ❌ Miner {uid}: {weight:.3f}")

        # Set weights
        self.validator.set_weights(final_weights)

        bt.logging.warning("")
        bt.logging.warning("✅ ROUND COMPLETE")
        bt.logging.warning("=" * 80)
        bt.logging.warning(f"Tasks completed: {tasks_completed}")
        bt.logging.warning(f"Miners evaluated: {len(avg_scores)}")
        bt.logging.warning(f"Winner: {max(avg_scores, key=avg_scores.get) if avg_scores else 'None'}")

    async def _wait_for_target_epoch(self, start_block: int):
        """Wait for the target epoch to set weights"""
        bt.logging.warning("")
        bt.logging.warning("⏳ WAITING FOR TARGET EPOCH")
        bt.logging.warning("=" * 80)

        boundaries = self.round_calculator.get_round_boundaries(start_block)
        target_epoch = boundaries['target_epoch']

        while True:
            current_block = self.validator.metagraph.block.item()
            current_epoch = self.round_calculator.block_to_epoch(current_block)
            wait_info = self.round_calculator.get_wait_info(current_block, start_block)

            if wait_info["reached_target"]:
                bt.logging.warning(f"🎯 Target epoch {target_epoch} REACHED!")
                bt.logging.warning(f"   Current epoch: {current_epoch:.2f}")
                break

            bt.logging.info(f"⏳ Waiting... Current: {current_epoch:.2f}, Target: {target_epoch}, Remaining: {wait_info['minutes_remaining']:.1f} min")

            # Wait for next block
            await asyncio.sleep(12)  # Wait for next block

        bt.logging.warning("=" * 80)
