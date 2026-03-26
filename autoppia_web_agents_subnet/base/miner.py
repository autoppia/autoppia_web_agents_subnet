# The MIT License (MIT)
# (c) 2023 Yuma Rao — modified for Autoppia Web Agents Subnet

import asyncio
import threading
import time
import traceback
from inspect import Parameter, Signature

import bittensor as bt

from autoppia_web_agents_subnet.base.neuron import BaseNeuron
from autoppia_web_agents_subnet.protocol import StartRoundSynapse

BLACKLIST_RETURN_ANNOTATION = __import__("typing").Tuple[bool, str]


class BaseMinerNeuron(BaseNeuron):
    """
    Base class for Bittensor miners in the Autoppia Web Agents subnet.

    Exposes one endpoint:
      - forward(StartRoundSynapse) → round handshake / miner metadata
    """

    neuron_type: str = "MinerNeuron"

    def __init__(self, config=None):
        super().__init__(config=config)

        # Warn if allowing incoming requests from anyone.
        if not self.config.blacklist.force_validator_permit:
            bt.logging.warning("You are allowing non-validators to send requests to your miner. This is a security risk.")
        if self.config.blacklist.allow_non_registered:
            bt.logging.warning("You are allowing non-registered entities to send requests to your miner. This is a security risk.")

        # The axon handles request processing, allowing validators to send this miner requests.
        self.axon = bt.axon(
            wallet=self.wallet,
            config=self.config() if callable(self.config) else self.config,
        )

        # Attach RPCs
        bt.logging.info("Attaching forward function to miner axon.")

        async def _blacklist_wrapper(
            synapse: StartRoundSynapse,
        ) -> tuple[bool, str]:
            return await self.blacklist(synapse)

        _blacklist_wrapper.__signature__ = Signature(  # type: ignore[attr-defined]
            [
                Parameter(
                    name="synapse",
                    kind=Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=StartRoundSynapse,
                )
            ],
            return_annotation=BLACKLIST_RETURN_ANNOTATION,
        )

        self.axon.attach(
            forward_fn=self.forward,
            blacklist_fn=_blacklist_wrapper,
            priority_fn=self.priority,
        )
        bt.logging.info(f"Axon created: {self.axon}")

        # Runtime flags / threading
        self.should_exit: bool = False
        self.is_running: bool = False
        self.thread: threading.Thread | None = None
        self.lock = asyncio.Lock()

    # ─────────────────────────── Runner ───────────────────────────

    def run(self):
        """
        Main loop:
          1) Ensure registration / sync.
          2) Serve & start axon.
          3) Epoch loop: sync metagraph periodically.
        """
        self.sync()

        bt.logging.info(f"Serving miner axon {self.axon} on network: {self.config.subtensor.chain_endpoint} with netuid: {self.config.netuid}")
        self.axon.serve(netuid=self.config.netuid, subtensor=self.subtensor)
        bt.logging.info("🔧 Axon configured, about to start listening...")
        self.axon.start()
        bt.logging.success(f"✅ Miner axon STARTED and LISTENING at block: {self.block}")
        bt.logging.success(f"✅ Miner IP: {self.axon.external_ip}:{self.axon.external_port}")
        bt.logging.success(f"✅ Miner hotkey: {self.wallet.hotkey.ss58_address}")

        try:
            while not self.should_exit:
                while self.block - self.metagraph.last_update[self.uid] < self.config.neuron.epoch_length:
                    time.sleep(1)
                    if self.should_exit:
                        break
                self.sync()
                self.step += 1

        except KeyboardInterrupt:
            self.axon.stop()
            bt.logging.success("Miner killed by keyboard interrupt.")
            exit()

        except Exception:
            bt.logging.error(traceback.format_exc())

    def run_in_background_thread(self):
        if not self.is_running:
            bt.logging.debug("Starting miner in background thread.")
            self.should_exit = False
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
            self.is_running = True
            bt.logging.debug("Started")

    def stop_run_thread(self):
        if self.is_running:
            bt.logging.debug("Stopping miner in background thread.")
            self.should_exit = True
            if self.thread is not None:
                self.thread.join(5)
            self.is_running = False
            bt.logging.debug("Stopped")

    def __enter__(self):
        self.run_in_background_thread()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop_run_thread()

    def resync_metagraph(self):
        """Resyncs the metagraph and updates the hotkeys and moving averages based on the new metagraph."""
        bt.logging.info("resync_metagraph()")
        self.metagraph.sync(subtensor=self.subtensor)

    # Overriding the abstract method from BaseNeuron to avoid instantiation error
    def set_weights(self):
        pass

    # ─────────────────────── Blacklists ───────────────────────

    async def blacklist(self, synapse: StartRoundSynapse) -> tuple[bool, str]:
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return True, "Missing dendrite or hotkey"

        validator_hotkey = synapse.dendrite.hotkey

        # Ensure hotkey is recognized.
        if not self.config.blacklist.allow_non_registered and validator_hotkey not in self.metagraph.hotkeys:
            bt.logging.warning(f"Unrecognized hotkey: {validator_hotkey}")
            return True, f"Unrecognized hotkey: {validator_hotkey}"

        uid = self.metagraph.hotkeys.index(validator_hotkey)

        # Optionally force only validators
        if self.config.blacklist.force_validator_permit and not self.metagraph.validator_permit[uid]:
            bt.logging.warning(f"Blacklisted Non-Validator {validator_hotkey}")
            return True, f"Non-validator hotkey: {validator_hotkey}"

        # Check minimum stake
        stake = self.metagraph.S[uid]
        min_stake = self.config.blacklist.minimum_stake_requirement
        if stake < min_stake:
            bt.logging.warning(f"Blacklisted insufficient stake: {validator_hotkey}")
            return (
                True,
                f"Insufficient stake ({stake} < {min_stake}) for {validator_hotkey}",
            )

        return False, f"Hotkey recognized: {validator_hotkey}"

    # ─────────────────────── Priority ───────────────────────

    async def priority(self, synapse: StartRoundSynapse) -> float:
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return 0.0

        validator_hotkey = synapse.dendrite.hotkey
        if validator_hotkey not in self.metagraph.hotkeys:
            return 0.0

        caller_uid = self.metagraph.hotkeys.index(validator_hotkey)
        return float(self.metagraph.S[caller_uid])
