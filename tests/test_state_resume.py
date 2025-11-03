from pathlib import Path
from types import SimpleNamespace

import pytest

from autoppia_web_agents_subnet.validator.round_state.state_manager import RoundStateManager


class StubValidator:
    def __init__(self):
        self.wallet = SimpleNamespace(hotkey=SimpleNamespace(ss58_address="5TestHotkey"))
        self.metagraph = SimpleNamespace(
            hotkeys=["hk0", "hk1"],
            axons=[SimpleNamespace(), SimpleNamespace()],
        )
        self.current_round_id = "round-test"
        self.round_start_timestamp = 123.0
        self.active_miner_uids = [0, 1]
        self.round_handshake_payloads = {}
        self._all_tasks_cache = []
        self.current_round_tasks = {}
        self.current_agent_runs = {}
        self.current_miner_snapshots = {}
        self.agent_run_accumulators = {}
        self._completed_pairs = set()
        self._eval_records = []
        self._phases = {"handshake_sent": True}
        self.round_manager = SimpleNamespace(
            start_block=10,
            round_rewards={0: [1.0]},
            round_eval_scores={0: [0.9]},
            round_times={0: [1.2]},
            final_round_rewards={},
            final_round_eval_scores={},
            final_round_times={},
            round_duplicate_counts={},
        )
        self._consensus_published = False
        self._consensus_mid_fetched = False
        self._agg_scores_cache = {}
        self._last_round_winner_uid = None
        self._final_started = False
        self._final_top_s_uids = []
        self._final_endpoints = {}
        self.dataset_collector = None


@pytest.mark.parametrize("overwrite", [False, True])
def test_round_state_save_and_load(tmp_path: Path, monkeypatch, overwrite: bool):
    monkeypatch.setenv("IWA_STATE_DIR", str(tmp_path))

    validator = StubValidator()
    manager = RoundStateManager(validator)

    validator._all_tasks_cache = ["task-1"]
    validator.current_round_tasks = {"task-1": SimpleNamespace(sequence=0)}
    validator.current_agent_runs = {0: SimpleNamespace(total_reward=1.0)}
    validator._completed_pairs = {(0, "task-1")}
    validator._eval_records = [{"miner_uid": 0, "reward": 1.0, "final_score": 0.9, "exec_time": 1.2}]
    validator._agg_scores_cache = {0: 0.5}
    validator._final_started = True
    validator._final_top_s_uids = [0]
    validator._final_endpoints = {0: "http://localhost"}

    manager.save_checkpoint(tasks=None)

    if overwrite:
        # Save again with new data to ensure overwrite works
        validator._eval_records.append({"miner_uid": 1, "reward": 0.5, "final_score": 0.4, "exec_time": 2.0})
        manager.save_checkpoint(tasks=None)

    new_validator = StubValidator()
    new_manager = RoundStateManager(new_validator)
    ckpt = new_manager.load_checkpoint()

    assert ckpt is not None
    assert new_validator._completed_pairs  # restored
    assert new_validator._eval_records
    assert new_validator._final_started is True
    assert new_validator._final_top_s_uids == [0]
    assert new_validator._final_endpoints[0] == "http://localhost"
