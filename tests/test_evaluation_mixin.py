import types
from types import SimpleNamespace

import numpy as np
import pytest

from autoppia_web_agents_subnet.validator.evaluation import mixin as evaluation_mixin
from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.round_manager import RoundManager


class DummyStateManager:
    def __init__(self):
        self.saved = 0

    def save_checkpoint(self, *_, **__):
        self.saved += 1


class DummyValidator(evaluation_mixin.EvaluationPhaseMixin):
    def __init__(self):
        self.version = "test"
        self.metagraph = SimpleNamespace(
            axons=[SimpleNamespace(uid=0)],
            hotkeys=["mock-hotkey"],
        )
        self.active_miner_uids = [0]
        self._completed_pairs = set()
        self._finalized_this_round = False
        self._consensus_published = False
        self._consensus_mid_fetched = False
        self._agg_scores_cache = None
        self.state_manager = DummyStateManager()
        self.dataset_collector = None
        self.block = 0
        self.round_manager = RoundManager(
            round_size_epochs=0.2,
            avg_task_duration_seconds=30,
            safety_buffer_epochs=0.02,
            minimum_start_block=0,
        )
        self.round_manager.start_new_round(0)
        self.round_manager.enter_phase(
            phase=self.round_manager.current_phase,
            block=0,
        )
        self.current_round_tasks = {}
        self.current_round_id = "round-1"
        self.agent_run_accumulators = {}
        self.current_agent_runs = {}
        self.current_miner_snapshots = {}
        self._phases = {"handshake_sent": True}

    async def _publish_final_snapshot(self, *_, **__):
        self._consensus_published = True

    async def _calculate_final_weights(self, *_, **__):
        self._finalized_this_round = True

    async def _iwap_submit_task_results(self, *_, **__):
        return True


def _build_task(sequence: int) -> TaskWithProject:
    project = SimpleNamespace(frontend_url="https://demo", name="demo")
    task = SimpleNamespace(
        id=f"task-{sequence}",
        prompt=f"prompt-{sequence}",
        tests=[],
        _seed_value=sequence,
    )
    return TaskWithProject(project=project, task=task)


@pytest.mark.asyncio
async def test_run_task_phase(monkeypatch):
    validator = DummyValidator()
    all_tasks = [_build_task(0), _build_task(1)]

    async def fake_send_task_synapse_to_miners(*_, **__):
        return [SimpleNamespace()]

    def fake_collect(task, responses, miner_uids):
        solution = SimpleNamespace(
            actions=[SimpleNamespace(type="click", selector=None, text="Hello")]
        )
        return [solution], [1.23]

    async def fake_evaluate(*_, **__):
        scores = np.array([0.9], dtype=np.float32)
        test_results = [[{"success": True}]]
        eval_results = [{"final_score": 0.9}]
        return scores, test_results, eval_results

    def fake_calc_rewards(*_, **__):
        return np.array([0.8], dtype=np.float32)

    async def fake_feedback(*_, **__):
        return None

    monkeypatch.setattr(
        evaluation_mixin,
        "send_task_synapse_to_miners",
        fake_send_task_synapse_to_miners,
    )
    monkeypatch.setattr(
        evaluation_mixin,
        "collect_task_solutions_and_execution_times",
        fake_collect,
    )
    monkeypatch.setattr(
        evaluation_mixin,
        "evaluate_task_solutions",
        fake_evaluate,
    )
    monkeypatch.setattr(
        evaluation_mixin,
        "calculate_rewards_for_task",
        fake_calc_rewards,
    )
    monkeypatch.setattr(
        evaluation_mixin,
        "send_feedback_synapse_to_miners",
        fake_feedback,
    )

    result = await validator._run_task_phase(all_tasks)

    assert result.tasks_completed == 2
    assert validator.state_manager.saved >= 2
    assert (0, "task-0") in validator._completed_pairs
    assert validator.round_manager.round_rewards[0][0] == pytest.approx(0.8, rel=1e-6)
