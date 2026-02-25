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

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import click

from autoppia_web_agents_subnet import SUBNET_IWA_VERSION

from .help import StyledAliasGroup
from .service import DEFAULT_NETUID, CommonOptions, MinerCliError, run_show, run_submit
from .ui import print_banner, print_error


def _common_options(func: Callable[..., Any]) -> Callable[..., Any]:
    options = [
        click.option("--wallet.name", "wallet_name", default="default", show_default=True, help="Wallet coldkey name."),
        click.option("--wallet.hotkey", "wallet_hotkey", default="default", show_default=True, help="Wallet hotkey name."),
        click.option(
            "--subtensor.network",
            "subtensor_network",
            default="finney",
            show_default=True,
            help="Subtensor network.",
        ),
        click.option(
            "--subtensor.chain_endpoint",
            "subtensor_chain_endpoint",
            default=None,
            help="Subtensor chain endpoint URL.",
        ),
        click.option("--netuid", type=int, default=DEFAULT_NETUID, show_default=True, help="Subnet netuid."),
    ]
    for option in reversed(options):
        func = option(func)
    return func


def _run_async(coro: Awaitable[None]) -> None:
    try:
        asyncio.run(coro)
    except MinerCliError as exc:
        print_error(str(exc))
        raise click.exceptions.Exit(1)
    except Exception as exc:
        print_error(f"{type(exc).__name__}: {exc}")
        raise click.exceptions.Exit(1)


@click.group(cls=StyledAliasGroup, invoke_without_command=True)
@click.version_option(version=SUBNET_IWA_VERSION, prog_name="autoppia-miner-cli")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """
    Submit miner agent metadata as an on-chain commitment.
    
    """
    if ctx.invoked_subcommand is None:
        print_banner()
        click.echo(ctx.get_help())
        raise click.exceptions.Exit(1)


@cli.command("submit")
@click.option(
    "--github",
    required=True,
    help="GitHub repo URL with ref, e.g. https://github.com/owner/repo/tree/branch",
)
@click.option("--agent.name", "agent_name", required=True, help="Agent display name.")
@click.option("--agent.image", "agent_image", default="", help="Agent Docker image (optional).")
@click.option("--target_round", type=int, default=None, help="Round to target (default: next round of this season).")
@click.option("--season", type=int, default=None, help="Season number (default: current season).")
@_common_options
def submit_command(
    github: str,
    agent_name: str,
    agent_image: str,
    target_round: int | None,
    season: int | None,
    wallet_name: str,
    wallet_hotkey: str,
    subtensor_network: str,
    subtensor_chain_endpoint: str | None,
    netuid: int,
) -> None:
    """Write a miner commitment on-chain."""
    options = CommonOptions(
        wallet_name=wallet_name,
        wallet_hotkey=wallet_hotkey,
        subtensor_network=subtensor_network,
        subtensor_chain_endpoint=subtensor_chain_endpoint,
        netuid=netuid,
    )
    _run_async(
        run_submit(
            options=options,
            github=github,
            agent_name=agent_name,
            agent_image=agent_image,
            target_round=target_round,
            season=season,
        )
    )


@cli.command("show")
@_common_options
def show_command(
    wallet_name: str,
    wallet_hotkey: str,
    subtensor_network: str,
    subtensor_chain_endpoint: str | None,
    netuid: int,
) -> None:
    """Read the current on-chain commitment for this wallet."""
    options = CommonOptions(
        wallet_name=wallet_name,
        wallet_hotkey=wallet_hotkey,
        subtensor_network=subtensor_network,
        subtensor_chain_endpoint=subtensor_chain_endpoint,
        netuid=netuid,
    )
    _run_async(run_show(options=options))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
