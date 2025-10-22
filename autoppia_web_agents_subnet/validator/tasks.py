# file: autoppia_web_agents_subnet/validator/tasks.py
"""
Task generation and processing utilities for validator.
Handles both task generation and task data processing.
"""
from __future__ import annotations

import math
import random
from typing import List, Tuple

import bittensor as bt

from autoppia_web_agents_subnet.validator.models import TaskWithProject, ProjectTasks
from autoppia_web_agents_subnet.utils.random import split_tasks_evenly
from autoppia_web_agents_subnet.protocol import TaskSynapse
from autoppia_web_agents_subnet.validator.config import MAX_ACTIONS_LENGTH, TIMEOUT, ENABLE_DYNAMIC_HTML

# IWA (module-wrapped) imports
from autoppia_iwa.src.demo_webs.config import demo_web_projects
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.data_generation.domain.classes import Task, TaskGenerationConfig
from autoppia_iwa.src.data_generation.application.tasks_generation_pipeline import (
    TaskGenerationPipeline,
)
from autoppia_iwa.src.data_generation.domain.classes import Task as IWATask
from autoppia_iwa.src.web_agents.classes import TaskSolution


# ═══════════════════════════════════════════════════════════════════════════════
# TASK GENERATION - Generate tasks for miners
# ═══════════════════════════════════════════════════════════════════════════════

async def _generate_tasks_limited_use_cases(
    project: WebProject,
    total_tasks: int,
    prompts_per_use_case: int,
    num_use_cases: int,
) -> List[Task]:
    """
    Generate up to `total_tasks` tasks for `project` sampling `num_use_cases` use-cases.
    """
    config = TaskGenerationConfig(
        prompts_per_use_case=prompts_per_use_case,
        generate_global_tasks=True,
        final_task_limit=total_tasks,
        num_use_cases=num_use_cases,
    )
    pipeline = TaskGenerationPipeline(web_project=project, config=config)
    return await pipeline.generate()


async def get_task_collection_interleaved(
    *,
    prompts_per_use_case: int,
) -> List[TaskWithProject]:
    """
    Generate tasks across demo web projects and return them as an interleaved list.

    Tasks are distributed evenly across projects and then interleaved using round-robin
    to ensure variety (alternating between different projects).

    Args:
        prompts_per_use_case: Number of prompts to generate per use case

    Returns:
        List[TaskWithProject]: Flat list of tasks already interleaved across projects
    """
    num_projects = len(demo_web_projects)
    total_prompts = num_projects

    if total_prompts <= 0:
        bt.logging.warning("[tasks] total_prompts <= 0 -> returning empty list")
        return []

    if num_projects == 0:
        bt.logging.warning("[tasks] no demo_web_projects found -> returning empty list")
        return []

    # Even split total prompts; remainder distributed one-by-one from the end
    task_distribution = split_tasks_evenly(total_prompts, num_projects)

    # Heuristic: cap how many distinct use-cases we touch per project
    use_cases_per_project = max(1, math.ceil(total_prompts / max(1, num_projects)))

    bt.logging.info(
        f"[tasks] Generating {total_prompts} tasks across {num_projects} projects: "
        f"distribution={task_distribution}, use_cases/project={use_cases_per_project}, "
        f"prompts_per_use_case={prompts_per_use_case}"
    )

    projects_tasks: List[ProjectTasks] = []

    # Generate tasks for each project
    for project, num_tasks in zip(demo_web_projects, task_distribution):
        if num_tasks <= 0:
            continue

        try:
            project_tasks = await _generate_tasks_limited_use_cases(
                project=project,
                total_tasks=num_tasks,
                prompts_per_use_case=prompts_per_use_case,
                num_use_cases=use_cases_per_project,
            )
        except Exception as e:
            bt.logging.error(f"[tasks] generation failed for project '{getattr(project, 'name', 'unknown')}': {e}")
            continue

        if not project_tasks:
            bt.logging.warning(f"[tasks] project '{getattr(project, 'name', 'unknown')}' produced 0 tasks.")
            continue

        # Add intra-project variety
        random.shuffle(project_tasks)
        projects_tasks.append(ProjectTasks(project=project, tasks=project_tasks))

    if not projects_tasks:
        bt.logging.warning("[tasks] No tasks generated in any project.")
        return []

    # Interleave tasks using round-robin across projects
    interleaved_tasks: List[TaskWithProject] = []
    queues = [(pt.project, list(pt.tasks)) for pt in projects_tasks if pt.tasks]

    while queues:
        for project, task_queue in list(queues):
            if task_queue:
                task = task_queue.pop(0)
                interleaved_tasks.append(TaskWithProject(project=project, task=task))
            if not task_queue:
                queues.remove((project, task_queue))

    bt.logging.info(
        f"[tasks] Generated {len(interleaved_tasks)} interleaved tasks "
        f"across {len(projects_tasks)} projects"
    )

    # Apply seed to task URLs if dynamic HTML is enabled
    if ENABLE_DYNAMIC_HTML:
        bt.logging.info("[tasks] Applying seeds to task URLs (ENABLE_DYNAMIC_HTML=true)")
        for task_with_project in interleaved_tasks:
            task = task_with_project.task
            task.assign_seed = True
            if "?seed=" not in task.url:
                task.assign_seed_to_url()
        bt.logging.info(f"[tasks] Seeds assigned to {len(interleaved_tasks)} tasks")

    return interleaved_tasks


# ═══════════════════════════════════════════════════════════════════════════════
# TASK PROCESSING - Process task data and miner responses
# ═══════════════════════════════════════════════════════════════════════════════

def get_task_solution_from_synapse(
    task_id: str,
    synapse: TaskSynapse,
    web_agent_id: str,
    max_actions_length: int = MAX_ACTIONS_LENGTH,
) -> TaskSolution:
    """
    Safely extract actions from a TaskSynapse response and limit their length.
    NOTE: correct slicing is [:max], not [max].
    """
    actions = []
    if synapse and hasattr(synapse, "actions") and isinstance(synapse.actions, list):
        actions = synapse.actions[:max_actions_length]
    return TaskSolution(task_id=task_id, actions=actions, web_agent_id=web_agent_id)


def collect_task_solutions_and_execution_times(
    task: IWATask,
    responses: List[TaskSynapse | None],
    miner_uids: List[int],
) -> Tuple[List[TaskSolution], List[float]]:
    """
    Convert miner responses into TaskSolution and gather process times.
    Handles None responses (failed requests) gracefully.
    """
    task_solutions: List[TaskSolution] = []
    execution_times: List[float] = []

    for miner_uid, response in zip(miner_uids, responses):
        # Handle None or failed responses
        if response is None:
            bt.logging.warning(f"Miner {miner_uid} returned None response")
            task_solutions.append(
                TaskSolution(task_id=task.id, actions=[], web_agent_id=str(miner_uid))
            )
            execution_times.append(TIMEOUT)
            bt.logging.debug(
                f"[TIME] uid={miner_uid} response=None -> using TIMEOUT={TIMEOUT:.3f}s"
            )
            continue

        # Try to parse valid response
        try:
            task_solutions.append(
                get_task_solution_from_synapse(
                    task_id=task.id,
                    synapse=response,
                    web_agent_id=str(miner_uid),
                )
            )
        except Exception as e:
            bt.logging.error(f"Miner response format error: {e}")
            task_solutions.append(
                TaskSolution(task_id=task.id, actions=[], web_agent_id=str(miner_uid))
            )

        if (
            response
            and hasattr(response, "dendrite")
            and hasattr(response.dendrite, "process_time")
            and response.dendrite.process_time is not None
        ):
            execution_times.append(response.dendrite.process_time)
            bt.logging.debug(
                f"[TIME] uid={miner_uid} process_time={response.dendrite.process_time:.3f}s (taken)"
            )
        else:
            execution_times.append(TIMEOUT)
            bt.logging.debug(
                f"[TIME] uid={miner_uid} process_time=None -> using TIMEOUT={TIMEOUT:.3f}s"
            )

    return task_solutions, execution_times
