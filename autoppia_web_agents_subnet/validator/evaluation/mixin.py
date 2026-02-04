"""Evaluation-phase helper mixin used in tests."""

from __future__ import annotations

from autoppia_web_agents_subnet.validator.github_validation import normalize_and_validate_github_url
from autoppia_web_agents_subnet.validator.evaluation.stateful_cua_eval import evaluate_with_stateful_cua
from autoppia_web_agents_subnet.validator.config import (
    MAXIMUM_EVALUATION_TIME, 
    MAXIMUM_CONSENSUS_TIME,
    AGENT_MAX_STEPS,
)
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.utils.logging import ColoredLogger

class ValidatorEvaluationMixin:
    """Mixin for evaluation phase."""

    async def _run_evaluation_phase(self) -> int:
        """
        Run the evaluation phase.
        """                
        current_block = self.block
        self.round_manager.enter_phase(
            RoundPhase.EVALUATION,
            block=current_block,
            note=f"Starting evaluation phase",
        )
        ColoredLogger.info("Starting evaluation phase", ColoredLogger.MAGENTA)
        
        # Get season tasks (pass round_length for proper season/round calculation)
        round_length = getattr(self.round_manager, 'round_block_length', 720)
        season_tasks = await self.season_manager.get_season_tasks(current_block, round_length)

        agents_evaluated = 0
        while not self.agents_queue.empty():    
            wait_info = self.round_manager.get_wait_info(current_block)
            if wait_info["minutes_to_settlement"] < (MAXIMUM_EVALUATION_TIME + MAXIMUM_CONSENSUS_TIME):
                ColoredLogger.info("Stopping evaluation phase for settlement", ColoredLogger.YELLOW)
                break

            agent = self.agents_queue.get()
            normalized_github_url = normalize_and_validate_github_url(agent.github_url, miner_uid=agent.uid)
            if normalized_github_url is None:
                continue

            agent_instance = None
            try:
                agent_instance = self.sandbox_manager.deploy_agent(agent.uid, normalized_github_url)
            except Exception as e:
                ColoredLogger.error(f"Error deploying agent {agent.uid}: {e}", ColoredLogger.RED)
                continue
                
            if agent_instance is None:
                ColoredLogger.error(f"Agent not deployed correctly for uid {agent.uid}", ColoredLogger.RED)
                continue

            try:
                scores = []
                for task in season_tasks:
                    try:
                        score, _, _ = await evaluate_with_stateful_cua(
                            task=task.task,
                            uid=agent.uid,
                            base_url=agent_instance.base_url,
                            max_steps=AGENT_MAX_STEPS,
                        )
                        scores.append(score)
                    except Exception as e:
                        ColoredLogger.error(f"Error evaluating task {task}: {e}", ColoredLogger.RED)
                        continue

                # Handle empty scores list
                if len(scores) > 0:
                    avg_score = sum(scores) / len(scores)
                    agent.score = avg_score
                else:
                    agent.score = 0.0
                    
                self.agents_dict[agent.uid] = agent
                agents_evaluated += 1
            finally:
                # Always cleanup, even if evaluation fails
                self.sandbox_manager.cleanup_agent(agent.uid)

        ColoredLogger.info("Evaluation phase completed", ColoredLogger.MAGENTA)
        return agents_evaluated
        
        
        
