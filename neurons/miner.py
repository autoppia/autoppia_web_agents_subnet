# The MIT License (MIT)
#
# Copyright © 2024 Autoppia
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.
#
# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import time
import typing
from typing import List

import bittensor as bt

from autoppia_web_agents_subnet.base.miner import BaseMinerNeuron
from autoppia_web_agents_subnet.protocol import TaskSynapse, TaskFeedbackSynapse
from autoppia_web_agents_subnet.utils.logging import ColoredLogger

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.execution.actions.base import BaseAction
from autoppia_iwa.src.web_agents.random.agent import RandomClickerWebAgent
from autoppia_iwa.src.web_agents.apified_agent import ApifiedWebAgent
from autoppia_iwa.config.config import (
    AGENT_HOST,
    AGENT_NAME,
    AGENT_PORT,
    USE_APIFIED_AGENT,
)
from autoppia_web_agents_subnet.utils.weights_version import is_version_in_range


class Miner(BaseMinerNeuron):
    """
    Miner neuron class. Inherits from BaseMinerNeuron. We override:
      - forward(): handles TaskSynapse
      - forward_feedback(): handles TaskFeedbackSynapse
    """

    def __init__(self, config=None):
        super(Miner, self).__init__(config=config)
        self.agent = (
            ApifiedWebAgent(name=AGENT_NAME, host=AGENT_HOST, port=AGENT_PORT)
            if USE_APIFIED_AGENT
            else RandomClickerWebAgent(is_random=False)
        )
        self.load_state()

    def show_actions(self, actions: List[BaseAction]) -> None:
        """
        Pretty-prints the list of actions in a more readable format.
        Args:
            actions: List of BaseAction objects to be logged.
        """
        if not actions:
            bt.logging.warning("No actions to log.")
            return

        bt.logging.info("Actions sent:")
        for i, action in enumerate(actions, 1):
            action_attrs = {}

            action_attrs = vars(action)

            # Log with consistent format
            bt.logging.info(f"  {i}. {action.type}: {action_attrs}")

    async def forward(self, synapse: TaskSynapse) -> TaskSynapse:

        # Checking Weights Versio
        # version_check = is_version_in_range(synapse.version, self.version, self.least_acceptable_version)

        # if not version_check:
        #     ColoredLogger.info(f"Not reponding due to version check: {synapse.version} not between {self.least_acceptable_version} - { self.version}. This is intended behaviour", "yellow")
        #     return synapse

        try:
            start_time = time.time()
            validator_hotkey = getattr(synapse.dendrite, "hotkey", None)

            ColoredLogger.info(
                f"Request Received from validator: {validator_hotkey}",
                ColoredLogger.YELLOW,
            )
            ColoredLogger.info(
                f"Task Prompt: {synapse.prompt}",
                ColoredLogger.WHITE,
            )

            # Create Task object
            task = Task(
                prompt=synapse.prompt,
                url=synapse.url,
                html=synapse.html,
                screenshot=synapse.screenshot,
            )
            task_for_agent = task.prepare_for_agent(str(self.uid))
            # Process the task
            task_solution = await self.agent.solve_task(task=task_for_agent)

            actions: List[BaseAction] = task_solution.actions

            # Show actions
            self.show_actions(actions)

            synapse.actions = actions

            ColoredLogger.success(
                f"Request completed successfully in {time.time() - start_time:.2f}s",
                ColoredLogger.GREEN,
            )
        except Exception as e:
            bt.logging.error(f"An error occurred on miner forward: {e}")

        return synapse

    async def forward_feedback(
        self, synapse: TaskFeedbackSynapse
    ) -> TaskFeedbackSynapse:
        """
        Endpoint for feedback requests from the validator.
        We just call print_in_terminal() to see a summary.
        """

        try:
            synapse.print_in_terminal()
        except Exception as e:
            ColoredLogger.error("Error occurred while printing in terminal TaskFeedback")
            bt.logging.info(e)
        return synapse

    async def blacklist(self, synapse: TaskSynapse) -> typing.Tuple[bool, str]:
        """
        Blacklist logic to disallow requests from certain hotkeys:
          - Missing or unrecognized hotkeys
          - Non-validator hotkeys if force_validator_permit is True
          - Hotkeys not meeting the minimum stake requirement
        """

        validator_hotkey = synapse.dendrite.hotkey
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return True, "Missing dendrite or hotkey"

        if (
            not self.config.blacklist.allow_non_registered
            and synapse.dendrite.hotkey not in self.metagraph.hotkeys
        ):
            bt.logging.warning(f"Received a request without a dendrite or hotkey. {validator_hotkey}")
            return True, f"Unrecognized hotkey: {validator_hotkey}"

        uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)

        if self.config.blacklist.force_validator_permit:
            if not self.metagraph.validator_permit[uid]:
                bt.logging.warning(f"Blacklisted Non-Validator {validator_hotkey}")
                return True, f"Non-validator hotkey: {validator_hotkey}"

        # -----------------------------------------------------------------------
        # Added check for minimum stake requirement
        # -----------------------------------------------------------------------
        stake = self.metagraph.S[uid]
        min_stake = self.config.blacklist.minimum_stake_requirement
        if stake < min_stake:
            bt.logging.warning(f"Blacklisted insufficient stake: {validator_hotkey}")
            return True, f"Insufficient stake ({stake} < {min_stake}) for {validator_hotkey}"

        return False, f"Hotkey recognized: {validator_hotkey}"

    async def blacklist_feedback(
        self, synapse: TaskFeedbackSynapse
    ) -> typing.Tuple[bool, str]:
        """
        Blacklist logic for feedback requests. Similar to blacklist().
        """
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return True, "Missing dendrite or hotkey"

        if (
            not self.config.blacklist.allow_non_registered
            and synapse.dendrite.hotkey not in self.metagraph.hotkeys
        ):
            return True, "Unrecognized hotkey"

        uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)

        if self.config.blacklist.force_validator_permit:
            if not self.metagraph.validator_permit[uid]:
                return True, "Non-validator hotkey"

        # -----------------------------------------------------------------------
        # Added check for minimum stake requirement (feedback path)
        # -----------------------------------------------------------------------
        stake = self.metagraph.S[uid]
        min_stake = self.config.blacklist.minimum_stake_requirement
        if stake < min_stake:
            return True, f"Insufficient stake ({stake} < {min_stake})"

        return False, "Hotkey recognized!"

    async def priority(self, synapse: TaskSynapse) -> float:
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return 0.0

        caller_uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)
        return float(self.metagraph.S[caller_uid])

    async def priority_feedback(self, synapse: TaskFeedbackSynapse) -> float:
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning(
                "Received a feedback request without a dendrite or hotkey."
            )
            return 0.0

        caller_uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)
        return float(self.metagraph.S[caller_uid])


if __name__ == "__main__":
    # Miner entrypoint
    app = AppBootstrap()  # Wiring IWA Dependency Injection
    with Miner() as miner:
        while True:
            # bt.logging.info(f"Miner running... {time.time()}")
            time.sleep(5)
