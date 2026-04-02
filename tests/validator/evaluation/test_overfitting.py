import random
from types import SimpleNamespace

import pytest

from autoppia_web_agents_subnet.validator.evaluation.overfitting import (
    apply_overfit_penalty,
    build_overfit_checks,
)


@pytest.mark.unit
def test_build_overfit_checks_samples_seeded_tasks_and_changes_seed():
    tasks = [
        SimpleNamespace(task=SimpleNamespace(id="task-1", url="https://example.com/a?seed=11")),
        SimpleNamespace(task=SimpleNamespace(id="task-2", url="https://example.com/b?seed=22&x=1")),
        SimpleNamespace(task=SimpleNamespace(id="task-3", url="https://example.com/c")),
        SimpleNamespace(task=SimpleNamespace(id="task-4", url="https://example.com/d?seed=44")),
    ]

    checks = build_overfit_checks(tasks, round_rng=random.Random(123))

    assert set(checks) == {"task-1", "task-2", "task-4"}
    for base_task_id, check in checks.items():
        assert check.base_task_id == base_task_id
        assert check.alt_task.id.startswith(f"{base_task_id}__overfit_seed_")
        assert f"seed={check.alt_seed}" in check.alt_task.url
        original_url = next(t.task.url for t in tasks if t.task.id == base_task_id)
        assert check.alt_task.url != original_url


@pytest.mark.unit
def test_apply_overfit_penalty_only_when_diff_exceeds_threshold():
    reward, diff, penalized = apply_overfit_penalty(
        base_reward=1.0,
        alt_reward=0.8,
        diff_threshold=0.25,
        penalty=0.3,
    )
    assert reward == 1.0
    assert diff == pytest.approx(0.2)
    assert penalized is False

    reward, diff, penalized = apply_overfit_penalty(
        base_reward=1.0,
        alt_reward=0.2,
        diff_threshold=0.25,
        penalty=0.3,
    )
    assert reward == pytest.approx(0.7)
    assert diff == pytest.approx(0.8)
    assert penalized is True
