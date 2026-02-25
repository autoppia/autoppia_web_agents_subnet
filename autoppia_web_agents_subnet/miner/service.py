from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .utils import compute_current_round, compute_next_round, compute_season, detect_github_ref_kind
from .ui import (
    console,
    print_banner,
    print_success,
    print_warning,
    show_chain_state_panel,
    show_commitment_panel,
    show_wallet_panel,
)

DEFAULT_NETUID = 36


class MinerCliError(Exception):
    """Raised for user-facing CLI errors."""


@dataclass(frozen=True)
class CommonOptions:
    wallet_name: str
    wallet_hotkey: str
    subtensor_network: str
    subtensor_chain_endpoint: str | None
    netuid: int


def _resolve_subtensor_config(options: CommonOptions) -> tuple[str, dict[str, str]]:
    if options.subtensor_chain_endpoint:
        endpoint = options.subtensor_chain_endpoint.strip()
        if endpoint:
            return endpoint, {"network": endpoint}
    return options.subtensor_network, {"network": options.subtensor_network}


def _validate_submit_inputs(
    github: str,
    agent_name: str,
    agent_image: str,
    target_round: int | None,
    season: int | None,
) -> tuple[str, str, str]:
    from autoppia_web_agents_subnet.opensource.utils_git import normalize_and_validate_github_url

    normalized, ref = normalize_and_validate_github_url(github, require_ref=True)
    if normalized is None or not ref:
        raise MinerCliError(
            f"Invalid GitHub URL: {github}\n"
            "       Must be https://github.com/owner/repo/tree/<ref> or /commit/<sha>."
        )

    stripped_name = agent_name.strip()
    if not stripped_name:
        raise MinerCliError("--agent.name must not be empty.")

    if season is not None and season <= 0:
        raise MinerCliError("--season must be a positive integer.")

    if target_round is not None and target_round <= 0:
        raise MinerCliError("--target_round must be a positive integer.")

    ref_kind = detect_github_ref_kind(github)
    github_url = f"{normalized}/{ref_kind}/{ref}"
    return github_url, stripped_name, (agent_image or "").strip()


async def run_submit(
    *,
    options: CommonOptions,
    github: str,
    agent_name: str,
    agent_image: str,
    target_round: int | None,
    season: int | None,
) -> None:
    import bittensor as bt
    from autoppia_web_agents_subnet.utils.commitments import read_my_plain_json, write_plain_commitment_json

    print_banner()
    github_url, stripped_name, stripped_image = _validate_submit_inputs(github, agent_name, agent_image, target_round, season)

    wallet = bt.Wallet(name=options.wallet_name, hotkey=options.wallet_hotkey)
    network_label, subtensor_kwargs = _resolve_subtensor_config(options)
    show_wallet_panel(wallet, network_label, options.netuid)

    async with bt.AsyncSubtensor(**subtensor_kwargs) as st:
        with console.status("[bold cyan]Connecting to subtensor...", spinner="dots"):
            current_block = await st.get_current_block()

        season_number = season if season is not None else compute_season(current_block)
        target_round_number = target_round if target_round is not None else compute_next_round(current_block, season_number)
        current_round = compute_current_round(current_block, season_number)

        show_chain_state_panel(current_block, season_number, current_round, target_round_number)

        payload: dict[str, Any] = {
            "t": "m",
            "g": github_url,
            "n": stripped_name,
            "r": int(target_round_number),
            "s": int(season_number),
        }
        if stripped_image:
            payload["i"] = stripped_image

        show_commitment_panel(payload, title="Commitment Payload", border_style="blue")

        with console.status("[bold cyan]Submitting commitment on-chain...", spinner="dots"):
            ok = await write_plain_commitment_json(st, wallet=wallet, data=payload, netuid=options.netuid)

        if not ok:
            raise MinerCliError("Commitment submission failed.")
        print_success("Commitment submitted successfully.")

        with console.status("[bold cyan]Verifying on-chain commitment...", spinner="dots"):
            readback = await read_my_plain_json(st, wallet=wallet, netuid=options.netuid)

        if readback:
            show_commitment_panel(readback, title="On-Chain Verification", border_style="green")
        else:
            print_warning("Could not read back commitment (may take a block to propagate).")


async def run_show(*, options: CommonOptions) -> None:
    import bittensor as bt
    from autoppia_web_agents_subnet.utils.commitments import read_my_plain_json

    print_banner()

    wallet = bt.Wallet(name=options.wallet_name, hotkey=options.wallet_hotkey)
    network_label, subtensor_kwargs = _resolve_subtensor_config(options)
    show_wallet_panel(wallet, network_label, options.netuid)

    async with bt.AsyncSubtensor(**subtensor_kwargs) as st:
        with console.status("[bold cyan]Connecting to subtensor...", spinner="dots"):
            current_block = await st.get_current_block()

        season_number = compute_season(current_block)
        current_round = compute_current_round(current_block, season_number)
        show_chain_state_panel(current_block, season_number, current_round)

        with console.status("[bold cyan]Reading commitment...", spinner="dots"):
            commitment = await read_my_plain_json(st, wallet=wallet, netuid=options.netuid)

        if commitment is None:
            print_warning("No commitment found on-chain for this hotkey.")
        else:
            show_commitment_panel(commitment, title="On-Chain Commitment", border_style="green")
