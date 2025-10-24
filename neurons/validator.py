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
    MAX_MINER_AGENT_NAME_LENGTH,
    ENABLE_DISTRIBUTED_CONSENSUS,
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION,
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION,
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION,
    BURN_UID,
)
from autoppia_web_agents_subnet.validator.tasks import get_task_collection_interleaved, collect_task_solutions_and_execution_times
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.data_generation.domain.classes import Task
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
from autoppia_web_agents_subnet.platform.validator_mixin import ValidatorPlatformMixin
from autoppia_web_agents_subnet.platform.round_phases import RoundPhaseValidatorMixin
from autoppia_web_agents_subnet.validator.consensus import (
    publish_round_snapshot,
    aggregate_scores_from_commitments,
)
from autoppia_iwa.src.bootstrap import AppBootstrap


class Validator(RoundPhaseValidatorMixin, ValidatorPlatformMixin, BaseValidatorNeuron):
    def __init__(self, config=None):
        if not VALIDATOR_NAME or not VALIDATOR_IMAGE:
            bt.logging.error("VALIDATOR_NAME and VALIDATOR_IMAGE must be set in the environment before starting the validator.")
            raise SystemExit(1)

        super().__init__(config=config)

        # Configure IWA (loguru) logging level based on CLI flag
        try:
            from autoppia_iwa.src.bootstrap import AppBootstrap
            iwa_debug = False
            if hasattr(self.config, "iwa") and hasattr(self.config.iwa, "logging") and hasattr(self.config.iwa.logging, "debug"):
                iwa_debug = bool(self.config.iwa.logging.debug)
            AppBootstrap(debug=iwa_debug)
        except Exception:
            pass
        self.forward_count = 0
        self.last_rewards: np.ndarray | None = None
        self.last_round_responses: Dict[int, StartRoundSynapse] = {}
        self.version: str = __version__

        # Active miners (those who responded to StartRoundSynapse handshake)
        self.active_miner_uids: list[int] = []

        # Burn-on-round-1 guard to avoid repeated chain sets
        self._burn_applied: bool = False
        # Consensus sharing
        self._consensus_published: bool = False
        self._consensus_mid_fetched: bool = False
        self._agg_scores_cache: dict[int, float] | None = None

        # ⭐ Round system components
        self.round_manager = RoundManager(
            round_size_epochs=ROUND_SIZE_EPOCHS,
            avg_task_duration_seconds=AVG_TASK_DURATION_SECONDS,
            safety_buffer_epochs=SAFETY_BUFFER_EPOCHS,
            minimum_start_block=DZ_STARTING_BLOCK,
        )

        bt.logging.info("load_state()")
        self.load_state()

    def should_set_weights(self) -> bool:
        """
        Skip automatic burns before any round has produced scores.
        Allow the base logic to run only after we have non-zero weights.
        """
        scores = np.asarray(getattr(self, "scores", []), dtype=np.float32)
        if scores.size == 0 or not np.any(scores):
            bt.logging.debug("Skipping set_weights: no scored miners yet.")
            return False
        return super().should_set_weights()

    def _reset_consensus_state(self) -> None:
        """Clear cached consensus state so a fresh round can publish again."""
        self._consensus_published = False
        self._consensus_mid_fetched = False
        self._agg_scores_cache = None
        # Clear any cached commit metadata
        for attr in ("_consensus_commit_block", "_consensus_commit_cid"):
            if hasattr(self, attr):
                try:
                    setattr(self, attr, None)
                except Exception:
                    pass

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
        bt.logging.info("🚀 Starting round-based forward")

        # Get current block and prevent early round execution
        current_block = self.metagraph.block.item()

        if not self.round_manager.can_start_round(current_block):
            blocks_remaining = self.round_manager.blocks_until_allowed(current_block)
            seconds_remaining = blocks_remaining * self.round_manager.SECONDS_PER_BLOCK
            minutes_remaining = seconds_remaining / 60
            hours_remaining = minutes_remaining / 60

            # Calculate current epoch and target epoch
            current_epoch = current_block / 360
            target_epoch = DZ_STARTING_BLOCK / 360

            eta = f"~{hours_remaining:.1f}h" if hours_remaining >= 1 else f"~{minutes_remaining:.0f}m"
            bt.logging.warning(
                f"🔒 Locked until block {DZ_STARTING_BLOCK:,} (epoch {target_epoch:.2f}) | "
                f"now {current_block:,} (epoch {current_epoch:.2f}) | ETA {eta}"
            )

            # Sleep for a bounded interval to re-check later without busy-waiting.
            wait_seconds = min(max(seconds_remaining, 30), 600)
            bt.logging.warning(f"💤 Rechecking in {wait_seconds:.0f}s...")

            await asyncio.sleep(wait_seconds)
            return

        # Skip early boundaries verification to avoid duplicate sync logs.

        # Log configuration summary
        self.round_manager.log_calculation_summary()

        # Round status snapshot before generation/resume
        try:
            boundaries_preview = self.round_manager.get_round_boundaries(current_block, log_debug=False)
            current_epoch_preview = self.round_manager.block_to_epoch(current_block)
            round_number_preview = await self.round_manager.calculate_round(current_block)
            blocks_to_target = max(boundaries_preview['target_block'] - current_block, 0)
            minutes_to_target = (blocks_to_target * self.round_manager.SECONDS_PER_BLOCK) / 60
            epochs_to_target = max(boundaries_preview['target_epoch'] - current_epoch_preview, 0.0)
            bt.logging.info(
                (
                    "Round status | round={round} | epoch {cur:.2f}/{target:.2f} | "
                    "epochs_to_next={ep:.2f} | minutes_to_next={mins:.1f}"
                ).format(
                    round=round_number_preview,
                    cur=current_epoch_preview,
                    target=boundaries_preview['target_epoch'],
                    ep=epochs_to_target,
                    mins=minutes_to_target,
                )
            )

            # Removed: Round 1 burn-all override
        except Exception as e:
            bt.logging.debug(f"Round status preview failed: {e}")

        # ═══════════════════════════════════════════════════════
        # PRE-GENERATION: Generate all tasks at the beginning
        # ═══════════════════════════════════════════════════════
        # Mark that this validator has started its first round
        try:
            self.forward_count = int(getattr(self, "forward_count", 0)) + 1
        except Exception:
            self.forward_count = 1
        # Pre-generation start; omit noisy log on every forward start

        pre_generation_start = time.time()
        all_tasks: list[TaskWithProject] = []

        # Try to resume from previous round state
        resumed = False
        state = self._load_round_state(current_block=current_block)
        if state and state.get("validator_round_id"):
            try:
                cached = list(getattr(self, "_all_tasks_cache", []) or [])
                if cached:
                    all_tasks.extend(cached)
                if all_tasks:
                    self.current_round_id = state["validator_round_id"]
                    resumed = True
                    bt.logging.info(
                        f"♻️ Resumed {len(all_tasks)} tasks; validator_round_id={self.current_round_id}"
                    )
                else:
                    bt.logging.warning(
                        "Resume checkpoint had 0 tasks; generating new tasks."
                    )
            except Exception as e:
                bt.logging.warning(f"Resume failed to restore tasks from checkpoint: {e}")
                # fall through to fresh generation

        # Emit a concise decision line for resume diagnostics
        try:
            info = getattr(self, "_last_resume_info", None) or {"status": "unknown"}
            if resumed:
                bt.logging.info(f"Resume decision: used prior state ({info})")
            else:
                bt.logging.info(f"Resume decision: fresh start ({info})")
        except Exception:
            pass

        if not resumed:
            try:
                self._reset_iwap_round_state()
            except Exception:
                self._reset_consensus_state()

        # Early round header with identifiers for clear traceability
        try:
            # Compute round number at current block
            round_header_block = current_block
            round_number_header = await self.round_manager.calculate_round(round_header_block)

            # Prefer resumed validator_round_id when available; otherwise, show the planned ID
            planned_round_id = None
            try:
                planned_round_id = self._generate_validator_round_id(current_block=round_header_block)
            except Exception:
                planned_round_id = None

            rid = getattr(self, "current_round_id", None) or planned_round_id or "<unknown>"

            # Validator identity (uid + hotkey short)
            uid = getattr(self, "uid", None)
            hotkey = getattr(getattr(self, "wallet", None), "hotkey", None)
            hk = getattr(hotkey, "ss58_address", None) or "<unknown>"
            hk_short = f"{hk[:8]}...{hk[-8:]}" if isinstance(hk, str) and len(hk) > 20 else hk

            # Optional human-readable validator name from config
            vname = VALIDATOR_NAME or "<unnamed>"

            bt.logging.info(
                (
                    "🏁 Round header | round={round} | validator_uid={uid} | hotkey={hk} | "
                    "validator_round_id={rid} | resumed={resumed} | name={vname}"
                ).format(
                    round=round_number_header,
                    uid=uid,
                    hk=hk_short,
                    rid=rid,
                    resumed=bool(resumed),
                    vname=vname,
                )
            )
        except Exception as e:
            bt.logging.debug(f"Round header logging failed: {e}")

        # Guard: if this is a fresh start and the current round is already too far
        # progressed, skip this round and wait for the next boundary.
        try:
            if not resumed:
                frac = float(self.round_manager.fraction_elapsed(current_block))
                bounds = self.round_manager.get_round_boundaries(current_block, log_debug=False)
                blocks_to_target = max(bounds['target_block'] - current_block, 0)
                # If we're exactly at the previous boundary (0 blocks remaining), treat as new round start (do not skip)
                at_boundary = (blocks_to_target == 0)
                if (not at_boundary) and (frac >= float(SKIP_ROUND_IF_STARTED_AFTER_FRACTION)):
                    minutes_remaining = (blocks_to_target * self.round_manager.SECONDS_PER_BLOCK) / 60
                    ColoredLogger.warning(
                        (
                            f"⏭️ Fresh start late in round: {frac*100:.1f}% >= "
                            f"{float(SKIP_ROUND_IF_STARTED_AFTER_FRACTION)*100:.0f}% — skipping to next round"
                        ),
                        ColoredLogger.YELLOW,
                    )
                    ColoredLogger.info(
                        f"   Waiting ~{minutes_remaining:.1f}m to next boundary...",
                        ColoredLogger.YELLOW,
                    )
                    # Wait until next target epoch without touching IWAP or round state
                    await self._wait_until_next_round_boundary()
                    return
        except Exception:
            # Never block the loop on this guard
            pass

        if not resumed:
            # Fresh generation path
            tasks_generated = 0
            while tasks_generated < PRE_GENERATED_TASKS:
                batch_start = time.time()

                batch_tasks = await get_task_collection_interleaved(prompts_per_use_case=PROMPTS_PER_USECASE)

                remaining = PRE_GENERATED_TASKS - tasks_generated
                tasks_to_add = batch_tasks[:remaining]
                all_tasks.extend(tasks_to_add)
                tasks_generated += len(tasks_to_add)

                batch_elapsed = time.time() - batch_start
                bt.logging.debug(
                    f"Generated batch: {len(tasks_to_add)} in {batch_elapsed:.1f}s "
                    f"(total {tasks_generated}/{PRE_GENERATED_TASKS})"
                )

            self.current_round_id = self._generate_validator_round_id(current_block=current_block)
            self.round_start_timestamp = pre_generation_start
            # Save initial state with tasks for crash-resume
            try:
                self._save_round_state(tasks=all_tasks)
            except Exception:
                pass

        # Build IWAP tasks from TaskWithProject list
        self.current_round_tasks = self._build_iwap_tasks(
            validator_round_id=self.current_round_id,
            tasks=all_tasks,
        )

        pre_generation_elapsed = time.time() - pre_generation_start
        bt.logging.info(
            f"✅ Task list ready: {len(all_tasks)} tasks in {pre_generation_elapsed:.1f}s (resumed={resumed})"
        )

        # ═══════════════════════════════════════════════════════
        # START ROUND HANDSHAKE: Send StartRoundSynapse ONCE
        # ═══════════════════════════════════════════════════════

        # Initialize new round in RoundManager (logs sync math once)
        self.round_manager.start_new_round(current_block)
        boundaries = self.round_manager.get_current_boundaries()
        # If not resuming, reset ephemeral structures; if resuming, keep loaded ones
        if not resumed:
            self.round_handshake_payloads = {}
            self.current_agent_runs = {}
            self.current_miner_snapshots = {}
            self.agent_run_accumulators = {}
            # Reset handshake flag for new round
            self._phases["handshake_sent"] = False

        # Send StartRoundSynapse to all miners ONCE at the beginning
        try:
            # Check if we already sent handshake in this round (via checkpoint)
            # Use phase flag to track if handshake was sent, not the presence of responses
            has_prior_handshake = resumed and self._phases.get("handshake_sent", False)

            handshake_responses = []

            if has_prior_handshake:
                # We already sent handshake before crash, use saved state
                ColoredLogger.info(
                    f"🤝 Handshake: using saved state (active_miners={len(self.active_miner_uids)}, already sent before restart)",
                    ColoredLogger.CYAN,
                )
                # Skip sending synapse; use saved state
                pass
            else:
                # First time sending handshake in this round - BUILD AND SEND
                ColoredLogger.info(f"🤝 Handshake: sending to {len(self.metagraph.uids)} miners...", ColoredLogger.CYAN)

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

                # 🔍 DEBUG: Show exactly what we're sending
                bt.logging.debug("=" * 80)
                bt.logging.debug("StartRoundSynapse content:")
                bt.logging.debug(f"  - version: {start_synapse.version}")
                bt.logging.debug(f"  - round_id: {start_synapse.round_id}")
                bt.logging.debug(f"  - validator_id: {start_synapse.validator_id}")
                bt.logging.debug(f"  - total_prompts: {start_synapse.total_prompts}")
                bt.logging.debug(f"  - prompts_per_use_case: {start_synapse.prompts_per_use_case}")
                bt.logging.debug(f"  - note: {start_synapse.note}")
                bt.logging.debug(f"  - has_rl: {getattr(start_synapse, 'has_rl', 'NOT_SET')}")
                bt.logging.debug(f"  - Sending to {len(all_axons)} miners")
                bt.logging.debug("=" * 80)

                handshake_responses = await send_start_round_synapse_to_miners(
                    validator=self,
                    miner_axons=all_axons,
                    start_synapse=start_synapse,
                    timeout=60,
                )

            # Filter and save UIDs of miners who responded successfully (normalize metadata)
            if not resumed:
                self.active_miner_uids = []

            def _normalized_optional(value):
                if value is None:
                    return None
                text = str(value).strip()
                return text or None

            def _truncate_agent_name(name: str) -> str:
                if MAX_MINER_AGENT_NAME_LENGTH and len(name) > MAX_MINER_AGENT_NAME_LENGTH:
                    bt.logging.debug(
                        f"Truncating agent name '{name}' to {MAX_MINER_AGENT_NAME_LENGTH} characters."
                    )
                    return name[:MAX_MINER_AGENT_NAME_LENGTH]
                return name

            # Filter successful responses - collect data without spamming logs
            successful_miners = []
            for i, response in enumerate(handshake_responses):
                if i >= len(all_axons):
                    continue

                mapped_uid = all_uids[i]
                if not response:
                    continue

                status_code = getattr(getattr(response, "dendrite", None), "status_code", None)
                status_numeric: int | None = None
                if status_code is not None:
                    try:
                        status_numeric = int(status_code)
                    except (TypeError, ValueError):
                        status_numeric = None
                if status_numeric is not None and status_numeric >= 400:
                    continue

                agent_name_raw = getattr(response, "agent_name", None)
                agent_name = _normalized_optional(agent_name_raw)
                if not agent_name:
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

                # Collect for table display
                successful_miners.append({
                    'uid': mapped_uid,
                    'agent': agent_name,
                    'version': getattr(response, 'agent_version', 'N/A'),
                    'rl': 'Yes' if getattr(response, 'has_rl', False) else 'No',
                    'hotkey': self.metagraph.hotkeys[mapped_uid][:10] + '...'
                })

            # Display results in a clean table format (only if we sent handshake)
            if not has_prior_handshake and successful_miners:
                bt.logging.info("=" * 100)
                bt.logging.info("📋 MINERS WHO RESPONDED TO HANDSHAKE:")
                bt.logging.info("=" * 100)
                bt.logging.info(f"{'UID':<6} | {'Agent Name':<20} | {'Version':<10} | {'RL':<4} | {'Hotkey':<15}")
                bt.logging.info("-" * 100)
                for m in successful_miners:
                    bt.logging.info(f"{m['uid']:<6} | {m['agent']:<20} | {m['version']:<10} | {m['rl']:<4} | {m['hotkey']:<15}")
                bt.logging.info("=" * 100)

            # Log results only if we actually sent the handshake (not when using saved state)
            if not has_prior_handshake:
                if self.active_miner_uids:
                    ColoredLogger.success(
                        f"✅ Handshake sent: {len(self.active_miner_uids)}/{len(all_axons)} miners responded",
                        ColoredLogger.GREEN,
                    )
                else:
                    ColoredLogger.warning(
                        f"⚠️ Handshake sent: 0/{len(all_axons)} miners responded", ColoredLogger.YELLOW
                    )

            # Mark that handshake was sent (for resume logic)
            # This flag prevents re-sending handshake after restart, regardless of responses
            # Only mark if we actually sent it (not if we skipped due to prior handshake)
            if not has_prior_handshake:
                self._phases["handshake_sent"] = True

            # Persist handshake state for resume
            try:
                self._save_round_state()
            except Exception:
                pass

        except Exception as e:
            bt.logging.error(f"StartRoundSynapse handshake failed: {e}")
            # Do NOT silently use all miners; skip task execution if no handshake
            self.active_miner_uids = []
            bt.logging.warning("No miners will be used this round due to handshake failure.")

        # Early audit log of round info
        round_number = await self.round_manager.calculate_round(current_block)
        start_epoch = boundaries['round_start_epoch']
        target_epoch = boundaries['target_epoch']
        blocks_remaining = boundaries['target_block'] - current_block
        minutes_remaining = (blocks_remaining * self.round_manager.SECONDS_PER_BLOCK) / 60
        bt.logging.info(
            (
                "Round init: validator_round_id={rid}, round={round}, "
                "start_block={blk}, start_epoch={start:.2f} -> target_epoch={target:.2f} (~{mins:.1f}m)"
            ).format(
                rid=self.current_round_id,
                round=round_number,
                blk=current_block,
                start=start_epoch,
                target=target_epoch,
                mins=max(minutes_remaining, 0.0),
            )
        )

        # If no miners are active, skip task loop and finish round gracefully
        if not self.active_miner_uids:
            ColoredLogger.warning("⚠️ No active miners after handshake; skipping tasks and finalizing round.", ColoredLogger.YELLOW)
            await self._calculate_final_weights(0)
            return

        await self._iwap_start_round(current_block=current_block, n_tasks=len(all_tasks))

        # If resuming and we have prior evaluations, rebuild accumulators and round aggregates
        if resumed and getattr(self, "_eval_records", None):
            ColoredLogger.info(
                f"♻️ Resume: rebuilding accumulators from {len(self._eval_records)} evaluations",
                ColoredLogger.CYAN,
            )
            # Ensure round_manager has been initialized with this round
            try:
                self._rebuild_from_saved_evaluations()
                ColoredLogger.success("✅ Resume: accumulators restored", ColoredLogger.GREEN)
            except Exception as e:
                bt.logging.warning(f"Resume rebuild failed: {e}")

        # ═══════════════════════════════════════════════════════
        # DYNAMIC LOOP: Execute tasks one by one based on time
        # ═══════════════════════════════════════════════════════
        ColoredLogger.info("🔄 Starting dynamic task execution", ColoredLogger.MAGENTA)

        task_index = 0
        tasks_completed = 0

        # Dynamic loop: consume pre-generated tasks and check AFTER evaluating
        while task_index < len(all_tasks):
            current_block = self.metagraph.block.item()
            current_epoch = self.round_manager.block_to_epoch(current_block)
            boundaries = self.round_manager.get_current_boundaries()
            wait_info = self.round_manager.get_wait_info(current_block)

            ColoredLogger.info(
                f"📍 Task {task_index + 1}/{len(all_tasks)} | "
                f"epoch {current_epoch:.2f}/{boundaries['target_epoch']} | "
                f"remaining {wait_info['minutes_remaining']:.1f}m",
                ColoredLogger.CYAN,
            )

            # Resume optimization: if every active miner already completed this task, skip re-sending
            try:
                # Find the IWAP task_id for this index (sequence)
                target_task_id = None
                for _tid, _payload in (self.current_round_tasks or {}).items():
                    if getattr(_payload, "sequence", None) == task_index:
                        target_task_id = _tid
                        break
                if target_task_id is None:
                    # Fallback to Task object's id if present
                    target_task_id = getattr(all_tasks[task_index].task, "id", None)

                if target_task_id is not None and getattr(self, "_completed_pairs", None) is not None and self.active_miner_uids:
                    all_done = all((uid, target_task_id) in self._completed_pairs for uid in self.active_miner_uids)  # type: ignore[attr-defined]
                    if all_done:
                        ColoredLogger.info(
                            f"⏭️ Skipping task {task_index + 1}: already completed by all active miners",
                            ColoredLogger.YELLOW,
                        )
                        tasks_completed += 1
                        task_index += 1
                        continue
            except Exception:
                # Never block the round on resume optimizations
                pass

            # Execute single task
            task_sent = await self._send_task_and_evaluate(all_tasks[task_index], task_index)
            if task_sent:
                tasks_completed += 1
            task_index += 1

            # Persist checkpoint after each task iteration (covers any missed per-miner writes)
            try:
                self.state_manager.save_checkpoint()
            except Exception:
                pass

            # Dynamic check: should we send another task?
            # Refresh block height after evaluation to get an accurate time window
            current_block = self.metagraph.block.item()
            # Compute fractional progress for reserved-window stop
            try:
                boundaries_now = self.round_manager.get_round_boundaries(current_block, log_debug=False)
                rsb = boundaries_now['round_start_block']
                tb = boundaries_now['target_block']
                bt_total = max(tb - rsb, 1)
                bt_done = max(current_block - rsb, 0)
                progress_frac = min(max(bt_done / bt_total, 0.0), 1.0)
            except Exception:
                progress_frac = 0.0
            if ENABLE_DISTRIBUTED_CONSENSUS and not self._consensus_published and (progress_frac >= float(STOP_TASK_EVALUATION_AT_ROUND_FRACTION)):
                ColoredLogger.error(
                    "\n" + "=" * 80,
                    ColoredLogger.RED,
                )
                ColoredLogger.error(
                    f"🛑🛑🛑 STOP FRACTION REACHED: {STOP_TASK_EVALUATION_AT_ROUND_FRACTION:.0%} 🛑🛑🛑",
                    ColoredLogger.RED,
                )
                ColoredLogger.error(
                    f"📤📤📤 PUBLISHING TO IPFS NOW WITH {tasks_completed} TASKS 📤📤📤",
                    ColoredLogger.RED,
                )
                ColoredLogger.error(
                    f"⏸️⏸️⏸️  HALTING ALL TASK EXECUTION ⏸️⏸️⏸️",
                    ColoredLogger.RED,
                )
                ColoredLogger.error(
                    "=" * 80 + "\n",
                    ColoredLogger.RED,
                )
                try:
                    round_number = await self.round_manager.calculate_round(current_block)
                    st = await self._get_async_subtensor()
                    await publish_round_snapshot(
                        validator=self,
                        st=st,
                        round_number=round_number,
                        tasks_completed=tasks_completed,
                    )
                    self._consensus_published = True
                    ColoredLogger.success(
                        "\n" + "=" * 80,
                        ColoredLogger.GREEN,
                    )
                    ColoredLogger.success(
                        f"✅✅✅ IPFS PUBLISH COMPLETE - NOW WAITING ✅✅✅",
                        ColoredLogger.GREEN,
                    )
                    ColoredLogger.success(
                        "=" * 80 + "\n",
                        ColoredLogger.GREEN,
                    )
                except Exception as e:
                    bt.logging.warning(f"Consensus publish (reserved-start) failed: {e}")
                break
            if not self.round_manager.should_send_next_task(current_block):
                ColoredLogger.warning(
                    "🛑 Stopping task execution: safety buffer reached",
                    ColoredLogger.YELLOW,
                )
                ColoredLogger.info(
                    f"   epoch={current_epoch:.2f}, remaining={wait_info['seconds_remaining']:.0f}s, "
                    f"buffer={SAFETY_BUFFER_EPOCHS} epochs, tasks={tasks_completed}/{len(all_tasks)}",
                    ColoredLogger.YELLOW,
                )
                try:
                    # Provide explicit context about what the target is (end-of-round)
                    bounds_ctx = self.round_manager.get_round_boundaries(current_block, log_debug=False)
                    target_epoch_ctx = bounds_ctx['target_epoch']
                    target_block_ctx = bounds_ctx['target_block']
                    round_no_ctx = await self.round_manager.calculate_round(current_block)
                    ColoredLogger.info(
                        (
                            f"   Waiting for end-of-round target epoch to set weights | "
                            f"round={round_no_ctx} | target_epoch={target_epoch_ctx:.2f} | target_block={target_block_ctx}"
                        ),
                        ColoredLogger.YELLOW,
                    )
                except Exception:
                    ColoredLogger.info("   Waiting for end-of-round target epoch to set weights", ColoredLogger.YELLOW)
                # Save state just before entering wait phase
                try:
                    self.state_manager.save_checkpoint()
                except Exception:
                    pass
                # Try to publish commitments if sharing and not yet published.
                if ENABLE_DISTRIBUTED_CONSENSUS and not self._consensus_published:
                    try:
                        round_number = await self.round_manager.calculate_round(current_block)
                        st = await self._get_async_subtensor()
                        await publish_round_snapshot(
                            validator=self,
                            st=st,
                            round_number=round_number,
                            tasks_completed=tasks_completed,
                        )
                        self._consensus_published = True
                        try:
                            self.state_manager.save_checkpoint()
                        except Exception:
                            pass
                    except Exception as e:
                        bt.logging.warning(f"Consensus publish (buffer) failed: {e}")
                break

        # ═══════════════════════════════════════════════════════
        # PUBLISH IF NOT DONE YET
        # If we completed all tasks before reaching 50%, publish NOW
        # This ensures round_number and validator_round_id match
        # ═══════════════════════════════════════════════════════
        if ENABLE_DISTRIBUTED_CONSENSUS and not self._consensus_published:
            ColoredLogger.error(
                "\n" + "=" * 80,
                ColoredLogger.RED,
            )
            ColoredLogger.error(
                f"📤📤📤 ALL TASKS DONE - PUBLISHING TO IPFS NOW 📤📤📤",
                ColoredLogger.RED,
            )
            ColoredLogger.error(
                f"📦 Tasks completed: {tasks_completed}/{len(all_tasks)}",
                ColoredLogger.RED,
            )
            ColoredLogger.error(
                "=" * 80 + "\n",
                ColoredLogger.RED,
            )
            try:
                current_block = self.metagraph.block.item()
                round_number = await self.round_manager.calculate_round(current_block)
                st = await self._get_async_subtensor()
                await publish_round_snapshot(
                    validator=self,
                    st=st,
                    round_number=round_number,
                    tasks_completed=tasks_completed,
                )
                self._consensus_published = True
                ColoredLogger.success(
                    "\n" + "=" * 80,
                    ColoredLogger.GREEN,
                )
                ColoredLogger.success(
                    f"✅✅✅ IPFS PUBLISH COMPLETE ✅✅✅",
                    ColoredLogger.GREEN,
                )
                ColoredLogger.success(
                    "=" * 80 + "\n",
                    ColoredLogger.GREEN,
                )
            except Exception as e:
                bt.logging.error(f"Consensus publish (post-tasks) failed: {e}")

        # ═══════════════════════════════════════════════════════
        # WAIT FOR TARGET EPOCH: Wait until the round ends
        # Always wait (for IPFS propagation and consensus), even if all tasks done
        # ═══════════════════════════════════════════════════════
        # Ensure we persist the checkpoint right before the wait window
        try:
            self.state_manager.save_checkpoint()
        except Exception:
            pass

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

            # 🔍 DEBUG: Log task details before sending
            ColoredLogger.debug("\n" + "=" * 80, ColoredLogger.CYAN)
            ColoredLogger.debug(f"🔍 TASK DETAILS - Task {task_index + 1}/{len(self.current_round_tasks)}", ColoredLogger.CYAN)
            ColoredLogger.debug("=" * 80, ColoredLogger.CYAN)
            ColoredLogger.debug(f"  📝 Prompt: {task.prompt}", ColoredLogger.BLUE)
            ColoredLogger.debug(f"  🌐 URL: {project.frontend_url}", ColoredLogger.BLUE)
            ColoredLogger.debug(f"  🎲 Seed: {seed}", ColoredLogger.BLUE)
            ColoredLogger.debug(f"  📦 Project: {web_project_name}", ColoredLogger.BLUE)
            ColoredLogger.debug(f"  🧪 Tests ({len(task.tests) if task.tests else 0}):", ColoredLogger.YELLOW)
            if task.tests:
                for test_idx, test in enumerate(task.tests, 1):
                    ColoredLogger.debug(f"     {test_idx}. {test.type}: {test.description}", ColoredLogger.GRAY)
                    ColoredLogger.debug(f"        Criteria: {getattr(test, 'event_criteria', 'N/A')}", ColoredLogger.GRAY)
            else:
                ColoredLogger.debug(f"     No tests for this task", ColoredLogger.GRAY)

            # 🔍 DEBUG: Log URL construction details
            ColoredLogger.debug(f"  🔗 URL Construction Details:", ColoredLogger.MAGENTA)
            ColoredLogger.debug(f"     - Base URL: {project.frontend_url}", ColoredLogger.MAGENTA)
            ColoredLogger.debug(f"     - Task URL: {getattr(task, 'url', 'N/A')}", ColoredLogger.MAGENTA)
            ColoredLogger.debug(f"     - Task assign_seed: {getattr(task, 'assign_seed', 'N/A')}", ColoredLogger.MAGENTA)
            ColoredLogger.debug(f"     - Final seed to use: {seed}", ColoredLogger.MAGENTA)

            ColoredLogger.debug("=" * 80 + "\n", ColoredLogger.CYAN)

            # Create TaskSynapse with the actual task
            # 🔧 FIX: Include seed in URL if available
            task_url = project.frontend_url
            if seed is not None:
                separator = "&" if "?" in task_url else "?"
                task_url = f"{task_url}{separator}seed={seed}"

            task_synapse = TaskSynapse(
                version=self.version,
                prompt=task.prompt,
                url=task_url,  # URL with seed included
                screenshot=None,  # Optional: could add screenshot support
                seed=seed,  # Also send seed separately for debugging
                web_project_name=web_project_name,
            )

            # 🔍 DEBUG: Log TaskSynapse details
            ColoredLogger.debug(f"  📤 TaskSynapse created:", ColoredLogger.MAGENTA)
            ColoredLogger.debug(f"     - Base URL: {project.frontend_url}", ColoredLogger.MAGENTA)
            ColoredLogger.debug(f"     - Final URL: {task_synapse.url}", ColoredLogger.MAGENTA)
            ColoredLogger.debug(f"     - Seed: {task_synapse.seed}", ColoredLogger.MAGENTA)
            ColoredLogger.debug(f"     - Prompt: {task_synapse.prompt[:100]}...", ColoredLogger.MAGENTA)

            # 🔍 DEBUG: Verify URL construction
            if seed is not None and f"seed={seed}" in task_synapse.url:
                ColoredLogger.debug(f"     ✅ URL includes seed correctly", ColoredLogger.GREEN)
            elif seed is not None:
                ColoredLogger.debug(f"     URL missing seed (expected seed={seed})", ColoredLogger.GRAY)

            # Send task to miners
            responses = await send_task_synapse_to_miners(
                validator=self,
                miner_axons=active_axons,
                task_synapse=task_synapse,
                timeout=120,
            )

            # Process responses and calculate rewards
            task_solutions, execution_times = collect_task_solutions_and_execution_times(
                task=task,
                responses=responses,
                miner_uids=list(self.active_miner_uids),
            )

            # 🔍 DEBUG: Log received actions from each miner
            ColoredLogger.debug("\n" + "=" * 80, ColoredLogger.CYAN)
            ColoredLogger.debug("🔍 ACTIONS RECEIVED FROM MINERS", ColoredLogger.CYAN)
            ColoredLogger.debug("=" * 80, ColoredLogger.CYAN)
            for i, (uid, solution) in enumerate(zip(self.active_miner_uids, task_solutions)):
                if solution and solution.actions:
                    ColoredLogger.debug(f"\n📊 Miner UID={uid}: {len(solution.actions)} actions", ColoredLogger.GREEN)
                    for j, action in enumerate(solution.actions, 1):
                        ColoredLogger.debug(f"  {j}. {action.type}: {vars(action)}", ColoredLogger.GRAY)

                        # 🔍 DEBUG: Check for seed discrepancies in NavigateAction
                        if hasattr(action, 'url') and action.url and action.type == 'NavigateAction':
                            ColoredLogger.debug(f"     🔗 Navigation URL: {action.url}", ColoredLogger.MAGENTA)

                            # Check seed presence and correctness
                            if seed is not None:  # Only validate if task has assigned seed
                                if 'seed=' in action.url:
                                    action_seed = action.url.split('seed=')[1].split('&')[0].split('?')[0]
                                    if action_seed != str(seed):
                                        ColoredLogger.warning(
                                            f"     ⚠️ Seed MISMATCH: expected seed={seed}, got seed={action_seed} (will score 0)",
                                            ColoredLogger.YELLOW
                                        )
                                    else:
                                        ColoredLogger.debug(f"     ✅ Seed matches: {action_seed}", ColoredLogger.GREEN)
                                else:
                                    # Seed is missing from NavigateAction URL
                                    ColoredLogger.warning(
                                        f"     ⚠️ Seed MISSING: expected seed={seed} in URL (will score 0)",
                                        ColoredLogger.RED
                                    )

                            # Check URL path discrepancies
                            expected_base = project.frontend_url.rstrip('/')
                            if not action.url.startswith(expected_base):
                                ColoredLogger.debug(f"     ⚠️ URL base mismatch: expected {expected_base}", ColoredLogger.GRAY)
                                ColoredLogger.debug(f"     Got URL: {action.url}", ColoredLogger.GRAY)
                            else:
                                ColoredLogger.debug(f"     ✅ URL base matches: {expected_base}", ColoredLogger.GREEN)
                else:
                    ColoredLogger.warning(f"\n📊 Miner UID={uid}: NO ACTIONS", ColoredLogger.YELLOW)
            ColoredLogger.debug("=" * 80 + "\n", ColoredLogger.CYAN)

            # Evaluate task solutions
            ColoredLogger.debug("🔍 STARTING EVALUATION...", ColoredLogger.CYAN)
            eval_scores, test_results_list, evaluation_results = await evaluate_task_solutions(
                web_project=project,
                task=task,
                task_solutions=task_solutions,
                execution_times=execution_times,
            )

            # 🔍 DEBUG: Log evaluation results in detail
            ColoredLogger.debug("\n" + "=" * 80, ColoredLogger.CYAN)
            ColoredLogger.debug("🔍 EVALUATION RESULTS DETAILED", ColoredLogger.CYAN)
            ColoredLogger.debug("=" * 80, ColoredLogger.CYAN)
            for i, uid in enumerate(self.active_miner_uids):
                ColoredLogger.debug(f"\n📊 Miner UID={uid}:", ColoredLogger.MAGENTA)
                ColoredLogger.debug(f"  📈 Eval Score: {eval_scores[i]:.4f}", ColoredLogger.GREEN)
                ColoredLogger.debug(f"  ⏱️  Execution Time: {execution_times[i]:.2f}s", ColoredLogger.BLUE)

                # Show evaluation_result but replace GIF content with just its length
                eval_result_display = evaluation_results[i].copy()
                if 'gif_recording' in eval_result_display and eval_result_display['gif_recording']:
                    eval_result_display['gif_recording'] = f"<length: {len(eval_result_display['gif_recording'])}>"

                ColoredLogger.debug(f"  📋 Evaluation Result: {eval_result_display}", ColoredLogger.YELLOW)

                # Show error message if present (e.g. seed validation failures)
                error_msg = evaluation_results[i].get("error_message", "")
                if error_msg:
                    ColoredLogger.warning(f"  ⚠️ Error: {error_msg}", ColoredLogger.RED)

                ColoredLogger.debug(f"  🧪 Test Results ({len(test_results_list[i])} tests):", ColoredLogger.CYAN)
                if test_results_list[i]:
                    for test_idx, test_result in enumerate(test_results_list[i], 1):
                        success = test_result.get("success", False)
                        status_emoji = "✅" if success else "❌"
                        extra_data = test_result.get("extra_data", {})

                        # Show test type and criteria from extra_data
                        test_type = extra_data.get("type", "Unknown")
                        event_name = extra_data.get("event_name", "N/A")

                        ColoredLogger.debug(f"     Test {test_idx}: {status_emoji} {test_type} - Event: {event_name}", ColoredLogger.GRAY)
                        if extra_data.get("event_criteria"):
                            ColoredLogger.debug(f"        Criteria: {extra_data.get('event_criteria')}", ColoredLogger.GRAY)
                else:
                    ColoredLogger.warning(f"     ⚠️  NO TEST RESULTS", ColoredLogger.RED)
            ColoredLogger.debug("=" * 80 + "\n", ColoredLogger.CYAN)

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
                    test_results_list=test_results_list,
                    evaluation_results=evaluation_results,
                    web_project_name=web_project_name or "Unknown",
                )
            except Exception as e:
                bt.logging.warning(f"Feedback failed: {e}")

            try:
                await self._iwap_submit_task_results(
                    task_item=task_item,
                    task_solutions=task_solutions,
                    eval_scores=eval_scores,
                    test_results_list=test_results_list,
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

        # reached target: minimal separator not needed

    async def _wait_until_next_round_boundary(self) -> None:
        """Wait until the end of the current (global) round window.

        This helper does not depend on round_manager.start_block, so it can be
        used before a round is initialized, e.g., when skipping a late fresh start.
        """
        # Fix the boundary at entry time to avoid jumping to the next window
        start_block_snapshot = self.subtensor.get_current_block()
        initial_bounds = self.round_manager.get_round_boundaries(start_block_snapshot, log_debug=False)
        fixed_start_block = int(initial_bounds['round_start_block'])
        fixed_target_block = int(initial_bounds['target_block'])
        fixed_target_epoch = float(initial_bounds['target_epoch'])

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

                # Progress within the FIXED window
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
                            "Waiting — next round boundary (global) — epoch {cur:.3f}/{target:.3f} ({pct:.2f}%) | "
                            "~{mins:.1f}m left — holding until block {target_blk} before carrying scores forward"
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
            except Exception:
                # Conservative sleep if anything goes wrong
                pass

            await asyncio.sleep(12)

    async def _calculate_final_weights(self, tasks_completed: int):
        """Calculate averages, apply WTA, set weights"""
        ColoredLogger.info("🏁 Phase: SetWeights — Calculating final weights", ColoredLogger.PURPLE)
        bt.logging.info(f"Distributed consensus active: {str(ENABLE_DISTRIBUTED_CONSENSUS).lower()}")

        # Check if no miners responded to handshake - BURN ALL WEIGHTS
        if not self.active_miner_uids:
            ColoredLogger.error("🔥 No active miners: burning all weights", ColoredLogger.RED)

            # Create burn weights: UID BURN_UID = 1.0, all others = 0.0
            burn_weights = np.zeros(self.metagraph.n, dtype=np.float32)
            idx = int(BURN_UID) if 0 <= int(BURN_UID) < self.metagraph.n else min(5, self.metagraph.n - 1)
            burn_weights[idx] = 1.0  # burn recipient

            # Update scores via standard path to keep behavior consistent
            all_uids = list(range(self.metagraph.n))
            self.update_scores(rewards=burn_weights, uids=all_uids)
            self.set_weights()

            ColoredLogger.success(f"✅ Burn complete (weight to UID {idx})", ColoredLogger.RED)
            ColoredLogger.info(f"Tasks attempted: {tasks_completed}", ColoredLogger.RED)
            return

        # Calculate average scores using round_manager
        avg_rewards = self.round_manager.get_average_rewards()

        # If sharing enabled, attempt to aggregate across validators via commitments/IPFS
        if ENABLE_DISTRIBUTED_CONSENSUS:
            try:
                boundaries = self.round_manager.get_current_boundaries()
                bt.logging.info("🤝 Consensus aggregation — preparing final scores")
                # Prefer cached mid-settlement aggregation if available
                agg = self._agg_scores_cache or {}
                if not agg:
                    bt.logging.debug("No cached aggregation; fetching now")
                    # Natural gap between STOP and FETCH ensures propagation
                    st = await self._get_async_subtensor()
                    agg = await aggregate_scores_from_commitments(
                        validator=self,
                        st=st,
                        start_epoch=boundaries['round_start_epoch'],
                        target_epoch=boundaries['target_epoch'],
                    )
                if agg:
                    ColoredLogger.info(
                        f"🤝 Using aggregated scores from commitments ({len(agg)} miners)",
                        ColoredLogger.CYAN,
                    )
                    avg_rewards = agg
                else:
                    ColoredLogger.warning("No aggregated scores available; using local averages.", ColoredLogger.YELLOW)
            except Exception as e:
                bt.logging.warning(f"Aggregation failed; using local averages: {e}")

        # If all miners have non-positive average scores, burn all weights and exit
        try:
            has_positive = any((float(s) > 0.0) for s in (avg_rewards or {}).values())
        except Exception:
            has_positive = False
        if not has_positive:
            ColoredLogger.error("🔥 All miners scored <= 0: burning all weights", ColoredLogger.RED)
            # Zero-out via standard update_scores path to keep flow consistent
            zero_vec = np.zeros(self.metagraph.n, dtype=np.float32)
            all_uids = list(range(self.metagraph.n))
            self.update_scores(rewards=zero_vec, uids=all_uids)
            self.set_weights()
            ColoredLogger.success("✅ Burn complete (no winners)", ColoredLogger.RED)
            ColoredLogger.info(f"Tasks attempted: {tasks_completed}", ColoredLogger.RED)
            return

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
        bt.logging.info("🎯 Final weights (WTA)")
        winner_uid = max(final_rewards_dict.keys(), key=lambda k: final_rewards_dict[k]) if final_rewards_dict else None
        if winner_uid is not None:
            hotkey = self.metagraph.hotkeys[winner_uid] if winner_uid < len(self.metagraph.hotkeys) else "<unknown>"
            bt.logging.info(
                f"🏆 Winner uid={winner_uid}, hotkey={hotkey[:10]}..., weight={final_rewards_dict[winner_uid]:.4f}"
            )
        else:
            bt.logging.info("❌ No miners evaluated.")

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
        self.set_weights()

        try:
            await self._finish_iwap_round(
                avg_rewards=avg_rewards,
                final_weights=final_rewards_dict,
                tasks_completed=tasks_completed,
            )
        except Exception as e:
            bt.logging.warning(f"IWAP finish_round failed: {e}")

        ColoredLogger.success("✅ Round complete", ColoredLogger.GREEN)
        ColoredLogger.info(f"Tasks completed: {tasks_completed}", ColoredLogger.GREEN)


if __name__ == "__main__":
    # Optional IWA bootstrap: only skip when the package is missing
    try:
        AppBootstrap()
        # IWA logging works with loguru
        logger.remove()
        logger.add("logfile.log", level="INFO")
        logger.add(lambda msg: print(msg, end=""), level="WARNING")
    except ImportError as e:
        bt.logging.warning("Autoppia_iwa init failed")
        raise e

    with Validator(config=config(role="validator")) as validator:
        validator.run()
