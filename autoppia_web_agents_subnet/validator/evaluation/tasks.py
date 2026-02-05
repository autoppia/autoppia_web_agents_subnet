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

async def _generate_task_for_project(project: WebProject) -> Task:
    """
    Generate a single task for a project (1 prompt per use case).
    
    Args:
        project: Web project to generate task for
        
    Returns:
        Single generated task
    """
    config = TaskGenerationConfig(
        prompts_per_use_case=1,
    )
    pipeline = TaskGenerationPipeline(web_project=project, config=config)
    tasks = await pipeline.generate()
    
    if not tasks:
        raise ValueError(f"Failed to generate task for project {project.name}")
    
    return tasks[0]


async def generate_tasks(num_tasks: int) -> List[TaskWithProject]:
    """
    Generate tasks across demo web projects using round-robin.
    
    Simple approach:
    1. Iterate through all projects in order
    2. Generate 1 task per project (1 prompt per use case)
    3. When all projects are done, start again from project 1
    4. Continue until we have exactly num_tasks
    
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
    
    # Round-robin through projects until we reach num_tasks
    project_index = 0
    while len(all_tasks) < num_tasks:
        project = demo_web_projects[project_index]
        
        try:
            task = await _generate_task_for_project(project)
            all_tasks.append(TaskWithProject(project=project, task=task))
            
            if len(all_tasks) % 10 == 0:  # Log progress every 10 tasks
                bt.logging.debug(f"[tasks] Generated {len(all_tasks)}/{num_tasks} tasks")
                
        except Exception as e:
            bt.logging.error(f"[tasks] Failed to generate task for project '{project.name}': {e}")
            # Continue with next project instead of failing
        
        # Move to next project (round-robin)
        project_index = (project_index + 1) % num_projects
    
    elapsed = time.time() - start_time
    bt.logging.info(f"✅ Generated {len(all_tasks)} tasks in {elapsed:.1f}s")
    
    return all_tasks
