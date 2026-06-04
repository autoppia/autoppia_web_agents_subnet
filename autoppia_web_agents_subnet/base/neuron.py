# The MIT License (MIT)
# Copyright © 2023 Yuma Rao

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import copy
import os
import re
import threading
import time
import traceback
from abc import ABC, abstractmethod
from types import SimpleNamespace

import bittensor as bt
import numpy as np

from autoppia_web_agents_subnet import SUBNET_IWA_VERSION, __least_acceptable_version__, __spec_version__

# Sync calls set weights and also resyncs the metagraph.
from autoppia_web_agents_subnet.base.utils.config import _bt_component, add_args, check_config, config
from autoppia_web_agents_subnet.base.utils.misc import _get_current_block_serialized, ttl_get_block
from autoppia_web_agents_subnet.utils.logging_filter import apply_subnet_module_logging_filters


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _split_env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _float_env_list(name: str, *, size: int, default: float = 0.0) -> list[float]:
    values: list[float] = []
    for raw_value in _split_env_list(name):
        try:
            values.append(float(raw_value))
        except ValueError:
            values.append(default)
    if len(values) < size:
        values.extend([default] * (size - len(values)))
    return values[:size]


def _bool_env_list(name: str, *, size: int, default: bool = False) -> list[bool]:
    values = [raw.strip().lower() in {"1", "true", "yes", "on"} for raw in _split_env_list(name)]
    if len(values) < size:
        values.extend([default] * (size - len(values)))
    return values[:size]


def _build_axon_infos(*, hotkeys: list[str], coldkeys: list[str]) -> list[bt.AxonInfo]:
    axon_specs = _split_env_list("STATIC_METAGRAPH_AXONS")
    axons: list[bt.AxonInfo] = []
    for idx, hotkey in enumerate(hotkeys):
        spec = axon_specs[idx] if idx < len(axon_specs) else ""
        host = "0.0.0.0"
        port = 0
        if spec:
            try:
                host_part, port_part = spec.rsplit(":", 1)
                host = host_part.strip() or host
                port = int(port_part)
            except Exception:
                bt.logging.warning(f"Invalid STATIC_METAGRAPH_AXONS entry at index {idx}: {spec!r}")
        axons.append(
            bt.AxonInfo(
                version=0,
                ip=host,
                port=port,
                ip_type=4,
                hotkey=hotkey,
                coldkey=coldkeys[idx] if idx < len(coldkeys) else "",
            )
        )
    return axons


def _build_testing_metagraph(*, validator_hotkey: str, netuid: int):
    hotkeys = _split_env_list("TEST_METAGRAPH_HOTKEYS")
    if not hotkeys:
        hotkeys = [validator_hotkey]
    if validator_hotkey not in hotkeys:
        hotkeys.append(validator_hotkey)

    coldkeys = _split_env_list("TEST_METAGRAPH_COLDKEYS")
    if len(coldkeys) < len(hotkeys):
        coldkeys.extend([""] * (len(hotkeys) - len(coldkeys)))

    stake_values = []
    for raw_stake in _split_env_list("TEST_METAGRAPH_STAKES"):
        try:
            stake_values.append(float(raw_stake))
        except ValueError:
            stake_values.append(0.0)
    if len(stake_values) < len(hotkeys):
        stake_values.extend([0.0] * (len(hotkeys) - len(stake_values)))

    n = len(hotkeys)
    uids = np.arange(n, dtype=np.int64)
    stakes = np.array(stake_values[:n], dtype=np.float32)
    last_update = np.zeros(n, dtype=np.int64)
    validator_permit = np.ones(n, dtype=bool)

    def _sync(*args, **kwargs):
        return None

    return SimpleNamespace(
        netuid=netuid,
        n=np.int64(n),
        uids=uids,
        hotkeys=hotkeys,
        coldkeys=coldkeys[:n],
        S=stakes,
        stake=stakes,
        last_update=last_update,
        validator_permit=validator_permit,
        axons=[],
        sync=_sync,
    )


def _build_static_metagraph(*, local_hotkey: str, netuid: int):
    hotkeys = _split_env_list("STATIC_METAGRAPH_HOTKEYS")
    if not hotkeys:
        hotkeys = [local_hotkey]
    if local_hotkey not in hotkeys:
        hotkeys.append(local_hotkey)

    coldkeys = _split_env_list("STATIC_METAGRAPH_COLDKEYS")
    if len(coldkeys) < len(hotkeys):
        coldkeys.extend([""] * (len(hotkeys) - len(coldkeys)))

    n = len(hotkeys)
    stakes = np.array(_float_env_list("STATIC_METAGRAPH_STAKES", size=n, default=0.0), dtype=np.float32)
    permits = np.array(_bool_env_list("STATIC_METAGRAPH_VALIDATOR_PERMITS", size=n, default=False), dtype=bool)
    uids = np.arange(n, dtype=np.int64)
    last_update = np.zeros(n, dtype=np.int64)
    axons = _build_axon_infos(hotkeys=hotkeys, coldkeys=coldkeys[:n])

    def _sync(*args, **kwargs):
        return None

    return SimpleNamespace(
        netuid=netuid,
        n=np.int64(n),
        uids=uids,
        hotkeys=hotkeys,
        coldkeys=coldkeys[:n],
        S=stakes,
        stake=stakes,
        last_update=last_update,
        validator_permit=permits,
        axons=axons,
        sync=_sync,
    )


class BaseNeuron(ABC):
    """
    Base class for Bittensor miners. This class is abstract and should be inherited by a subclass. It contains the core logic for all neurons; validators and miners.

    In addition to creating a wallet, subtensor, and metagraph, this class also handles the synchronization of the network state via a basic checkpointing mechanism based on epoch length.
    """

    neuron_type: str = "BaseNeuron"

    @classmethod
    def check_config(cls, config: "bt.Config"):
        check_config(cls, config)

    @classmethod
    def add_args(cls, parser):
        add_args(cls, parser)

    @classmethod
    def config(cls):
        return config(cls)

    subtensor: "bt.subtensor"
    wallet: "bt.wallet"
    metagraph: "bt.metagraph"
    spec_version: int = __spec_version__

    @property
    def block(self):
        return self.get_current_block()

    def get_current_block(self, *, fresh: bool = False) -> int:
        """Thread-safe block read. `fresh=True` bypasses TTL cache."""
        if fresh:
            return _get_current_block_serialized(self)
        return ttl_get_block(self)

    def __init__(self, config=None):
        base_config = copy.deepcopy(config or BaseNeuron.config())
        self.config = self.config()
        self.config.merge(base_config)
        self.check_config(self.config)

        # Version check
        self.parse_versions()

        # Set up logging with the provided configuration.
        bt.logging.set_config(config=self.config.logging)
        apply_subnet_module_logging_filters(logging_config=self.config.logging)

        # Filter out noisy dendrite connection errors without changing global log level
        # Note: bt.logging uses its own logger; standard logging.Filter may not catch it.
        # We install both: (1) a stdlib logging Filter for modules that use logging;
        # (2) a lightweight monkey-patch on bt.logging.debug to drop matching messages.
        import logging

        class DendriteNoiseFilter(logging.Filter):
            """Filter to block noisy dendrite connection errors (stdlib logging)."""

            NOISE_PATTERNS = (
                r"ClientConnectorError.*Cannot connect to host",
                r"TimeoutError#[a-f0-9-]+:",
                r"Cannot connect to host 0\.0\.0\.0:(?:0|8091)",
            )

            def filter(self, record):
                try:
                    msg = record.getMessage()
                except Exception:
                    return True
                return all(not re.search(pattern, msg) for pattern in self.NOISE_PATTERNS)

        # Attach stdlib filter (harmless if unused)
        logging.getLogger("bittensor.dendrite").addFilter(DendriteNoiseFilter())

        # Optional bt.logging debug filter (covers loguru-style logger used by bittensor)
        if getattr(self.config, "logging", None) is None or getattr(self.config.logging, "suppress_dendrite_noise", True):
            patterns = [
                re.compile(r"ClientConnectorError.*Cannot connect to host"),
                re.compile(r"TimeoutError#[a-f0-9-]+:"),
                re.compile(r"Cannot connect to host 0\.0\.0\.0:(?:0|8091)"),
            ]

            _orig_debug = bt.logging.debug

            def _filtered_debug(message, *args, **kwargs):
                try:
                    text = message if isinstance(message, str) else str(message)
                except Exception:
                    text = ""
                for rgx in patterns:
                    if rgx.search(text):
                        return  # swallow noisy debug line
                return _orig_debug(message, *args, **kwargs)

            # Install once per process
            if not hasattr(bt.logging, "_dendrite_noise_filter_installed"):
                bt.logging.debug = _filtered_debug
                bt.logging._dendrite_noise_filter_installed = True

        # If a gpu is required, set the device to cuda:N (e.g. cuda:0)
        self.device = self.config.neuron.device

        # Log the configuration for reference.
        bt.logging.info(self.config)

        # Build Bittensor objects
        # These are core Bittensor classes to interact with the network.
        bt.logging.info("Setting up bittensor objects.")

        # The wallet holds the cryptographic key pairs for the miner.

        self.wallet = _bt_component("wallet", "Wallet")(config=self.config)
        while True:
            try:
                bt.logging.info("Initializing subtensor and metagraph")
                self.subtensor = _bt_component("subtensor", "Subtensor")(config=self.config)
                if _env_bool("STATIC_METAGRAPH"):
                    bt.logging.warning("STATIC_METAGRAPH enabled; using env-provided metagraph")
                    self.metagraph = _build_static_metagraph(
                        local_hotkey=self.wallet.hotkey.ss58_address,
                        netuid=int(self.config.netuid),
                    )
                elif _env_bool("TESTING") and _env_bool("TEST_SKIP_CHAIN_METAGRAPH"):
                    bt.logging.warning("TEST_SKIP_CHAIN_METAGRAPH enabled; using local testing metagraph")
                    self.metagraph = _build_testing_metagraph(
                        validator_hotkey=self.wallet.hotkey.ss58_address,
                        netuid=int(self.config.netuid),
                    )
                else:
                    self.metagraph = self.subtensor.metagraph(
                        self.config.netuid,
                        lite=_env_bool("METAGRAPH_LITE"),
                    )
                break
            except Exception as e:
                bt.logging.error(f"Couldn't init subtensor and metagraph with error: {e}")
                bt.logging.error("If you use public RPC endpoint try to move to local node")
                time.sleep(5)

        bt.logging.info(f"Wallet: {self.wallet}")
        bt.logging.info(f"Subtensor: {self.subtensor}")
        bt.logging.info(f"Metagraph: {self.metagraph}")

        # Check if the miner is registered on the Bittensor network before proceeding further.
        self.check_registered()

        # Each miner gets a unique identity (UID) in the network for differentiation.
        self.uid = self.metagraph.hotkeys.index(self.wallet.hotkey.ss58_address)
        bt.logging.info(f"Running neuron on subnet: {self.config.netuid} with uid {self.uid} using network: {self.subtensor.chain_endpoint}")
        self.step = 0
        self.last_update = 0
        self._sync_lock = threading.RLock()

    @abstractmethod
    async def forward(self, synapse: bt.Synapse) -> bt.Synapse: ...

    @abstractmethod
    def run(self): ...

    @abstractmethod
    def resync_metagraph(self):
        """
        Abstract method that forces subclasses to implement resync_metagraph.
        This ensures that all subclasses define their own way of resynchronizing
        the metagraph.
        """
        pass

    @abstractmethod
    def set_weights(self):
        pass

    def sync(self):
        """
        Wrapper for synchronizing the state of the network for the given miner or validator.
        """
        with self._sync_lock:
            # Ensure miner or validator hotkey is still registered on the network.
            self.check_registered()

            try:
                if self.should_sync_metagraph():
                    self.last_update = self.block
                    self.resync_metagraph()

                if self.should_set_weights():
                    self.set_weights()

                # Always save state.
                self.save_state()
            except Exception:
                bt.logging.error(f"Coundn't sync metagraph or set weights: {traceback.format_exc()}")
                bt.logging.error("If you use public RPC endpoint try to move to local node")
                time.sleep(5)

    def check_registered(self):
        # --- Check for registration.
        if _env_bool("STATIC_METAGRAPH") and _env_bool("STATIC_METAGRAPH_SKIP_REGISTRATION_CHECK", default=True):
            if self.wallet.hotkey.ss58_address in getattr(self.metagraph, "hotkeys", []):
                return
        if _env_bool("TESTING") and _env_bool("TEST_SKIP_CHAIN_METAGRAPH"):
            if self.wallet.hotkey.ss58_address in getattr(self.metagraph, "hotkeys", []):
                return
        if not self.subtensor.is_hotkey_registered(
            netuid=self.config.netuid,
            hotkey_ss58=self.wallet.hotkey.ss58_address,
        ):
            bt.logging.error(f"Wallet: {self.wallet} is not registered on netuid {self.config.netuid}. Please register the hotkey using `btcli subnets register` before trying again")
            exit()

    def should_sync_metagraph(self):
        """
        Check if enough epoch blocks have elapsed since the last checkpoint to sync.

        """
        if _env_bool("STATIC_METAGRAPH"):
            return False
        last_update = self.metagraph.last_update[self.uid] if self.neuron_type != "MinerNeuron" else self.last_update

        return (self.block - last_update) > self.config.neuron.epoch_length

    def should_set_weights(self) -> bool:
        if _env_bool("STATIC_METAGRAPH"):
            return False

        # Don't set weights on initialization.
        if self.step == 0:
            return False

        # Check if enough epoch blocks have elapsed since the last epoch.
        if self.config.neuron.disable_set_weights:
            return False

        # Define appropriate logic for when set weights.
        return (self.block - self.metagraph.last_update[self.uid]) > self.config.neuron.epoch_length and self.neuron_type != "MinerNeuron"  # don't set weights if you're a miner

    def save_state(self):
        bt.logging.trace("save_state() not implemented for this neuron. You can implement this function to save model checkpoints or other useful data.")

    def load_state(self):
        bt.logging.trace("load_state() not implemented for this neuron. You can implement this function to load model checkpoints or other useful data.")

    def parse_versions(self):
        # No network version check: validators should not block startup on an
        # external request. Local package versions are the source of truth.
        self.version = SUBNET_IWA_VERSION
        self.least_acceptable_version = __least_acceptable_version__
        return
