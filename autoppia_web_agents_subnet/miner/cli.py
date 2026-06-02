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

from .config import load_config, update_config
from .help import StyledAliasGroup
from .chutes_deploy import ChutesCliError, run_deploy
from .service import DEFAULT_NETUID, CommonOptions, MinerCliError, render_config_panel, run_show, run_status, run_submit
from .ui import print_banner, print_error, print_success


def _common_options(func: Callable[..., Any]) -> Callable[..., Any]:
    options = [
        click.option("--wallet.name", "wallet_name", default=None, help="Wallet coldkey name. Falls back to config/default."),
        click.option("--wallet.hotkey", "wallet_hotkey", default=None, help="Wallet hotkey name. Falls back to config/default."),
        click.option(
            "--hotkey",
            "inspect_hotkey_ss58",
            default=None,
            help="Inspect this miner hotkey SS58 directly without needing a local wallet.",
        ),
        click.option(
            "--hotkey.ss58",
            "inspect_hotkey_ss58",
            default=None,
            hidden=True,
            help="Deprecated alias for --hotkey.",
        ),
        click.option("--round", "inspect_round", type=int, default=None, help="Filter consensus inspection by round."),
        click.option("--season", "inspect_season", type=int, default=None, help="Filter consensus inspection by season."),
        click.option(
            "--consensus-version",
            "consensus_version",
            type=int,
            default=None,
            help="Consensus version/id to inspect. Falls back to config/default prod version.",
        ),
        click.option(
            "--subtensor.network",
            "subtensor_network",
            default="finney",
            show_default=True,
            help="Subtensor network. Falls back to config if changed.",
        ),
        click.option(
            "--subtensor.chain_endpoint",
            "subtensor_chain_endpoint",
            default=None,
            help="Subtensor chain endpoint URL. Falls back to config if unset.",
        ),
        click.option("--netuid", type=int, default=DEFAULT_NETUID, show_default=True, help="Subnet netuid. Falls back to config if changed."),
    ]
    for option in reversed(options):
        func = option(func)
    return func


def _run_async(coro: Awaitable[None]) -> None:
    try:
        asyncio.run(coro)
    except MinerCliError as exc:
        print_error(str(exc))
        raise click.exceptions.Exit(1) from exc
    except ChutesCliError as exc:
        print_error(str(exc))
        raise click.exceptions.Exit(1) from exc
    except Exception as exc:
        print_error(f"{type(exc).__name__}: {exc}")
        raise click.exceptions.Exit(1) from exc


@click.group(cls=StyledAliasGroup, invoke_without_command=True)
@click.version_option(version=SUBNET_IWA_VERSION, prog_name="autoppia-miner-cli")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """
    Manage miner commitments, trigger evaluations, and inspect latest consensus state.

    """
    if ctx.invoked_subcommand is None:
        print_banner()
        click.echo(ctx.get_help())
        raise click.exceptions.Exit(1)


@cli.command("submit")
@click.option(
    "--github",
    default=None,
    help="GitHub repo URL with ref, e.g. https://github.com/owner/repo/tree/branch",
)
@click.option("--agent.name", "agent_name", default=None, help="Agent display name. Falls back to config if set.")
@click.option("--agent.image", "agent_image", default=None, help="Agent Docker image (optional). Falls back to config if set.")
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
    inspect_hotkey_ss58: str | None,
    inspect_round: int | None,
    inspect_season: int | None,
    consensus_version: int | None,
    subtensor_network: str,
    subtensor_chain_endpoint: str | None,
    netuid: int,
) -> None:
    """Write a miner commitment on-chain."""
    config = load_config()
    options = CommonOptions(
        wallet_name=wallet_name,
        wallet_hotkey=wallet_hotkey,
        inspect_hotkey_ss58=inspect_hotkey_ss58,
        inspect_round=inspect_round,
        inspect_season=inspect_season,
        consensus_version=consensus_version,
        subtensor_network=subtensor_network,
        subtensor_chain_endpoint=subtensor_chain_endpoint,
        netuid=netuid,
    )
    _run_async(
        run_submit(
            options=options,
            github=(github or config.get("github") or ""),
            agent_name=(agent_name or config.get("agent_name") or ""),
            agent_image=(agent_image if agent_image is not None else config.get("agent_image") or ""),
            target_round=target_round,
            season=season,
        )
    )


@cli.command("trigger-eval")
@click.option(
    "--github",
    default=None,
    help="GitHub repo URL with ref, e.g. https://github.com/owner/repo/tree/branch",
)
@click.option("--agent.name", "agent_name", default=None, help="Agent display name. Falls back to config if set.")
@click.option("--agent.image", "agent_image", default=None, help="Agent Docker image (optional). Falls back to config if set.")
@click.option("--target_round", type=int, default=None, help="Round to target (default: next round of this season).")
@click.option("--season", type=int, default=None, help="Season number (default: current season).")
@_common_options
def trigger_eval_command(
    github: str,
    agent_name: str,
    agent_image: str,
    target_round: int | None,
    season: int | None,
    wallet_name: str,
    wallet_hotkey: str,
    inspect_hotkey_ss58: str | None,
    inspect_round: int | None,
    inspect_season: int | None,
    consensus_version: int | None,
    subtensor_network: str,
    subtensor_chain_endpoint: str | None,
    netuid: int,
) -> None:
    """Alias for submit, optimized for miners who just want the validator to pick up a new commit."""
    config = load_config()
    options = CommonOptions(
        wallet_name=wallet_name,
        wallet_hotkey=wallet_hotkey,
        inspect_hotkey_ss58=inspect_hotkey_ss58,
        inspect_round=inspect_round,
        inspect_season=inspect_season,
        consensus_version=consensus_version,
        subtensor_network=subtensor_network,
        subtensor_chain_endpoint=subtensor_chain_endpoint,
        netuid=netuid,
    )
    _run_async(
        run_submit(
            options=options,
            github=(github or config.get("github") or ""),
            agent_name=(agent_name or config.get("agent_name") or ""),
            agent_image=(agent_image if agent_image is not None else config.get("agent_image") or ""),
            target_round=target_round,
            season=season,
        )
    )


@cli.command("show")
@_common_options
def show_command(
    wallet_name: str,
    wallet_hotkey: str,
    inspect_hotkey_ss58: str | None,
    inspect_round: int | None,
    inspect_season: int | None,
    consensus_version: int | None,
    subtensor_network: str,
    subtensor_chain_endpoint: str | None,
    netuid: int,
) -> None:
    """Read the current on-chain commitment for this wallet."""
    options = CommonOptions(
        wallet_name=wallet_name,
        wallet_hotkey=wallet_hotkey,
        inspect_hotkey_ss58=inspect_hotkey_ss58,
        inspect_round=inspect_round,
        inspect_season=inspect_season,
        consensus_version=consensus_version,
        subtensor_network=subtensor_network,
        subtensor_chain_endpoint=subtensor_chain_endpoint,
        netuid=netuid,
    )
    _run_async(run_show(options=options))


@cli.command("status")
@_common_options
def status_command(
    wallet_name: str,
    wallet_hotkey: str,
    inspect_hotkey_ss58: str | None,
    inspect_round: int | None,
    inspect_season: int | None,
    consensus_version: int | None,
    subtensor_network: str,
    subtensor_chain_endpoint: str | None,
    netuid: int,
) -> None:
    """Show current commitment plus the latest consensus/ranking view for this miner."""
    options = CommonOptions(
        wallet_name=wallet_name,
        wallet_hotkey=wallet_hotkey,
        inspect_hotkey_ss58=inspect_hotkey_ss58,
        inspect_round=inspect_round,
        inspect_season=inspect_season,
        consensus_version=consensus_version,
        subtensor_network=subtensor_network,
        subtensor_chain_endpoint=subtensor_chain_endpoint,
        netuid=netuid,
    )
    _run_async(run_status(options=options))


@cli.group("config")
def config_group() -> None:
    """Manage persistent autoppia-miner-cli defaults."""


@config_group.command("show")
def config_show_command() -> None:
    """Show the currently configured defaults."""
    render_config_panel()


@config_group.command("set")
@click.option("--wallet.name", "wallet_name", default=None, help="Default wallet coldkey name.")
@click.option("--wallet.hotkey", "wallet_hotkey", default=None, help="Default wallet hotkey name.")
@click.option("--subtensor.network", "subtensor_network", default=None, help="Default subtensor network.")
@click.option("--subtensor.chain_endpoint", "subtensor_chain_endpoint", default=None, help="Default chain endpoint.")
@click.option("--netuid", type=int, default=None, help="Default netuid.")
@click.option("--consensus-version", "consensus_version", type=int, default=None, help="Default consensus version/id for status inspection.")
@click.option("--github", default=None, help="Default GitHub URL for trigger-eval/submit.")
@click.option("--agent.name", "agent_name", default=None, help="Default agent name.")
@click.option("--agent.image", "agent_image", default=None, help="Default agent image.")
def config_set_command(
    wallet_name: str | None,
    wallet_hotkey: str | None,
    subtensor_network: str | None,
    subtensor_chain_endpoint: str | None,
    netuid: int | None,
    consensus_version: int | None,
    github: str | None,
    agent_name: str | None,
    agent_image: str | None,
) -> None:
    """Persist default values so the miner does not need to retype them every time."""
    updates = {
        "wallet_name": wallet_name,
        "wallet_hotkey": wallet_hotkey,
        "subtensor_network": subtensor_network,
        "subtensor_chain_endpoint": subtensor_chain_endpoint,
        "netuid": netuid,
        "consensus_version": consensus_version,
        "github": github,
        "agent_name": agent_name,
        "agent_image": agent_image,
    }
    if all(value is None for value in updates.values()):
        raise click.exceptions.UsageError("Pass at least one value to store.")
    updates = {key: value for key, value in updates.items() if value is not None}
    path, _config = update_config(updates)
    print_success(f"Saved miner CLI defaults to {path}")
    render_config_panel()


@cli.group("chutes")
def chutes_group() -> None:
    """Chutes.ai deployment management."""


@chutes_group.command("deploy")
@click.option("--username", default=None, help="Chutes username.")
@click.option("--model", default=None, help="HuggingFace model (e.g. unsloth/Llama-3.2-1B-Instruct).")
@click.option("--revision", default=None, help="Model revision (40-char commit hash). Leave blank for auto.")
@click.option("--image", default=None, help="Chutes image.")
@click.option("--gpu-count", "gpu_count", default=None, help="Number of GPUs.")
@click.option("--min-vram", "min_vram", default=None, help="Minimum VRAM per GPU in GB.")
@click.option("--include-gpus", "include_gpus", default=None, help="Include GPUs (comma-separated).")
@click.option("--exclude-gpus", "exclude_gpus", default=None, help="Exclude GPUs (comma-separated).")
@click.option("--concurrency", default=None, help="Max concurrent requests.")
@click.option("--engine-args", "engine_args", default=None, help="Engine args.")
@click.option("--accept-fee/--no-accept-fee", "accept_fee", default=None, help="Accept deployment fee automatically.")
@click.option("--dry-run", is_flag=True, default=False, help="Dry run only.")
def chutes_deploy_command(
    username: str | None,
    model: str | None,
    revision: str | None,
    image: str | None,
    gpu_count: str | None,
    min_vram: str | None,
    include_gpus: str | None,
    exclude_gpus: str | None,
    concurrency: str | None,
    engine_args: str | None,
    accept_fee: bool | None,
    dry_run: bool,
) -> None:
    """Deploy a custom model to Chutes.ai."""
    _run_async(
        run_deploy(
            username=username,
            model=model,
            revision=revision,
            image=image,
            gpu_count=gpu_count,
            min_vram=min_vram,
            include_gpus=include_gpus,
            exclude_gpus=exclude_gpus,
            concurrency=concurrency,
            engine_args=engine_args,
            accept_fee=accept_fee,
            dry_run=dry_run,
        )
    )


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
