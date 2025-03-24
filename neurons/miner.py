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
import json
import os

# For concurrency-safe file access across multiple processes
# pip install filelock
from filelock import FileLock

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
from autoppia_web_agents_subnet.miner.stats import MinerStats
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

        # Instantiate your MinerStats to keep track of feedback across tasks
        self.miner_stats = MinerStats()

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

        bt.logging.info("Actions sent: ")
        for i, action in enumerate(actions, 1):
            action_attrs = vars(action)
            ColoredLogger.info(
                f"    {i}. {action.type}: {action_attrs}",
                ColoredLogger.GREEN,
            )
            bt.logging.info(f"  {i}. {action.type}: {action_attrs}")

    async def forward(self, synapse: TaskSynapse) -> TaskSynapse:
        """
        Called when the validator (or other hotkeys) wants to generate a solution (actions).
        """

        validator_hotkey = getattr(synapse.dendrite, "hotkey", None)
        ColoredLogger.info(
            f"Request Received from validator: {validator_hotkey}",
            ColoredLogger.YELLOW,
        )

        # Checking Weights Version (commented out for now)
        # version_check = is_version_in_range(
        #     synapse.version, self.version, self.least_acceptable_version
        # )
        # if not version_check:
        #     ColoredLogger.info(
        #         f"Not responding to {validator_hotkey} due to version mismatch",
        #         "yellow",
        #     )
        #     return synapse

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

            ColoredLogger.info(
                f"Task Prompt: {task_for_agent.prompt}",
                ColoredLogger.BLUE,
            )
            bt.logging.info("Generating actions....")

            # Process the task using your chosen WebAgent
            task_solution = await self.agent.solve_task(task=task_for_agent)
            actions: List[BaseAction] = task_solution.actions

            # Show actions in logs
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
        Logs the feedback, updates MinerStats, prints a summary,
        AND saves feedback to tasks.json (with concurrency-safe writing).
        """
        ColoredLogger.info("Received feedback", ColoredLogger.GRAY)
        try:
            # 1) Update our in-memory stats
            self.miner_stats.log_feedback(synapse.score, synapse.execution_time)

            # 2) Print feedback in terminal, including a global stats snapshot
            synapse.print_in_terminal(miner_stats=self.miner_stats)

            # 3) Save feedback to tasks.json
            feedback_data = {
                "timestamp": time.time(),
                "score": synapse.score,
                "execution_time": synapse.execution_time,
                "prompt": synapse.prompt,
                "url": synapse.url,
                "hotkey": getattr(synapse.dendrite, "hotkey", "unknown_hotkey")
            }

            # Use a file lock to prevent concurrent writes
            lock_file = "tasks.json.lock"
            json_file = "tasks.json"

            with FileLock(lock_file):
                # If tasks.json doesn't exist, initialize it as an empty list
                if not os.path.isfile(json_file):
                    with open(json_file, "w") as f:
                        json.dump([], f)

                # Read current list of feedback
                with open(json_file, "r") as f:
                    data_list = json.load(f)

                # Append new feedback item
                data_list.append(feedback_data)

                # Write updated list back to tasks.json
                with open(json_file, "w") as f:
                    json.dump(data_list, f, indent=4)

        except Exception as e:
            ColoredLogger.error("Error occurred while processing feedback")
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
            bt.logging.warning(
                f"Received a request with unrecognized hotkey: {validator_hotkey}"
            )
            return True, f"Unrecognized hotkey: {validator_hotkey}"

        uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)

        if self.config.blacklist.force_validator_permit:
            if not self.metagraph.validator_permit[uid]:
                bt.logging.warning(f"Blacklisted Non-Validator {validator_hotkey}")
                return True, f"Non-validator hotkey: {validator_hotkey}"

        # Added check for minimum stake requirement
        stake = self.metagraph.S[uid]
        min_stake = self.config.blacklist.minimum_stake_requirement
        if stake < min_stake:
            bt.logging.warning(f"Blacklisted insufficient stake: {validator_hotkey}")
            return (
                True,
                f"Insufficient stake ({stake} < {min_stake}) for {validator_hotkey}",
            )

        return False, f"Hotkey recognized: {validator_hotkey}"

    async def blacklist_feedback(
        self, synapse: TaskFeedbackSynapse
    ) -> typing.Tuple[bool, str]:
        """
        Blacklist logic for feedback requests. Similar to blacklist().
        """
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a feedback request without a dendrite or hotkey.")
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

        # Added check for minimum stake requirement (feedback path)
        stake = self.metagraph.S[uid]
        min_stake = self.config.blacklist.minimum_stake_requirement
        if stake < min_stake:
            return True, f"Insufficient stake ({stake} < {min_stake})"

        return False, "Hotkey recognized!"

    async def priority(self, synapse: TaskSynapse) -> float:
        """
        Priority logic for forward requests. 
        Could be a function of stake or other criteria.
        """
        if synapse.dendrite is None or synapse.dendrite.hotkey is None:
            bt.logging.warning("Received a request without a dendrite or hotkey.")
            return 0.0

        caller_uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)
        return float(self.metagraph.S[caller_uid])

    async def priority_feedback(self, synapse: TaskFeedbackSynapse) -> float:
        """
        Priority logic for feedback requests.
        """
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
            time.sleep(5)
