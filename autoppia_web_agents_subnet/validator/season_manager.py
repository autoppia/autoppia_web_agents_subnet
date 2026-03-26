from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import bittensor as bt

# IWA imports for Task serialization
from autoppia_iwa.src.data_generation.tasks.classes import Task
from autoppia_iwa.src.demo_webs.config import demo_web_projects

from autoppia_web_agents_subnet import SUBNET_IWA_VERSION
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.config import (
    BLOCKS_PER_EPOCH as CONFIG_BLOCKS_PER_EPOCH,
    MINIMUM_START_BLOCK,
    SEASON_SIZE_EPOCHS,
    TASKS_PER_SEASON,
)
from autoppia_web_agents_subnet.validator.evaluation.tasks import generate_tasks
from autoppia_web_agents_subnet.validator.models import TaskWithProject


class SeasonManager:
    """
    Manages season lifecycle and task generation with persistent storage.

    Flow:
    1. Validator starts → checks current season and round
    2. If round == 1: Generate tasks and save to JSON
    3. If round != 1: Load tasks from JSON (in case of restart)
    """

    BLOCKS_PER_EPOCH = CONFIG_BLOCKS_PER_EPOCH
    TASKS_DIR = Path("data")

    def __init__(self):
        self.season_size_epochs = SEASON_SIZE_EPOCHS
        self.minimum_start_block = MINIMUM_START_BLOCK

        self.season_block_length = int(self.BLOCKS_PER_EPOCH * self.season_size_epochs)
        self.season_number: int | None = None

        self.season_tasks: list[TaskWithProject] = []
        self.task_generated_season: int | None = None

        # Create tasks directory if it doesn't exist
        self.TASKS_DIR.mkdir(parents=True, exist_ok=True)

    def get_season_number(self, current_block: int) -> int:
        """
        Calculate the current season number.

        Season 0: blocks before minimum_start_block
        Season 1+: blocks from minimum_start_block onward, each season is season_block_length
        """
        base = int(self.minimum_start_block)
        if current_block < base:
            self.season_number = 0
            return 0

        idx = int((current_block - base) // int(self.season_block_length))
        self.season_number = int(idx + 1)
        return int(self.season_number)

    def resolve_season_reference_block(self, current_block: int, round_manager=None) -> int:
        """
        Resolve the canonical block that identifies the current round/season.

        We must anchor season math to the round start block, not to the latest
        chain block seen later in the round. Otherwise tasks/files may roll to
        the next season while IWAP still persists the round in the previous one.
        """
        if round_manager is not None:
            for attr in ("start_block", "_settlement_round_start_block"):
                try:
                    value = getattr(round_manager, attr, None)
                except Exception:
                    value = None
                if value is not None:
                    try:
                        return int(value)
                    except Exception:
                        pass
            try:
                boundaries = round_manager.get_round_boundaries(current_block, log_debug=False)
                round_start_block = boundaries.get("round_start_block")
                if round_start_block is not None:
                    return int(round_start_block)
            except Exception:
                pass
        return int(current_block)

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
        """Get the path to the tasks JSON file for a given season.

        New layout:
          data/season_<n>/tasks.json
        """
        season_dir = self.TASKS_DIR / f"season_{season_number}"
        return season_dir / "tasks.json"

    def _get_legacy_season_tasks_file(self, season_number: int) -> Path:
        """Legacy path kept for compatibility (read-only fallback)."""
        return self.TASKS_DIR / "season_tasks" / f"season_{season_number}_tasks.json"

    def _migrate_legacy_tasks_file(self, season_number: int) -> bool:
        """Migrate legacy season tasks file to the new per-season folder layout."""
        tasks_file = self._get_season_tasks_file(season_number)
        legacy_tasks_file = self._get_legacy_season_tasks_file(season_number)

        if tasks_file.exists() or not legacy_tasks_file.exists():
            return False

        try:
            tasks_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_tasks_file, tasks_file)
            ColoredLogger.info(f"📦 Migrated legacy tasks file {legacy_tasks_file} -> {tasks_file}")
            return True
        except Exception as e:
            ColoredLogger.warning(f"Failed to migrate legacy tasks file for season {season_number}: {e}")
            return False

    def _serialize_tasks(self, tasks: list[TaskWithProject]) -> list[dict]:
        """Serialize TaskWithProject objects to JSON-compatible format using native Task methods."""
        serialized = []
        for task_with_project in tasks:
            task = task_with_project.task
            project = task_with_project.project

            serialized.append(
                {
                    "project_name": project.name,
                    "task": task.serialize(),  # ← Usa el método nativo de Task
                }
            )
        return serialized

    def _deserialize_tasks(self, serialized_tasks: list[dict]) -> list[TaskWithProject]:
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
                "validator_version": str(SUBNET_IWA_VERSION),
                "num_tasks": len(self.season_tasks),
                "tasks": serialized,
            }

            tasks_file.parent.mkdir(parents=True, exist_ok=True)
            with tasks_file.open("w") as f:
                json.dump(data, f, indent=2, default=str)

            ColoredLogger.success(f"💾 Saved {len(self.season_tasks)} tasks for season {season_number} to {tasks_file}")
            return True
        except Exception as e:
            ColoredLogger.error(f"Failed to save season tasks: {e}")
            return False

    def load_season_tasks(self, season_number: int) -> bool:
        """Load season tasks from JSON file."""
        tasks_file = self._get_season_tasks_file(season_number)
        legacy_tasks_file = self._get_legacy_season_tasks_file(season_number)

        if not tasks_file.exists() and legacy_tasks_file.exists():
            migrated = self._migrate_legacy_tasks_file(season_number)
            if not migrated:
                tasks_file = legacy_tasks_file

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
            declared_num_tasks = data.get("num_tasks")
            cached_version = str(data.get("validator_version") or "")
            expected_version = str(SUBNET_IWA_VERSION)
            if cached_version != expected_version:
                cached_label = cached_version or "<missing>"
                ColoredLogger.warning(f"Season tasks cache version mismatch: file version {cached_label}, current {expected_version}. Ignoring cached file.")
                return False
            actual_num_tasks = len(serialized_tasks)
            expected_num_tasks = int(TASKS_PER_SEASON)
            if isinstance(declared_num_tasks, int) and declared_num_tasks != expected_num_tasks:
                ColoredLogger.warning(f"Season tasks cache count mismatch: file declares {declared_num_tasks}, expected {expected_num_tasks}. Ignoring cached file.")
                return False
            if actual_num_tasks != expected_num_tasks:
                ColoredLogger.warning(f"Season tasks cache size mismatch: file has {actual_num_tasks}, expected {expected_num_tasks}. Ignoring cached file.")
                return False
            self.season_tasks = self._deserialize_tasks(serialized_tasks)
            self.task_generated_season = season_number

            ColoredLogger.success(f"📂 Loaded {len(self.season_tasks)} tasks for season {season_number} from {tasks_file}")
            return True
        except Exception as e:
            ColoredLogger.error(f"Failed to load season tasks: {e}")
            return False

    async def get_season_tasks(self, current_block: int, round_manager=None) -> list[TaskWithProject]:
        """
        Get tasks for the current season.

        Flow:
        - Always try to load from JSON first (for any round, including restarts)
        - If not found: Generate tasks and save (regardless of round number)

        Args:
            current_block: Current blockchain block number
            round_manager: RoundManager instance to get round number in season
        """
        reference_block = self.resolve_season_reference_block(current_block, round_manager)
        season_number = self.get_season_number(reference_block)
        round_in_season = 1
        if round_manager is not None:
            try:
                round_in_season = int(round_manager.get_round_number_in_season(reference_block))
            except Exception:
                round_in_season = 1

        ColoredLogger.info(f"🔍 Season {season_number}, Round {round_in_season}")

        # In-memory cache: if we already have tasks for this season in this
        # process, don't hit disk again.
        if self.task_generated_season == season_number and self.season_tasks:
            if len(self.season_tasks) == int(TASKS_PER_SEASON):
                ColoredLogger.success(f"✅ Using cached {len(self.season_tasks)} tasks for season {season_number}")
                return self.season_tasks
            ColoredLogger.warning(f"⚠️ In-memory season cache has {len(self.season_tasks)} tasks but TASKS_PER_SEASON={TASKS_PER_SEASON}; regenerating cache.")
            self.season_tasks = []
            self.task_generated_season = None

        # Always try to load first (handles restarts in any round)
        loaded = self.load_season_tasks(season_number)

        if loaded:
            ColoredLogger.success(f"✅ Loaded {len(self.season_tasks)} tasks for season {season_number}")
            return self.season_tasks

        # Not loaded - generate tasks (regardless of round number)
        ColoredLogger.info(f"🌱 No tasks found in JSON for season {season_number} (Round {round_in_season}). Generating {TASKS_PER_SEASON} new tasks...")
        self.season_tasks = await generate_tasks(TASKS_PER_SEASON)
        self.task_generated_season = season_number
        self.save_season_tasks(season_number)
        ColoredLogger.success(f"✅ Generated and saved {len(self.season_tasks)} tasks")
        return self.season_tasks

    async def generate_season_tasks(self, current_block: int, round_manager=None) -> list[TaskWithProject]:
        """Legacy method - kept for compatibility. Use get_season_tasks() instead."""
        return await self.get_season_tasks(current_block, round_manager)

    def should_start_new_season(self, current_block: int) -> bool:
        """Check if we're in a new season."""
        season_number = self.get_season_number(current_block)
        return bool(not self.task_generated_season or self.task_generated_season != season_number)
