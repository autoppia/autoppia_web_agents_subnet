# autoppia_web_agents_subnet/validator/validator.py
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import bittensor as bt
import numpy as np
from loguru import logger

from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.bittensor_config import config
from autoppia_web_agents_subnet.config import EVAL_SCORE_WEIGHT, TIME_WEIGHT, ROUND_SIZE_EPOCHS, AVG_TASK_DURATION_SECONDS, SAFETY_BUFFER_EPOCHS, PROMPTS_PER_USECASE, PRE_GENERATED_TASKS
from autoppia_web_agents_subnet.validator.tasks import get_task_plan, collect_task_solutions_and_execution_times
from autoppia_web_agents_subnet.validator.synapse_handlers import send_feedback_synapse_to_miners
from autoppia_web_agents_subnet.synapses import StartRoundSynapse
from autoppia_web_agents_subnet.validator.rewards import blend_eval_and_time, wta_rewards
from autoppia_web_agents_subnet.validator.eval import evaluate_task_solutions
from autoppia_web_agents_subnet.validator.models import TaskPlan
from autoppia_web_agents_subnet.validator.round_manager import RoundManager
from autoppia_web_agents_subnet.validator.leaderboard.leaderboard_sender import LeaderboardSender
from autoppia_web_agents_subnet.utils.random import get_random_uids
# IWA
from autoppia_iwa_module.autoppia_iwa.src.bootstrap import AppBootstrap


class Validator(BaseValidatorNeuron):
    def __init__(self, config=None):
        super().__init__(config=config)
        self.forward_count = 0
        self.last_rewards: np.ndarray | None = None
        self.last_round_responses: Dict[int, StartRoundSynapse] = {}
        self.version: str = __version__

        # ⭐ Round system components
        self.round_manager = RoundManager(
            round_size_epochs=ROUND_SIZE_EPOCHS,
            avg_task_duration_seconds=AVG_TASK_DURATION_SECONDS,
            safety_buffer_epochs=SAFETY_BUFFER_EPOCHS,
        )

        # ⭐ Leaderboard integration
        self.leaderboard_sender = LeaderboardSender()

        bt.logging.info("load_state()")
        self.load_state()

    # ═══════════════════════════════════════════════════════════════════════════════
    # MAIN FORWARD LOOP - Round-based system
    # ═══════════════════════════════════════════════════════════════════════════════
    async def forward(self) -> None:
        """
        Execute the complete forward loop for the round.
        This forward spans the ENTIRE round (~24h):
        1. Pre-generates all tasks at the beginning
        2. Dynamic loop: sends tasks one by one based on time remaining
        3. Accumulates scores from all miners
        4. When finished, WAIT until target epoch
        5. Calculates averages, applies WTA, sets weights
        """
        bt.logging.warning("")
        bt.logging.warning("🚀 STARTING ROUND-BASED FORWARD")
        bt.logging.warning("=" * 80)

        # Get current block and calculate round boundaries
        current_block = self.metagraph.block.item()
        boundaries = self.round_manager.get_round_boundaries(current_block)

        bt.logging.info(f"Round boundaries: start={boundaries['round_start_epoch']}, target={boundaries['target_epoch']}")

        # Log configuration summary
        self.round_manager.log_calculation_summary()

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
            current_block = self.metagraph.block.item()
            current_epoch = self.round_manager.block_to_epoch(current_block)
            boundaries = self.round_manager.get_round_boundaries(start_block)
            wait_info = self.round_manager.get_wait_info(current_block, start_block)

            bt.logging.info(
                f"📍 TASK {task_index + 1}/{len(all_tasks)} | "
                f"Epoch {current_epoch:.2f}/{boundaries['target_epoch']} | "
                f"Time remaining: {wait_info['minutes_remaining']:.1f} min"
            )

            # Execute single task
            success = await self._execute_single_task(all_tasks[task_index], task_index, start_block)
            if success:
                tasks_completed += 1
            task_index += 1

            # Dynamic check: should we send another task?
            if not self.round_manager.should_send_next_task(current_block, start_block):
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
        await self._calculate_final_weights(tasks_completed, start_block)

    # ═══════════════════════════════════════════════════════════════════════════════
    # TASK EXECUTION HELPERS
    # ═══════════════════════════════════════════════════════════════════════════════
    async def _execute_single_task(self, task_data, task_index: int, start_block: int) -> bool:
        """Execute a single task and accumulate results"""
        project, task = task_data

        try:
            # Get active miners
            active_uids = get_random_uids(
                self.metagraph,
                k=min(5, len(self.metagraph.uids)),
            )
            active_axons = [self.metagraph.axons[uid] for uid in active_uids]

            # Send task
            boundaries = self.round_manager.get_round_boundaries(start_block)
            task_synapse = StartRoundSynapse(
                version=self.version,
                round_id=f"round_{boundaries['round_start_epoch']}",
                validator_id=str(self.uid),
                total_prompts=1,
                prompts_per_use_case=PROMPTS_PER_USECASE,
            )

            responses = await self.dendrite(
                axons=active_axons,
                synapse=task_synapse,
                deserialize=True,
                timeout=60,
            )

            # Process responses and calculate rewards
            task_solutions, execution_times = collect_task_solutions_and_execution_times(
                task=task,
                responses=responses,
                miner_uids=list(active_uids),
            )

            # Evaluate task solutions
            eval_scores, test_results_matrices, evaluation_results = await evaluate_task_solutions(
                web_project=project,
                task=task,
                task_solutions=task_solutions,
                execution_times=execution_times,
            )

            # Calculate rewards using rewards.py
            rewards = blend_eval_and_time(
                eval_scores=eval_scores,
                execution_times=execution_times,
                n_miners=len(active_uids),
                eval_score_weight=EVAL_SCORE_WEIGHT,
                time_weight=TIME_WEIGHT,
            )

            # Accumulate scores for the round using round_manager
            self.round_manager.accumulate_scores(list(active_uids), rewards.tolist(), execution_times)

            # Send feedback to miners
            try:
                await send_feedback_synapse_to_miners(
                    validator=self,
                    miner_axons=list(active_axons),
                    miner_uids=list(active_uids),
                    task=task,
                    rewards=rewards.tolist(),
                    execution_times=execution_times,
                    task_solutions=task_solutions,
                    test_results_matrices=test_results_matrices,
                    evaluation_results=evaluation_results,
                )
            except Exception as e:
                bt.logging.warning(f"Feedback failed: {e}")

            bt.logging.info(f"✅ Task {task_index + 1} completed")
            return True

        except Exception as e:
            bt.logging.error(f"Task execution failed: {e}")
            return False

    async def _wait_for_target_epoch(self, start_block: int):
        """Wait for the target epoch to set weights"""
        bt.logging.warning("")
        bt.logging.warning("⏳ WAITING FOR TARGET EPOCH")
        bt.logging.warning("=" * 80)

        boundaries = self.round_manager.get_round_boundaries(start_block)
        target_epoch = boundaries['target_epoch']

        while True:
            current_block = self.metagraph.block.item()
            current_epoch = self.round_manager.block_to_epoch(current_block)
            wait_info = self.round_manager.get_wait_info(current_block, start_block)

            if wait_info["reached_target"]:
                bt.logging.warning(f"🎯 Target epoch {target_epoch} REACHED!")
                bt.logging.warning(f"   Current epoch: {current_epoch:.2f}")
                break

            bt.logging.info(f"⏳ Waiting... Current: {current_epoch:.2f}, Target: {target_epoch}, Remaining: {wait_info['minutes_remaining']:.1f} min")

            # Wait for next block
            await asyncio.sleep(12)  # Wait for next block

        bt.logging.warning("=" * 80)

    async def _calculate_final_weights(self, tasks_completed: int, start_block: int):
        """Calculate averages, apply WTA, set weights"""
        bt.logging.warning("")
        bt.logging.warning("🏁 CALCULATING FINAL WEIGHTS")
        bt.logging.warning("=" * 80)

        # Calculate average scores using round_manager
        avg_scores = self.round_manager.get_average_scores()

        # Log round summary
        self.round_manager.log_round_summary()

        # Apply WTA to get final weights
        # Convert dict to numpy array for wta_rewards
        uids = list(avg_scores.keys())
        scores_array = np.array([avg_scores[uid] for uid in uids], dtype=np.float32)
        final_weights_array = wta_rewards(scores_array)

        # Convert back to dict
        final_weights = {uid: float(weight) for uid, weight in zip(uids, final_weights_array)}

        bt.logging.warning("")
        bt.logging.warning("🎯 FINAL WEIGHTS (WTA)")
        bt.logging.warning("=" * 80)
        for uid, weight in final_weights.items():
            if weight > 0:
                bt.logging.warning(f"  🏆 Miner {uid}: {weight:.3f}")
            else:
                bt.logging.info(f"  ❌ Miner {uid}: {weight:.3f}")

        # Set weights (store in validator for set_weights to use)
        self.last_rewards = np.zeros(len(self.metagraph.uids), dtype=np.float32)
        for uid, weight in final_weights.items():
            if uid < len(self.last_rewards):
                self.last_rewards[uid] = weight
        self.set_weights()

        # ═══════════════════════════════════════════════════════
        # LEADERBOARD: Post round results to API
        # ═══════════════════════════════════════════════════════
        self.leaderboard_sender.post_round_results(
            validator=self,
            start_block=start_block,
            tasks_completed=tasks_completed,
            avg_scores=avg_scores,
            final_weights=final_weights,
            round_manager=self.round_manager,
        )

        bt.logging.warning("")
        bt.logging.warning("✅ ROUND COMPLETE")
        bt.logging.warning("=" * 80)
        bt.logging.warning(f"Tasks completed: {tasks_completed}")
        bt.logging.warning(f"Miners evaluated: {len(avg_scores)}")
        winner_uid = max(avg_scores.keys(), key=lambda k: avg_scores[k]) if avg_scores else None
        bt.logging.warning(f"Winner: {winner_uid}")


if __name__ == "__main__":
    # Initializing Dependency Injection In IWA
    app = AppBootstrap()

    # IWA logging works with loguru
    logger.remove()
    logger.add("logfile.log", level="INFO")
    logger.add(lambda msg: print(msg, end=""), level="WARNING")

    with Validator(config=config(role="validator")) as validator:
        while True:
            bt.logging.info(f"Validator running... {time.time()}")
            time.sleep(5)
