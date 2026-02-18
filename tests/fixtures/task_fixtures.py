"""
Task fixtures for testing task generation and evaluation.

Provides fixtures for:
- Mock tasks
- Tasks with projects
- Season task collections
"""

import pytest
from typing import List
from autoppia_web_agents_subnet.validator.models import TaskWithProject


@pytest.fixture
def mock_task():
    """
    Create a single mock task using the IWA stub from conftest.
    """
    from autoppia_iwa.src.data_generation.tasks.classes import Task
    
    task = Task(
        url="https://example.com",
        prompt="Click the submit button",
        tests=[
            {"type": "element_exists", "selector": "#submit"},
            {"type": "url_matches", "pattern": "success"},
        ],
    )
    return task


@pytest.fixture
def mock_web_project():
    """
    Create a mock web project using the IWA stub from conftest.
    """
    from autoppia_iwa.src.demo_webs.classes import WebProject
    
    return WebProject(
        name="test_project",
        frontend_url="https://test-project.com",
    )


@pytest.fixture
def task_with_project(mock_task, mock_web_project) -> TaskWithProject:
    """
    Create a TaskWithProject instance for testing.
    """
    return TaskWithProject(
        project=mock_web_project,
        task=mock_task,
    )


@pytest.fixture
def season_tasks(mock_web_project) -> List[TaskWithProject]:
    """
    Create a collection of tasks for a season.
    
    Returns multiple tasks that would be generated for a season,
    useful for testing evaluation across multiple tasks.
    """
    from autoppia_iwa.src.data_generation.tasks.classes import Task
    
    tasks = []
    for i in range(5):
        task = Task(
            url=f"https://example.com/task{i}",
            prompt=f"Complete task {i}",
            tests=[
                {"type": "element_exists", "selector": f"#task{i}"},
            ],
        )
        tasks.append(TaskWithProject(project=mock_web_project, task=task))
    
    return tasks


@pytest.fixture
def complex_task():
    """
    Create a complex task with multiple test types.
    
    Useful for testing comprehensive evaluation scenarios.
    """
    from autoppia_iwa.src.data_generation.tasks.classes import Task
    
    return Task(
        url="https://complex-app.com",
        prompt="Complete the multi-step form and submit",
        tests=[
            {"type": "element_exists", "selector": "#name_field"},
            {"type": "element_exists", "selector": "#email_field"},
            {"type": "element_exists", "selector": "#submit_button"},
            {"type": "url_matches", "pattern": "confirmation"},
            {"type": "text_contains", "selector": "#message", "text": "Success"},
        ],
    )
