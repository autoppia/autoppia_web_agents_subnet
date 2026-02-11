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

                # Prepare batch data for IWAP submission
                batch_eval_data = []  # Store (task_item, score, exec_time, cost, reward, eval_result)
                
                for task_item, eval_result in zip(batch_tasks, eval_results):
                    if isinstance(eval_result, Exception):
                        ColoredLogger.error(f"Error evaluating agent {agent.uid} on task {task_item.task.id}: {eval_result}", ColoredLogger.RED)
                        continue

                    score, exec_time, task_solution = eval_result                    
                    usage_for_task = self.sandbox_manager.get_usage_for_task(task_id=task_item.task.id)
                    cost = usage_for_task.get("total_cost", 0.0) if usage_for_task else 0.0
                    tokens = usage_for_task.get("total_tokens", 0) if usage_for_task else 0
                    
                    ColoredLogger.info(
                        f"  Agent {agent.uid}: score={score:.3f}, time={exec_time:.2f}s, cost=${cost:.4f}, tokens={tokens}",
                        ColoredLogger.CYAN
                    )

                    reward = calculate_reward_for_task(
                        eval_score=score,
                        execution_time=exec_time,
                        token_cost=cost,
                    )
                    rewards.append(reward)
                    
                    # Store evaluation data for batch submission
                    batch_eval_data.append({
                        'task_item': task_item,
                        'score': score,
                        'exec_time': exec_time,
                        'cost': cost,
                        'tokens': tokens,
                        'reward': reward,
                        'task_solution': task_solution,
                    })
                
                # Submit batch evaluations to IWAP
                if batch_eval_data:
                    try:
                        await self._submit_batch_evaluations_to_iwap(
                            agent_uid=agent.uid,
                            batch_eval_data=batch_eval_data,
                        )
                        ColoredLogger.info(
                            f"✅ Submitted {len(batch_eval_data)} evaluations to IWAP for agent {agent.uid}",
                            ColoredLogger.GREEN
                        )
                    except Exception as e:
                        ColoredLogger.error(
                            f"Failed to submit batch evaluations to IWAP for agent {agent.uid}: {e}",
                            ColoredLogger.RED
                        )

                if len(rewards) >= SCREENING_TASKS_FOR_EARLY_STOP and sum(rewards) == 0.0:
                    ColoredLogger.warning(f"Agent {agent.uid} is failing first {len(rewards)} tasks, stopping evaluation", ColoredLogger.YELLOW)
                    break
                

        ColoredLogger.info("Evaluation phase completed", ColoredLogger.MAGENTA)
        return agents_evaluated
    
    async def _submit_batch_evaluations_to_iwap(
        self,
        *,
        agent_uid: int,
        batch_eval_data: list,
    ) -> None:
        """
        Submit a batch of evaluations to IWAP for a single agent.
        
        This method prepares evaluation payloads for all tasks in the batch
        and sends them in a single HTTP request to IWAP.
        
        Args:
            agent_uid: The UID of the agent being evaluated
            batch_eval_data: List of dicts containing evaluation data:
                - task_item: Task with project
                - score: Evaluation score
                - exec_time: Execution time
                - cost: Token cost
                - reward: Calculated reward
                - task_solution: TaskSolution from evaluate_with_stateful_cua
        """
        if not hasattr(self, 'current_round_id') or not self.current_round_id:
            ColoredLogger.warning("No current round ID, skipping IWAP submission", ColoredLogger.YELLOW)
            return
        
        if not hasattr(self, 'current_agent_runs') or agent_uid not in self.current_agent_runs:
            ColoredLogger.warning(f"No agent run found for agent {agent_uid}, skipping IWAP submission", ColoredLogger.YELLOW)
            return
        
        agent_run = self.current_agent_runs[agent_uid]
        
        # Prepare all evaluation payloads
        from autoppia_web_agents_subnet.platform.utils.task_flow import prepare_evaluation_payload
        
        evaluations_batch = []
        for eval_data in batch_eval_data:
            task_item = eval_data['task_item']
            
            # Get task payload from current round tasks
            base_task_id = getattr(task_item.task, "id", None)
            if base_task_id is None:
                continue
            
            # Build the full task_id that matches what was stored in IWAP
            full_task_id = f"{self.current_round_id}_{base_task_id}"
            task_payload = self.current_round_tasks.get(full_task_id)
            if task_payload is None:
                task_payload = self.current_round_tasks.get(base_task_id)
            if task_payload is None:
                ColoredLogger.warning(f"Task {base_task_id} not found in current round tasks", ColoredLogger.YELLOW)
                continue
            
            # task_solution comes from evaluate_with_stateful_cua (TaskSolution); support dict for backwards compat
            task_solution = eval_data['task_solution']
            
            # Extract solution and actions
            solution = None
            actions = []
            test_results_data = []
            evaluation_meta_dict = {}
            
            from autoppia_iwa.src.web_agents.classes import TaskSolution
            if isinstance(task_solution, TaskSolution):
                solution = task_solution
                actions = getattr(solution, 'actions', []) or []
            elif isinstance(task_solution, dict):
                # Legacy: dict form (e.g. execution_history, test_results)
                evaluation_meta_dict = task_solution
                # Extract actions from execution_history if present
                if 'execution_history' in task_solution:
                    execution_history = task_solution['execution_history']
                    if isinstance(execution_history, list):
                        for step in execution_history:
                            if isinstance(step, dict) and 'action' in step:
                                actions.append(step['action'])
                # Extract test_results
                test_results_data = task_solution.get('test_results', [])
                # Create solution object with extracted actions
                solution = TaskSolution(
                    task_id=base_task_id,
                    actions=actions,
                    web_agent_id=str(agent_uid)
                )
            else:
                # Fallback: create empty solution
                solution = TaskSolution(
                    task_id=base_task_id,
                    actions=[],
                    web_agent_id=str(agent_uid)
                )
            
            evaluation_payload = prepare_evaluation_payload(
                ctx=self,
                task_payload=task_payload,
                agent_run=agent_run,
                miner_uid=agent_uid,
                solution=solution,
                eval_score=eval_data['score'],
                evaluation_meta=evaluation_meta_dict if isinstance(task_solution, dict) else {},
                test_results_data=test_results_data,
                exec_time=eval_data['exec_time'],
                reward=eval_data['reward'],
                llm_cost=eval_data.get('cost'),
                llm_tokens=eval_data.get('tokens'),
                llm_provider=eval_data.get('provider'),
            )
            
            evaluations_batch.append(evaluation_payload)
        
        if not evaluations_batch:
            ColoredLogger.warning("No evaluations to submit in batch", ColoredLogger.YELLOW)
            return
        
        # Submit batch to IWAP
        if hasattr(self, 'iwap_client') and self.iwap_client:
            try:
                result = await self.iwap_client.add_evaluations_batch(
                    validator_round_id=self.current_round_id,
                    agent_run_id=agent_run.agent_run_id,
                    evaluations=evaluations_batch,
                )
                ColoredLogger.info(
                    f"Batch submission result: {result.get('message', 'Success')}",
                    ColoredLogger.GREEN
                )
            except Exception as e:
                ColoredLogger.error(f"Failed to submit batch: {e}", ColoredLogger.RED)
                raise
        
        
        
