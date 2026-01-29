"""
Task generation and processing utilities for validator.
Handles both task generation and task data processing.
"""
from __future__ import annotations

import math
import time
import random
from typing import List

import bittensor as bt

from autoppia_web_agents_subnet.validator.models import TaskWithProject, ProjectTasks
from autoppia_web_agents_subnet.utils.random import split_tasks_evenly
from autoppia_web_agents_subnet.validator.config import PROMPTS_PER_USE_CASE

# IWA (module-wrapped) imports
from autoppia_iwa.src.demo_webs.config import demo_web_projects
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.data_generation.tasks.classes import Task, TaskGenerationConfig
from autoppia_iwa.src.data_generation.tasks.pipeline import TaskGenerationPipeline


# ═══════════════════════════════════════════════════════════════════════════════
# TASK GENERATION - Generate tasks for agents
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


async def _get_task_collection_interleaved(
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

    bt.logging.debug(
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

    bt.logging.debug(
        f"[tasks] Generated {len(interleaved_tasks)} interleaved tasks "
        f"across {len(projects_tasks)} projects"
    )

    return interleaved_tasks


# Public wrapper used in tests/validator flow
async def get_task_collection_interleaved(*, prompts_per_use_case: int) -> List[TaskWithProject]:
    return await _get_task_collection_interleaved(prompts_per_use_case=prompts_per_use_case)

async def generate_tasks(pre_generated_tasks: int) -> List[TaskWithProject]:
    pre_generation_start = time.time()
    all_tasks: List[TaskWithProject] = []

    tasks_generated = 0
    while tasks_generated < pre_generated_tasks:
        batch_start = time.time()
        batch_tasks = await _get_task_collection_interleaved(
            prompts_per_use_case=PROMPTS_PER_USE_CASE
        )
        remaining = pre_generated_tasks - tasks_generated
        tasks_to_add = batch_tasks[:remaining]
        all_tasks.extend(tasks_to_add)
        tasks_generated += len(tasks_to_add)

        batch_elapsed = time.time() - batch_start
        bt.logging.debug(
            f"Generated batch: {len(tasks_to_add)} in {batch_elapsed:.1f}s "
            f"(total {tasks_generated}/{pre_generated_tasks})"
        )

    pre_generation_elapsed = time.time() - pre_generation_start
    bt.logging.info(
        f"✅ Task list ready: {len(all_tasks)} tasks in {pre_generation_elapsed:.1f}s"
    )

    return all_tasks

