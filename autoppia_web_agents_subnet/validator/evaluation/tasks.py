"""
Task generation and processing utilities for validator.
Handles both task generation and task data processing.
"""

from __future__ import annotations

import time
from typing import List

import bittensor as bt

from autoppia_web_agents_subnet.validator.models import TaskWithProject

# IWA (module-wrapped) imports
from autoppia_iwa.src.demo_webs.config import demo_web_projects
from autoppia_iwa.src.demo_webs.classes import WebProject
from autoppia_iwa.src.data_generation.tasks.classes import Task, TaskGenerationConfig
from autoppia_iwa.src.data_generation.tasks.pipeline import TaskGenerationPipeline


# ═══════════════════════════════════════════════════════════════════════════════
# TASK GENERATION - Generate tasks for agents
# ═══════════════════════════════════════════════════════════════════════════════


async def _generate_task_for_project(project: WebProject, use_case_name: str) -> Task:
    """
    Generate a single task for a project (1 prompt per use case).

    Args:
        project: Web project to generate task for

    Returns:
        Single generated task
    """
    config = TaskGenerationConfig(
        prompts_per_use_case=1,
        # Limit generation to a single use case to avoid N×LLM calls per project.
        use_cases=[use_case_name],
        # Dynamic tasks include ?seed=... in the URL (required for deterministic variants)
        dynamic=True,
    )
    pipeline = TaskGenerationPipeline(web_project=project, config=config)
    tasks = await pipeline.generate()

    if not tasks:
        raise ValueError(f"Failed to generate task for project {project.name} (use_case={use_case_name})")

    return tasks[0]


async def generate_tasks(num_tasks: int) -> List[TaskWithProject]:
    """
    Generate tasks across demo web projects with balanced coverage.

    Rules:
    - Avoid repeating a project until all projects have been used.
    - Within a project, avoid repeating a use case until all its use cases have been used.
    - When a pool is exhausted (projects or a project's use cases), reshuffle and continue.

    Args:
        num_tasks: Total number of tasks to generate

    Returns:
        List of TaskWithProject objects
    """
    start_time = time.time()
    all_tasks: List[TaskWithProject] = []

    num_projects = len(demo_web_projects)
    if num_projects == 0:
        bt.logging.warning("[tasks] No demo_web_projects found")
        return []

    bt.logging.info(f"[tasks] Generating {num_tasks} tasks across {num_projects} projects")

    # Build per-project use case queues (shuffled).
    project_use_cases: dict[str, list[str]] = {}
    for project in demo_web_projects:
        use_cases = [uc.name for uc in (project.use_cases or []) if getattr(uc, "name", None)]
        if not use_cases:
            bt.logging.warning(f"[tasks] Project '{project.name}' has no use cases; skipping")
            continue
        project_use_cases[project.id] = use_cases

    if not project_use_cases:
        bt.logging.warning("[tasks] No projects with use cases available")
        return []

    # Project cycle: shuffled list of project ids, reshuffled when exhausted.
    import random

    project_cycle = list(project_use_cases.keys())
    random.shuffle(project_cycle)
    project_index = 0

    # Per-project use case cycles (shuffled, reshuffled when exhausted).
    use_case_cycles: dict[str, list[str]] = {}
    for project_id, use_cases in project_use_cases.items():
        uc_list = list(use_cases)
        random.shuffle(uc_list)
        use_case_cycles[project_id] = uc_list

    while len(all_tasks) < num_tasks:
        if project_index >= len(project_cycle):
            random.shuffle(project_cycle)
            project_index = 0

        project_id = project_cycle[project_index]
        project_index += 1

        # Find the actual project object
        project = next((p for p in demo_web_projects if p.id == project_id), None)
        if project is None:
            bt.logging.warning(f"[tasks] Missing project for id={project_id}; skipping")
            continue

        # Refill use case cycle if exhausted
        if not use_case_cycles.get(project_id):
            uc_list = list(project_use_cases[project_id])
            random.shuffle(uc_list)
            use_case_cycles[project_id] = uc_list

        use_case_name = use_case_cycles[project_id].pop(0)

        try:
            task = await _generate_task_for_project(project, use_case_name)
            all_tasks.append(TaskWithProject(project=project, task=task))

            if len(all_tasks) % 10 == 0:  # Log progress every 10 tasks
                bt.logging.debug(f"[tasks] Generated {len(all_tasks)}/{num_tasks} tasks")

        except Exception as e:
            bt.logging.error(
                f"[tasks] Failed to generate task for project '{project.name}' (use_case={use_case_name}): {e}"
            )
            # Continue with next project instead of failing

    elapsed = time.time() - start_time
    bt.logging.info(f"✅ Generated {len(all_tasks)} tasks in {elapsed:.1f}s")

    return all_tasks
