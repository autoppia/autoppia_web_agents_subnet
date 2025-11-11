from __future__ import annotations

import bittensor as bt
from rich import box
from rich.console import Console
from rich.table import Table

from autoppia_web_agents_subnet.protocol import StartRoundSynapse
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.config import (
    MAX_MINER_AGENT_NAME_LENGTH,
    PROMPTS_PER_USE_CASE,
)
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.evaluation.synapse_handlers import (
    send_start_round_synapse_to_miners,
)

async def _run_screening_handshake_phase(self, total_prompts: int) -> None:
    current_block = self.block

    self.round_manager.enter_phase(
        RoundPhase.SCREENING_HANDSHAKE,
        block=current_block,
        note="Preparing miner handshake",
    )        
    ColoredLogger.info(
        f"🤝 Handshake: sending to {len(self.metagraph.uids)} miners...",
        ColoredLogger.CYAN,
    )

    boundaries = self.round_manager.get_current_boundaries()
    all_uids = list(range(len(self.metagraph.uids)))
    all_axons = [self.metagraph.axons[uid] for uid in all_uids]
    start_synapse = StartRoundSynapse(
        version=self.version,
        round_id=self.current_round_id or f"round_{boundaries['round_start_epoch']}",
        validator_id=str(self.uid),
        total_prompts=total_prompts,
        prompts_per_use_case=PROMPTS_PER_USE_CASE,
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

    miner_status_map = {}
    self.active_miner_uids = []

    for idx, response in enumerate(handshake_responses):
        if idx >= len(all_axons):
            continue

        mapped_uid = all_uids[idx]
        miner_status_map[mapped_uid] = {
            "response": response,
            "success": False,
            "agent_name": None,
            "version": None,
            "hotkey": self.metagraph.hotkeys[mapped_uid][:12] + "..."
            if mapped_uid < len(self.metagraph.hotkeys)
            else "N/A",
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
            self._log_miner_status(miner_status_map, len(all_axons))

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

def _log_miner_status(self, miner_status_map: dict, all_axons_length: int):
    console = Console()
    table = Table(
        title=(
            f"[bold magenta]🤝 Handshake Results - {len(self.active_miner_uids)}/"
            f"{all_axons_length} Miners Responded[/bold magenta]"
        ),
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