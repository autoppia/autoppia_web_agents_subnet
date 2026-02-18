"""
Unit tests for SeasonManager.

Tests season calculations, task generation, and caching.
"""

import pytest
from unittest.mock import patch
from autoppia_web_agents_subnet.validator.season_manager import SeasonManager
from autoppia_web_agents_subnet.validator.models import TaskWithProject


@pytest.mark.unit
class TestSeasonBoundaries:
    """Test season boundary calculations."""

    def test_get_season_number_calculates_correctly(self):
        """Test that get_season_number calculates season from block number."""
        manager = SeasonManager()
        base = int(manager.minimum_start_block)
        season_len = int(manager.season_block_length)

        # Season 0: before base
        assert manager.get_season_number(base - 1) == 0

        # Season 1: [base, base+season_len)
        assert manager.get_season_number(base) == 1
        assert manager.get_season_number(base + (season_len // 2)) == 1
        assert manager.get_season_number(base + season_len - 1) == 1

        # Season 2: [base+season_len, base+2*season_len)
        assert manager.get_season_number(base + season_len) == 2
        assert manager.get_season_number(base + season_len + (season_len // 2)) == 2

    def test_season_block_length_uses_season_size_epochs(self):
        """Test that season_block_length is calculated from SEASON_SIZE_EPOCHS."""
        manager = SeasonManager()
        
        # season_block_length = BLOCKS_PER_EPOCH * season_size_epochs
        expected_length = 360 * manager.season_size_epochs
        assert manager.season_block_length == int(expected_length)

    def test_season_boundaries_align_with_minimum_start_block(self):
        """Test that season boundaries start from minimum_start_block."""
        manager = SeasonManager()
        
        # Before minimum_start_block should be season 0
        season_num = manager.get_season_number(manager.minimum_start_block - 1)
        assert season_num == 0
        
        # At minimum_start_block should be season 1
        season_num = manager.get_season_number(manager.minimum_start_block)
        assert season_num == 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestTaskGeneration:
    """Test task generation and caching."""

    async def test_generate_season_tasks_creates_correct_number(self, tmp_path, monkeypatch):
        """Test that generate_season_tasks creates the expected number of tasks."""
        monkeypatch.setattr(SeasonManager, "TASKS_DIR", tmp_path)
        manager = SeasonManager()

        from autoppia_iwa.src.demo_webs.config import demo_web_projects
        from autoppia_iwa.src.data_generation.tasks.classes import Task
        project = demo_web_projects[0]
        
        with patch('autoppia_web_agents_subnet.validator.season_manager.generate_tasks') as mock_gen:
            # Mock generate_tasks to return a list of TaskWithProject
            mock_tasks = [
                TaskWithProject(project=project, task=Task(url=f"https://example.com/{i}", prompt=f"prompt-{i}", tests=[]))
                for i in range(5)
            ]
            mock_gen.return_value = mock_tasks
            
            tasks = await manager.generate_season_tasks(manager.minimum_start_block)
            
            assert len(tasks) == 5
            assert manager.task_generated_season == 1

    async def test_get_season_tasks_returns_cached_tasks_within_season(self, tmp_path, monkeypatch):
        """Test that get_season_tasks returns cached tasks without regenerating."""
        monkeypatch.setattr(SeasonManager, "TASKS_DIR", tmp_path)
        manager = SeasonManager()

        from autoppia_iwa.src.demo_webs.config import demo_web_projects
        from autoppia_iwa.src.data_generation.tasks.classes import Task
        project = demo_web_projects[0]
        
        with patch('autoppia_web_agents_subnet.validator.season_manager.generate_tasks') as mock_gen:
            mock_tasks = [
                TaskWithProject(project=project, task=Task(url=f"https://example.com/{i}", prompt=f"prompt-{i}", tests=[]))
                for i in range(3)
            ]
            mock_gen.return_value = mock_tasks
            
            # First call generates tasks
            tasks1 = await manager.get_season_tasks(manager.minimum_start_block)
            assert mock_gen.call_count == 1
            
            # Second call in same season should use cache
            tasks2 = await manager.get_season_tasks(manager.minimum_start_block + 1)
            assert mock_gen.call_count == 1  # Not called again
            assert tasks1 == tasks2

    async def test_task_generated_season_is_stored_correctly(self, tmp_path, monkeypatch):
        """Test that task_generated_season tracks which season tasks were generated for."""
        monkeypatch.setattr(SeasonManager, "TASKS_DIR", tmp_path)
        manager = SeasonManager()
        base = int(manager.minimum_start_block)
        season_len = int(manager.season_block_length)
        
        with patch('autoppia_web_agents_subnet.validator.season_manager.generate_tasks') as mock_gen:
            mock_gen.return_value = []
            
            await manager.generate_season_tasks(base)
            assert manager.task_generated_season == 1
            
            await manager.generate_season_tasks(base + season_len)
            assert manager.task_generated_season == 2


@pytest.mark.unit
class TestSeasonTransitions:
    """Test season transition detection and handling."""

    def test_should_start_new_season_detects_transitions(self):
        """Test that should_start_new_season returns True when season changes."""
        manager = SeasonManager()
        base = int(manager.minimum_start_block)
        season_len = int(manager.season_block_length)
        
        # No tasks generated yet
        assert manager.should_start_new_season(base) is True
        
        # Mark season 1 as generated
        manager.task_generated_season = 1
        
        # Still in season 1
        assert manager.should_start_new_season(base + 1) is False
        
        # Moved to season 2
        assert manager.should_start_new_season(base + season_len) is True

    @pytest.mark.asyncio
    async def test_new_season_regenerates_tasks(self, tmp_path, monkeypatch):
        """Test that moving to a new season triggers task regeneration."""
        monkeypatch.setattr(SeasonManager, "TASKS_DIR", tmp_path)
        manager = SeasonManager()
        base = int(manager.minimum_start_block)
        season_len = int(manager.season_block_length)

        from autoppia_iwa.src.demo_webs.config import demo_web_projects
        from autoppia_iwa.src.data_generation.tasks.classes import Task
        project = demo_web_projects[0]
        
        with patch('autoppia_web_agents_subnet.validator.season_manager.generate_tasks') as mock_gen:
            mock_gen.return_value = [TaskWithProject(project=project, task=Task(url="https://example.com", prompt="p", tests=[]))]
            
            # Generate tasks for season 1
            await manager.get_season_tasks(base)
            assert mock_gen.call_count == 1
            
            # Move to season 2 - should regenerate
            await manager.get_season_tasks(base + season_len)
            assert mock_gen.call_count == 2

    def test_season_number_increments_correctly(self):
        """Test that season_number increments as blocks progress."""
        manager = SeasonManager()
        base = int(manager.minimum_start_block)
        season_len = int(manager.season_block_length)
        
        season1 = manager.get_season_number(base)
        season2 = manager.get_season_number(base + season_len)
        season3 = manager.get_season_number(base + 2 * season_len)
        
        assert season2 == season1 + 1
        assert season3 == season2 + 1


@pytest.mark.unit
class TestSeasonManagerInitialization:
    """Test SeasonManager initialization."""

    def test_initialization_sets_correct_defaults(self):
        """Test that SeasonManager initializes with correct default values."""
        manager = SeasonManager()
        
        assert manager.season_number is None
        assert manager.task_generated_season is None
        assert manager.season_tasks == []
        assert manager.BLOCKS_PER_EPOCH == 360

    def test_season_block_length_calculated_on_init(self):
        """Test that season_block_length is calculated during initialization."""
        manager = SeasonManager()
        
        expected = int(manager.BLOCKS_PER_EPOCH * manager.season_size_epochs)
        assert manager.season_block_length == expected
