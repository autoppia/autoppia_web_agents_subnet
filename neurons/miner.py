# The MIT License (MIT)
# Copyright © 2024 Autoppia

import time
from typing import List

import bittensor as bt

from autoppia_web_agents_subnet.base.miner import BaseMinerNeuron
from autoppia_web_agents_subnet.protocol import (
    TaskSynapse,
    TaskFeedbackSynapse,
    SetOperatorEndpointSynapse,
)
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.miner.stats import MinerStats

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
    OPERATOR_ENDPOINT,
)


class Miner(BaseMinerNeuron):
    """
    Miner neuron implementation.

    Inherits default blacklist/priority logic from BaseMinerNeuron.
    This class only implements:
      - forward: handles task requests
      - forward_feedback: handles feedback from validators
      - forward_set_organic_endpoint: sets operator endpoint
    """

    def __init__(self, config=None):
        super().__init__(config=config)
        self.agent = ApifiedWebAgent(name=AGENT_NAME, host=AGENT_HOST, port=AGENT_PORT) if USE_APIFIED_AGENT else RandomClickerWebAgent(is_random=False)
        self.miner_stats = MinerStats()
        self.load_state()

    # ------------------------- Utilities -------------------------
    def show_actions(self, actions: List[BaseAction]) -> None:
        """Pretty-print executed actions in logs."""
        if not actions:
            bt.logging.warning("No actions to log.")
            return
        bt.logging.info("Actions sent:")
        for i, action in enumerate(actions, 1):
            attrs = vars(action)
            ColoredLogger.info(f"    {i}. {action.type}: {attrs}", ColoredLogger.GREEN)
            bt.logging.info(f"  {i}. {action.type}: {attrs}")

    # ------------------------- Axon routes ------------------------
    async def forward(self, synapse: TaskSynapse) -> TaskSynapse:
        """Handles TaskSynapse requests from validators."""
        validator_hotkey = getattr(synapse.dendrite, "hotkey", None)
        ColoredLogger.info(
            f"Request received from validator: {validator_hotkey}",
            ColoredLogger.YELLOW,
        )
        try:
            t0 = time.time()

            # Build task for the agent
            task = Task(
                prompt=synapse.prompt,
                url=synapse.url,
                html=synapse.html,
                screenshot=synapse.screenshot,
            )
            task_for_agent = task.prepare_for_agent(str(self.uid))

            ColoredLogger.info(f"Task Prompt: {task_for_agent.prompt}", ColoredLogger.BLUE)
            bt.logging.info("Generating actions...")

            # Let the agent solve the task
            solution = await self.agent.solve_task(task=task_for_agent)
            solution.web_agent_id = str(self.uid)
            actions: List[BaseAction] = solution.replace_web_agent_id()

            # Log and attach actions to synapse
            self.show_actions(actions)
            synapse.actions = actions

            ColoredLogger.success(
                f"Request completed in {time.time() - t0:.2f}s",
                ColoredLogger.GREEN,
            )
        except Exception as e:
            bt.logging.error(f"Error in miner forward: {e}")

        return synapse

    async def forward_feedback(self, synapse: TaskFeedbackSynapse) -> TaskFeedbackSynapse:
        """Handles feedback from validators, updates miner stats, and logs results."""
        ColoredLogger.info("Received feedback", ColoredLogger.GRAY)
        try:
            self.miner_stats.log_feedback(synapse.score, synapse.execution_time)
            synapse.print_in_terminal(miner_stats=self.miner_stats)
        except Exception as e:
            ColoredLogger.error("Error while printing TaskFeedback", ColoredLogger.RED)
            raise e
        return synapse

    async def forward_set_organic_endpoint(self, synapse: SetOperatorEndpointSynapse) -> SetOperatorEndpointSynapse:
        """Sets the operator endpoint in the synapse."""
        synapse.endpoint = OPERATOR_ENDPOINT
        return synapse


if __name__ == "__main__":
    # Miner entrypoint
    app = AppBootstrap()  # Wiring IWA dependency injection
    with Miner() as miner:
        while True:
            time.sleep(5)
