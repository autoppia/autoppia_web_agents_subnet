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
from autoppia_web_agents_subnet.protocol import (
    TaskSynapse,
    TaskFeedbackSynapse,
    SetOperatorEndpointSynapse
)
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.miner.stats import MinerStats
from autoppia_web_agents_subnet.utils.config import config

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
    OPERATOR_ENDPOINT
)

# from autoppia_web_agents_subnet.utils.weights_version import is_version_in_range


class Miner(BaseMinerNeuron):
    """
    Miner neuron class. Inherits from BaseMinerNeuron. We override:
      - forward(): handles TaskSynapse
      - forward_feedback(): handles TaskFeedbackSynapse
      - forward_set_organic_endpoint(): sets Operator Endpoint
      - blacklist*(): unify into _common_blacklist
      - priority*(): unify into _common_priority
    """

    def __init__(self, config=None):
        super(Miner, self).__init__(config=config)
        self.agent = (
            ApifiedWebAgent(name=AGENT_NAME, host=AGENT_HOST, port=AGENT_PORT)
            if USE_APIFIED_AGENT
            else RandomClickerWebAgent(is_random=False)
        )
        self.miner_stats = MinerStats()
        self.load_state()

    def show_actions(self, actions: List[BaseAction]) -> None:
        """
        Pretty-prints the list of actions in a more readable format.
        """
        if not actions:
            bt.logging.warning("No actions to log.")
            return

        bt.logging.info("Actions sent: ")
        for i, action in enumerate(actions, 1):
            action_attrs = vars(action)
            ColoredLogger.info(
                f"    {i}. {action.type}: {action_attrs}",
                ColoredLogger.GREEN,
            )
            bt.logging.info(f"  {i}. {action.type}: {action_attrs}")

    async def forward(self, synapse: TaskSynapse) -> TaskSynapse:
        validator_hotkey = getattr(synapse.dendrite, "hotkey", None)
        ColoredLogger.info(
            f"Request Received from validator: {validator_hotkey}",
            ColoredLogger.YELLOW,
        )

        # Checking Weights Version (commented out for now)
        # version_check = is_version_in_range(...)

        try:
            start_time = time.time()

            # Create Task object
            task = Task(
                prompt=synapse.prompt,
                url=synapse.url,
                html=synapse.html,
                screenshot=synapse.screenshot,
            )
            task_for_agent = task.prepare_for_agent(str(self.uid))

            ColoredLogger.info(f"Task Prompt: {task_for_agent.prompt}", ColoredLogger.BLUE)
            bt.logging.info("Generating actions....")

            # Process the task
            task_solution = await self.agent.solve_task(task=task_for_agent)
            actions: List[BaseAction] = task_solution.actions

            self.show_actions(actions)

            # Assign actions back to the synapse
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
        Logs the feedback, updates MinerStats, and prints a summary.
        """
        ColoredLogger.info("Received feedback", ColoredLogger.GRAY)
        try:
            # Update our MinerStats with the feedback
            self.miner_stats.log_feedback(synapse.score, synapse.execution_time)
            # Print feedback in terminal, including a global stats snapshot
            synapse.print_in_terminal(miner_stats=self.miner_stats)
        except Exception as e:
            ColoredLogger.error("Error occurred while printing in terminal TaskFeedback")
            bt.logging.info(e)
        return synapse

    # Renamed method
    async def forward_set_organic_endpoint(
        self, synapse: SetOperatorEndpointSynapse
    ) -> SetOperatorEndpointSynapse:
        """
        Sets the operator endpoint for the given synapse.
        """
        synapse.endpoint = OPERATOR_ENDPOINT
        return synapse

    # ---------------------------------------------------------------------
    # Blacklist logic
    # ---------------------------------------------------------------------
    async def blacklist(self, synapse: TaskSynapse) -> typing.Tuple[bool, str]:
        return await self._common_blacklist(synapse)

    async def blacklist_feedback(
        self, synapse: TaskFeedbackSynapse
    ) -> typing.Tuple[bool, str]:
        return await self._common_blacklist(synapse)

    async def blacklist_set_organic_endpoint(
        self, synapse: SetOperatorEndpointSynapse
    ) -> typing.Tuple[bool, str]:
        return await self._common_blacklist(synapse)

    async def _common_blacklist(
        self,
        synapse: typing.Union[
            TaskSynapse,
            TaskFeedbackSynapse,
            SetOperatorEndpointSynapse
        ]
    ) -> typing.Tuple[bool, str]:
        """
        Shared blacklist logic used by forward, feedback, and set_organic_endpoint.
        Returns a tuple: (bool, str).
        """
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return True, "Missing dendrite or hotkey"

        validator_hotkey = synapse.dendrite.hotkey

        # Ensure hotkey is recognized
        if (
            not self.config.blacklist.allow_non_registered
            and validator_hotkey not in self.metagraph.hotkeys
        ):
            bt.logging.warning(f"Unrecognized hotkey: {validator_hotkey}")
            return True, f"Unrecognized hotkey: {validator_hotkey}"

        uid = self.metagraph.hotkeys.index(validator_hotkey)

        # Optionally force only validators
        if self.config.blacklist.force_validator_permit:
            if not self.metagraph.validator_permit[uid]:
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

    # ---------------------------------------------------------------------
    # Priority logic
    # ---------------------------------------------------------------------
    async def priority(self, synapse: TaskSynapse) -> float:
        return await self._common_priority(synapse)

    async def priority_feedback(self, synapse: TaskFeedbackSynapse) -> float:
        return await self._common_priority(synapse)

    async def priority_set_organic_endpoint(
        self, synapse: SetOperatorEndpointSynapse
    ) -> float:
        return await self._common_priority(synapse)

    async def _common_priority(
        self,
        synapse: typing.Union[
            TaskSynapse,
            TaskFeedbackSynapse,
            SetOperatorEndpointSynapse
        ]
    ) -> float:
        """
        Shared priority logic used by forward, feedback, and set_organic_endpoint.
        Returns a float indicating the priority value.
        """
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return 0.0

        validator_hotkey = synapse.dendrite.hotkey
        if validator_hotkey not in self.metagraph.hotkeys:
            # Not recognized => zero priority
            return 0.0

        caller_uid = self.metagraph.hotkeys.index(validator_hotkey)
        return float(self.metagraph.S[caller_uid])


if __name__ == "__main__":
    # Miner entrypoint
    app = AppBootstrap()  # Wiring IWA Dependency Injection
    with Miner(config=config()) as miner:
        while True:
            time.sleep(5)
