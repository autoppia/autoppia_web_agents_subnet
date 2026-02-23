"""
autoppia-miner-cli -- submit miner agent metadata as an on-chain commitment.

Usage:
    autoppia-miner-cli submit \
        --github https://github.com/owner/repo/tree/branch \
        --agent.name MyAgent \
        [--agent.image myimage:latest] \
        [--target_round 23] \
        [--season 4] \
        [--wallet.name default] \
        [--wallet.hotkey default] \
        [--subtensor.network finney] \
        [--netuid 36]

    autoppia-miner-cli show \
        [--wallet.name default] \
        [--wallet.hotkey default] \
        [--subtensor.network finney] \
        [--netuid 36]

By default ``submit`` targets the NEXT round of the CURRENT season.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import bittensor as bt
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from autoppia_web_agents_subnet.opensource.utils_git import normalize_and_validate_github_url
from autoppia_web_agents_subnet.utils.commitments import write_plain_commitment_json, read_my_plain_json

console = Console()
err_console = Console(stderr=True)

# CLI defaults mirroring validator config to keep it self-contained without env vars.
_BLOCKS_PER_EPOCH = 360
_DEFAULT_SEASON_SIZE_EPOCHS = 280.0
_DEFAULT_ROUND_SIZE_EPOCHS = 4.0
_DEFAULT_MINIMUM_START_BLOCK = 7_586_110
_DEFAULT_NETUID = 36

# Season / round helpers
def _season_block_length() -> int:
    return int(_BLOCKS_PER_EPOCH * _DEFAULT_SEASON_SIZE_EPOCHS)

def _round_block_length() -> int:
    return int(_BLOCKS_PER_EPOCH * _DEFAULT_ROUND_SIZE_EPOCHS)

def compute_season(current_block: int) -> int:
    base = _DEFAULT_MINIMUM_START_BLOCK
    if current_block < base:
        return 0
    return int((current_block - base) // _season_block_length()) + 1

def compute_season_start_block(season_number: int) -> int:
    if season_number <= 0:
        return _DEFAULT_MINIMUM_START_BLOCK
    return _DEFAULT_MINIMUM_START_BLOCK + (season_number - 1) * _season_block_length()

def compute_current_round(current_block: int, season_number: int) -> int:
    season_start = compute_season_start_block(season_number)
    effective = max(current_block, season_start)
    return int((effective - season_start) // _round_block_length()) + 1

def compute_next_round(current_block: int, season_number: int) -> int:
    return compute_current_round(current_block, season_number) + 1

# Display helpers
def _banner() -> None:
    console.print(
        Panel(
            Text("autoppia-miner-cli", style="bold cyan", justify="center"),
            subtitle="Miner Agent On-Chain Commitment Tool",
            border_style="bright_blue",
        )
    )
    console.print()

def _wallet_table(wallet: bt.Wallet, network: str, netuid: int) -> Table:
    table = Table(show_header=False, border_style="dim", pad_edge=False, box=None)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Wallet", f"{wallet.name} / {wallet.hotkey_str}")
    table.add_row("Hotkey", f"{wallet.hotkey.ss58_address}")
    table.add_row("Network", network)
    table.add_row("Netuid", str(netuid))
    return table

def _chain_info_table(current_block: int, season: int, current_round: int, target_round: int | None = None) -> Table:
    table = Table(show_header=False, border_style="dim", pad_edge=False, box=None)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Current block", f"{current_block:,}")
    table.add_row("Season", str(season))
    table.add_row("Current round", str(current_round))
    if target_round is not None:
        table.add_row("Target round", f"[bold yellow]{target_round}[/bold yellow]")
    return table

def _error(msg: str) -> None:
    err_console.print(f"[bold red]ERROR:[/bold red] {msg}")

def _warn(msg: str) -> None:
    console.print(f"[bold yellow]WARNING:[/bold yellow] {msg}")

def _success(msg: str) -> None:
    console.print(f"[bold green]OK:[/bold green] {msg}")

# Argument parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autoppia-miner-cli",
        description="Submit miner agent metadata as an on-chain commitment.",
    )
    sub = parser.add_subparsers(dest="command")

    # -- submit ----------------------------------------------------------------
    submit_p = sub.add_parser("submit", help="Write a miner commitment on-chain.")
    submit_p.add_argument("--github", required=True, help="GitHub repo URL with ref, e.g. https://github.com/owner/repo/tree/branch")
    submit_p.add_argument("--agent.name", dest="agent_name", required=True, help="Agent display name.")
    submit_p.add_argument("--agent.image", dest="agent_image", default="", help="Agent Docker image (optional).")
    submit_p.add_argument("--target_round", type=int, default=None, help="Round to target (default: next round of this season).")
    submit_p.add_argument("--season", type=int, default=None, help="Season number (default: current season).")
    _add_common_args(submit_p)

    # -- show ------------------------------------------------------------------
    show_p = sub.add_parser("show", help="Read the current on-chain commitment for this wallet.")
    _add_common_args(show_p)

    return parser

def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--wallet.name", dest="wallet_name", default="default", help="Wallet coldkey name.")
    p.add_argument("--wallet.hotkey", dest="wallet_hotkey", default="default", help="Wallet hotkey name.")
    p.add_argument("--subtensor.network", dest="subtensor_network", default="finney", help="Subtensor network.")
    p.add_argument("--subtensor.chain_endpoint", dest="subtensor_chain_endpoint", default=None, help="Subtensor chain endpoint URL.")
    p.add_argument("--netuid", type=int, default=_DEFAULT_NETUID, help="Subnet netuid.")

# Core logic
async def _submit(args: argparse.Namespace) -> None:
    _banner()

    # Validate GitHub URL
    normalized, ref = normalize_and_validate_github_url(args.github, require_ref=True)
    if normalized is None:
        _error(
            f"Invalid GitHub URL: {args.github}\n"
            "       Must be https://github.com/owner/repo/tree/<ref> or /commit/<sha>."
        )
        sys.exit(1)

    # Reconstruct the full URL with ref for the commitment
    github_url = f"{normalized}/tree/{ref}" if ref else normalized

    agent_name = args.agent_name.strip()
    if not agent_name:
        _error("--agent.name must not be empty.")
        sys.exit(1)

    agent_image = (args.agent_image or "").strip()

    # Connect to subtensor
    wallet = bt.Wallet(name=args.wallet_name, hotkey=args.wallet_hotkey)
    subtensor_kwargs = {"network": args.subtensor_network}
    if args.subtensor_chain_endpoint:
        subtensor_kwargs["network"] = args.subtensor_chain_endpoint

    console.print(Panel(_wallet_table(wallet, args.subtensor_network, args.netuid), title="Wallet", border_style="blue"))

    async with bt.AsyncSubtensor(**subtensor_kwargs) as st:
        with console.status("[bold cyan]Connecting to subtensor...", spinner="dots"):
            current_block = await st.get_current_block()

        # Resolve season
        season = args.season if args.season is not None else compute_season(current_block)

        # Resolve round
        target_round = args.target_round
        if target_round is None:
            target_round = compute_next_round(current_block, season)

        cur_round = compute_current_round(current_block, season)
        console.print(Panel(
            _chain_info_table(current_block, season, cur_round, target_round),
            title="Chain State",
            border_style="blue",
        ))

        # Build compact commitment payload
        payload = {
            "t": "m",
            "g": github_url,
            "n": agent_name,
            "r": int(target_round),
            "s": int(season),
        }
        if agent_image:
            payload["i"] = agent_image

        console.print(Panel(_commitment_detail_table(payload), title="Commitment Payload", border_style="blue"))

        with console.status("[bold cyan]Submitting commitment on-chain...", spinner="dots"):
            ok = await write_plain_commitment_json(
                st,
                wallet=wallet,
                data=payload,
                netuid=args.netuid,
            )

        if ok:
            _success("Commitment submitted successfully.")
        else:
            _error("Commitment submission failed.")
            sys.exit(1)

        # Read back to confirm
        with console.status("[bold cyan]Verifying on-chain commitment...", spinner="dots"):
            readback = await read_my_plain_json(st, wallet=wallet, netuid=args.netuid)

        if readback:
            console.print(Panel(_commitment_detail_table(readback), title="On-Chain Verification", border_style="green"))
        else:
            _warn("Could not read back commitment (may take a block to propagate).")


async def _show(args: argparse.Namespace) -> None:
    _banner()

    wallet = bt.Wallet(name=args.wallet_name, hotkey=args.wallet_hotkey)
    subtensor_kwargs = {"network": args.subtensor_network}
    if args.subtensor_chain_endpoint:
        subtensor_kwargs["network"] = args.subtensor_chain_endpoint

    console.print(Panel(_wallet_table(wallet, args.subtensor_network, args.netuid), title="Wallet", border_style="blue"))

    async with bt.AsyncSubtensor(**subtensor_kwargs) as st:
        with console.status("[bold cyan]Connecting to subtensor...", spinner="dots"):
            current_block = await st.get_current_block()

        season = compute_season(current_block)
        cur_round = compute_current_round(current_block, season)

        console.print(Panel(
            _chain_info_table(current_block, season, cur_round),
            title="Chain State",
            border_style="blue",
        ))

        with console.status("[bold cyan]Reading commitment...", spinner="dots"):
            commitment = await read_my_plain_json(st, wallet=wallet, netuid=args.netuid)

        if commitment is None:
            _warn("No commitment found on-chain for this hotkey.")
        else:
            console.print(Panel(_commitment_detail_table(commitment), title="On-Chain Commitment", border_style="green"))


def _commitment_detail_table(data: dict) -> Table:
    _FIELD_LABELS = {
        "t": ("Type", lambda v: "miner" if v == "m" else "validator" if v == "v" else str(v)),
        "g": ("GitHub", str),
        "n": ("Agent name", str),
        "r": ("Round", str),
        "s": ("Season", str),
        "i": ("Image", str),
    }
    table = Table(show_header=False, border_style="dim", pad_edge=False, box=None)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    for key, value in data.items():
        if key in _FIELD_LABELS:
            label, fmt = _FIELD_LABELS[key]
            table.add_row(label, fmt(value))
        else:
            table.add_row(key, str(value))
    return table

# Entrypoint
def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        _banner()
        parser.print_help()
        sys.exit(1)

    if args.command == "submit":
        asyncio.run(_submit(args))
    elif args.command == "show":
        asyncio.run(_show(args))
    else:
        _banner()
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()