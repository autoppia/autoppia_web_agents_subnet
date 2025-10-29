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
from rich.console import Console
from rich.table import Table
from rich import box
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
        # Track if final weights + IWAP finish_round were already sent this round
        self._finalized_this_round: bool = False

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
        # Get current block and prevent early round execution
        # Use live chain height, not metagraph.block (which updates only on sync)
        current_block = self.block

        current_round_number: int | None = None
        try:
            current_round_number = await self.round_manager.calculate_round(current_block)
            if current_round_number is not None:
                setattr(self, "_current_round_number", int(current_round_number))
        except Exception as exc:
            bt.logging.debug(f"Unable to calculate current round number: {exc}")
            current_round_number = None

        if current_round_number is not None:
            bt.logging.info(f"🚀 Starting round-based forward (round {current_round_number})")
            try:
                ColoredLogger.info(f"🚦 Starting Round: {int(current_round_number)}", ColoredLogger.GREEN)
            except Exception:
                pass
        else:
            bt.logging.info("🚀 Starting round-based forward")

        if not self.round_manager.can_start_round(current_block):
            blocks_remaining = self.round_manager.blocks_until_allowed(current_block)
            seconds_remaining = blocks_remaining * self.round_manager.SECONDS_PER_BLOCK
            minutes_remaining = seconds_remaining / 60
            hours_remaining = minutes_remaining / 60

            # Calculate current epoch and target epoch
            current_epoch = current_block / 360
            target_epoch = DZ_STARTING_BLOCK / 360

            eta = f"~{hours_remaining:.1f}h" if hours_remaining >= 1 else f"~{minutes_remaining:.0f}m"
            bt.logging.warning(f"🔒 Locked until block {DZ_STARTING_BLOCK:,} (epoch {target_epoch:.2f}) | " f"now {current_block:,} (epoch {current_epoch:.2f}) | ETA {eta}")

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
            blocks_to_target = max(boundaries_preview["target_block"] - current_block, 0)
            minutes_to_target = (blocks_to_target * self.round_manager.SECONDS_PER_BLOCK) / 60
            epochs_to_target = max(boundaries_preview["target_epoch"] - current_epoch_preview, 0.0)
            bt.logging.info(
                ("Round status | round={round} | epoch {cur:.2f}/{target:.2f} | " "epochs_to_next={ep:.2f} | minutes_to_next={mins:.1f}").format(
                    round=round_number_preview,
                    cur=current_epoch_preview,
                    target=boundaries_preview["target_epoch"],
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
                    bt.logging.info(f"♻️ Resumed {len(all_tasks)} tasks; validator_round_id={self.current_round_id}")
                else:
                    bt.logging.warning("Resume checkpoint had 0 tasks; generating new tasks.")
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
                ("🏁 Round header | round={round} | validator_uid={uid} | hotkey={hk} | " "validator_round_id={rid} | resumed={resumed} | name={vname}").format(
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
                blocks_to_target = max(bounds["target_block"] - current_block, 0)
                # If we're exactly at the previous boundary (0 blocks remaining), treat as new round start (do not skip)
                at_boundary = blocks_to_target == 0
                if (not at_boundary) and (frac >= float(SKIP_ROUND_IF_STARTED_AFTER_FRACTION)):
                    minutes_remaining = (blocks_to_target * self.round_manager.SECONDS_PER_BLOCK) / 60
                    ColoredLogger.warning(
                        (f"⏭️ Fresh start late in round: {frac * 100:.1f}% >= " f"{float(SKIP_ROUND_IF_STARTED_AFTER_FRACTION) * 100:.0f}% — skipping to next round"),
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
                bt.logging.debug(f"Generated batch: {len(tasks_to_add)} in {batch_elapsed:.1f}s " f"(total {tasks_generated}/{PRE_GENERATED_TASKS})")

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
        bt.logging.info(f"✅ Task list ready: {len(all_tasks)} tasks in {pre_generation_elapsed:.1f}s (resumed={resumed})")

        # ═══════════════════════════════════════════════════════
        # START ROUND HANDSHAKE: Send StartRoundSynapse ONCE
        # ═══════════════════════════════════════════════════════

        # Initialize new round in RoundManager (logs sync math once)
        self.round_manager.start_new_round(current_block)
        # New round: ensure finalize flag is reset
        self._finalized_this_round = False
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
                    note=f"Starting round at epoch {boundaries['round_start_epoch']}",
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
                    bt.logging.debug(f"Truncating agent name '{name}' to {MAX_MINER_AGENT_NAME_LENGTH} characters.")
                    return name[:MAX_MINER_AGENT_NAME_LENGTH]
                return name

            # Filter successful responses - collect data without spamming logs
            successful_miners = []
            miner_status_map = {}  # UID -> response data

            for i, response in enumerate(handshake_responses):
                if i >= len(all_axons):
                    continue

                mapped_uid = all_uids[i]

                # Track all miners (successful or not)
                miner_status_map[mapped_uid] = {
                    "response": response,
                    "success": False,
                    "agent_name": None,
                    "version": None,
                    "hotkey": self.metagraph.hotkeys[mapped_uid][:12] + "..." if mapped_uid < len(self.metagraph.hotkeys) else "N/A",
                }

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

                # Update status map
                miner_status_map[mapped_uid].update({"success": True, "agent_name": agent_name, "version": getattr(response, "agent_version", "N/A")})

                # Collect for backward compatibility
                successful_miners.append(
                    {
                        "uid": mapped_uid,
                        "agent": agent_name,
                        "version": getattr(response, "agent_version", "N/A"),
                        "rl": "Yes" if getattr(response, "has_rl", False) else "No",
                        "hotkey": miner_status_map[mapped_uid]["hotkey"],
                    }
                )

            # Display results in a Rich table (always show if we have miner data)
            if miner_status_map:
                try:
                    console = Console()
                    table = Table(
                        title=f"[bold magenta]🤝 Handshake Results - {len(self.active_miner_uids)}/{len(all_axons)} Miners Responded[/bold magenta]",
                        box=box.ROUNDED,
                        show_header=True,
                        header_style="bold cyan",
                        title_style="bold magenta",
                        expand=False,
                    )

                    table.add_column("Status", justify="center", style="bold", width=8)
                    table.add_column("UID", justify="right", style="cyan", width=6)
                    table.add_column("Agent Name", justify="left", style="white", width=25)
                    table.add_column("Version", justify="center", style="yellow", width=12)
                    table.add_column("Hotkey", justify="left", style="blue", width=18)

                    # Sort by UID
                    sorted_uids = sorted(miner_status_map.keys())

                    # Add ALL miners (no limit)
                    for idx, uid in enumerate(sorted_uids):
                        miner = miner_status_map[uid]

                        if miner["success"]:
                            status_icon = "[bold green]✅[/bold green]"
                            agent_name = miner["agent_name"] or "N/A"
                            version = miner["version"] or "N/A"
                            style = None
                        else:
                            status_icon = "[bold red]❌[/bold red]"
                            agent_name = "[dim]N/A[/dim]"
                            version = "[dim]N/A[/dim]"
                            style = "dim"

                        table.add_row(status_icon, str(uid), agent_name, version, miner["hotkey"], style=style)

                    console.print(table)
                    console.print()
                except Exception as e:
                    bt.logging.warning(f"Failed to render handshake table: {e}")

            # Log results only if we actually sent the handshake (not when using saved state)
            if not has_prior_handshake:
                if self.active_miner_uids:
                    ColoredLogger.success(
                        f"✅ Handshake sent: {len(self.active_miner_uids)}/{len(all_axons)} miners responded",
                        ColoredLogger.GREEN,
                    )
                else:
                    ColoredLogger.warning(f"⚠️ Handshake sent: 0/{len(all_axons)} miners responded", ColoredLogger.YELLOW)

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
        start_epoch = boundaries["round_start_epoch"]
        target_epoch = boundaries["target_epoch"]
        total_blocks = boundaries["target_block"] - boundaries["round_start_block"]
        blocks_remaining = boundaries["target_block"] - current_block
        minutes_remaining = (blocks_remaining * self.round_manager.SECONDS_PER_BLOCK) / 60

        from autoppia_web_agents_subnet.utils.log_colors import round_details_tag

        bt.logging.info("=" * 100)
        bt.logging.info(round_details_tag(f"🚀 ROUND START"))
        bt.logging.info(round_details_tag(f"Round Number: {round_number}"))
        bt.logging.info(round_details_tag(f"Validator Round ID: {self.current_round_id}"))
        bt.logging.info(round_details_tag(f"Start Block: {current_block:,}"))
        bt.logging.info(round_details_tag(f"Start Epoch: {start_epoch:.2f}"))
        bt.logging.info(round_details_tag(f"Target Epoch: {target_epoch:.2f}"))
        bt.logging.info(round_details_tag(f"Duration: ~{minutes_remaining:.1f} minutes"))
        bt.logging.info(round_details_tag(f"Total Blocks: {total_blocks}"))
        bt.logging.info(round_details_tag(f"Tasks to Execute: {len(all_tasks)}"))
        bt.logging.info(round_details_tag(f"Stop Evaluation at: {STOP_TASK_EVALUATION_AT_ROUND_FRACTION:.0%}"))
        bt.logging.info(round_details_tag(f"Fetch Commits at: {FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION:.0%}"))
        bt.logging.info("=" * 100)

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
            # Always use live chain height to avoid stale epoch math
            current_block = self.block
            current_epoch = self.round_manager.block_to_epoch(current_block)
            boundaries = self.round_manager.get_current_boundaries()
            wait_info = self.round_manager.get_wait_info(current_block)

            ColoredLogger.info(
                f"📍 Task {task_index + 1}/{len(all_tasks)} | " f"epoch {current_epoch:.2f}/{boundaries['target_epoch']} | " f"remaining {wait_info['minutes_remaining']:.1f}m",
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
            # Refresh block height after evaluation to get an accurate time window
            current_block = self.block
            # Compute fractional progress for reserved-window stop
            try:
                boundaries_now = self.round_manager.get_round_boundaries(current_block, log_debug=False)
                rsb = boundaries_now["round_start_block"]
                tb = boundaries_now["target_block"]
                bt_total = max(tb - rsb, 1)
                bt_done = max(current_block - rsb, 0)
                progress_frac = min(max(bt_done / bt_total, 0.0), 1.0)
            except Exception:
                progress_frac = 0.0

            # Early finalize window: fetch aggregated scores, set weights and finish_round
            if (not self._finalized_this_round) and (progress_frac >= float(FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION)):
                ColoredLogger.info(
                    f"⏳ Finalizing early at {FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION:.0%} to avoid boundary issues",
                    ColoredLogger.PURPLE,
                )
                try:
                    await self._calculate_final_weights(tasks_completed)
                    self._finalized_this_round = True
                except Exception as e:
                    bt.logging.warning(f"Early finalize failed; will retry later: {e}")
                # Stop scheduling more tasks; wait for boundary afterwards
                break
            if ENABLE_DISTRIBUTED_CONSENSUS and (not self._finalized_this_round) and (not self._consensus_published) and (progress_frac >= float(STOP_TASK_EVALUATION_AT_ROUND_FRACTION)):
                ColoredLogger.error("\n" + "=" * 80, ColoredLogger.RED)
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
                ColoredLogger.error("=" * 80 + "\n", ColoredLogger.RED)
                # Additional structured consensus logs (no logic change)
                try:
                    from autoppia_web_agents_subnet.utils.log_colors import consensus_tag
                    bt.logging.info("=" * 80)
                    bt.logging.info(consensus_tag(f"🛑 STOP EVAL @ {STOP_TASK_EVALUATION_AT_ROUND_FRACTION:.0%}"))
                    bt.logging.info(consensus_tag(f"Progress: {progress_frac:.2f}"))
                    bt.logging.info(consensus_tag(f"Current Block: {current_block:,}"))
                    bt.logging.info(consensus_tag(f"Blocks Done/Total: {bt_done}/{bt_total}"))
                    bt.logging.info(consensus_tag(f"Tasks Completed: {tasks_completed}"))
                    bt.logging.info(consensus_tag("Publishing to IPFS now..."))
                    bt.logging.info("=" * 80)
                except Exception:
                    pass
                try:
                    round_number = await self.round_manager.calculate_round(current_block)
                    st = await self._get_async_subtensor()

                    cid = await publish_round_snapshot(
                        validator=self,
                        st=st,
                        round_number=round_number,
                        tasks_completed=tasks_completed,
                    )

                    self._consensus_published = True
                    if cid:
                        bt.logging.success(f"[CONSENSUS] ✅ IPFS publish complete - CID: {cid}")
                    else:
                        bt.logging.warning(f"[CONSENSUS] ⚠️ IPFS publish returned no CID")
                except Exception as e:
                    bt.logging.error("=" * 80)
                    bt.logging.error(f"[CONSENSUS] ❌ IPFS publish failed | Error: {type(e).__name__}: {e}")
                    import traceback

                    bt.logging.error(f"[CONSENSUS] Traceback:\n{traceback.format_exc()}")
                    bt.logging.error("=" * 80)
                break
            if not self.round_manager.should_send_next_task(current_block):
                ColoredLogger.warning(
                    "🛑 Stopping task execution: safety buffer reached",
                    ColoredLogger.YELLOW,
                )
                ColoredLogger.info(
                    f"   epoch={current_epoch:.2f}, remaining={wait_info['seconds_remaining']:.0f}s, " f"buffer={SAFETY_BUFFER_EPOCHS} epochs, tasks={tasks_completed}/{len(all_tasks)}",
                    ColoredLogger.YELLOW,
                )
                try:
                    # Provide explicit context about what the target is (end-of-round)
                    bounds_ctx = self.round_manager.get_round_boundaries(current_block, log_debug=False)
                    target_epoch_ctx = bounds_ctx["target_epoch"]
                    target_block_ctx = bounds_ctx["target_block"]
                    round_no_ctx = await self.round_manager.calculate_round(current_block)
                    ColoredLogger.info(
                        (f"   Waiting for end-of-round target epoch to set weights | " f"round={round_no_ctx} | target_epoch={target_epoch_ctx:.2f} | target_block={target_block_ctx}"),
                        ColoredLogger.YELLOW,
                    )
                except Exception:
                    ColoredLogger.info("   Waiting for end-of-round target epoch to set weights", ColoredLogger.YELLOW)
                # Save state just before entering wait phase
                try:
                    self.state_manager.save_checkpoint()
                except Exception:
                    pass
                # Try to publish commitments if sharing and not yet published and not already finalized.
                if ENABLE_DISTRIBUTED_CONSENSUS and (not self._consensus_published) and (not self._finalized_this_round):
                    try:
                        bt.logging.info(f"[CONSENSUS] Safety buffer reached - publishing to IPFS with {tasks_completed} tasks")
                        round_number = await self.round_manager.calculate_round(current_block)
                        st = await self._get_async_subtensor()
                        cid = await publish_round_snapshot(
                            validator=self,
                            st=st,
                            round_number=round_number,
                            tasks_completed=tasks_completed,
                        )
                        if cid:
                            self._consensus_published = True
                        else:
                            bt.logging.warning("Consensus publish returned no CID; will retry later if window allows.")
                        try:
                            self.state_manager.save_checkpoint()
                        except Exception:
                            pass
                    except Exception as e:
                        bt.logging.error("=" * 80)
                        bt.logging.error(f"[CONSENSUS] ❌ IPFS publish failed | Error: {type(e).__name__}: {e}")
                        import traceback

                        bt.logging.error(f"[CONSENSUS] Traceback:\n{traceback.format_exc()}")
                        bt.logging.error("=" * 80)
                break

        # ═══════════════════════════════════════════════════════
        # PUBLISH IF NOT DONE YET
        # If we completed all tasks before reaching 50%, publish NOW
        # This ensures round_number and validator_round_id match
        # ═══════════════════════════════════════════════════════
        if ENABLE_DISTRIBUTED_CONSENSUS and (not self._consensus_published) and (not self._finalized_this_round):
            ColoredLogger.error("\n" + "=" * 80, ColoredLogger.RED)
            ColoredLogger.error(
                f"📤📤📤 ALL TASKS DONE - PUBLISHING TO IPFS NOW 📤📤📤",
                ColoredLogger.RED,
            )
            ColoredLogger.error(
                f"📦 Tasks completed: {tasks_completed}/{len(all_tasks)}",
                ColoredLogger.RED,
            )
            ColoredLogger.error("=" * 80 + "\n", ColoredLogger.RED)
            # Additional structured consensus logs (no logic change)
            try:
                from autoppia_web_agents_subnet.utils.log_colors import consensus_tag
                bt.logging.info("=" * 80)
                bt.logging.info(consensus_tag(f"All tasks done ({tasks_completed}/{len(all_tasks)}) - Publishing to IPFS now..."))
                bt.logging.info("=" * 80)
            except Exception:
                pass
            try:
                current_block = self.block
                round_number = await self.round_manager.calculate_round(current_block)
                st = await self._get_async_subtensor()
                cid = await publish_round_snapshot(
                    validator=self,
                    st=st,
                    round_number=round_number,
                    tasks_completed=tasks_completed,
                )
                if cid:
                    self._consensus_published = True
                else:
                    bt.logging.warning("Consensus publish returned no CID; will retry later if window allows.")
            except Exception as e:
                bt.logging.error("=" * 80)
                bt.logging.error(f"[CONSENSUS] ❌ IPFS publish failed | Error: {type(e).__name__}: {e}")
                import traceback

                bt.logging.error(f"[CONSENSUS] Traceback:\n{traceback.format_exc()}")
                bt.logging.error("=" * 80)

        # ═══════════════════════════════════════════════════════
        # WAIT FOR TARGET EPOCH: Wait until the round ends
        # Always wait (for IPFS propagation and consensus), even if all tasks done
        # ═══════════════════════════════════════════════════════
        # Ensure we persist the checkpoint right before the wait window
        try:
            self.state_manager.save_checkpoint()
        except Exception:
            pass
        # Actively wait until the fixed end-of-round boundary before finalizing
        try:
            await self._wait_until_next_round_boundary()
        except Exception as e:
            bt.logging.warning(f"Wait-until-boundary failed, proceeding to finalize: {e}")

        # ═══════════════════════════════════════════════════════
        # FINAL WEIGHTS (fallback): If not done early, finalize now
        # ═══════════════════════════════════════════════════════
        if not self._finalized_this_round:
            await self._calculate_final_weights(tasks_completed)
            self._finalized_this_round = True
        else:
            ColoredLogger.info("✅ Weights already finalized earlier; skipping.", ColoredLogger.GREEN)

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

            # 🔍 Show task details in Rich table
            try:
                console = Console()
                task_table = Table(
                    title=f"[bold cyan]📋 Task {task_index + 1}/{len(self.current_round_tasks)}[/bold cyan]",
                    box=box.DOUBLE,
                    show_header=True,
                    header_style="bold yellow",
                    expand=False,
                )

                task_table.add_column("Field", justify="left", style="cyan", width=12)
                task_table.add_column("Value", justify="left", style="white", no_wrap=False)

                # Project
                task_table.add_row("📦 Project", f"[magenta]{web_project_name}[/magenta]")

                # URL
                task_url_display = project.frontend_url
                if seed is not None:
                    separator = "&" if "?" in task_url_display else "?"
                    task_url_display = f"{task_url_display}{separator}seed={seed}"
                task_table.add_row("🌐 URL", f"[blue]{task_url_display}[/blue]")

                # Prompt
                task_table.add_row("📝 Prompt", f"[white]{task.prompt}[/white]")

                # Tests - Show full details including criteria
                tests_count = len(task.tests) if task.tests else 0
                tests_info = []
                if task.tests:
                    for test_idx, test in enumerate(task.tests, 1):
                        test_lines = [f"[yellow]{test_idx}. {test.type}[/yellow]: {test.description}"]

                        # Add event name if available
                        if hasattr(test, "event_name"):
                            test_lines.append(f"   Event: [cyan]{test.event_name}[/cyan]")

                        # Add criteria details
                        if hasattr(test, "event_criteria") and test.event_criteria:
                            import json

                            criteria_str = json.dumps(test.event_criteria, indent=2)
                            test_lines.append(f"   Criteria: [dim]{criteria_str}[/dim]")

                        tests_info.append("\n".join(test_lines))
                    tests_str = "\n\n".join(tests_info)
                else:
                    tests_str = "[dim]No tests[/dim]"
                task_table.add_row(f"🧪 Tests ({tests_count})", tests_str)

                console.print()
                console.print(task_table)
                console.print()

            except Exception as e:
                bt.logging.warning(f"Failed to render task table: {e}")
                # Fallback to simple log
                ColoredLogger.debug(f"Task {task_index + 1}: {task.prompt[:100]}...", ColoredLogger.CYAN)

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

            # Group miners by identical solutions (same actions)
            import hashlib

            solution_groups = {}  # hash -> {'uids': [list], 'solution': solution, 'results': [list]}

            for i, (uid, solution) in enumerate(zip(self.active_miner_uids, task_solutions)):
                # Create hash of actions to group identical solutions
                if solution and solution.actions:
                    # Create a simple string representation for hashing (avoid JSON serialization issues)
                    actions_repr = []
                    for a in solution.actions:
                        # Use action type and basic attributes for grouping
                        action_str = f"{a.type}"
                        if hasattr(a, "url"):
                            action_str += f"|{a.url}"
                        if hasattr(a, "text"):
                            action_str += f"|{a.text}"
                        if hasattr(a, "selector") and a.selector:
                            selector_str = f"{getattr(a.selector, 'type', '')}:{getattr(a.selector, 'value', '')}"
                            action_str += f"|{selector_str}"
                        actions_repr.append(action_str)

                    actions_str = "||".join(actions_repr)
                    solution_hash = hashlib.md5(actions_str.encode()).hexdigest()[:8]
                else:
                    solution_hash = "no_actions"

                if solution_hash not in solution_groups:
                    solution_groups[solution_hash] = {"uids": [], "solution": solution, "indices": []}

                solution_groups[solution_hash]["uids"].append(uid)
                solution_groups[solution_hash]["indices"].append(i)

            # Evaluate task solutions
            ColoredLogger.debug("🔍 STARTING EVALUATION...", ColoredLogger.CYAN)
            eval_scores, test_results_list, evaluation_results = await evaluate_task_solutions(
                web_project=project,
                task=task,
                task_solutions=task_solutions,
                execution_times=execution_times,
            )

            # 🔍 DEBUG: Show actions + results together for each GROUP
            try:
                console = Console()
                expected_base = project.frontend_url.rstrip("/")

                # Display actions AND results for each GROUP of miners with identical solutions
                for group_idx, (solution_hash, group_data) in enumerate(solution_groups.items(), 1):
                    group_uids = group_data["uids"]
                    group_indices = group_data["indices"]
                    solution = group_data["solution"]

                    # Get results for all miners in this group
                    group_scores = [eval_scores[i] for i in group_indices]
                    group_times = [execution_times[i] for i in group_indices]
                    group_errors = [evaluation_results[i].get("error_message", "") for i in group_indices]

                    # 1️⃣ Actions Table (for group)
                    if solution and solution.actions:
                        # Count seed issues
                        seed_issues = 0
                        for action in solution.actions:
                            if hasattr(action, "url") and action.url and action.type == "NavigateAction" and seed is not None:
                                if "seed=" not in action.url:
                                    seed_issues += 1
                                else:
                                    action_seed = action.url.split("seed=")[1].split("&")[0].split("?")[0]
                                    if action_seed != str(seed):
                                        seed_issues += 1

                        status_emoji = "✅" if seed_issues == 0 else "⚠️"
                        uids_str = ", ".join([str(u) for u in group_uids])
                        actions_table = Table(
                            title=f"[bold cyan]{status_emoji} Group {group_idx} | UIDs: [{uids_str}] - Actions Submitted[/bold cyan]",
                            box=box.ROUNDED,
                            show_header=True,
                            header_style="bold yellow",
                            expand=False,
                        )

                        actions_table.add_column("#", justify="right", style="cyan", width=4)
                        actions_table.add_column("Action Type", justify="left", style="magenta", width=25)
                        actions_table.add_column("Details (Full)", justify="left", style="white", no_wrap=False)
                        actions_table.add_column("Status", justify="center", style="bold", width=6)

                        for j, action in enumerate(solution.actions, 1):
                            action_type = action.type
                            status = "[bold green]✅[/bold green]"

                            # Show COMPLETE action details in readable format
                            action_dict = vars(action)
                            details_lines = []
                            for key, value in action_dict.items():
                                if key == "type":
                                    continue  # Skip type as it's in another column
                                # Format selector objects nicely
                                if hasattr(value, "__dict__"):
                                    value = vars(value)
                                details_lines.append(f"{key}: {value}")
                            details = "\n".join(details_lines)

                            # For NavigateAction, check seed
                            if action_type == "NavigateAction" and seed is not None:
                                url = getattr(action, "url", "")
                                if "seed=" not in url:
                                    status = "[bold red]❌[/bold red]"
                                else:
                                    action_seed = url.split("seed=")[1].split("&")[0].split("?")[0]
                                    if action_seed != str(seed):
                                        status = "[bold red]❌[/bold red]"

                            actions_table.add_row(str(j), action_type, details, status)

                        console.print(actions_table)
                    else:
                        uids_str = ", ".join([str(u) for u in group_uids])
                        console.print(f"[yellow]📊 Group {group_idx} | UIDs: [{uids_str}] - NO ACTIONS SUBMITTED[/yellow]")

                    # 2️⃣ Backend tests summary for this GROUP (compact, sourced from test_results_list)
                    try:
                        group_tests: list[list[dict]] = [test_results_list[i] if i < len(test_results_list) else [] for i in group_indices]
                        tests_table = Table(
                            title=f"[bold green]🧪 Group {group_idx} | UIDs: [{uids_str}] - Backend Tests[/bold green]",
                            box=box.SIMPLE,
                            show_header=True,
                            header_style="bold green",
                            expand=False,
                        )
                        tests_table.add_column("UID", justify="right", style="cyan", width=8)
                        tests_table.add_column("Tests", justify="center", style="white", width=8)
                        tests_table.add_column("Passed", justify="center", style="white", width=8)
                        tests_table.add_column("Example Event", justify="left", style="white")

                        for uid, tests in zip(group_uids, group_tests):
                            total = len(tests or [])
                            passed = sum(1 for t in (tests or []) if bool(t.get("success", False)))
                            # Try to extract a representative event name from extra_data
                            example = ""
                            try:
                                if tests:
                                    ed = (tests[0] or {}).get("extra_data", {}) or {}
                                    example = str(ed.get("event_name") or ed.get("type") or "")
                            except Exception:
                                example = ""
                            tests_table.add_row(str(uid), str(total), str(passed), example)

                        console.print(tests_table)
                    except Exception:
                        # Non-fatal: if the structure is different, skip this summary quietly
                        pass

                    # 3️⃣ Results Table for this group (show all UIDs)
                    uids_str = ", ".join([str(u) for u in group_uids])
                    result_table = Table(
                        title=f"[bold magenta]📊 Group {group_idx} | UIDs: [{uids_str}] - Evaluation Results[/bold magenta]",
                        box=box.SIMPLE,
                        show_header=True,
                        header_style="bold cyan",
                        expand=False,
                    )

                    result_table.add_column("UID", justify="right", style="cyan", width=8)
                    result_table.add_column("Score", justify="center", style="bold", width=10)
                    result_table.add_column("Time", justify="center", style="blue", width=12)
                    result_table.add_column("Status", justify="left", style="white", width=50)
                    result_table.add_column("Result", justify="center", style="bold", width=8)

                    # Add a row for each UID in the group
                    for idx, (uid, score, exec_time, error_msg) in enumerate(zip(group_uids, group_scores, group_times, group_errors)):
                        # Format score with color
                        if score >= 0.8:
                            score_str = f"[bold green]{score:.4f}[/bold green]"
                            result_icon = "[bold green]✅[/bold green]"
                        elif score >= 0.5:
                            score_str = f"[bold yellow]{score:.4f}[/bold yellow]"
                            result_icon = "[bold yellow]⚠️[/bold yellow]"
                        else:
                            score_str = f"[bold red]{score:.4f}[/bold red]"
                            result_icon = "[bold red]❌[/bold red]"

                        # Time
                        time_str = f"[blue]{exec_time:.2f}s[/blue]"

                        # Status message
                        if error_msg:
                            status_msg = f"[red]{error_msg[:47]}...[/red]" if len(error_msg) > 50 else f"[red]{error_msg}[/red]"
                        elif score >= 0.8:
                            status_msg = "[green]All tests passed[/green]"
                        elif score > 0:
                            status_msg = "[yellow]Some tests failed[/yellow]"
                        else:
                            status_msg = "[red]All tests failed[/red]"

                        result_table.add_row(str(uid), score_str, time_str, status_msg, result_icon)

                    console.print(result_table)
                    console.print()
                    console.print("[dim]" + "─" * 100 + "[/dim]")
                    console.print()

            except Exception as e:
                bt.logging.warning(f"Failed to render miner tables: {e}")
                import traceback

                bt.logging.warning(f"Traceback: {traceback.format_exc()}")
                # Fallback to simple logging
                for i, uid in enumerate(self.active_miner_uids):
                    ColoredLogger.debug(f"UID={uid}: Score={eval_scores[i]:.4f}, Time={execution_times[i]:.2f}s", ColoredLogger.GREEN)

            # Calculate final scores (combining eval quality + execution speed)
            rewards = calculate_rewards_for_task(
                eval_scores=eval_scores,
                execution_times=execution_times,
                n_miners=len(self.active_miner_uids),
                eval_score_weight=EVAL_SCORE_WEIGHT,
                time_weight=TIME_WEIGHT,
            )

            # Accumulate scores for the round using round_manager
            self.round_manager.accumulate_rewards(miner_uids=list(self.active_miner_uids), rewards=rewards.tolist(), eval_scores=eval_scores.tolist(), execution_times=execution_times)

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

                # Progress within the FIXED window
                total = max(fixed_target_block - fixed_start_block, 1)
                done = max(current_block - fixed_start_block, 0)
                progress = min(max((done / total) * 100.0, 0.0), 100.0)

                blocks_remaining = max(fixed_target_block - current_block, 0)
                minutes_remaining = (blocks_remaining * self.round_manager.SECONDS_PER_BLOCK) / 60

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
        bt.logging.info("=" * 80)
        bt.logging.info("[CONSENSUS] Phase: SetWeights - Calculating final weights")
        bt.logging.info(f"[CONSENSUS] Distributed consensus: {str(ENABLE_DISTRIBUTED_CONSENSUS).lower()}")
        bt.logging.info("=" * 80)

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
                bt.logging.info("[CONSENSUS] Aggregating scores from other validators...")
                # Prefer cached mid-settlement aggregation if available
                agg = self._agg_scores_cache or {}
                agg_meta = None
                if not agg:
                    # Calculate current progress
                    try:
                        current_block_now = self.metagraph.block.item()
                        bounds_now = self.round_manager.get_round_boundaries(current_block_now, log_debug=False)
                        rsb = bounds_now["round_start_block"]
                        tb = bounds_now["target_block"]
                        progress_now = min(max((current_block_now - rsb) / max(tb - rsb, 1), 0.0), 1.0)
                    except Exception:
                        progress_now = 0.0
                        current_block_now = 0

                    from autoppia_web_agents_subnet.utils.log_colors import consensus_tag

                    bt.logging.info("=" * 80)
                    bt.logging.info(consensus_tag(f"📥 FETCH COMMITS @ {FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION:.0%}"))
                    bt.logging.info(consensus_tag(f"Progress: {progress_now:.2f}"))
                    bt.logging.info(consensus_tag(f"Current Block: {current_block_now:,}"))
                    bt.logging.info(consensus_tag("Fetching commitments from IPFS to aggregate scores"))
                    bt.logging.info("=" * 80)

                    # Natural gap between STOP and FETCH ensures propagation
                    st = await self._get_async_subtensor()
                    agg, agg_meta = await aggregate_scores_from_commitments(
                        validator=self,
                        st=st,
                        start_epoch=boundaries["round_start_epoch"],
                        target_epoch=boundaries["target_epoch"],
                    )
                if agg:
                    ColoredLogger.info(
                        f"🤝 Using aggregated scores from commitments ({len(agg)} miners)",
                        ColoredLogger.CYAN,
                    )
                    avg_rewards = agg
                    # Cache the details for rendering
                    try:
                        self._consensus_last_details = agg_meta or {}
                    except Exception:
                        pass
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
            ColoredLogger.warning("🔥 All miners scored <= 0: burning all weights", ColoredLogger.RED)
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

        # Render enhanced summary table including consensus details when available
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
        except Exception as e:
            bt.logging.debug(f"Round summary table failed: {e}")

        # Minimal final weights log: only winner
        bt.logging.info("🎯 Final weights (WTA)")
        winner_uid = max(final_rewards_dict.keys(), key=lambda k: final_rewards_dict[k]) if final_rewards_dict else None
        if winner_uid is not None:
            hotkey = self.metagraph.hotkeys[winner_uid] if winner_uid < len(self.metagraph.hotkeys) else "<unknown>"
            bt.logging.info(f"🏆 Winner uid={winner_uid}, hotkey={hotkey[:10]}..., weight={final_rewards_dict[winner_uid]:.4f}")
        else:
            bt.logging.info("❌ No miners evaluated.")

        # Set on-chain weights to the consensus WTA winner, even if not local/active,
        # to ensure all validators converge on the same winner.
        winner_uid = max(final_rewards_dict.keys(), key=lambda k: final_rewards_dict[k]) if final_rewards_dict else None
        wta_full = np.zeros(self.metagraph.n, dtype=np.float32)
        if winner_uid is not None and 0 <= int(winner_uid) < self.metagraph.n:
            wta_full[int(winner_uid)] = 1.0
        all_uids = list(range(self.metagraph.n))
        bt.logging.info(f"Updating scores for on-chain WTA winner uid={winner_uid}")
        self.update_scores(rewards=wta_full, uids=all_uids)
        self.set_weights()

        try:
            await self._finish_iwap_round(
                avg_rewards=avg_rewards,
                final_weights=final_rewards_dict,
                tasks_completed=tasks_completed,
            )
        except Exception as e:
            bt.logging.warning(f"IWAP finish_round failed: {e}")

        try:
            round_finished = getattr(self, "_current_round_number", None)
        except Exception:
            round_finished = None
        if round_finished is not None:
            ColoredLogger.success(f"✅ Round completed: {int(round_finished)}", ColoredLogger.GREEN)
        else:
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
        while True:
            bt.logging.debug(f"Heartbeat — validator running... {time.time()}")
            time.sleep(120)  # Every 5 minutes instead of 30 seconds
