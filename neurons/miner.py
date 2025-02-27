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


class Miner(BaseMinerNeuron):
    """
    Miner neuron class. Inherits from BaseMinerNeuron. We override:
      - forward(): handles TaskSynapse
      - forward_feedback(): handles TaskFeedbackSynapse
      - blacklist*/priority* if needed
    """

    def __init__(self, config=None):
        super(Miner, self).__init__(config=config)
        self.agent = (
            ApifiedWebAgent(name=AGENT_NAME, host=AGENT_HOST, port=AGENT_PORT)
            if USE_APIFIED_AGENT
            else RandomClickerWebAgent(is_random=False)
        )
        self.load_state()

    async def forward(self, synapse: TaskSynapse) -> TaskSynapse:
        try:
            start_time = time.time()
            validator_hotkey = getattr(synapse.dendrite, "hotkey", None)

            ColoredLogger.info(
                f"Request Received from validator: {validator_hotkey}",
                ColoredLogger.YELLOW,
            )
            ColoredLogger.info(
                f"Task Prompt: {synapse.prompt}",
                ColoredLogger.YELLOW,
            )

            # Create Task object
            task = Task(
                prompt=synapse.prompt,
                url=synapse.url,
                html=synapse.html,
                screenshot=synapse.screenshot,
            )

            # Decide which agent
            # if validator_hotkey == "5GbVehXamAezbKVedqsRgU3pmpUN47ntqXGKfiCcxHn46kSb":
            #     task_solution = await self.agent.solve_task(task=task)
            # else:
            #     random_agent = RandomClickerWebAgent(is_random=False)
            #     task_solution = await random_agent.solve_task(task=task)
            if validator_hotkey == "5GbVehXamAezbKVedqsRgU3pmpUN47ntqXGKfiCcxHn46kSb":
                random_agent = RandomClickerWebAgent(is_random=False)
                task_solution = await random_agent.solve_task(task=task)
            else:
                return synapse
            actions: List[BaseAction] = task_solution.actions
            bt.logging.info(f"Task solved. Actions: {actions}")

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
        ColoredLogger.info(
            f" Synapse Feedback received{synapse}. I am going to print in terminal"
        )

        try:
            synapse.print_in_terminal()
        except Exception as e:
            ColoredLogger.error(
                "Error occurred while printing in terminal TaskFeedback"
            )
            bt.logging.info(e)
        return synapse

    async def blacklist(self, synapse: TaskSynapse) -> typing.Tuple[bool, str]:
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return True, "Missing dendrite or hotkey"

        uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)
        if (
            not self.config.blacklist.allow_non_registered
            and synapse.dendrite.hotkey not in self.metagraph.hotkeys
        ):
            return True, "Unrecognized hotkey"

        if self.config.blacklist.force_validator_permit:
            if not self.metagraph.validator_permit[uid]:
                return True, "Non-validator hotkey"

        return False, "Hotkey recognized!"

    async def blacklist_feedback(
        self, synapse: TaskFeedbackSynapse
    ) -> typing.Tuple[bool, str]:
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning(
                "Received a feedback request without a dendrite or hotkey."
            )
            return True, "Missing dendrite or hotkey"

        uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)
        if (
            not self.config.blacklist.allow_non_registered
            and synapse.dendrite.hotkey not in self.metagraph.hotkeys
        ):
            return True, "Unrecognized hotkey"

        if self.config.blacklist.force_validator_permit:
            if not self.metagraph.validator_permit[uid]:
                return True, "Non-validator hotkey"

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
    # Typical miner entrypoint
    app = AppBootstrap()
    with Miner() as miner:
        while True:
            bt.logging.info(f"Miner running... {time.time()}")
            time.sleep(5)
