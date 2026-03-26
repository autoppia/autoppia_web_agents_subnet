from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from autoppia_web_agents_subnet import SUBNET_IWA_VERSION
from autoppia_web_agents_subnet.platform.mixin import ValidatorPlatformMixin
from autoppia_web_agents_subnet.validator import config as validator_config
from neurons.validator import Validator


def _bind_version_helpers(validator):
    validator._extract_round_numbers_from_round_id = ValidatorPlatformMixin._extract_round_numbers_from_round_id
    validator._current_round_numbers = ValidatorPlatformMixin._current_round_numbers.__get__(validator, type(validator))
    validator._artifact_context_metadata_path = Validator._artifact_context_metadata_path.__get__(validator, type(validator))
    validator._artifact_context_payload = Validator._artifact_context_payload.__get__(validator, type(validator))
    validator._load_saved_artifact_context = Validator._load_saved_artifact_context.__get__(validator, type(validator))
    validator._persist_artifact_context = Validator._persist_artifact_context.__get__(validator, type(validator))
    validator._normalize_artifact_context_mapping = Validator._normalize_artifact_context_mapping.__get__(validator, type(validator))
    validator._iter_artifact_context_candidates = Validator._iter_artifact_context_candidates.__get__(validator, type(validator))
    validator._infer_saved_artifact_context_from_existing_artifacts = Validator._infer_saved_artifact_context_from_existing_artifacts.__get__(validator, type(validator))
    validator._find_stale_artifact_context_against_current = Validator._find_stale_artifact_context_against_current.__get__(validator, type(validator))
    validator._clear_round_artifacts_preserving_tasks = Validator._clear_round_artifacts_preserving_tasks.__get__(validator, type(validator))
    validator._clear_all_artifacts_preserving_tasks = Validator._clear_all_artifacts_preserving_tasks.__get__(validator, type(validator))
    validator._clear_all_artifacts_including_tasks = Validator._clear_all_artifacts_including_tasks.__get__(validator, type(validator))
    validator._invalidate_round_artifacts_if_context_changed = Validator._invalidate_round_artifacts_if_context_changed.__get__(validator, type(validator))
    validator._winner_snapshot_from_post_consensus = Validator._winner_snapshot_from_post_consensus
    validator._resolve_loaded_round_leadership = Validator._resolve_loaded_round_leadership.__get__(validator, type(validator))
    validator._coerce_loaded_leader_after_snapshot = Validator._coerce_loaded_leader_after_snapshot.__get__(validator, type(validator))
    validator._load_competition_state = Validator._load_competition_state.__get__(validator, type(validator))
    validator._load_evaluated_commit_history = Validator._load_evaluated_commit_history.__get__(validator, type(validator))
    validator._version_major = Validator._version_major
    validator._version_tuple = Validator._version_tuple
    validator._evaluation_context_payload = ValidatorPlatformMixin._evaluation_context_payload.__get__(validator, type(validator))
    validator._is_same_evaluation_context = ValidatorPlatformMixin._is_same_evaluation_context.__get__(validator, type(validator))
    validator._find_reusable_commit_stats = ValidatorPlatformMixin._find_reusable_commit_stats.__get__(validator, type(validator))
    return validator


def _make_validator(tmp_path: Path, *, version: str):
    validator = SimpleNamespace()
    validator.version = version
    validator.current_round_id = "validator_round_1_1_test"
    validator.round_manager = SimpleNamespace(
        BLOCKS_PER_EPOCH=int(getattr(validator_config, "BLOCKS_PER_EPOCH", 360)),
        round_size_epochs=float(getattr(validator_config, "ROUND_SIZE_EPOCHS", 1.0)),
    )
    validator.season_manager = SimpleNamespace(
        season_number=1,
        season_size_epochs=float(getattr(validator_config, "SEASON_SIZE_EPOCHS", 0.0)),
    )
    validator._season_competition_history = {1: {"summary": {"current_winner_uid": 48}}}
    validator._evaluated_commits_by_miner = {
        48: {
            "https://github.com/example/miner|deadbeef": {
                "agent_run_id": "agent-run-48-old",
                "total_tasks": 100,
                "average_reward": 0.42,
                "average_score": 0.42,
                "average_execution_time": 22.0,
                "average_cost": 0.02,
                "success_tasks": 42,
                "evaluation_context": {},
            }
        }
    }
    validator._state_summary_root = lambda: tmp_path
    return _bind_version_helpers(validator)


def _write_saved_context(tmp_path: Path, *, version: str, minimum_start_block: int | None = None):
    if minimum_start_block is None:
        minimum_start_block = int(validator_config.MINIMUM_START_BLOCK)
    payload = {
        "round_size_epochs": float(getattr(validator_config, "ROUND_SIZE_EPOCHS", 1.0)),
        "season_size_epochs": float(getattr(validator_config, "SEASON_SIZE_EPOCHS", 0.0)),
        "blocks_per_epoch": int(getattr(validator_config, "BLOCKS_PER_EPOCH", 360)),
        "minimum_start_block": minimum_start_block,
        "minimum_validator_version": version,
    }
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["evaluation_context_hash"] = f"sha256:{__import__('hashlib').sha256(payload_json.encode('utf-8')).hexdigest()}"
    (tmp_path / "evaluation_context.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _seed_season_artifacts(tmp_path: Path):
    season_dir = tmp_path / "season_1"
    round_dir = season_dir / "round_1"
    round_dir.mkdir(parents=True, exist_ok=True)
    (season_dir / "tasks.json").write_text('{"tasks": [1, 2, 3]}', encoding="utf-8")
    legacy_tasks_dir = tmp_path / "season_tasks"
    legacy_tasks_dir.mkdir(parents=True, exist_ok=True)
    (legacy_tasks_dir / "season_1_tasks.json").write_text('{"tasks": [1, 2, 3]}', encoding="utf-8")
    (round_dir / "post_consensus.json").write_text('{"summary": "x"}', encoding="utf-8")
    (round_dir / "ipfs_uploaded.json").write_text('{"payload": "x"}', encoding="utf-8")


def _seed_season_artifacts_with_context(tmp_path: Path, *, version: str, minimum_start_block: int):
    season_dir = tmp_path / "season_1"
    round_dir = season_dir / "round_1"
    round_dir.mkdir(parents=True, exist_ok=True)
    (season_dir / "tasks.json").write_text('{"tasks": [1, 2, 3]}', encoding="utf-8")
    legacy_tasks_dir = tmp_path / "season_tasks"
    legacy_tasks_dir.mkdir(parents=True, exist_ok=True)
    (legacy_tasks_dir / "season_1_tasks.json").write_text('{"tasks": [1, 2, 3]}', encoding="utf-8")
    evaluation_context = {
        "blocks_per_epoch": int(getattr(validator_config, "BLOCKS_PER_EPOCH", 360)),
        "minimum_start_block": minimum_start_block,
        "minimum_validator_version": version,
        "round_size_epochs": float(getattr(validator_config, "ROUND_SIZE_EPOCHS", 1.0)),
        "season_size_epochs": float(getattr(validator_config, "SEASON_SIZE_EPOCHS", 0.0)),
    }
    context_json = json.dumps(evaluation_context, sort_keys=True, separators=(",", ":"))
    evaluation_context["evaluation_context_hash"] = f"sha256:{__import__('hashlib').sha256(context_json.encode('utf-8')).hexdigest()}"
    payload = {
        "payload": {
            "miners": [
                {
                    "best_run": {
                        "reward": 0.42,
                        "score": 0.42,
                        "time": 22.0,
                        "cost": 0.02,
                        "tasks_received": 100,
                        "tasks_success": 42,
                        "evaluation_context": evaluation_context,
                    }
                }
            ]
        }
    }
    (round_dir / "ipfs_uploaded.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (round_dir / "post_consensus.json").write_text('{"summary": "x"}', encoding="utf-8")


def _seed_rehydratable_artifacts(tmp_path: Path):
    season_dir = tmp_path / "season_1"
    round_dir = season_dir / "round_1"
    round_dir.mkdir(parents=True, exist_ok=True)
    (season_dir / "tasks.json").write_text('{"tasks": [1, 2, 3]}', encoding="utf-8")
    (tmp_path / "stray-root-state.json").write_text('{"stale": true}', encoding="utf-8")
    (round_dir / "post_consensus.json").write_text(
        json.dumps(
            {
                "summary": {
                    "leader_after_round": {"uid": 127, "reward": 0.0},
                    "percentage_to_dethrone": 5.0,
                },
                "miners": [
                    {
                        "uid": 48,
                        "best_run_consensus": {
                            "reward": 0.15,
                            "score": 0.15,
                            "time": 80.0,
                            "cost": 0.03,
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (round_dir / "ipfs_uploaded.json").write_text(
        json.dumps(
            {
                "payload": {
                    "miners": [
                        {
                            "uid": 48,
                            "best_run": {
                                "github_url": "https://github.com/example/miner/commit/deadbeef",
                                "normalized_repo": "https://github.com/example/miner",
                                "commit_sha": "deadbeef",
                                "tasks_received": 100,
                                "tasks_success": 42,
                                "reward": 0.42,
                                "score": 0.42,
                                "time": 22.0,
                                "cost": 0.02,
                                "evaluation_context": {},
                            },
                        }
                    ]
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _reusable_stats_for_current_context(validator):
    validator._evaluated_commits_by_miner.setdefault(48, {})["https://github.com/example/miner|deadbeef"] = {
        "agent_run_id": "agent-run-48-old",
        "total_tasks": 100,
        "average_reward": 0.42,
        "average_score": 0.42,
        "average_execution_time": 22.0,
        "average_cost": 0.02,
        "success_tasks": 42,
        "evaluation_context": validator._evaluation_context_payload(),
    }
    return validator._find_reusable_commit_stats(
        uid=48,
        github_url="https://github.com/example/miner/commit/deadbeef",
        normalized_repo="https://github.com/example/miner",
        commit_sha="deadbeef",
    )


def _assert_all_local_history_reset(validator, tmp_path: Path):
    assert not (tmp_path / "season_1").exists()
    assert validator._season_competition_history == {}
    assert validator._evaluated_commits_by_miner == {}


@pytest.mark.integration
def test_version_bump_major_clears_all_artifacts_and_forces_reevaluation(tmp_path):
    """
    Scenario:
    The validator restarts with a higher major version.

    What this test proves:
    - season tasks and round artifacts are both deleted
    - local competition state is reset
    - local evaluated-commit history is reset, so the same commit must be re-evaluated
    """
    validator = _make_validator(tmp_path, version="16.0.0")
    _seed_season_artifacts(tmp_path)
    _write_saved_context(tmp_path, version="15.9.0")

    validator._invalidate_round_artifacts_if_context_changed()

    _assert_all_local_history_reset(validator, tmp_path)
    persisted_context = json.loads((tmp_path / "evaluation_context.json").read_text(encoding="utf-8"))
    assert persisted_context["minimum_validator_version"] == "16.0.0"


@pytest.mark.integration
def test_version_bump_major_prevents_any_stale_state_from_rehydrating_after_restart(tmp_path):
    """
    Scenario:
    A validator had old season folders, uploaded payloads, post-consensus summaries,
    and stray root files on disk, then restarted with a higher major version.

    What this test proves:
    - a major bump removes every stale entry under the validator state root
    - only the fresh evaluation-context metadata is recreated afterward
    - reloading from disk cannot resurrect stale competition history or reusable commits
    """
    validator = _make_validator(tmp_path, version="16.0.0")
    _seed_rehydratable_artifacts(tmp_path)
    _write_saved_context(tmp_path, version="15.9.0")

    validator._invalidate_round_artifacts_if_context_changed()
    validator._load_competition_state()
    validator._load_evaluated_commit_history()

    remaining_entries = sorted(path.name for path in tmp_path.iterdir())
    assert remaining_entries == ["evaluation_context.json"]
    assert validator._season_competition_history == {}
    assert validator._evaluated_commits_by_miner == {}
    reusable = validator._find_reusable_commit_stats(
        uid=48,
        github_url="https://github.com/example/miner/commit/deadbeef",
        normalized_repo="https://github.com/example/miner",
        commit_sha="deadbeef",
    )
    assert reusable is None


@pytest.mark.integration
def test_version_bump_major_without_saved_metadata_still_clears_all_artifacts_from_ipfs_context(tmp_path):
    """
    Scenario:
    The validator state root has old season artifacts but no `evaluation_context.json`.
    The only remaining version/context signal lives inside historical IPFS payload artifacts.

    What this test proves:
    - a major bump still clears the whole validator state root
    - stale season tasks are not preserved accidentally just because the metadata file is missing
    """
    validator = _make_validator(tmp_path, version="18.0.0")
    _seed_season_artifacts_with_context(tmp_path, version="17.0.0", minimum_start_block=7740314)

    validator._invalidate_round_artifacts_if_context_changed()

    remaining_entries = sorted(path.name for path in tmp_path.iterdir())
    assert remaining_entries == ["evaluation_context.json"]
    persisted_context = json.loads((tmp_path / "evaluation_context.json").read_text(encoding="utf-8"))
    assert persisted_context["minimum_validator_version"] == "18.0.0"


@pytest.mark.integration
def test_version_bump_minor_without_saved_metadata_preserves_tasks_but_clears_round_artifacts_from_ipfs_context(tmp_path):
    """
    Scenario:
    The validator state root has old season artifacts but no `evaluation_context.json`.
    The prior version/context can only be recovered from the saved IPFS payload.

    What this test proves:
    - a non-major bump still applies the "preserve tasks, clear the rest" policy
    - missing metadata does not block cleanup anymore
    """
    validator = _make_validator(tmp_path, version="17.1.0")
    _seed_season_artifacts_with_context(tmp_path, version="17.0.0", minimum_start_block=7740314)

    validator._invalidate_round_artifacts_if_context_changed()

    assert (tmp_path / "season_1").exists()
    assert (tmp_path / "season_1" / "tasks.json").exists()
    assert (tmp_path / "season_tasks" / "season_1_tasks.json").exists()
    assert not (tmp_path / "season_1" / "round_1").exists()
    persisted_context = json.loads((tmp_path / "evaluation_context.json").read_text(encoding="utf-8"))
    assert persisted_context["minimum_validator_version"] == "17.1.0"


@pytest.mark.integration
def test_version_bump_minor_currently_also_clears_all_artifacts_and_forces_reevaluation(tmp_path):
    """
    Scenario:
    The validator restarts with a higher minor version.

    What this test proves:
    a non-major version bump preserves task inventories but still clears:
    - round artifacts
    - stale root metadata/state files
    - local commit history is reset
    - the same commit is not reusable and must be re-evaluated
    """
    validator = _make_validator(tmp_path, version="16.1.0")
    _seed_season_artifacts(tmp_path)
    _write_saved_context(tmp_path, version="16.0.0")

    validator._invalidate_round_artifacts_if_context_changed()

    assert (tmp_path / "season_1").exists()
    assert (tmp_path / "season_1" / "tasks.json").exists()
    assert (tmp_path / "season_tasks" / "season_1_tasks.json").exists()
    assert not (tmp_path / "season_1" / "round_1").exists()
    assert validator._season_competition_history == {}
    assert validator._evaluated_commits_by_miner == {}
    assert json.loads((tmp_path / "evaluation_context.json").read_text(encoding="utf-8"))["minimum_validator_version"] == "16.1.0"


@pytest.mark.integration
def test_version_bump_patch_currently_also_clears_all_artifacts_and_forces_reevaluation(tmp_path):
    """
    Scenario:
    The validator restarts with a higher patch version only.

    What this test proves:
    a patch bump follows the same non-major cleanup policy:
    - season tasks are preserved
    - round artifacts are deleted
    - the same commit is not reused
    """
    validator = _make_validator(tmp_path, version="16.0.1")
    _seed_season_artifacts(tmp_path)
    _write_saved_context(tmp_path, version="16.0.0")

    validator._invalidate_round_artifacts_if_context_changed()

    assert (tmp_path / "season_1").exists()
    assert (tmp_path / "season_1" / "tasks.json").exists()
    assert (tmp_path / "season_tasks" / "season_1_tasks.json").exists()
    assert not (tmp_path / "season_1" / "round_1").exists()
    assert validator._season_competition_history == {}
    assert validator._evaluated_commits_by_miner == {}
    assert json.loads((tmp_path / "evaluation_context.json").read_text(encoding="utf-8"))["minimum_validator_version"] == "16.0.1"


@pytest.mark.integration
def test_non_version_context_change_preserves_tasks_but_clears_round_artifacts_and_forces_reevaluation(tmp_path):
    """
    Scenario:
    The validator version is unchanged, but a real evaluation condition changes,
    for example `MINIMUM_START_BLOCK`.

    What this test proves:
    - season-level task files are preserved
    - round-level artifacts are cleared
    - local commit history is reset, so reuse is blocked across incompatible conditions
    """
    validator = _make_validator(tmp_path, version="16.0.0")
    _seed_season_artifacts(tmp_path)
    _write_saved_context(tmp_path, version="16.0.0", minimum_start_block=7736200)

    with patch("neurons.validator.validator_config.MINIMUM_START_BLOCK", 7736300):
        validator._invalidate_round_artifacts_if_context_changed()

    assert (tmp_path / "season_1").exists()
    assert (tmp_path / "season_1" / "tasks.json").exists()
    assert not (tmp_path / "season_1" / "round_1").exists()
    assert validator._season_competition_history == {}
    assert validator._evaluated_commits_by_miner == {}


@pytest.mark.integration
def test_same_version_and_same_context_keeps_artifacts_and_allows_reuse(tmp_path):
    """
    Scenario:
    The validator restarts without any version bump and without any evaluation-context change.

    What this test proves:
    - local artifacts are preserved
    - local commit history survives
    - the same repo+commit stays reusable and should not be re-evaluated
    """
    validator = _make_validator(tmp_path, version=SUBNET_IWA_VERSION)
    _seed_season_artifacts(tmp_path)
    _write_saved_context(tmp_path, version=SUBNET_IWA_VERSION)
    validator._evaluated_commits_by_miner[48]["https://github.com/example/miner|deadbeef"]["evaluation_context"] = validator._evaluation_context_payload()

    validator._invalidate_round_artifacts_if_context_changed()

    assert (tmp_path / "season_1").exists()
    assert (tmp_path / "season_1" / "tasks.json").exists()
    assert (tmp_path / "season_1" / "round_1").exists()
    reusable = validator._find_reusable_commit_stats(
        uid=48,
        github_url="https://github.com/example/miner/commit/deadbeef",
        normalized_repo="https://github.com/example/miner",
        commit_sha="deadbeef",
    )
    assert reusable is not None
    assert reusable["agent_run_id"] == "agent-run-48-old"


@pytest.mark.integration
def test_missing_saved_metadata_but_same_inferred_context_keeps_artifacts_and_reuse(tmp_path):
    """
    Scenario:
    The validator lost `evaluation_context.json`, but the existing IPFS payload on disk
    still matches the current runtime version and timing config.

    What this test proves:
    - the validator does not destroy reusable state just because the metadata file is missing
    - inferred context matching the current context keeps round artifacts and reuse intact
    """
    validator = _make_validator(tmp_path, version=SUBNET_IWA_VERSION)
    _seed_season_artifacts_with_context(
        tmp_path,
        version=SUBNET_IWA_VERSION,
        minimum_start_block=int(validator_config.MINIMUM_START_BLOCK),
    )
    validator._evaluated_commits_by_miner[48]["https://github.com/example/miner|deadbeef"]["evaluation_context"] = validator._evaluation_context_payload()

    validator._invalidate_round_artifacts_if_context_changed()

    assert (tmp_path / "season_1").exists()
    assert (tmp_path / "season_1" / "tasks.json").exists()
    assert (tmp_path / "season_1" / "round_1").exists()
    reusable = validator._find_reusable_commit_stats(
        uid=48,
        github_url="https://github.com/example/miner/commit/deadbeef",
        normalized_repo="https://github.com/example/miner",
        commit_sha="deadbeef",
    )
    assert reusable is not None


@pytest.mark.integration
def test_current_metadata_does_not_hide_stale_major_artifacts_on_disk(tmp_path):
    """
    Scenario:
    The validator already has a fresh `evaluation_context.json` for the current version,
    but historical season artifacts on disk still embed an older evaluation context.

    What this test proves:
    a stale artifact payload cannot survive just because the metadata file was already
    rewritten to the current version; the validator still forces a major-version cleanup.
    """
    validator = _make_validator(tmp_path, version="19.0.0")
    _seed_season_artifacts_with_context(tmp_path, version="16.0.0", minimum_start_block=7736300)
    _write_saved_context(tmp_path, version="19.0.0", minimum_start_block=7740451)

    validator._invalidate_round_artifacts_if_context_changed()

    remaining_entries = sorted(path.name for path in tmp_path.iterdir())
    assert remaining_entries == ["evaluation_context.json"]
    persisted_context = json.loads((tmp_path / "evaluation_context.json").read_text(encoding="utf-8"))
    assert persisted_context["minimum_validator_version"] == "19.0.0"
    assert persisted_context["minimum_start_block"] == int(validator_config.MINIMUM_START_BLOCK)


@pytest.mark.integration
def test_current_metadata_does_not_hide_stale_minor_artifacts_on_disk(tmp_path):
    """
    Scenario:
    The validator metadata file already matches the current minor version, but the
    saved round artifacts still come from the previous minor version/context.

    What this test proves:
    stale artifacts on disk still trigger the non-major cleanup policy:
    season tasks survive, but round/IPFS state is removed.
    """
    validator = _make_validator(tmp_path, version="19.1.0")
    _seed_season_artifacts_with_context(tmp_path, version="19.0.0", minimum_start_block=7740451)
    _write_saved_context(tmp_path, version="19.1.0", minimum_start_block=7740555)

    validator._invalidate_round_artifacts_if_context_changed()

    assert (tmp_path / "season_1").exists()
    assert (tmp_path / "season_1" / "tasks.json").exists()
    assert (tmp_path / "season_tasks" / "season_1_tasks.json").exists()
    assert not (tmp_path / "season_1" / "round_1").exists()
    persisted_context = json.loads((tmp_path / "evaluation_context.json").read_text(encoding="utf-8"))
    assert persisted_context["minimum_validator_version"] == "19.1.0"
    assert persisted_context["minimum_start_block"] == int(validator_config.MINIMUM_START_BLOCK)


@pytest.mark.integration
def test_load_competition_state_repairs_impossible_stale_leader_after_snapshot(tmp_path):
    """
    Scenario:
    A stale local `post_consensus.json` says `leader_after_round=127` with reward 0,
    even though the only real winner in the saved miner rows is miner 48.

    What this test proves:
    restart rehydration does not blindly trust that stale `leader_after_round`;
    it repairs the loaded season state so the winner comes from the real round data.
    """
    validator = _make_validator(tmp_path, version="16.0.0")
    season_dir = tmp_path / "season_1"
    round_dir = season_dir / "round_1"
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "post_consensus.json").write_text(
        json.dumps(
            {
                "summary": {
                    "leader_before_round": None,
                    "candidate_this_round": {"uid": 48, "reward": 0.1539},
                    "leader_after_round": {"uid": 127, "reward": 0.0},
                    "percentage_to_dethrone": 0.05,
                },
                "miners": [
                    {
                        "uid": 48,
                        "best_run_consensus": {"reward": 0.1539, "score": 0.15, "time": 80.0, "cost": 0.03},
                    },
                    {
                        "uid": 196,
                        "best_run_consensus": {"reward": 0.1533, "score": 0.15, "time": 81.0, "cost": 0.03},
                    },
                    {
                        "uid": 127,
                        "best_run_consensus": {"reward": 0.0, "score": 0.0, "time": 0.0, "cost": 0.0},
                    },
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    validator._load_competition_state()

    summary = validator._season_competition_history[1]["summary"]
    assert summary["current_winner_uid"] == 48
    assert summary["current_winner_reward"] == pytest.approx(0.1539)
    assert summary["current_winner_snapshot"]["uid"] == 48


@pytest.mark.integration
def test_load_competition_state_repairs_leader_chain_from_previous_round(tmp_path):
    """
    Scenario:
    Round 2 was persisted with a corrupted summary that inflated the reigning
    leader reward to the current-round consensus value and kept the wrong
    `leader_after_round`, even though the challenger should have dethroned.

    What this test proves:
    rehydration rebuilds the leader chain from the previous round winner plus
    the current round post-consensus miners, so the loaded current winner stays
    continuous across rounds.
    """
    validator = _make_validator(tmp_path, version="16.0.0")
    season_dir = tmp_path / "season_1"
    round_1_dir = season_dir / "round_1"
    round_2_dir = season_dir / "round_2"
    round_1_dir.mkdir(parents=True, exist_ok=True)
    round_2_dir.mkdir(parents=True, exist_ok=True)

    (round_1_dir / "post_consensus.json").write_text(
        json.dumps(
            {
                "summary": {
                    "leader_before_round": None,
                    "candidate_this_round": {"uid": 168, "reward": 0.17547999119965071},
                    "leader_after_round": {"uid": 168, "reward": 0.17547999119965071, "score": 0.28, "time": 86.99, "cost": 0.0034},
                    "percentage_to_dethrone": 0.05,
                    "dethroned": False,
                },
                "miners": [
                    {"uid": 168, "best_run_consensus": {"reward": 0.17547999119965071, "score": 0.28, "time": 86.99, "cost": 0.0034}},
                    {"uid": 196, "best_run_consensus": {"reward": 0.17522848947837152, "score": 0.28, "time": 90.80, "cost": 0.0025}},
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    (round_2_dir / "post_consensus.json").write_text(
        json.dumps(
            {
                "summary": {
                    "leader_before_round": {"uid": 168, "reward": 0.1849726186432933, "score": 0.08, "time": 80.71, "cost": 0.0020},
                    "candidate_this_round": {"uid": 196, "reward": 0.1907841665631254, "score": 0.13, "time": 117.16, "cost": 0.0028},
                    "leader_after_round": {"uid": 168, "reward": 0.1849726186432933, "score": 0.08, "time": 80.71, "cost": 0.0020},
                    "percentage_to_dethrone": 0.05,
                    "dethroned": False,
                },
                "miners": [
                    {"uid": 168, "best_run_consensus": {"reward": 0.1849726186432933, "score": 0.08, "time": 80.71, "cost": 0.0020}},
                    {"uid": 196, "best_run_consensus": {"reward": 0.1907841665631254, "score": 0.13078707785595142, "time": 117.16, "cost": 0.0028}},
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    validator._load_competition_state()

    summary = validator._season_competition_history[1]["summary"]
    assert summary["current_winner_uid"] == 196
    assert summary["current_winner_reward"] == pytest.approx(0.1907841665631254)

    repaired_round_2 = validator._season_competition_history[1]["rounds"][2]["post_consensus_json"]["summary"]
    assert repaired_round_2["leader_before_round"]["uid"] == 168
    assert repaired_round_2["leader_before_round"]["reward"] == pytest.approx(0.17547999119965071)
    assert repaired_round_2["dethroned"] is True
    assert repaired_round_2["leader_after_round"]["uid"] == 196
