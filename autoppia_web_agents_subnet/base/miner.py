# The MIT License (MIT)
# Copyright © 2023 Yuma Rao

import time
import asyncio
import threading
import argparse
import typing
import traceback

import bittensor as bt

from autoppia_web_agents_subnet.base.neuron import BaseNeuron
from autoppia_web_agents_subnet.utils.config import add_miner_args

from typing import Union
from autoppia_web_agents_subnet.protocol import (
    TaskSynapse,
    TaskFeedbackSynapse,
    SetOperatorEndpointSynapse,
)


class BaseMinerNeuron(BaseNeuron):
    """
    Base class for Bittensor miners.

    Responsibilities:
      - Start and manage the axon and the main miner loop.
      - Provide default blacklist/priority implementations for all routes.
      - Expose helper methods `_common_blacklist(...)` and `_common_priority(...)`
        which can be overridden by subclasses for custom behavior.
    """

    neuron_type: str = "MinerNeuron"

    def __init__(self, config=None):
        super().__init__(config=config)

        # Security warnings.
        if not self.config.blacklist.force_validator_permit:
            bt.logging.warning("You are allowing non-validators to send requests to your miner. This is a security risk.")
        if self.config.blacklist.allow_non_registered:
            bt.logging.warning("You are allowing non-registered entities to send requests to your miner. This is a security risk.")

        # Axon to receive requests.
        self.axon = bt.axon(
            wallet=self.wallet,
            config=self.config() if callable(self.config) else self.config,
        )

        # Routes: task, feedback and set_operator_endpoint
        bt.logging.info("Attaching forward functions to miner axon.")
        self.axon.attach(
            forward_fn=self.forward,
            blacklist_fn=self.blacklist,
            priority_fn=self.priority,
        )
        self.axon.attach(
            forward_fn=self.forward_feedback,
            blacklist_fn=self.blacklist_feedback,
            priority_fn=self.priority_feedback,
        )
        self.axon.attach(
            forward_fn=self.forward_set_organic_endpoint,
            blacklist_fn=self.blacklist_set_organic_endpoint,
            priority_fn=self.priority_set_organic_endpoint,
        )
        bt.logging.info(f"Axon created: {self.axon}")

        # Background thread control
        self.should_exit: bool = False
        self.is_running: bool = False
        self.thread: Union[threading.Thread, None] = None
        self.lock = asyncio.Lock()

    # ----------------------------- Main loop ------------------------------
    def run(self):
        """Main loop of the miner process."""
        # Ensure miner is registered on the network.
        self.sync()

        bt.logging.info(f"Serving miner axon {self.axon} on network: {self.config.subtensor.chain_endpoint} with netuid: {self.config.netuid}")
        self.axon.serve(netuid=self.config.netuid, subtensor=self.subtensor)
        self.axon.start()

        bt.logging.info(f"Miner starting at block: {self.block}")

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
            bt.logging.success("Miner stopped by keyboard interrupt.")
            exit()
        except Exception:
            bt.logging.error(traceback.format_exc())

    def run_in_background_thread(self):
        """Starts the miner loop in a background thread."""
        if not self.is_running:
            bt.logging.debug("Starting miner in background thread.")
            self.should_exit = False
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
            self.is_running = True
            bt.logging.debug("Started")

    def stop_run_thread(self):
        """Stops the miner loop if it is running in a background thread."""
        if self.is_running:
            bt.logging.debug("Stopping miner in background thread.")
            self.should_exit = True
            if self.thread is not None:
                self.thread.join(5)
            self.is_running = False
            bt.logging.debug("Stopped")

    def __enter__(self):
        """Context manager entry: start miner in a background thread."""
        self.run_in_background_thread()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Context manager exit: stop miner in background thread."""
        self.stop_run_thread()

    # ------------------------ Default blacklist -------------------
    async def blacklist(self, synapse: TaskSynapse) -> typing.Tuple[bool, str]:
        return await self._common_blacklist(synapse)

    async def blacklist_feedback(self, synapse: TaskFeedbackSynapse) -> typing.Tuple[bool, str]:
        return await self._common_blacklist(synapse)

    async def blacklist_set_organic_endpoint(self, synapse: SetOperatorEndpointSynapse) -> typing.Tuple[bool, str]:
        return await self._common_blacklist(synapse)

    async def _common_blacklist(
        self,
        synapse: typing.Union[TaskSynapse, TaskFeedbackSynapse, SetOperatorEndpointSynapse],
    ) -> typing.Tuple[bool, str]:
        """
        Shared blacklist logic for all routes. Rejects if:
          - No dendrite/hotkey present
          - Hotkey not found in the metagraph (depending on config)
          - Permit is required and caller does not have one
          - Stake is below the configured minimum
        """
        try:
            if synapse.dendrite is None or synapse.dendrite.hotkey is None:
                bt.logging.warning("BLK: Missing dendrite/hotkey")
                return True, "Missing dendrite or hotkey"

            hk = synapse.dendrite.hotkey

            # Non-registered
            if not self.config.blacklist.allow_non_registered and hk not in self.metagraph.hotkeys:
                bt.logging.warning(f"BLK: Unrecognized hotkey: {hk}")
                return True, f"Unrecognized hotkey: {hk}"

            # UID
            try:
                uid = self.metagraph.hotkeys.index(hk) if hk in self.metagraph.hotkeys else -1
            except Exception:
                uid = -1

            # Permit
            try:
                permit = self.metagraph.validator_permit[uid] if uid >= 0 else False
            except Exception:
                permit = False

            # Stake
            try:
                stake = float(self.metagraph.S[uid]) if uid >= 0 else 0.0
            except Exception:
                stake = 0.0

            # Require permit if configured
            if self.config.blacklist.force_validator_permit and not permit:
                bt.logging.warning(f"BLK: Non-validator hk={hk} uid={uid}")
                return True, f"Non-validator hotkey: {hk}"

            # Minimum stake
            try:
                min_stake = float(self.config.blacklist.minimum_stake_requirement)
            except Exception:
                min_stake = 0.0

            if stake < min_stake:
                bt.logging.warning(f"BLK: Insufficient stake {stake} < {min_stake} hk={hk} uid={uid}")
                return True, f"Insufficient stake ({stake} < {min_stake}) for {hk}"

            bt.logging.info(f"[BLK] Accepted hk={hk} uid={uid} stake={stake}")
            return False, f"Hotkey recognized: {hk}"
        except Exception as e:
            bt.logging.error(f"Blacklist error: {e}")
            return True, "Internal blacklist error"

    # ------------------------ Default priority -------------------

    async def priority(self, synapse: TaskSynapse) -> float:
        return await self._common_priority(synapse)

    async def priority_feedback(self, synapse: TaskFeedbackSynapse) -> float:
        return await self._common_priority(synapse)

    async def priority_set_organic_endpoint(self, synapse: SetOperatorEndpointSynapse) -> float:
        return await self._common_priority(synapse)

    async def _common_priority(
        self,
        synapse: typing.Union[TaskSynapse, TaskFeedbackSynapse, SetOperatorEndpointSynapse],
    ) -> float:
        """
        Default priority:
          - Returns 0 if the caller is not recognized.
          - Returns the caller's stake otherwise.
        """
        try:
            if synapse.dendrite is None or synapse.dendrite.hotkey is None:
                return 0.0
            hk = synapse.dendrite.hotkey
            if hk not in self.metagraph.hotkeys:
                return 0.0
            uid = self.metagraph.hotkeys.index(hk)
            return float(self.metagraph.S[uid])
        except Exception:
            return 0.0

    # ------------------------- Metagraph sync hook -------------------------
    def resync_metagraph(self):
        """Resync the metagraph with the subtensor."""
        bt.logging.info("resync_metagraph()")
        self.metagraph.sync(subtensor=self.subtensor)

    # Miners typically do not emit weights, so leave empty.
    def set_weights(self):
        pass

    @classmethod
    def add_args(cls, parser: argparse.ArgumentParser):
        super().add_args(parser)
        add_miner_args(cls, parser)
