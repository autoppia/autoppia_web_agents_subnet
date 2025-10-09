# autoppia_web_agents_subnet/validator/validator.py
from __future__ import annotations

import asyncio
import time
from typing import Dict

import bittensor as bt
import numpy as np
from loguru import logger

from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.bittensor_config import config
from autoppia_web_agents_subnet.validator.config import EVAL_SCORE_WEIGHT, TIME_WEIGHT, ROUND_SIZE_EPOCHS, AVG_TASK_DURATION_SECONDS, SAFETY_BUFFER_EPOCHS, PROMPTS_PER_USECASE, PRE_GENERATED_TASKS
from autoppia_web_agents_subnet.validator.tasks import get_task_collection_interleaved, collect_task_solutions_and_execution_times
from autoppia_web_agents_subnet.validator.synapse_handlers import send_feedback_synapse_to_miners
from autoppia_web_agents_subnet.synapses import StartRoundSynapse, TaskSynapse
from autoppia_web_agents_subnet.validator.rewards import calculate_rewards_for_task, wta_rewards
from autoppia_web_agents_subnet.validator.eval import evaluate_task_solutions
from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.round_manager import RoundManager
from autoppia_web_agents_subnet.validator.leaderboard.leaderboard_sender import LeaderboardSender
from autoppia_web_agents_subnet.utils.random import get_random_uids
# IWA
from autoppia_iwa.src.bootstrap import AppBootstrap


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
        all_tasks: list[TaskWithProject] = []

        # Generate all tasks in batches (already interleaved)
        tasks_generated = 0
        while tasks_generated < PRE_GENERATED_TASKS:
            batch_start = time.time()

            # Generate a batch of tasks (returns flat list, already interleaved)
            batch_tasks = await get_task_collection_interleaved(prompts_per_use_case=PROMPTS_PER_USECASE)

            # Take only what we need from this batch
            remaining = PRE_GENERATED_TASKS - tasks_generated
            tasks_to_add = batch_tasks[:remaining]
            all_tasks.extend(tasks_to_add)
            tasks_generated += len(tasks_to_add)

            batch_elapsed = time.time() - batch_start
            bt.logging.info(f"   Generated batch: {len(tasks_to_add)} tasks in {batch_elapsed:.1f}s (total: {tasks_generated}/{PRE_GENERATED_TASKS})")

        pre_generation_elapsed = time.time() - pre_generation_start
        bt.logging.warning(f"✅ Pre-generation complete: {len(all_tasks)} tasks in {pre_generation_elapsed:.1f}s")
        bt.logging.warning("=" * 80)

        # ═══════════════════════════════════════════════════════
        # START ROUND HANDSHAKE: Send StartRoundSynapse ONCE
        # ═══════════════════════════════════════════════════════
        bt.logging.warning("")
        bt.logging.warning("🤝 SENDING START ROUND HANDSHAKE")
        bt.logging.warning("=" * 80)

        # Initialize new round in RoundManager
        self.round_manager.start_new_round(current_block)
        boundaries = self.round_manager.get_current_boundaries()

        # Send StartRoundSynapse to all miners ONCE at the beginning
        try:
            all_axons = [self.metagraph.axons[uid] for uid in range(len(self.metagraph.uids))]
            start_synapse = StartRoundSynapse(
                version=self.version,
                round_id=f"round_{boundaries['round_start_epoch']}",
                validator_id=str(self.uid),
                total_prompts=len(all_tasks),
                prompts_per_use_case=PROMPTS_PER_USECASE,
                note=f"Starting round at epoch {boundaries['round_start_epoch']}"
            )

            bt.logging.info(f"Sending StartRoundSynapse to {len(all_axons)} miners...")
            handshake_responses = await self.dendrite(
                axons=all_axons,
                synapse=start_synapse,
                deserialize=True,
                timeout=30,
            )

            # Log miner responses (agent names, versions, etc.)
            responding_miners = sum(1 for r in handshake_responses if r and hasattr(r, 'agent_name') and r.agent_name)
            bt.logging.info(f"✅ Handshake complete: {responding_miners}/{len(all_axons)} miners responded")

        except Exception as e:
            bt.logging.error(f"StartRoundSynapse handshake failed: {e}")

        # ═══════════════════════════════════════════════════════
        # DYNAMIC LOOP: Execute tasks one by one based on time
        # ═══════════════════════════════════════════════════════
        bt.logging.warning("")
        bt.logging.warning("🔄 STARTING DYNAMIC TASK EXECUTION")
        bt.logging.warning("=" * 80)

        task_index = 0
        tasks_completed = 0

        # Dynamic loop: consume pre-generated tasks and check AFTER evaluating
        while task_index < len(all_tasks):
            current_block = self.metagraph.block.item()
            current_epoch = self.round_manager.block_to_epoch(current_block)
            boundaries = self.round_manager.get_current_boundaries()
            wait_info = self.round_manager.get_wait_info(current_block)

            bt.logging.info(
                f"📍 TASK {task_index + 1}/{len(all_tasks)} | "
                f"Epoch {current_epoch:.2f}/{boundaries['target_epoch']} | "
                f"Time remaining: {wait_info['minutes_remaining']:.1f} min"
            )

            # Execute single task
            task_sent = await self._send_task_and_evaluate(all_tasks[task_index], task_index)
            if task_sent:
                tasks_completed += 1
            task_index += 1

            # Dynamic check: should we send another task?
            if not self.round_manager.should_send_next_task(current_block):
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
            await self._wait_for_target_epoch()

        # ═══════════════════════════════════════════════════════
        # FINAL WEIGHTS: Calculate averages, apply WTA, set weights
        # ═══════════════════════════════════════════════════════
        await self._calculate_final_weights(tasks_completed)

    # ═══════════════════════════════════════════════════════════════════════════════
    # TASK EXECUTION HELPERS
    # ═══════════════════════════════════════════════════════════════════════════════
    async def _send_task_and_evaluate(self, task_item: TaskWithProject, task_index: int) -> bool:
        """Execute a single task and accumulate results"""
        project = task_item.project
        task = task_item.task

        try:
            # Get active miners
            active_uids = get_random_uids(
                self.metagraph,
                k=min(5, len(self.metagraph.uids)),
            )
            active_axons = [self.metagraph.axons[uid] for uid in active_uids]

            # Create TaskSynapse with the actual task
            task_synapse = TaskSynapse(
                version=self.version,
                prompt=task.prompt,
                url=project.frontend_url,
                screenshot=None,  # Optional: could add screenshot support
            )

            # Send task to miners
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

            # Calculate final scores (combining eval quality + execution speed)
            rewards = calculate_rewards_for_task(
                eval_scores=eval_scores,
                execution_times=execution_times,
                n_miners=len(active_uids),
                eval_score_weight=EVAL_SCORE_WEIGHT,
                time_weight=TIME_WEIGHT,
            )

            # Accumulate scores for the round using round_manager
            self.round_manager.accumulate_rewards(
                miner_uids=list(active_uids),
                rewards=rewards.tolist(),
                eval_scores=eval_scores.tolist(),
                execution_times=execution_times
            )

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

    async def _wait_for_target_epoch(self):
        """Wait for the target epoch to set weights"""
        bt.logging.warning("")
        bt.logging.warning("⏳ WAITING FOR TARGET EPOCH")
        bt.logging.warning("=" * 80)

        boundaries = self.round_manager.get_current_boundaries()
        target_epoch = boundaries['target_epoch']

        while True:
            current_block = self.metagraph.block.item()
            current_epoch = self.round_manager.block_to_epoch(current_block)
            wait_info = self.round_manager.get_wait_info(current_block)

            if wait_info["reached_target"]:
                bt.logging.warning(f"🎯 Target epoch {target_epoch} REACHED!")
                bt.logging.warning(f"   Current epoch: {current_epoch:.2f}")
                break

            bt.logging.info(f"⏳ Waiting... Current: {current_epoch:.2f}, Target: {target_epoch}, Remaining: {wait_info['minutes_remaining']:.1f} min")

            # Wait for next block
            await asyncio.sleep(12)  # Wait for next block

        bt.logging.warning("=" * 80)

    async def _calculate_final_weights(self, tasks_completed: int):
        """Calculate averages, apply WTA, set weights"""
        bt.logging.warning("")
        bt.logging.warning("🏁 CALCULATING FINAL WEIGHTS")
        bt.logging.warning("=" * 80)

        # Calculate average scores using round_manager
        avg_rewards = self.round_manager.get_average_rewards()

        # Log round summary
        self.round_manager.log_round_summary()

        # Apply WTA to get final weights
        # Convert dict to numpy array for wta_rewards
        uids = list(avg_rewards.keys())
        scores_array = np.array([avg_rewards[uid] for uid in uids], dtype=np.float32)
        final_rewards_array = wta_rewards(scores_array)

        # Convert back to dict
        final_rewards_dict = {uid: float(reward) for uid, reward in zip(uids, final_rewards_array)}

        bt.logging.warning("")
        bt.logging.warning("🎯 FINAL rewardS (WTA)")
        bt.logging.warning("=" * 80)
        for uid, reward in final_rewards_dict.items():
            if reward > 0:
                bt.logging.warning(f"  🏆 Miner {uid}: {reward:.3f}")
            else:
                bt.logging.info(f"  ❌ Miner {uid}: {reward:.3f}")

        # Set rewards (store in validator for set_rewards to use)
        self.final_rewards_np = np.zeros(len(self.metagraph.uids), dtype=np.float32)
        for uid, reward in final_rewards_dict.items():
            if uid < len(self.final_rewards_np):
                self.final_rewards_np[uid] = reward
        self.last_rewards = self.final_rewards_np
        self.update_scores(self.final_rewards_np, uids)
        self.set_weights()

        # ═══════════════════════════════════════════════════════
        # LEADERBOARD: Post round results to API
        # ═══════════════════════════════════════════════════════
        boundaries = self.round_manager.get_current_boundaries()
        self.leaderboard_sender.post_round_results(
            validator=self,
            start_block=boundaries['round_start_block'],
            tasks_completed=tasks_completed,
            avg_scores=avg_rewards,
            final_weights=final_rewards_dict,
            round_manager=self.round_manager,
        )

        bt.logging.warning("")
        bt.logging.warning("✅ ROUND COMPLETE")
        bt.logging.warning("=" * 80)
        bt.logging.warning(f"Tasks completed: {tasks_completed}")
        bt.logging.warning(f"Miners evaluated: {len(avg_rewards)}")
        winner_uid = max(avg_rewards.keys(), key=lambda k: avg_rewards[k]) if avg_rewards else None
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
