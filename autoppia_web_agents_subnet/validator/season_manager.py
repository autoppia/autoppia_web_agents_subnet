from __future__ import annotations

from typing import List

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.evaluation.tasks import generate_tasks
from autoppia_web_agents_subnet.validator.config import (
    SEASON_SIZE_EPOCHS,
    MINIMUM_START_BLOCK,
    PRE_GENERATED_TASKS,
)

class SeasonManager:

    BLOCKS_PER_EPOCH = 360

    def __init__(self):
        self.season_size_epochs = SEASON_SIZE_EPOCHS
        self.minimum_start_block = MINIMUM_START_BLOCK

        self.season_block_length = int(self.BLOCKS_PER_EPOCH * self.season_size_epochs)
        self.season_number: int | None = None

        self.season_tasks: List[TaskWithProject] = []
        self.task_generated_season: int | None = None

    def get_season_number(self, current_block: int) -> int:
        base_block = int(self.minimum_start_block)
        effective_block = max(current_block, base_block)

        blocks_since_base = effective_block - base_block
        season_index = blocks_since_base // self.season_block_length

        self.season_number = season_index + 1
        return int(self.season_number)

    async def get_season_tasks(self, current_block: int) -> List[TaskWithProject]:
        if self.should_start_new_season(current_block):
            ColoredLogger.info(f"Season tasks not generated for season {self.season_number}, generating...")
            await self.generate_season_tasks(current_block)
        else:
            ColoredLogger.info(f"Season tasks already generated for season {self.season_number}")
        return self.season_tasks

    async def generate_season_tasks(self, current_block: int) -> List[TaskWithProject]:
        season_number = self.get_season_number(current_block)
        ColoredLogger.info(f"Generating season tasks for season {season_number}")

        self.season_tasks = await generate_tasks(PRE_GENERATED_TASKS)
        self.task_generated_season = season_number

        ColoredLogger.success(f"Season tasks generated for season {season_number}")
        return self.season_tasks

    def should_start_new_season(self, current_block: int) -> bool:
        season_number = self.get_season_number(current_block)
        if not self.task_generated_season or self.task_generated_season != season_number:
            return True
        return False
