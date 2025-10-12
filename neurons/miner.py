import os
import time
from typing import List

import bittensor as bt

from autoppia_web_agents_subnet.base.miner import BaseMinerNeuron
from autoppia_web_agents_subnet.protocol import (
    TaskSynapse,
    TaskFeedbackSynapse,
    StartRoundSynapse,
)
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.miner.models import MinerStats
from autoppia_web_agents_subnet.bittensor_config import config

# IWA dependencies (agent + task types)
from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.execution.actions.base import BaseAction
from autoppia_iwa.src.web_agents.random.agent import RandomClickerWebAgent
from autoppia_iwa.src.web_agents.apified_agent import ApifiedWebAgent
from autoppia_iwa.config.config import (
    AGENT_HOST,
    AGENT_NAME as CFG_AGENT_NAME,
    AGENT_PORT,
    USE_APIFIED_AGENT,
)

from autoppia_web_agents_subnet.miner.logging import print_task_feedback

# Miner configuration
from autoppia_web_agents_subnet.miner.config import (
    AGENT_NAME,
    AGENT_IMAGE,
    GITHUB_URL,
    AGENT_VERSION,
    HAS_RL,
)


class Miner(BaseMinerNeuron):
    def __init__(self, config=None):
        super(Miner, self).__init__(config=config)

        # Choose agent implementation
        self.agent = (
            ApifiedWebAgent(name=AGENT_NAME, host=AGENT_HOST, port=AGENT_PORT)
            if USE_APIFIED_AGENT
            else RandomClickerWebAgent(is_random=False)
        )

        self.miner_stats = MinerStats()
        self.load_state()

    # ────────────────────────── Round Handshake ──────────────────────────
    async def forward_start_round(self, synapse: StartRoundSynapse) -> StartRoundSynapse:
        """
        Respond to a StartRound handshake with miner/agent metadata.
        No side-effects beyond logging and returning metadata.
        """
        validator_hotkey = getattr(synapse.dendrite, "hotkey", None)
        ColoredLogger.info(
            f"[StartRound] from validator: {validator_hotkey} round_id={getattr(synapse, 'round_id', '')}",
            ColoredLogger.YELLOW,
        )

        # Respond with our metadata
        synapse.agent_name = AGENT_NAME
        synapse.agent_image = AGENT_IMAGE or None
        synapse.github_url = GITHUB_URL or None
        synapse.agent_version = AGENT_VERSION
        synapse.has_rl = HAS_RL

        ColoredLogger.success(
            f"[StartRound] Responded with agent={AGENT_NAME} v{AGENT_VERSION} RL={HAS_RL}",
            ColoredLogger.GREEN,
        )
        return synapse

    # ───────────────────────────── Tasks ─────────────────────────────
    def _show_actions(self, actions: List[BaseAction]) -> None:
        """Pretty-prints the list of actions in a more readable format."""
        if not actions:
            bt.logging.warning("No actions to log.")
            return

        bt.logging.info("Actions sent:")
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
                screenshot=synapse.screenshot,
            )
            task_for_agent = task.prepare_for_agent(str(self.uid))

            ColoredLogger.info(
                f"Task Prompt: {task_for_agent.prompt}", ColoredLogger.BLUE
            )
            bt.logging.info("Generating actions...")

            # Process the task
            task_solution = await self.agent.solve_task(task=task_for_agent)
            task_solution.web_agent_id = str(self.uid)
            actions: List[BaseAction] = task_solution.replace_web_agent_id()

            self._show_actions(actions)

            # Assign actions back to the synapse
            synapse.actions = actions

            ColoredLogger.success(
                f"Request completed successfully in {time.time() - start_time:.2f}s",
                ColoredLogger.GREEN,
            )
        except Exception as e:
            bt.logging.error(f"An error occurred on miner forward: {e}")

        return synapse

    # ─────────────────────────── Feedback ───────────────────────────
    async def forward_feedback(
        self, synapse: TaskFeedbackSynapse
    ) -> TaskFeedbackSynapse:
        """
        Endpoint for feedback requests from the validator.
        Logs the feedback, updates MinerStats, and prints a summary.
        """
        ColoredLogger.info("Received feedback", ColoredLogger.GRAY)

        # DEBUG: Log detailed TaskFeedbackSynapse content
        ColoredLogger.info(f"🔍 DEBUG TaskFeedbackSynapse content:", ColoredLogger.YELLOW)
        ColoredLogger.info(f"  - task_id: {synapse.task_id}", ColoredLogger.GRAY)
        ColoredLogger.info(f"  - score: {synapse.score}", ColoredLogger.GRAY)
        ColoredLogger.info(f"  - execution_time: {synapse.execution_time}", ColoredLogger.GRAY)
        ColoredLogger.info(f"  - tests: {synapse.tests}", ColoredLogger.GRAY)
        ColoredLogger.info(f"  - test_results_matrix: {synapse.test_results_matrix}", ColoredLogger.GRAY)
        ColoredLogger.info(f"  - actions: {len(synapse.actions) if synapse.actions else 0} actions", ColoredLogger.GRAY)
        ColoredLogger.info(f"  - evaluation_result: {synapse.evaluation_result}", ColoredLogger.GRAY)

        try:
            # Defensive defaults
            score = float(synapse.score or 0.0)
            exec_time = float(synapse.execution_time or 0.0)

            self.miner_stats.log_feedback(score, exec_time)
            print_task_feedback(synapse, self.miner_stats)
        except Exception as e:
            ColoredLogger.error("Error occurred while printing TaskFeedback in terminal")
            raise e

        return synapse


if __name__ == "__main__":
    # Initializing Dependency Injection In IWA
    app = AppBootstrap()
    with Miner(config=config(role="miner")) as miner:
        while True:
            time.sleep(5)
