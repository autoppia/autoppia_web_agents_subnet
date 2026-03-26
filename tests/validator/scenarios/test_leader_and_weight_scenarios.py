from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from autoppia_web_agents_subnet.platform.utils.round_flow import _normalize_post_consensus_leadership_summary
from autoppia_web_agents_subnet.validator.settlement.consensus import _build_local_round_summary


def _stats_entry(*, score: float, time_s: float, cost: float) -> dict:
    return {
        "avg_eval_score": score,
        "avg_eval_time": time_s,
        "avg_cost": cost,
    }


def _consensus_miner(*, uid: int, reward: float, score: float, time_s: float, cost: float) -> dict:
    return {
        "uid": uid,
        "best_run": {
            "reward": reward,
            "score": score,
            "time": time_s,
            "cost": cost,
            "tasks_received": 100,
            "tasks_success": int(reward * 100),
        },
    }


@pytest.mark.integration
def test_local_round_summary_first_round_has_no_candidate_and_picks_top_miner():
    """
    Scenario:
    First round of a season. There is no reigning leader yet.

    What this test proves:
    - the top reward miner becomes `leader_after_round`
    - `leader_before_round` is null
    - `candidate_this_round` is null, so we do not incorrectly duplicate the leader as its own challenger
    """
    validator = SimpleNamespace(
        _season_competition_history={},
    )

    summary = _build_local_round_summary(
        validator,
        season_number=1,
        round_number=1,
        miners_payload=[
            _consensus_miner(uid=48, reward=0.20, score=0.20, time_s=20.0, cost=0.02),
            _consensus_miner(uid=127, reward=0.50, score=0.50, time_s=10.0, cost=0.01),
            _consensus_miner(uid=196, reward=0.40, score=0.40, time_s=15.0, cost=0.015),
        ],
    )

    assert summary["leader_before_round"] is None
    assert summary["candidate_this_round"] is None
    assert summary["leader_after_round"]["uid"] == 127
    assert summary["leader_after_round"]["reward"] == pytest.approx(0.50)


def _setup_settlement_validator(dummy_validator):
    from tests.conftest import _bind_settlement_mixin

    validator = _bind_settlement_mixin(dummy_validator)
    validator.season_manager.season_number = 1
    validator.round_manager.round_number = 1
    validator.metagraph.n = 300
    validator.metagraph.hotkeys = [f"hotkey{i}" for i in range(300)]
    validator.metagraph.stake = [15000.0] * 300
    validator.metagraph.S = [15000.0] * 300
    validator.eligibility_status_by_uid = {48: "evaluated", 127: "evaluated", 196: "evaluated"}
    validator._agg_meta_cache = {
        "stats_by_miner": {
            48: _stats_entry(score=0.20, time_s=20.0, cost=0.02),
            127: _stats_entry(score=0.50, time_s=10.0, cost=0.01),
            196: _stats_entry(score=0.40, time_s=15.0, cost=0.015),
        }
    }
    validator._finish_iwap_round = AsyncMock(return_value=True)
    validator.current_agent_runs = {}
    return validator


@pytest.mark.integration
@pytest.mark.asyncio
async def test_settlement_first_round_leader_is_highest_post_consensus_reward_and_gets_weight(dummy_validator):
    """
    Scenario:
    First season round with three eligible miners and no reigning leader.

    What this test proves:
    - the miner with the highest post-consensus reward becomes season leader
    - the season summary stores no candidate for round 1
    - the winner gets the non-burn weight
    """
    validator = _setup_settlement_validator(dummy_validator)

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"),
        patch("autoppia_web_agents_subnet.validator.settlement.mixin.BURN_AMOUNT_PERCENTAGE", 0.925),
    ):
        await validator._calculate_final_weights(consensus_rewards={48: 0.20, 127: 0.50, 196: 0.40})

    rewards = validator.update_scores.call_args.kwargs["rewards"]
    assert float(rewards[127]) == pytest.approx(0.075, abs=1e-6)
    assert float(rewards[5]) == pytest.approx(0.925, abs=1e-6)

    summary = validator._season_competition_history[1]["rounds"][1]["post_consensus_json"]["summary"]
    assert summary["leader_before_round"] is None
    assert summary["candidate_this_round"] is None
    assert summary["leader_after_round"]["uid"] == 127
    assert summary["leader_after_round"]["weight"] == pytest.approx(0.075, abs=1e-6)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_settlement_keeps_reigning_leader_when_candidate_has_less_reward(dummy_validator):
    """
    Scenario:
    The reigning leader comes into the next round with the best season reward.
    The best challenger in the round is worse.

    What this test proves:
    - `candidate_this_round` is the best challenger, not the reigning leader
    - no dethrone happens
    - `leader_after_round` stays on the reigning leader
    """
    validator = _setup_settlement_validator(dummy_validator)

    with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
        await validator._calculate_final_weights(consensus_rewards={48: 0.90, 127: 0.80})
        validator.round_manager.round_number = 2
        validator._agg_meta_cache = {
            "stats_by_miner": {
                48: _stats_entry(score=0.10, time_s=30.0, cost=0.03),
                127: _stats_entry(score=0.89, time_s=8.0, cost=0.01),
            }
        }
        await validator._calculate_final_weights(consensus_rewards={48: 0.10, 127: 0.89})

    summary = validator._season_competition_history[1]["rounds"][2]["post_consensus_json"]["summary"]
    assert summary["dethroned"] is False
    assert summary["leader_before_round"]["uid"] == 48
    assert summary["candidate_this_round"]["uid"] == 127
    assert summary["candidate_this_round"]["uid"] != summary["leader_before_round"]["uid"]
    assert summary["leader_after_round"]["uid"] == 48


@pytest.mark.integration
@pytest.mark.asyncio
async def test_settlement_does_not_dethrone_when_candidate_improves_but_not_enough(dummy_validator):
    """
    Scenario:
    The challenger beats the reigning leader in the current round,
    but does not beat the reigning season-best by the required 5%.

    What this test proves:
    - a better current-round score is still not enough by itself
    - dethrone only happens when the threshold is exceeded
    """
    validator = _setup_settlement_validator(dummy_validator)

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"),
        patch("autoppia_web_agents_subnet.validator.settlement.mixin.validator_config.LAST_WINNER_BONUS_PCT", 0.05),
    ):
        await validator._calculate_final_weights(consensus_rewards={48: 0.90, 127: 0.82})
        validator.round_manager.round_number = 2
        validator._agg_meta_cache = {
            "stats_by_miner": {
                48: _stats_entry(score=0.70, time_s=20.0, cost=0.02),
                127: _stats_entry(score=0.93, time_s=9.0, cost=0.01),
            }
        }
        await validator._calculate_final_weights(consensus_rewards={48: 0.70, 127: 0.93})

    summary = validator._season_competition_history[1]["rounds"][2]["post_consensus_json"]["summary"]
    assert summary["dethroned"] is False
    assert summary["leader_before_round"]["uid"] == 48
    assert summary["candidate_this_round"]["uid"] == 127
    assert summary["leader_after_round"]["uid"] == 48


@pytest.mark.integration
@pytest.mark.asyncio
async def test_settlement_dethrones_when_candidate_beats_required_percentage(dummy_validator):
    """
    Scenario:
    The challenger exceeds the reigning season-best by more than the required 5%.

    What this test proves:
    - dethrone happens
    - the challenger becomes `leader_after_round`
    - the final winner weight moves to that miner
    """
    validator = _setup_settlement_validator(dummy_validator)

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"),
        patch("autoppia_web_agents_subnet.validator.settlement.mixin.validator_config.LAST_WINNER_BONUS_PCT", 0.05),
        patch("autoppia_web_agents_subnet.validator.settlement.mixin.BURN_AMOUNT_PERCENTAGE", 0.80),
    ):
        await validator._calculate_final_weights(consensus_rewards={48: 0.90, 127: 0.82})
        validator.round_manager.round_number = 2
        validator._agg_meta_cache = {
            "stats_by_miner": {
                48: _stats_entry(score=0.70, time_s=20.0, cost=0.02),
                127: _stats_entry(score=0.96, time_s=9.0, cost=0.01),
            }
        }
        await validator._calculate_final_weights(consensus_rewards={48: 0.70, 127: 0.96})

    summary = validator._season_competition_history[1]["rounds"][2]["post_consensus_json"]["summary"]
    assert summary["dethroned"] is True
    assert summary["leader_before_round"]["uid"] == 48
    assert summary["candidate_this_round"]["uid"] == 127
    assert summary["leader_after_round"]["uid"] == 127
    assert summary["leader_after_round"]["weight"] == pytest.approx(0.20, abs=1e-6)

    rewards = validator.update_scores.call_args.kwargs["rewards"]
    assert float(rewards[127]) == pytest.approx(0.20, abs=1e-6)
    assert float(rewards[5]) == pytest.approx(0.80, abs=1e-6)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_settlement_uses_previous_round_leader_snapshot_for_dethrone_threshold(dummy_validator):
    """
    Scenario:
    The previous round ended with miner 48 at 0.17548, but the aggregated
    summary state was later contaminated with an inflated current_winner_reward.

    What this test proves:
    settlement must use the previous round `leader_after_round` snapshot as the
    reigning baseline for the next round, instead of the mutable season summary.
    """
    validator = _setup_settlement_validator(dummy_validator)

    with (
        patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"),
        patch("autoppia_web_agents_subnet.validator.settlement.mixin.validator_config.LAST_WINNER_BONUS_PCT", 0.05),
    ):
        await validator._calculate_final_weights(consensus_rewards={48: 0.17547999119965071, 127: 0.17522848947837152})
        validator.round_manager.round_number = 2
        validator._agg_meta_cache = {
            "stats_by_miner": {
                48: _stats_entry(score=0.08, time_s=80.71, cost=0.0020),
                127: _stats_entry(score=0.13078707785595142, time_s=117.16, cost=0.0028),
            }
        }
        season_summary = validator._season_competition_history[1]["summary"]
        season_summary["current_winner_uid"] = 48
        season_summary["current_winner_reward"] = 0.1849726186432933
        season_summary["current_winner_snapshot"] = {
            "uid": 48,
            "reward": 0.1849726186432933,
            "score": 0.08,
            "time": 80.71,
            "cost": 0.0020,
        }
        await validator._calculate_final_weights(consensus_rewards={48: 0.1849726186432933, 127: 0.1907841665631254})

    round_entry = validator._season_competition_history[1]["rounds"][2]
    summary = round_entry["post_consensus_json"]["summary"]
    assert summary["leader_before_round"]["uid"] == 48
    assert summary["leader_before_round"]["reward"] == pytest.approx(0.17547999119965071)
    assert round_entry["decision"]["required_reward_to_dethrone"] == pytest.approx(0.17547999119965071 * 1.05)
    assert summary["candidate_this_round"]["uid"] == 127
    assert summary["candidate_this_round"]["reward"] == pytest.approx(0.1907841665631254)
    assert summary["dethroned"] is True
    assert summary["leader_after_round"]["uid"] == 127


@pytest.mark.integration
@pytest.mark.asyncio
async def test_settlement_single_eligible_reigning_leader_has_no_candidate(dummy_validator):
    """
    Scenario:
    The reigning leader is the only eligible miner this round.

    What this test proves:
    - `candidate_this_round` stays null
    - the validator does not invent a fake challenger
    """
    validator = _setup_settlement_validator(dummy_validator)

    with patch("autoppia_web_agents_subnet.validator.settlement.mixin.render_round_summary_table"):
        await validator._calculate_final_weights(consensus_rewards={48: 0.90, 127: 0.80})
        validator.round_manager.round_number = 2
        validator.eligibility_status_by_uid = {48: "evaluated"}
        validator._agg_meta_cache = {
            "stats_by_miner": {
                48: _stats_entry(score=0.50, time_s=18.0, cost=0.02),
            }
        }
        await validator._calculate_final_weights(consensus_rewards={48: 0.50, 127: 0.0})

    summary = validator._season_competition_history[1]["rounds"][2]["post_consensus_json"]["summary"]
    assert summary["leader_before_round"]["uid"] == 48
    assert summary["candidate_this_round"] is None
    assert summary["leader_after_round"]["uid"] == 48


def test_post_consensus_normalization_preserves_leader_before_chain_and_allows_dethrone():
    """
    Scenario:
    The previous round ended with miner 168 at 0.17548. In the current round,
    miner 168 improves to 0.18497 and miner 196 reaches 0.19078.

    What this test proves:
    - `leader_before_round` must stay anchored to the previous round reward
    - the dethrone threshold must be computed from that previous reward
    - the current-round incumbent improvement must not inflate the threshold
    """
    summary = {
        "round": 2,
        "season": 1,
        "percentage_to_dethrone": 0.05,
        "leader_before_round": {"uid": 168, "reward": 0.17547999119965071, "score": 0.28, "time": 86.99, "cost": 0.0034},
        "candidate_this_round": {"uid": 196, "reward": 0.1907841665631254, "score": 0.13, "time": 117.16, "cost": 0.0028},
        "leader_after_round": {"uid": 196, "reward": 0.1907841665631254, "score": 0.13, "time": 117.16, "cost": 0.0028},
        "dethroned": True,
    }
    best_run_by_uid = {
        168: {"reward": 0.1849726186432933, "score": 0.08, "time": 80.71, "cost": 0.0020},
        196: {"reward": 0.1907841665631254, "score": 0.13078707785595142, "time": 117.16, "cost": 0.0028},
    }

    normalized = _normalize_post_consensus_leadership_summary(
        summary,
        best_run_by_uid=best_run_by_uid,
    )

    assert normalized["leader_before_round"]["uid"] == 168
    assert normalized["leader_before_round"]["reward"] == pytest.approx(0.17547999119965071)
    assert normalized["required_reward_to_dethrone"] == pytest.approx(0.17547999119965071 * 1.05)
    assert normalized["candidate_this_round"]["uid"] == 196
    assert normalized["candidate_this_round"]["reward"] == pytest.approx(0.1907841665631254)
    assert normalized["dethroned"] is True
    assert normalized["leader_after_round"]["uid"] == 196
