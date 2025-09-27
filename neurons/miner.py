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
from autoppia_web_agents_subnet.miner.models import MinerStats
from autoppia_web_agents_subnet.base.utils.config import config
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
from autoppia_web_agents_subnet.miner.logging import print_task_feedback


class Miner(BaseMinerNeuron):

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

        try:
            start_time = time.time()

            task = Task(
                prompt=synapse.prompt,
                url=synapse.url,
                html=synapse.html,
                screenshot=synapse.screenshot,
            )
            task_for_agent = task.prepare_for_agent(str(self.uid))

            ColoredLogger.info(
                f"Task Prompt: {task_for_agent.prompt}", ColoredLogger.BLUE
            )
            bt.logging.info("Generating actions....")

            # Process the task
            task_solution = await self.agent.solve_task(task=task_for_agent)
            task_solution.web_agent_id = str(self.uid)
            actions: List[BaseAction] = task_solution.replace_web_agent_id()

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
            self.miner_stats.log_feedback(synapse.score, synapse.execution_time)
            print_task_feedback(synapse, self.miner_stats)
        except Exception as e:
            ColoredLogger.error(
                "Error occurred while printing in terminal TaskFeedback"
            )
            raise e

        return synapse

    async def forward_set_organic_endpoint(
        self, synapse: SetOperatorEndpointSynapse
    ) -> SetOperatorEndpointSynapse:
        """
        Sets the operator endpoint for the given synapse.
        """
        synapse.endpoint = OPERATOR_ENDPOINT
        return synapse


if __name__ == "__main__":
    # Initializing Dependency Injection In IWA
    app = AppBootstrap()  
    with Miner(config=config(role="miner")) as miner:
        while True:
            time.sleep(5)
