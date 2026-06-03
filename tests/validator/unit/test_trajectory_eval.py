import asyncio
import types

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_trajectory_calls_find_trayectory_endpoint_and_concurrent_evaluator(monkeypatch):
    from autoppia_iwa.src.data_generation.tasks.classes import Task
    from autoppia_iwa.src.demo_webs.classes import WebProject
    from autoppia_iwa.src.web_agents.classes import TaskSolution

    import autoppia_web_agents_subnet.validator.evaluation.trajectory_eval as module

    captured = {}

    class DummyTrajectoryClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def find_trayectory(self, task):
            captured["find_trayectory_task"] = task
            return TaskSolution(task_id=task.id, actions=[types.SimpleNamespace(type="ClickAction")], web_agent_id="miner-response")

    class DummyEvaluator:
        def __init__(self, *, web_project, config):
            captured["web_project"] = web_project
            captured["config"] = config

        async def evaluate_single_task_solution(self, task, solution):
            captured["evaluated_task"] = task
            captured["solution"] = solution
            return types.SimpleNamespace(raw_score=1.0, final_score=1.0, execution_history=["executed"], gif_recording="")

    monkeypatch.setattr(module, "ApifiedHarvester", DummyTrajectoryClient)
    monkeypatch.setattr(module, "ConcurrentEvaluator", DummyEvaluator)

    task = Task(url="https://example.com", prompt="p")
    project = WebProject(name="demo")

    score, elapsed, solution = await module.evaluate_trajectory(
        task=task,
        project=project,
        uid=42,
        base_url="http://miner",
        max_tools=10,
    )

    assert score == 1.0
    assert elapsed >= 0.0
    assert solution.web_agent_id == "42"
    assert solution.recording == {"execution_history": ["executed"]}
    assert captured["client_kwargs"]["base_url"] == "http://miner"
    assert captured["client_kwargs"]["endpoint_path"] == "/find_trayectory"
    assert captured["web_project"] is project
    assert captured["solution"] is solution
    assert captured["config"].browser_timeout == max(float(module.TRAJECTORY_ACTION_TIMEOUT_SECONDS) * 1000.0, 1000.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_trajectory_truncates_tools(monkeypatch):
    from autoppia_iwa.src.data_generation.tasks.classes import Task
    from autoppia_iwa.src.demo_webs.classes import WebProject
    from autoppia_iwa.src.web_agents.classes import TaskSolution

    import autoppia_web_agents_subnet.validator.evaluation.trajectory_eval as module

    captured = {}

    class DummyTrajectoryClient:
        def __init__(self, **_):
            pass

        async def find_trayectory(self, task):
            tools = [types.SimpleNamespace(type=f"Tool{i}") for i in range(5)]
            return TaskSolution(task_id=task.id, actions=tools, web_agent_id="miner-response")

    class DummyEvaluator:
        def __init__(self, **_):
            pass

        async def evaluate_single_task_solution(self, _task, solution):
            captured["tool_count"] = len(solution.actions)
            return types.SimpleNamespace(raw_score=0.5, final_score=0.5, execution_history=[], gif_recording="")

    monkeypatch.setattr(module, "ApifiedHarvester", DummyTrajectoryClient)
    monkeypatch.setattr(module, "ConcurrentEvaluator", DummyEvaluator)

    score, _elapsed, solution = await module.evaluate_trajectory(
        task=Task(url="https://example.com", prompt="p"),
        project=WebProject(name="demo"),
        uid=42,
        base_url="http://miner",
        max_tools=2,
    )

    assert score == 0.5
    assert len(solution.actions) == 2
    assert captured["tool_count"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_trajectory_times_out_replay_independently(monkeypatch):
    from autoppia_iwa.src.data_generation.tasks.classes import Task
    from autoppia_iwa.src.demo_webs.classes import WebProject
    from autoppia_iwa.src.web_agents.classes import TaskSolution

    import autoppia_web_agents_subnet.validator.evaluation.trajectory_eval as module

    class DummyTrajectoryClient:
        def __init__(self, **_):
            pass

        async def find_trayectory(self, task):
            return TaskSolution(task_id=task.id, actions=[types.SimpleNamespace(type="ClickAction")], web_agent_id="miner-response")

    class SlowEvaluator:
        def __init__(self, **_):
            pass

        async def evaluate_single_task_solution(self, _task, _solution):
            await asyncio.sleep(1.0)
            return types.SimpleNamespace(raw_score=1.0, final_score=1.0, execution_history=[], gif_recording="")

    monkeypatch.setattr(module, "ApifiedHarvester", DummyTrajectoryClient)
    monkeypatch.setattr(module, "ConcurrentEvaluator", SlowEvaluator)
    monkeypatch.setattr(module, "TASK_TIMEOUT_SECONDS", 10.0)
    monkeypatch.setattr(module, "TRAJECTORY_REPLAY_TIMEOUT_SECONDS", 0.01)

    score, elapsed, solution = await module.evaluate_trajectory(
        task=Task(url="https://example.com", prompt="p"),
        project=WebProject(name="demo"),
        uid=42,
        base_url="http://miner",
        max_tools=10,
    )

    assert score == 0.0
    assert elapsed < 1.0
    assert len(solution.actions) == 1
