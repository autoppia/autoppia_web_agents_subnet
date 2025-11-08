from __future__ import annotations

import time
from typing import List

import bittensor as bt
from rich import box
from rich.console import Console
from rich.table import Table

from autoppia_web_agents_subnet.protocol import StartRoundSynapse
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.utils.log_colors import round_details_tag
from autoppia_web_agents_subnet.validator.config import (
    FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION,
    MAX_MINER_AGENT_NAME_LENGTH,
    PRE_GENERATED_TASKS,
    PROMPTS_PER_USECASE,
    SKIP_ROUND_IF_STARTED_AFTER_FRACTION,
    STOP_TASK_EVALUATION_AT_ROUND_FRACTION,
)
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.round_start.types import StartPhaseResult
from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.evaluation.tasks import get_task_collection_interleaved
from autoppia_web_agents_subnet.validator.evaluation.synapse_handlers import (
    send_start_round_synapse_to_miners,
)


class RoundStartMixin:
    """Round preparation: resume checkpoints, pre-generate tasks, and perform handshake."""

    async def _run_start_phase(self, current_block: int) -> StartPhaseResult:
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

        self.forward_count = int(getattr(self, "forward_count", 0)) + 1

        pre_generation_start = time.time()
        all_tasks: List[TaskWithProject] = []

        resumed = False
        state = self._load_round_state(current_block=current_block)
        if state and state.get("validator_round_id"):
            cached = list(getattr(self, "_all_tasks_cache", []) or [])
            if cached:
                all_tasks.extend(cached)
            if all_tasks:
                self.current_round_id = state["validator_round_id"]
                resumed = True
                bt.logging.info(f"♻️ Resumed {len(all_tasks)} tasks; validator_round_id={self.current_round_id}")
            else:
                bt.logging.warning("Resume checkpoint had 0 tasks; generating new tasks.")

        info = getattr(self, "_last_resume_info", None) or {"status": "unknown"}
        if resumed:
            bt.logging.info(f"Resume decision: used prior state ({info})")
        else:
            bt.logging.info(f"Resume decision: fresh start ({info})")

        if not resumed:
            self._reset_iwap_round_state()
            reset_consensus = getattr(self, "_reset_consensus_state", None)
            if callable(reset_consensus):
                reset_consensus()

        if not resumed:
            frac = float(self.round_manager.fraction_elapsed(current_block))
            bounds = self.round_manager.get_round_boundaries(current_block, log_debug=False)
            blocks_to_target = max(bounds["target_block"] - current_block, 0)
            at_boundary = blocks_to_target == 0
            if (not at_boundary) and (frac >= float(SKIP_ROUND_IF_STARTED_AFTER_FRACTION)):
                minutes_remaining = (blocks_to_target * self.round_manager.SECONDS_PER_BLOCK) / 60
                ColoredLogger.warning(
                    (f"⏭️ Fresh start late in round: {frac * 100:.1f}% >= " f"{float(SKIP_ROUND_IF_STARTED_AFTER_FRACTION) * 100:.0f}% — skipping"),
                    ColoredLogger.YELLOW,
                )
                ColoredLogger.info(
                    f"   Waiting ~{minutes_remaining:.1f}m to next boundary...",
                    ColoredLogger.YELLOW,
                )
                self.round_manager.enter_phase(
                    RoundPhase.WAITING,
                    block=current_block,
                    note="Late start detected; deferring to next boundary",
                )
                await self._wait_until_next_round_boundary()
                return StartPhaseResult(
                    all_tasks=[],
                    resumed=False,
                    continue_forward=False,
                    reason="late_start_boundary_wait",
                )

        if not resumed:
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
            self._save_round_state(tasks=all_tasks)

        self.current_round_tasks = self._build_iwap_tasks(
            validator_round_id=self.current_round_id,
            tasks=all_tasks,
        )

        pre_generation_elapsed = time.time() - pre_generation_start
        bt.logging.info(f"✅ Task list ready: {len(all_tasks)} tasks in {pre_generation_elapsed:.1f}s (resumed={resumed})")

        self.round_manager.start_new_round(current_block)
        
        # Initialize round report (NEW) - Always initialize, even if resumed
        round_number = await self.round_manager.calculate_round(current_block)
        self._init_round_report(
            round_number=round_number,
            validator_round_id=self.current_round_id,
            start_block=self.round_manager.start_block,
            start_epoch=self.round_manager.block_to_epoch(self.round_manager.start_block),
            planned_tasks=len(all_tasks),
        )
        bt.logging.info(f"📊 Round report initialized for round {round_number} (resumed={resumed})")

        self.round_manager.enter_phase(
            RoundPhase.HANDSHAKE,
            block=current_block,
            note="Preparing miner handshake",
        )
        self._finalized_this_round = False
        boundaries = self.round_manager.get_current_boundaries()
        if not resumed:
            self.round_handshake_payloads = {}
            self.current_agent_runs = {}
            self.current_miner_snapshots = {}
            self.agent_run_accumulators = {}
            self._phases["handshake_sent"] = False

        all_uids = list(range(len(self.metagraph.uids)))
        all_axons = [self.metagraph.axons[uid] for uid in all_uids]

        has_prior_handshake = resumed and self._phases.get("handshake_sent", False)
        handshake_responses = []

        if has_prior_handshake:
            ColoredLogger.info(
                f"🤝 Handshake: using saved state (active_miners={len(self.active_miner_uids)}, already sent before restart)",
                ColoredLogger.CYAN,
            )
        else:
            ColoredLogger.info(
                f"🤝 Handshake: sending to {len(self.metagraph.uids)} miners...",
                ColoredLogger.CYAN,
            )
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

            try:
                handshake_responses = await send_start_round_synapse_to_miners(
                    validator=self,
                    miner_axons=all_axons,
                    start_synapse=start_synapse,
                    timeout=60,
                )
            except Exception as exc:  # noqa: BLE001
                self.round_manager.enter_phase(
                    RoundPhase.ERROR,
                    block=current_block,
                    note="Handshake failed to dispatch synapse",
                )
                raise RuntimeError("Failed to send StartRoundSynapse to miners") from exc

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

            miner_status_map = {}

            for idx, response in enumerate(handshake_responses):
                if idx >= len(all_axons):
                    continue

                mapped_uid = all_uids[idx]
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
                status_numeric = None
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

                miner_status_map[mapped_uid].update(
                    {
                        "success": True,
                        "agent_name": agent_name,
                        "version": getattr(response, "agent_version", "N/A"),
                    }
                )

            if miner_status_map:
                console = Console()
                table = Table(
                    title=(f"[bold magenta]🤝 Handshake Results - {len(self.active_miner_uids)}/" f"{len(all_axons)} Miners Responded[/bold magenta]"),
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

                for uid in sorted(miner_status_map.keys()):
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

            if not has_prior_handshake:
                self._phases["handshake_sent"] = True
                if self.active_miner_uids:
                    ColoredLogger.success(
                        f"✅ Handshake sent: {len(self.active_miner_uids)}/{len(all_axons)} miners responded",
                        ColoredLogger.GREEN,
                    )
                else:
                    ColoredLogger.warning(
                        f"⚠️ Handshake sent: 0/{len(all_axons)} miners responded",
                        ColoredLogger.YELLOW,
                    )

                # Record handshake in report (NEW)
                self._report_handshake_sent(total_miners=len(all_axons))

                for uid in self.active_miner_uids:
                    hotkey = self.metagraph.hotkeys[uid] if uid < len(self.metagraph.hotkeys) else "unknown"
                    payload = self.round_handshake_payloads.get(uid)

                    agent_name = None
                    agent_image = None
                    if payload:
                        agent_name = getattr(payload, "agent_name", None)
                        agent_image = getattr(payload, "agent_image", None)

                    self._report_handshake_response(uid, hotkey, agent_name, agent_image)

                self._save_round_state()

            self.round_manager.enter_phase(
                RoundPhase.HANDSHAKE,
                block=current_block,
                note=f"Handshake completed with {len(self.active_miner_uids)} active miners",
            )

        round_number = await self.round_manager.calculate_round(current_block)
        start_epoch = boundaries["round_start_epoch"]
        target_epoch = boundaries["target_epoch"]
        total_blocks = boundaries["target_block"] - boundaries["round_start_block"]
        blocks_remaining = boundaries["target_block"] - current_block
        minutes_remaining = (blocks_remaining * self.round_manager.SECONDS_PER_BLOCK) / 60

        bt.logging.info("=" * 100)
        bt.logging.info(round_details_tag("🚀 ROUND START"))
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

        if not self.active_miner_uids:
            ColoredLogger.warning(
                "⚠️ No active miners after handshake; skipping tasks and finalizing round.",
                ColoredLogger.YELLOW,
            )
            await self._calculate_final_weights(0)
            self.round_manager.enter_phase(
                RoundPhase.COMPLETE,
                block=current_block,
                note="No active miners; round finalized with burn",
                force=True,
            )
            self.round_manager.log_phase_history()
            return StartPhaseResult(
                all_tasks=all_tasks,
                resumed=resumed,
                continue_forward=False,
                tasks_completed=0,
                reason="no_active_miners",
            )

        await self._iwap_start_round(current_block=current_block, n_tasks=len(all_tasks))

        if resumed and getattr(self, "_eval_records", None):
            ColoredLogger.info(
                f"♻️ Resume: rebuilding accumulators from {len(self._eval_records)} evaluations",
                ColoredLogger.CYAN,
            )
            self._rebuild_from_saved_evaluations()
            ColoredLogger.success("✅ Resume: accumulators restored", ColoredLogger.GREEN)

        return StartPhaseResult(
            all_tasks=all_tasks,
            resumed=resumed,
            continue_forward=True,
        )
