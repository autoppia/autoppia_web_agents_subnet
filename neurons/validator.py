# autoppia_web_agents_subnet/validator/validator.py
from __future__ import annotations

import asyncio
import time
from typing import Dict
from urllib.parse import parse_qs, urlparse

import bittensor as bt
import numpy as np
from loguru import logger

from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.bittensor_config import config
from autoppia_web_agents_subnet.validator.config import (
    EVAL_SCORE_WEIGHT,
    TIME_WEIGHT,
    ROUND_SIZE_EPOCHS,
    AVG_TASK_DURATION_SECONDS,
    SAFETY_BUFFER_EPOCHS,
    PROMPTS_PER_USECASE,
    PRE_GENERATED_TASKS,
    VALIDATOR_NAME,
    VALIDATOR_IMAGE,
    DZ_STARTING_BLOCK,
    MAX_AGENT_NAME_LENGTH,
)
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
from autoppia_web_agents_subnet.validator.visualization.round_table import render_round_summary_table
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.platform.iwa.validator_mixin import ValidatorPlatformMixin


class Validator(ValidatorPlatformMixin, BaseValidatorNeuron):
    def __init__(self, config=None):
        if not VALIDATOR_NAME or not VALIDATOR_IMAGE:
            bt.logging.error("VALIDATOR_NAME and VALIDATOR_IMAGE must be set in the environment before starting the validator.")
            raise SystemExit(1)

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
            minimum_start_block=DZ_STARTING_BLOCK,
        )

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

        # Get current block and prevent early round execution
        current_block = self.metagraph.block.item()

        if not self.round_manager.can_start_round(current_block):
            blocks_remaining = self.round_manager.blocks_until_allowed(current_block)
            seconds_remaining = blocks_remaining * self.round_manager.SECONDS_PER_BLOCK
            ColoredLogger.warning(
                (
                    "⏳ Waiting for minimum launch block before starting rounds. "
                    f"Current block: {current_block}, required > {DZ_STARTING_BLOCK}."
                ),
                ColoredLogger.YELLOW,
            )
            if blocks_remaining > 0:
                ColoredLogger.warning(
                    (
                        f"   Blocks remaining: {blocks_remaining} "
                        f"(≈{seconds_remaining/60:.1f} minutes)."
                    ),
                    ColoredLogger.YELLOW,
                )

            # Sleep for a bounded interval to re-check later without busy-waiting.
            wait_seconds = min(max(seconds_remaining, 30), 600)
            await asyncio.sleep(wait_seconds)
            return

        # Get current block and calculate round boundaries
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

        self.current_round_id = self._generate_validator_round_id()
        self.round_start_timestamp = pre_generation_start
        self.current_round_tasks = self._build_iwap_tasks(
            validator_round_id=self.current_round_id,
            tasks=all_tasks,
        )

        pre_generation_elapsed = time.time() - pre_generation_start
        bt.logging.warning(f"✅ Pre-generation complete: {len(all_tasks)} tasks in {pre_generation_elapsed:.1f}s")
        bt.logging.warning("=" * 80)

        # ═══════════════════════════════════════════════════════
        # START ROUND HANDSHAKE: Send StartRoundSynapse ONCE
        # ═══════════════════════════════════════════════════════
        ColoredLogger.warning("", ColoredLogger.CYAN)
        ColoredLogger.warning("🤝 SENDING START ROUND HANDSHAKE", ColoredLogger.CYAN)
        ColoredLogger.warning("=" * 80, ColoredLogger.CYAN)

        # Initialize new round in RoundManager
        self.round_manager.start_new_round(current_block)
        boundaries = self.round_manager.get_current_boundaries()
        self.round_handshake_payloads = {}
        self.current_agent_runs = {}
        self.current_miner_snapshots = {}
        self.agent_run_accumulators = {}

        # Send StartRoundSynapse to all miners ONCE at the beginning
        try:
            # Build parallel lists of UIDs and axons to preserve mapping
            all_uids = list(range(len(self.metagraph.uids)))
            all_axons = [self.metagraph.axons[uid] for uid in all_uids]
            start_synapse = StartRoundSynapse(
                version=self.version,
                round_id=self.current_round_id or f"round_{boundaries['round_start_epoch']}",
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

            # Filter and save UIDs of miners who responded successfully (normalize metadata)
            self.active_miner_uids = []

            def _normalized_optional(value):
                if value is None:
                    return None
                text = str(value).strip()
                return text or None

            def _truncate_agent_name(name: str) -> str:
                if MAX_AGENT_NAME_LENGTH and len(name) > MAX_AGENT_NAME_LENGTH:
                    bt.logging.debug(
                        f"Truncating agent name '{name}' to {MAX_AGENT_NAME_LENGTH} characters."
                    )
                    return name[:MAX_AGENT_NAME_LENGTH]
                return name

            # Filter successful responses only
            for i, response in enumerate(handshake_responses):
                if i >= len(all_axons):
                    bt.logging.warning(f"  Response {i}: No corresponding axon (out of bounds)")
                    continue

                mapped_uid = all_uids[i]
                if not response:
                    bt.logging.debug(f"  Skipping uid={mapped_uid}: no handshake response object")
                    continue

                status_code = getattr(getattr(response, "dendrite", None), "status_code", None)
                status_numeric: int | None = None
                if status_code is not None:
                    try:
                        status_numeric = int(status_code)
                    except (TypeError, ValueError):
                        status_numeric = None
                if status_numeric is not None and status_numeric >= 400:
                    bt.logging.debug(
                        f"  Skipping uid={mapped_uid}: handshake returned status {status_numeric}"
                    )
                    continue

                agent_name_raw = getattr(response, "agent_name", None)
                agent_name = _normalized_optional(agent_name_raw)
                if not agent_name:
                    bt.logging.debug(
                        f"  Skipping uid={mapped_uid}: handshake missing agent metadata"
                    )
                    continue

                agent_name = _truncate_agent_name(agent_name)

                response.agent_name = agent_name
                response.agent_image = _normalized_optional(getattr(response, "agent_image", None))
                response.github_url = _normalized_optional(getattr(response, "github_url", None))
                agent_version = _normalized_optional(getattr(response, "agent_version", None))
                if agent_version is not None:
                    response.agent_version = agent_version

                self.round_handshake_payloads[mapped_uid] = response
                self.active_miner_uids.append(mapped_uid)

            # Log only successful responders for clarity
            if self.active_miner_uids:
                responders = [
                    f"uid={uid}, hotkey={self.metagraph.hotkeys[uid]}"
                    for uid in self.active_miner_uids
                ]
                ColoredLogger.success(
                    f"✅ Handshake complete: {len(self.active_miner_uids)}/{len(all_axons)} miners responded: "
                    + "; ".join(responders), ColoredLogger.GREEN
                )
            else:
                ColoredLogger.warning(
                    f"⚠️ Handshake complete: 0/{len(all_axons)} miners responded", ColoredLogger.YELLOW
                )

        except Exception as e:
            bt.logging.error(f"StartRoundSynapse handshake failed: {e}")
            # Do NOT silently use all miners; skip task execution if no handshake
            self.active_miner_uids = []
            bt.logging.warning("   No miners will be used this round due to handshake failure.")

        await self._iwap_start_round(current_block=current_block, n_tasks=len(all_tasks))

        # ═══════════════════════════════════════════════════════
        # DYNAMIC LOOP: Execute tasks one by one based on time
        # ═══════════════════════════════════════════════════════
        ColoredLogger.warning("", ColoredLogger.MAGENTA)
        ColoredLogger.warning("🔄 STARTING DYNAMIC TASK EXECUTION", ColoredLogger.MAGENTA)
        ColoredLogger.warning("=" * 80, ColoredLogger.MAGENTA)

        task_index = 0
        tasks_completed = 0

        # Dynamic loop: consume pre-generated tasks and check AFTER evaluating
        while task_index < len(all_tasks):
            current_block = self.metagraph.block.item()
            current_epoch = self.round_manager.block_to_epoch(current_block)
            boundaries = self.round_manager.get_current_boundaries()
            wait_info = self.round_manager.get_wait_info(current_block)

            ColoredLogger.info(
                f"📍 TASK {task_index + 1}/{len(all_tasks)} | "
                f"Epoch {current_epoch:.2f}/{boundaries['target_epoch']} | "
                f"Time remaining: {wait_info['minutes_remaining']:.1f} min", ColoredLogger.CYAN
            )

            # Execute single task
            task_sent = await self._send_task_and_evaluate(all_tasks[task_index], task_index)
            if task_sent:
                tasks_completed += 1
            task_index += 1

            # Dynamic check: should we send another task?
            if not self.round_manager.should_send_next_task(current_block):
                ColoredLogger.warning("", ColoredLogger.YELLOW)
                ColoredLogger.warning("🛑 STOPPING TASK EXECUTION - SAFETY BUFFER REACHED", ColoredLogger.YELLOW)
                ColoredLogger.warning(f"   Reason: Insufficient time remaining for another task", ColoredLogger.YELLOW)
                ColoredLogger.info(f"   Current epoch: {current_epoch:.2f}", ColoredLogger.YELLOW)
                ColoredLogger.info(f"   Time remaining: {wait_info['seconds_remaining']:.0f}s", ColoredLogger.YELLOW)
                ColoredLogger.info(f"   Safety buffer: {SAFETY_BUFFER_EPOCHS} epochs", ColoredLogger.YELLOW)
                ColoredLogger.info(f"   Tasks completed: {tasks_completed}/{len(all_tasks)}", ColoredLogger.YELLOW)
                ColoredLogger.info(f"   ⏳ Now waiting for target epoch to set weights...", ColoredLogger.YELLOW)
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
                ColoredLogger.warning("⚠️ No active miners responded to handshake; skipping task send.", ColoredLogger.YELLOW)
                return False

            active_axons = [self.metagraph.axons[uid] for uid in self.active_miner_uids]

            # Capture task metadata to forward to miners
            seed: int | None = getattr(task, "_seed_value", None)
            if seed is None and isinstance(getattr(task, "url", None), str):
                try:
                    parsed = urlparse(task.url)
                    query = parse_qs(parsed.query)
                    raw_seed = query.get("seed", [None])[0]
                    seed = int(str(raw_seed)) if raw_seed is not None else None
                except (ValueError, TypeError):
                    seed = None

            web_project_name = getattr(project, "name", None)

            # Create TaskSynapse with the actual task
            task_synapse = TaskSynapse(
                version=self.version,
                prompt=task.prompt,
                url=project.frontend_url,
                screenshot=None,  # Optional: could add screenshot support
                seed=seed,
                web_project_name=web_project_name,
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

            try:
                await self._iwap_submit_task_results(
                    task_item=task_item,
                    task_solutions=task_solutions,
                    eval_scores=eval_scores,
                    test_results_matrices=test_results_matrices,
                    evaluation_results=evaluation_results,
                    execution_times=execution_times,
                    rewards=rewards.tolist(),
                )
            except Exception as e:
                bt.logging.warning(f"IWAP submission failed: {e}")

            bt.logging.info(f"✅ Task {task_index + 1} completed")
            return True

        except Exception as e:
            bt.logging.error(f"Task execution failed: {e}")
            return False

    async def _wait_for_target_epoch(self):
        """Wait for the target epoch to set weights"""
        ColoredLogger.warning("", ColoredLogger.BLUE)
        ColoredLogger.warning("⏳ WAITING FOR TARGET EPOCH", ColoredLogger.BLUE)
        ColoredLogger.warning("=" * 80, ColoredLogger.BLUE)

        boundaries = self.round_manager.get_current_boundaries()
        target_epoch = boundaries['target_epoch']
        last_log_time = time.time()

        while True:
            # Fetch latest block from network to keep time in sync
            current_block = self.subtensor.get_current_block()
            current_epoch = self.round_manager.block_to_epoch(current_block)
            wait_info = self.round_manager.get_wait_info(current_block)

            if wait_info["reached_target"]:
                ColoredLogger.success(f"🎯 Target epoch {target_epoch} REACHED!", ColoredLogger.GREEN)
                ColoredLogger.info(f"   Current epoch: {current_epoch:.2f}", ColoredLogger.GREEN)
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
                ColoredLogger.info("⏳ Waiting for target epoch", ColoredLogger.BLUE)
                ColoredLogger.info(
                    f"   - Epoch: current={current_epoch:.3f} | target={target_epoch:.3f}", ColoredLogger.BLUE
                )
                ColoredLogger.info(
                    f"   - Blocks: current={current_block} | target={target_block} | progress={progress:.2f}%", ColoredLogger.BLUE
                )
                ColoredLogger.info(
                    f"   - Remaining: {wait_info['minutes_remaining']:.1f} min (~{wait_info['minutes_remaining']*60:.0f}s)", ColoredLogger.BLUE
                )
                last_log_time = time.time()

            # Wait for next block
            await asyncio.sleep(12)  # Wait for next block

        bt.logging.warning("=" * 80)

    async def _calculate_final_weights(self, tasks_completed: int):
        """Calculate averages, apply WTA, set weights"""
        ColoredLogger.warning("", ColoredLogger.PURPLE)
        ColoredLogger.warning("🏁 CALCULATING FINAL WEIGHTS", ColoredLogger.PURPLE)
        ColoredLogger.warning("=" * 80, ColoredLogger.PURPLE)

        # Check if no miners responded to handshake - BURN ALL WEIGHTS
        if not self.active_miner_uids:
            ColoredLogger.error("🔥 NO ACTIVE MINERS - BURNING ALL WEIGHTS", ColoredLogger.RED)
            ColoredLogger.warning("   - Setting weight=1.0 to UID 0 (burn address)", ColoredLogger.RED)
            ColoredLogger.warning("   - All other UIDs get weight=0.0", ColoredLogger.RED)

            # Create burn weights: UID 0 = 1.0, all others = 0.0
            burn_weights = np.zeros(self.metagraph.n, dtype=np.float32)
            burn_weights[0] = 1.0  # UID 0 gets all weight (burn)

            # Set these burn weights directly
            self.scores = burn_weights
            self._maybe_set_weights()

            ColoredLogger.warning("", ColoredLogger.RED)
            ColoredLogger.success("✅ BURN COMPLETE", ColoredLogger.RED)
            ColoredLogger.warning("=" * 80, ColoredLogger.RED)
            ColoredLogger.info(f"Tasks attempted: {tasks_completed}", ColoredLogger.RED)
            ColoredLogger.info(f"Miners evaluated: 0", ColoredLogger.RED)
            ColoredLogger.info(f"Result: BURNED (weight=1.0 to UID 0)", ColoredLogger.RED)
            return

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
        self._maybe_set_weights()

        try:
            await self._finish_iwap_round(
                avg_rewards=avg_rewards,
                final_weights=final_rewards_dict,
                tasks_completed=tasks_completed,
            )
        except Exception as e:
            bt.logging.warning(f"IWAP finish_round failed: {e}")

        ColoredLogger.warning("", ColoredLogger.GREEN)
        ColoredLogger.success("✅ ROUND COMPLETE", ColoredLogger.GREEN)
        ColoredLogger.warning("=" * 80, ColoredLogger.GREEN)
        ColoredLogger.info(f"Tasks completed: {tasks_completed}", ColoredLogger.GREEN)

    def _maybe_set_weights(self) -> None:
        """Commit weights to the chain only when permitted."""
        disable = getattr(self.config.neuron, "disable_set_weights", False)
        if disable:
            bt.logging.warning("Skipping set_weights because neuron.disable_set_weights is true")
            return
        self.set_weights()


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
