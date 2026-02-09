"""Evaluation-phase helper mixin used in tests."""

from __future__ import annotations
import asyncio

from autoppia_web_agents_subnet.validator.evaluation.stateful_cua_eval import evaluate_with_stateful_cua
from autoppia_web_agents_subnet.validator.evaluation.rewards import calculate_reward_for_task
from autoppia_web_agents_subnet.validator.config import (
    MAXIMUM_EVALUATION_TIME, 
    MAXIMUM_CONSENSUS_TIME,
    SCREENING_TASKS_FOR_EARLY_STOP,
    AGENT_MAX_STEPS,
    CONCURRENT_EVALUATION_NUM,
)
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.utils.logging import ColoredLogger

class ValidatorEvaluationMixin:
    """Mixin for evaluation phase."""

    async def _run_evaluation_phase(self) -> int:
        """
        Run the evaluation phase.
        
        Flow:
        1. Deploy all available agents
        2. For each task:
           - Evaluate all deployed agents
           - Send results to IWAP
        3. Cleanup agents
        """                
        current_block = self.block
        self.round_manager.enter_phase(
            RoundPhase.EVALUATION,
            block=current_block,
            note=f"Starting evaluation phase",
        )
        ColoredLogger.info("Starting evaluation phase", ColoredLogger.MAGENTA)
        
        # Get tasks for this round (all season tasks)
        season_tasks = await self.round_manager.get_round_tasks(current_block, self.season_manager)
        
        agents_evaluated = 0
        while not self.agents_queue.empty():    
            wait_info = self.round_manager.get_wait_info(current_block)
            if wait_info["minutes_to_settlement"] < (MAXIMUM_EVALUATION_TIME + MAXIMUM_CONSENSUS_TIME):
                ColoredLogger.info("Stopping evaluation phase for settlement", ColoredLogger.YELLOW)
                return agents_evaluated

            agent = self.agents_queue.get()

            agent_instance = None
            try:
                agent_instance = self.sandbox_manager.deploy_agent(agent.uid, agent.github_url)
            except Exception as e:
                ColoredLogger.error(f"Error deploying agent {agent.uid}: {e}", ColoredLogger.RED)
                continue
                
            if agent_instance is None:
                ColoredLogger.error(f"Agent not deployed correctly for uid {agent.uid}", ColoredLogger.RED)
                continue
            
            rewards = []
            batch_size = CONCURRENT_EVALUATION_NUM
            
            for i in range(0, len(season_tasks), batch_size):
                batch_tasks = season_tasks[i:i+batch_size]
                eval_results = await asyncio.gather(
                    *[
                        evaluate_with_stateful_cua(
                            task=task_item.task,
                            uid=agent.uid,
                            base_url=agent_instance.base_url,
                            max_steps=AGENT_MAX_STEPS,
                        ) for task_item in batch_tasks
                    ], 
                    return_exceptions=True
                )

                for task_item, eval_result in zip(batch_tasks, eval_results):
                    if isinstance(eval_result, Exception):
                        ColoredLogger.error(f"Error evaluating agent {agent.uid} on task {task_item.task.id}: {eval_result}", ColoredLogger.RED)
                        continue

                    score, exec_time, _ = eval_result                    
                    usage_for_task = self.sandbox_manager.get_usage_for_task(task_id=task_item.task.id)
                    cost = usage_for_task.get("total_cost", 0.0) if usage_for_task else 0.0
                    ColoredLogger.info(
                        f"  Agent {agent.uid}: score={score:.3f}, time={exec_time:.2f}s, cost=${cost:.4f}",
                        ColoredLogger.CYAN
                    )

                    reward = calculate_reward_for_task(
                        eval_score=score,
                        execution_time=exec_time,
                        token_cost=cost,
                    )
                    rewards.append(reward)

                if len(rewards) >= SCREENING_TASKS_FOR_EARLY_STOP and sum(rewards) == 0.0:
                    ColoredLogger.warning(f"Agent {agent.uid} is failing first {len(rewards)} tasks, stopping evaluation", ColoredLogger.YELLOW)
                    break
                

        ColoredLogger.info("Evaluation phase completed", ColoredLogger.MAGENTA)
        return agents_evaluated
        
        
        
