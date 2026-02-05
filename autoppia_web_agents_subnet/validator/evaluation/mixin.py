"""Evaluation-phase helper mixin used in tests."""

from __future__ import annotations
from typing import Dict, List

from autoppia_web_agents_subnet.validator.evaluation.stateful_cua_eval import evaluate_with_stateful_cua
from autoppia_web_agents_subnet.validator.evaluation.rewards import calculate_reward_for_task
from autoppia_web_agents_subnet.validator.config import (
    MAXIMUM_EVALUATION_TIME, 
    MAXIMUM_CONSENSUS_TIME,
    SCREENING_TASKS_FOR_EARLY_STOP,
    AGENT_MAX_STEPS,
    COST_LIMIT_VALUE,
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

        # Deploy all available agents first
        deployed_agents = {}  # uid -> (agent_info, agent_instance)
        
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
            
            deployed_agents[agent.uid] = (agent, agent_instance)
            ColoredLogger.success(f"Deployed agent {agent.uid}", ColoredLogger.GREEN)

        if not deployed_agents:
            ColoredLogger.warning("No agents deployed for evaluation", ColoredLogger.YELLOW)
            return 0

        # Evaluate each task across all deployed agents
        try:
            for task_item in season_tasks:
                ColoredLogger.info(f"Evaluating task {task_item.task.id} for {len(deployed_agents)} agents", ColoredLogger.CYAN)
                
                # Collect results from all agents for this task
                task_solutions = []
                eval_scores = []
                execution_times = []
                test_results_list = []
                evaluation_results = []
                rewards = []
                
                for uid, (agent, agent_instance) in deployed_agents.items():
                    try:
                        prev_usage = self.sandbox_manager.get_current_usage()
                        prev_cost = getattr(prev_usage, "total_cost", 0.0)

                        score, exec_time, task_solution = await evaluate_with_stateful_cua(
                            task=task_item.task,
                            uid=uid,
                            base_url=agent_instance.base_url,
                            max_steps=AGENT_MAX_STEPS,
                        )
                        
                        task_solutions.append(task_solution)
                        eval_scores.append(score)
                        execution_times.append(exec_time)
                        test_results_list.append([])  # Simplified - no detailed test results
                        evaluation_results.append({})  # Simplified - no detailed evaluation metadata
                        rewards.append(score)  # Simplified - reward = score
                        
                        ColoredLogger.info(
                            f"  Agent {uid}: score={score:.3f}, time={exec_time:.2f}s",
                            ColoredLogger.CYAN
                        )                        
                        
                        after_usage = self.sandbox_manager.get_current_usage()
                        after_cost = getattr(after_usage, "total_cost", COST_LIMIT_VALUE * 2)  # If we can't get cost, assume it's over the limit
                        token_cost = max(after_cost - prev_cost, 0.0)

                        reward = calculate_reward_for_task(
                            eval_score=score,
                            execution_time=exec_time,
                            token_cost=token_cost,
                        )

                        if after_cost > COST_LIMIT_VALUE:
                            ColoredLogger.warning(f"Agent {agent.uid} exceeded cost limit with estimated cost ${after_cost:.2f}, stopping evaluation", ColoredLogger.YELLOW)
                            break

                        eval_scores.append(reward)

                        if len(eval_scores) >= SCREENING_TASKS_FOR_EARLY_STOP and sum(eval_scores) == 0.0:
                            ColoredLogger.warning(f"Agent {agent.uid} is failing first {len(eval_scores)} tasks, stopping evaluation", ColoredLogger.YELLOW)
                            break
                    except Exception as e:
                        ColoredLogger.error(f"Error evaluating task {task_item.task.id} for agent {uid}: {e}", ColoredLogger.RED)
                        # Add empty/zero results for failed evaluations
                        task_solutions.append(None)
                        eval_scores.append(0.0)
                        execution_times.append(0.0)
                        test_results_list.append([])
                        evaluation_results.append({})
                        rewards.append(0.0)
                
                # Send results to IWAP for this task
                try:
                    await self._iwap_submit_task_results(
                        task_item=task_item,
                        task_solutions=task_solutions,
                        eval_scores=eval_scores,
                        test_results_list=test_results_list,
                        evaluation_results=evaluation_results,
                        execution_times=execution_times,
                        rewards=rewards,
                    )
                    ColoredLogger.success(
                        f"✅ Sent results to IWAP for task {task_item.task.id}",
                        ColoredLogger.GREEN
                    )
                except Exception as e:
                    ColoredLogger.error(
                        f"Failed to send results to IWAP for task {task_item.task.id}: {e}",
                        ColoredLogger.RED
                    )
            
            # Calculate average scores for each agent
            for uid, (agent, _) in deployed_agents.items():
                agent.score = 0.0  # Will be calculated from IWAP data
                self.agents_dict[uid] = agent
                agents_evaluated += 1
                
        finally:
            # Cleanup all deployed agents
            for uid in deployed_agents.keys():
                try:
                    self.sandbox_manager.cleanup_agent(uid)
                    ColoredLogger.info(f"Cleaned up agent {uid}", ColoredLogger.CYAN)
                except Exception as e:
                    ColoredLogger.error(f"Error cleaning up agent {uid}: {e}", ColoredLogger.RED)

        ColoredLogger.info("Evaluation phase completed", ColoredLogger.MAGENTA)
        return agents_evaluated
        
        
        
