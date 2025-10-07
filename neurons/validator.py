from __future__ import annotations

import asyncio
import time
from typing import List

import bittensor as bt

from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.bittensor_config import config
from autoppia_web_agents_subnet.utils.random import get_random_uids
from autoppia_web_agents_subnet.config import FORWARD_SLEEP_SECONDS, TIMEOUT, EVAL_SCORE_WEIGHT, TIME_WEIGHT
from autoppia_web_agents_subnet.validator.tasks import get_task_plan, collect_task_solutions_and_execution_times
from autoppia_web_agents_subnet.validator.synapse_handlers import send_synapse_to_miners_generic, send_feedback_synapse_to_miners
from autoppia_web_agents_subnet.synapses import StartRoundSynapse, TaskSynapse
from autoppia_web_agents_subnet.validator.rewards import blend_eval_and_time, reduce_rewards_to_averages, pad_or_trim, wta_rewards
from autoppia_web_agents_subnet.validator.eval import evaluate_task_solutions
from autoppia_web_agents_subnet.validator.models import TaskPlan, PerTaskResult, ScoredTask, EvalOutput
from autoppia_web_agents_subnet.validator.stats import ForwardStats

from autoppia_web_agents_subnet.validator.leaderboard import LeaderboardAPI, Phase, TaskInfo, TaskResult, AgentEvaluationRun, WeightsSnapshot, RoundResults
from autoppia_web_agents_subnet.validator.forward import ForwardHandler
# IWA
from autoppia_iwa_module.autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa_module.autoppia_iwa.src.bootstrap import AppBootstrap


SUCCESS_THRESHOLD = 0.0  # UI semantics for "success"


class Validator(BaseValidatorNeuron):
    def __init__(self, config=None):
        super().__init__(config=config)
        self.forward_count = 0
        self.leaderboard = LeaderboardAPI()
        self.forward_handler = ForwardHandler(self)

    async def forward(self):
        """
        Validator forward pass. Called by every validator.
        """
        try:
            await self.forward_handler.execute_forward()
        except Exception as e:
            bt.logging.error(f"Forward failed: {e}")
            raise

    async def blacklist(self, synapse: bittensor.Synapse) -> Tuple[bool, str]:
        """
        Determines whether an incoming request should be blacklisted.
        """
        # Implementation details...
        return False, ""

    async def priority(self, synapse: bittensor.Synapse) -> float:
        """
        Determines the priority of the incoming request.
        """
        # Implementation details...
        return 0.0

    def resync_metagraph(self, metagraph: bittensor.metagraph):
        """
        Resyncs the metagraph and updates the hotkeys and moving averages based on the new metagraph.
        """
        # Implementation details...
        pass

    def set_weights(self, weights: torch.FloatTensor):
        """
        Sets the validator weights to the metagraph.
        """
        # Implementation details...
        pass

    def save_state(self):
        """
        Saves the state of the validator to disk.
        """
        # Implementation details...
        pass

    def load_state(self):
        """
        Loads the state of the validator from disk.
        """
        # Implementation details...
        pass
