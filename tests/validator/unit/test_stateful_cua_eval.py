import types
from urllib.parse import parse_qs, urlsplit

import pytest


@pytest.mark.unit
def test_augment_demo_web_url_preserves_seed_and_sets_ids():
    from autoppia_web_agents_subnet.validator.evaluation.stateful_cua_eval import _augment_demo_web_url

    out = _augment_demo_web_url(
        "https://example.com/path?seed=7",
        web_agent_id="123",
        validator_id="validator-test",
    )
    qs = parse_qs(urlsplit(out).query)

    assert qs["seed"] == ["7"]
    assert qs["X-WebAgent-Id"] == ["123"]
    assert qs["web_agent_id"] == ["123"]
    assert qs["X-Validator-Id"] == ["validator-test"]
    assert qs["validator_id"] == ["validator-test"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_with_stateful_cua_does_not_mutate_task_url(monkeypatch):
    # Ensure deterministic validator id selection.
    monkeypatch.setenv("VALIDATOR_ID", "validator-test")

    from autoppia_iwa.src.data_generation.tasks.classes import Task
    import autoppia_web_agents_subnet.validator.evaluation.stateful_cua_eval as module

    captured: dict[str, object] = {}

    class CapturingEvaluator:
        def __init__(self, *, task, web_agent_id: str, **_):  # noqa: ANN001
            captured["task"] = task
            captured["web_agent_id"] = web_agent_id

        async def reset(self):
            return types.SimpleNamespace(
                score=types.SimpleNamespace(raw_score=0.0, success=False),
                snapshot=types.SimpleNamespace(html="", url=""),
            )

        async def step(self, _action):  # noqa: ANN001
            return types.SimpleNamespace(
                score=types.SimpleNamespace(raw_score=1.0, success=True),
                snapshot=types.SimpleNamespace(html="", url=""),
            )

        async def close(self):
            return None

        @property
        def history(self):  # noqa: D401
            """Expose an empty history list for solution reconstruction."""
            return []

    class DummyAgent:
        def __init__(self, *_, **__):
            pass

        async def act(self, *_, **__):
            return [object()]

    monkeypatch.setattr(module, "AsyncStatefulEvaluator", CapturingEvaluator)
    monkeypatch.setattr(module, "ApifiedWebCUA", DummyAgent)

    original_url = "https://example.com/path?seed=7"
    task = Task(url=original_url, prompt="p", tests=[])

    score, _elapsed, _solution = await module.evaluate_with_stateful_cua(task=task, uid=123, base_url="http://agent")
    assert score == 1.0
    assert task.url == original_url

    augmented_url = str(getattr(captured.get("task"), "url", ""))
    qs = parse_qs(urlsplit(augmented_url).query)
    assert qs["seed"] == ["7"]
    assert qs["web_agent_id"] == ["123"]
    assert qs["validator_id"] == ["validator-test"]

