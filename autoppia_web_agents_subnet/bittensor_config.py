from __future__ import annotations

import sys
import subprocess
import argparse
from pathlib import Path
import bittensor as bt


# ───────────────────────── utilities ───────────────────────── #


def is_cuda_available() -> str:
    """Return 'cuda' if a CUDA device/toolchain looks available, else 'cpu'."""
    try:
        out = subprocess.check_output(["nvidia-smi", "-L"], stderr=subprocess.STDOUT)
        if b"NVIDIA" in out:
            return "cuda"
    except Exception:
        pass
    try:
        out = subprocess.check_output(["nvcc", "--version"], stderr=subprocess.STDOUT)
        if b"release" in out:
            return "cuda"
    except Exception:
        pass
    return "cpu"


# ───────────────────── argument groups (defaults) ───────────────────── #


def add_shared_args(parser: argparse.ArgumentParser) -> None:
    """Arguments shared by miners and validators."""
    parser.add_argument("--netuid", type=int, default=1, help="Subnet netuid.")
    parser.add_argument("--mock", action="store_true", default=False, help="Mock neuron and all network components.")

    parser.add_argument("--neuron.device", type=str, default=is_cuda_available(), help="Device to run on (cpu|cuda).")
    parser.add_argument("--neuron.epoch_length", type=int, default=360, help="Epoch length in (~12s) blocks.")
    parser.add_argument("--neuron.events_retention_size", type=int, default=2 * 1024 * 1024 * 1024, help="Max size for persisted event logs (bytes).")  # 2 GiB
    parser.add_argument("--neuron.dont_save_events", action="store_true", default=False, help="If set, events are not saved to a log file.")

    # Fresh boot helper (shared)
    parser.add_argument(
        "--fresh",
        action="store_true",
        default=False,
        help="Clear local state and start fresh " "(miners: miner_state.json; " "validators: validated_epochs.json, jailed_coldkeys.json, reputation.json).",
    )


def add_validator_args(parser: argparse.ArgumentParser) -> None:
    """Default validator arguments."""
    parser.add_argument("--neuron.name", type=str, default="validator", help="Trials go in neuron.root/(wallet_cold-wallet_hot)/neuron.name.")

    parser.add_argument("--neuron.timeout", type=float, default=10.0, help="Timeout per forward (seconds).")
    parser.add_argument("--neuron.num_concurrent_forwards", type=int, default=1, help="Concurrent forwards.")
    parser.add_argument("--neuron.sample_size", type=int, default=50, help="Number of miners to query per step.")

    # NOTE: Validators can opt-out of serving an Axon
    parser.add_argument("--neuron.axon_off", "--axon_off", action="store_true", default=False, help="Set this flag to not attempt to serve an Axon (validators only).")

    parser.add_argument("--neuron.vpermit_tao_limit", type=int, default=4096, help="Max TAO allowed to query a validator with a vpermit.")

    # Validator-specific testing args
    parser.add_argument("--no_epoch", action="store_true", default=False, help="Enable mock mode (no real chain calls).")
    parser.add_argument("--neuron.moving_average_alpha", type=float, default=1.0, help="Moving average alpha parameter for validator rewards blending.")

    parser.add_argument(
        "--neuron.disable_set_weights",
        action="store_true",
        help="Disables setting weights.",
        default=True,
    )


def add_miner_args(parser: argparse.ArgumentParser) -> None:
    """Default miner arguments."""
    parser.add_argument("--neuron.name", type=str, default="miner", help="Trials go in neuron.root/(wallet_cold-wallet_hot)/neuron.name.")

    # IMPORTANT: default False so AuctionStart/WinSynapse work without vpermit
    parser.add_argument("--blacklist.force_validator_permit", action="store_true", default=True, help="Force incoming requests to have a validator permit.")
    parser.add_argument("--no-blacklist.force_validator_permit", action="store_false", dest="blacklist.force_validator_permit", help="Do NOT force incoming requests to have a validator permit.")

    parser.add_argument("--blacklist.minimum_stake_requirement", type=int, default=1_000, help="Minimum stake required to send requests to miners.")
    parser.add_argument("--blacklist.allow_non_registered", action="store_true", default=False, help="Accept queries from non-registered entities (dangerous).")


# ──────────────────────── main entrypoint ───────────────────────── #


def config(role: str = "auto") -> bt.config:
    """
    Build and return a bittensor config with explicit, layered arg addition:
      1) Core Bittensor groups
      2) Shared defaults
      3) Role-specific defaults (validator | miner | both)
    Args:
        role: "validator", "miner", or "auto" (adds both miner and validator args).
    """
    parser = argparse.ArgumentParser(conflict_handler="resolve")

    # 1) Core bittensor argument groups
    bt.wallet.add_args(parser)
    bt.subtensor.add_args(parser)
    bt.logging.add_args(parser)
    bt.axon.add_args(parser)

    # 2) Shared defaults
    add_shared_args(parser)

    # 3) Role-specific
    role = role.lower()
    if role == "validator":
        add_validator_args(parser)
    elif role == "miner":
        add_miner_args(parser)
    else:  # "auto" → include both
        add_validator_args(parser)
        add_miner_args(parser)

    return bt.config(parser)


# ─────────────────────────── convenience ─────────────────────────── #


def detect_role_from_context() -> str:
    """Helper to pick a role at runtime based on script name."""
    exe = Path(sys.argv[0]).name.lower()
    if "validator" in exe:
        return "validator"
    if "miner" in exe:
        return "miner"
    return "auto"
