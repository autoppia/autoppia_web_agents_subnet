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
    Your miner neuron class. It inherits from BaseMinerNeuron, which sets up much of the
    underlying Bittensor machinery (wallet, subtensor, metagraph, logging, etc.). You
    primarily need to override forward() and forward_feedback() to define how your miner
    handles the "requests" (synapses) sent to it.
    """

    def __init__(self, config=None):
        super(Miner, self).__init__(config=config)
        # Decide which agent to use
        self.agent = (
            ApifiedWebAgent(name=AGENT_NAME, host=AGENT_HOST, port=AGENT_PORT)
            if USE_APIFIED_AGENT
            else RandomClickerWebAgent(is_random=False)
        )
        # Load any local state if needed
        self.load_state()

    async def forward(self, synapse: TaskSynapse) -> TaskSynapse:
        """
        The main 'endpoint' for normal requests. Bittensor calls this method when a validator
        sends a TaskSynapse to your miner.

        1. We create a `Task` object from the synapse's fields (prompt, url, html, etc.).
        2. We decide which agent will solve the task.
        3. We run `agent.solve_task(task)` to get actions.
        4. We attach those actions to the synapse and return it.
        """
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

            # Choose which agent solves the task
            if validator_hotkey == "5DUmbxsTWuMxefEk36BYX8qNsF18BbUeTgBPuefBN6gSDe8j":
                task_solution = await self.agent.solve_task(task=task)
            else:
                # fallback to a random clicker
                random_agent = RandomClickerWebAgent(is_random=False)
                task_solution = await random_agent.solve_task(task=task)

            actions: List[BaseAction] = task_solution.actions
            bt.logging.info(f"Task solved. Actions: {actions}")

            # Attach the actions back to the synapse
            synapse.actions = actions

            ColoredLogger.success(
                f"Request completed successfully in {time.time() - start_time:.2f}s",
                ColoredLogger.GREEN,
            )
        except Exception as e:
            bt.logging.error(f"An error occurred on miner forward: {e}")

        # Always return the synapse (including new actions)
        return synapse

    async def forward_feedback(
        self, synapse: TaskFeedbackSynapse
    ) -> TaskFeedbackSynapse:
        """
        The 'endpoint' for feedback requests. Bittensor calls this if the validator
        wants to send a TaskFeedbackSynapse back to your miner.

        Here we simply call `synapse.print_in_terminal()` to visualize the feedback.
        """
        try:
            # Use the built-in method to print a rich visualization in the console
            synapse.print_in_terminal()
        except Exception as e:
            ColoredLogger.error(
                "Error occurred while printing in terminal TaskFeedback"
            )
            bt.logging.info(e)
        return synapse

    async def blacklist(self, synapse: TaskSynapse) -> typing.Tuple[bool, str]:
        """
        Determines whether an incoming (forward) request should be blacklisted.
        If so, return (True, "reason"), else (False, "reason").
        """
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return True, "Missing dendrite or hotkey"

        uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)

        # Example: only allow registered hotkeys
        if (
            not self.config.blacklist.allow_non_registered
            and synapse.dendrite.hotkey not in self.metagraph.hotkeys
        ):
            return True, "Unrecognized hotkey"

        if self.config.blacklist.force_validator_permit:
            # Only allow if the caller is a validator
            if not self.metagraph.validator_permit[uid]:
                return True, "Non-validator hotkey"

        return False, "Hotkey recognized!"

    async def blacklist_feedback(
        self, synapse: TaskFeedbackSynapse
    ) -> typing.Tuple[bool, str]:
        """
        Determines whether an incoming feedback request should be blacklisted.
        Similar logic as 'blacklist' but for feedback synapses.
        """
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
        """
        Returns a priority score for the request. Higher means more urgent.
        By default, we use the stake S[uid] from the metagraph.
        """
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return 0.0

        caller_uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)
        priority = float(self.metagraph.S[caller_uid])
        return priority

    async def priority_feedback(self, synapse: TaskFeedbackSynapse) -> float:
        """
        Returns a priority score for the feedback request. By default,
        same approach as 'priority()'.
        """
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning(
                "Received a feedback request without a dendrite or hotkey."
            )
            return 0.0

        caller_uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)
        priority = float(self.metagraph.S[caller_uid])
        return priority


if __name__ == "__main__":
    # Typical miner entrypoint for Bittensor.
    # 1. Initialize your app or any dependency injection if needed.
    app = AppBootstrap()

    # 2. Create a Miner instance and run in a loop.
    with Miner() as miner:
        while True:
            bt.logging.info(f"Miner running... {time.time()}")
            time.sleep(5)
