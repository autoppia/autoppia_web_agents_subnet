# autoppia_web_agents_subnet/validator/validator.py
from __future__ import annotations

import asyncio
import random
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
from autoppia_web_agents_subnet.validator.synapse_handlers import (
    send_start_round_synapse_to_miners,
    send_task_synapse_to_miners,
    send_feedback_synapse_to_miners,
)
from autoppia_web_agents_subnet.protocol import StartRoundSynapse, TaskSynapse
from autoppia_web_agents_subnet.validator.rewards import calculate_rewards_for_task, wta_rewards
from autoppia_web_agents_subnet.validator.eval import evaluate_task_solutions
from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.round_manager import RoundManager
from autoppia_web_agents_subnet.validator.leaderboard.leaderboard_sender import LeaderboardSender
from autoppia_web_agents_subnet.validator.visualization.round_table import render_round_summary_table


class Validator(BaseValidatorNeuron):
    def __init__(self, config=None):
        super().__init__(config=config)
        self.forward_count = 0
        self.last_rewards: np.ndarray | None = None
        self.last_round_responses: Dict[int, StartRoundSynapse] = {}
        self.version: str = __version__

        # Active miners (those who responded to StartRoundSynapse handshake)
        self.active_miner_uids: list[int] = []

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
            # Build parallel lists of UIDs and axons to preserve mapping
            all_uids = list(range(len(self.metagraph.uids)))
            all_axons = [self.metagraph.axons[uid] for uid in all_uids]
            start_synapse = StartRoundSynapse(
                version=self.version,
                round_id=f"round_{boundaries['round_start_epoch']}",
                validator_id=str(self.uid),
                total_prompts=len(all_tasks),
                prompts_per_use_case=PROMPTS_PER_USECASE,
                note=f"Starting round at epoch {boundaries['round_start_epoch']}"
            )

            handshake_responses = await send_start_round_synapse_to_miners(
                validator=self,
                miner_axons=all_axons,
                start_synapse=start_synapse,
                timeout=30,
            )

            # Filter and save UIDs of miners who responded successfully (must include agent_name)
            self.active_miner_uids = []

            # Filter successful responses only
            for i, response in enumerate(handshake_responses):
                if i < len(all_axons):
                    mapped_uid = all_uids[i]
                    agent_name = getattr(response, 'agent_name', None) if response else None

                    if response and agent_name:
                        self.active_miner_uids.append(mapped_uid)
                else:
                    bt.logging.warning(f"  Response {i}: No corresponding axon (out of bounds)")

            # Log only successful responders for clarity
            if self.active_miner_uids:
                responders = [
                    f"uid={uid}, hotkey={self.metagraph.hotkeys[uid]}"
                    for uid in self.active_miner_uids
                ]
                bt.logging.info(
                    f"✅ Handshake complete: {len(self.active_miner_uids)}/{len(all_axons)} miners responded: "
                    + "; ".join(responders)
                )
            else:
                bt.logging.info(
                    f"✅ Handshake complete: 0/{len(all_axons)} miners responded"
                )

        except Exception as e:
            bt.logging.error(f"StartRoundSynapse handshake failed: {e}")
            # Do NOT silently use all miners; skip task execution if no handshake
            self.active_miner_uids = []
            bt.logging.warning("   No miners will be used this round due to handshake failure.")

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

            # Guard: if no active miners responded to handshake, skip task
            if not self.active_miner_uids:
                bt.logging.warning("No active miners responded to handshake; skipping task send.")
                return False

            active_axons = [self.metagraph.axons[uid] for uid in self.active_miner_uids]

            # Create TaskSynapse with the actual task
            task_synapse = TaskSynapse(
                version=self.version,
                prompt=task.prompt,
                url=project.frontend_url,
                screenshot=None,  # Optional: could add screenshot support
            )

            # Send task to miners
            responses = await send_task_synapse_to_miners(
                validator=self,
                miner_axons=active_axons,
                task_synapse=task_synapse,
                timeout=60,
            )

            # Process responses and calculate rewards
            task_solutions, execution_times = collect_task_solutions_and_execution_times(
                task=task,
                responses=responses,
                miner_uids=list(self.active_miner_uids),
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
                n_miners=len(self.active_miner_uids),
                eval_score_weight=EVAL_SCORE_WEIGHT,
                time_weight=TIME_WEIGHT,
            )

            # Accumulate scores for the round using round_manager
            self.round_manager.accumulate_rewards(
                miner_uids=list(self.active_miner_uids),
                rewards=rewards.tolist(),
                eval_scores=eval_scores.tolist(),
                execution_times=execution_times
            )

            # Send feedback to miners
            try:
                await send_feedback_synapse_to_miners(
                    validator=self,
                    miner_axons=list(active_axons),
                    miner_uids=list(self.active_miner_uids),
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
        last_log_time = time.time()

        while True:
            # Fetch latest block from network to keep time in sync
            current_block = self.subtensor.get_current_block()
            current_epoch = self.round_manager.block_to_epoch(current_block)
            wait_info = self.round_manager.get_wait_info(current_block)

            if wait_info["reached_target"]:
                bt.logging.warning(f"🎯 Target epoch {target_epoch} REACHED!")
                bt.logging.warning(f"   Current epoch: {current_epoch:.2f}")
                break

            # Recompute round boundaries and progress on each tick
            boundaries = self.round_manager.get_round_boundaries(current_block)
            target_epoch = boundaries['target_epoch']
            round_start_block = boundaries['round_start_block']
            target_block = boundaries['target_block']

            # Progress based on blocks within the round window
            blocks_total = max(target_block - round_start_block, 1)
            blocks_done = max(current_block - round_start_block, 0)
            progress = min(max((blocks_done / blocks_total) * 100.0, 0.0), 100.0)

            # Log progress every 30 seconds
            if time.time() - last_log_time >= 30:
                # Verbose, human-friendly status
                bt.logging.info("⏳ Waiting for target epoch")
                bt.logging.info(
                    f"   - Epoch: current={current_epoch:.3f} | target={target_epoch:.3f}"
                )
                bt.logging.info(
                    f"   - Blocks: current={current_block} | target={target_block} | progress={progress:.2f}%"
                )
                bt.logging.info(
                    f"   - Remaining: {wait_info['minutes_remaining']:.1f} min (~{wait_info['minutes_remaining']*60:.0f}s)"
                )
                last_log_time = time.time()

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

        # Render concise round summary table (UID, hotkey prefix, avg score, avg time, reward)
        try:
            render_round_summary_table(self.round_manager, final_rewards_dict, self.metagraph, to_console=True)
        except Exception as e:
            bt.logging.debug(f"Round summary table failed: {e}")

        # Minimal final weights log: only winner
        bt.logging.warning("")
        bt.logging.warning("🎯 FINAL WEIGHTS (WTA)")
        bt.logging.warning("=" * 80)
        winner_uid = max(final_rewards_dict.keys(), key=lambda k: final_rewards_dict[k]) if final_rewards_dict else None
        if winner_uid is not None:
            hotkey = self.metagraph.hotkeys[winner_uid] if winner_uid < len(self.metagraph.hotkeys) else "<unknown>"
            bt.logging.warning(f"  🏆 Winner uid={winner_uid}, hotkey={hotkey[:10]}..., weight={final_rewards_dict[winner_uid]:.4f}")
        else:
            bt.logging.warning("  ❌ No miners evaluated.")

        # Update EMA scores (only for active miners who responded to handshake)
        # Prepare aligned arrays: rewards and uids must have the same length
        active_rewards = np.array(
            [final_rewards_dict.get(uid, 0.0) for uid in self.active_miner_uids], 
            dtype=np.float32
        )

        bt.logging.info(f"Updating scores for {len(self.active_miner_uids)} active miners")
        self.update_scores(
            rewards=active_rewards,           # Array of rewards for active miners
            uids=self.active_miner_uids       # List of active miner UIDs (same length)
        )

        # Set weights on blockchain
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
    # Optional IWA bootstrap (if available)
    try:
        # Optional dependency: autoppia_iwa (may not be installed)
        import importlib
        _mod = importlib.import_module("autoppia_iwa.src.bootstrap")
        _AppBootstrap = getattr(_mod, "AppBootstrap")
        _app = _AppBootstrap()
        # IWA logging works with loguru
        logger.remove()
        logger.add("logfile.log", level="INFO")
        logger.add(lambda msg: print(msg, end=""), level="WARNING")
    except Exception:
        pass

    with Validator(config=config(role="validator")) as validator:
        while True:
            bt.logging.info(f"Validator running... {time.time()}")
            time.sleep(30)
