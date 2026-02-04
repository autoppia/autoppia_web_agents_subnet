from __future__ import annotations

import os
import json
from pathlib import Path
from typing import List
from datetime import datetime

import bittensor as bt

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.evaluation.tasks import generate_tasks
from autoppia_web_agents_subnet.validator.config import (
    SEASON_SIZE_EPOCHS,
    MINIMUM_START_BLOCK,
    TASKS_PER_SEASON,
)
from autoppia_web_agents_subnet.platform.client import (
    compute_season_number,
)

# IWA imports for Task serialization
from autoppia_iwa.src.data_generation.tasks.classes import Task
from autoppia_iwa.src.demo_webs.config import demo_web_projects


class SeasonManager:
    """
    Manages season lifecycle and task generation with persistent storage.
    
    Flow:
    1. Validator starts → checks current season and round
    2. If round == 1: Generate tasks and save to JSON
    3. If round != 1: Load tasks from JSON (in case of restart)
    """

    BLOCKS_PER_EPOCH = 360
    TASKS_DIR = Path("data/season_tasks")

    def __init__(self):
        self.season_size_epochs = SEASON_SIZE_EPOCHS
        self.minimum_start_block = MINIMUM_START_BLOCK

        self.season_block_length = int(self.BLOCKS_PER_EPOCH * self.season_size_epochs)
        self.season_number: int | None = None

        self.season_tasks: List[TaskWithProject] = []
        self.task_generated_season: int | None = None
        
        # Create tasks directory if it doesn't exist
        self.TASKS_DIR.mkdir(parents=True, exist_ok=True)

    def get_season_number(self, current_block: int) -> int:
        """Calculate the current season number."""
        self.season_number = compute_season_number(current_block)
        return self.season_number

    def get_season_start_block(self, current_block: int) -> int:
        """
        Get the starting block of the current season.
        
        This is used by RoundManager to calculate round boundaries within a season.
        
        Args:
            current_block: Current blockchain block number
            
        Returns:
            Block number where the current season started
        """
        season_number = self.get_season_number(current_block)
        
        if season_number == 0:
            # Before starting block, return minimum_start_block
            return int(self.minimum_start_block)
        
        # Calculate: base_block + (season_number - 1) * season_block_length
        base_block = int(self.minimum_start_block)
        season_index = season_number - 1
        season_start_block = base_block + (season_index * self.season_block_length)
        
        return int(season_start_block)

    def _get_season_tasks_file(self, season_number: int) -> Path:
        """Get the path to the tasks JSON file for a given season."""
        return self.TASKS_DIR / f"season_{season_number}_tasks.json"

    def _serialize_tasks(self, tasks: List[TaskWithProject]) -> List[dict]:
        """Serialize TaskWithProject objects to JSON-compatible format using native Task methods."""
        serialized = []
        for task_with_project in tasks:
            task = task_with_project.task
            project = task_with_project.project
            
            serialized.append({
                "project_name": project.name,
                "task": task.serialize(),  # ← Usa el método nativo de Task
            })
        return serialized

    def _deserialize_tasks(self, serialized_tasks: List[dict]) -> List[TaskWithProject]:
        """Deserialize JSON data back to TaskWithProject objects using native Task methods."""
        tasks = []
        projects_map = {project.name: project for project in demo_web_projects}
        
        for item in serialized_tasks:
            project_name = item.get("project_name")
            task_data = item.get("task", {})
            
            project = projects_map.get(project_name)
            if not project:
                bt.logging.warning(f"Project '{project_name}' not found, skipping task")
                continue
            
            # Usa el método nativo de Task para deserializar
            task = Task.deserialize(task_data)
            
            tasks.append(TaskWithProject(project=project, task=task))
        
        return tasks

    def save_season_tasks(self, season_number: int) -> bool:
        """Save current season tasks to JSON file."""
        if not self.season_tasks:
            ColoredLogger.warning(f"No season tasks to save for season {season_number}")
            return False
        
        tasks_file = self._get_season_tasks_file(season_number)
        
        try:
            serialized = self._serialize_tasks(self.season_tasks)
            data = {
                "season_number": season_number,
                "generated_at": datetime.now().isoformat(),
                "num_tasks": len(self.season_tasks),
                "tasks": serialized,
            }
            
            with tasks_file.open("w") as f:
                json.dump(data, f, indent=2)
            
            ColoredLogger.success(f"💾 Saved {len(self.season_tasks)} tasks for season {season_number} to {tasks_file}")
            return True
        except Exception as e:
            ColoredLogger.error(f"Failed to save season tasks: {e}")
            return False

    def load_season_tasks(self, season_number: int) -> bool:
        """Load season tasks from JSON file."""
        tasks_file = self._get_season_tasks_file(season_number)
        
        if not tasks_file.exists():
            return False
        
        try:
            with tasks_file.open("r") as f:
                data = json.load(f)
            
            saved_season = data.get("season_number")
            if saved_season != season_number:
                ColoredLogger.warning(f"Season mismatch: file says {saved_season}, expected {season_number}")
                return False
            
            serialized_tasks = data.get("tasks", [])
            self.season_tasks = self._deserialize_tasks(serialized_tasks)
            self.task_generated_season = season_number
            
            ColoredLogger.success(f"📂 Loaded {len(self.season_tasks)} tasks for season {season_number} from {tasks_file}")
            return True
        except Exception as e:
            ColoredLogger.error(f"Failed to load season tasks: {e}")
            return False

    async def get_season_tasks(self, current_block: int, round_manager) -> List[TaskWithProject]:
        """
        Get tasks for the current season.
        
        Flow:
        - Round 1: Generate tasks and save to JSON
        - Round > 1: Load tasks from JSON (in case of restart)
        
        Args:
            current_block: Current blockchain block number
            round_manager: RoundManager instance to get round number in season
        """
        season_number = self.get_season_number(current_block)
        round_in_season = round_manager.get_round_number_in_season(current_block)
        
        ColoredLogger.info(f"🔍 Season {season_number}, Round {round_in_season}")
        
        if round_in_season == 1:
            # Round 1: Generate tasks and save
            ColoredLogger.info(f"🌱 Round 1: Generating {TASKS_PER_SEASON} tasks for season {season_number}")
            self.season_tasks = await generate_tasks(TASKS_PER_SEASON)
            self.task_generated_season = season_number
            self.save_season_tasks(season_number)
            ColoredLogger.success(f"✅ Generated and saved {len(self.season_tasks)} tasks")
        else:
            # Round > 1: Try to load from JSON
            ColoredLogger.info(f"🔄 Round {round_in_season}: Loading tasks from JSON...")
            loaded = self.load_season_tasks(season_number)
            
            if not loaded:
                ColoredLogger.warning(
                    f"⚠️  No saved tasks found for season {season_number}. "
                    f"Tasks are only generated in Round 1!"
                )
                return []
        
        return self.season_tasks

    async def generate_season_tasks(self, current_block: int, round_manager) -> List[TaskWithProject]:
        """Legacy method - kept for compatibility. Use get_season_tasks() instead."""
        return await self.get_season_tasks(current_block, round_manager)

    def should_start_new_season(self, current_block: int) -> bool:
        """Check if we're in a new season."""
        season_number = self.get_season_number(current_block)
        if not self.task_generated_season or self.task_generated_season != season_number:
            return True
        return False
