from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()
err_console = Console(stderr=True)


def print_banner() -> None:
    console.print(
        Panel(
            Text("autoppia-miner-cli", style="bold cyan", justify="center"),
            subtitle="Miner Agent On-Chain Commitment Tool",
            border_style="bright_blue",
        )
    )
    console.print()


def print_error(msg: str) -> None:
    err_console.print(f"[bold red]ERROR:[/bold red] {msg}")


def print_warning(msg: str) -> None:
    console.print(f"[bold yellow]WARNING:[/bold yellow] {msg}")


def print_success(msg: str) -> None:
    console.print(f"[bold green]OK:[/bold green] {msg}")


def _wallet_table(wallet: Any, network_label: str, netuid: int) -> Table:
    table = Table(show_header=False, border_style="dim", pad_edge=False, box=None)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Wallet", f"{wallet.name} / {wallet.hotkey_str}")
    table.add_row("Hotkey", f"{wallet.hotkey.ss58_address}")
    table.add_row("Network", network_label)
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


def _commitment_detail_table(data: dict[str, Any]) -> Table:
    field_labels: dict[str, tuple[str, Any]] = {
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
        if key in field_labels:
            label, fmt = field_labels[key]
            table.add_row(label, fmt(value))
        else:
            table.add_row(key, str(value))
    return table


def show_wallet_panel(wallet: Any, network_label: str, netuid: int) -> None:
    console.print(Panel(_wallet_table(wallet, network_label, netuid), title="Wallet", border_style="blue"))


def show_chain_state_panel(
    current_block: int,
    season: int,
    current_round: int,
    target_round: int | None = None,
) -> None:
    console.print(
        Panel(
            _chain_info_table(current_block, season, current_round, target_round),
            title="Chain State",
            border_style="blue",
        )
    )


def show_commitment_panel(data: dict[str, Any], *, title: str, border_style: str) -> None:
    console.print(Panel(_commitment_detail_table(data), title=title, border_style=border_style))
