from __future__ import annotations

import json
from datetime import datetime
import time
import queue
import os
from pathlib import Path
import bittensor as bt

from autoppia_web_agents_subnet import SUBNET_IWA_VERSION

from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.bittensor_config import config
from autoppia_web_agents_subnet.validator.config import (
    ROUND_SIZE_EPOCHS,
)
from autoppia_web_agents_subnet.validator.round_manager import RoundManager, RoundPhase
from autoppia_web_agents_subnet.validator.season_manager import SeasonManager
from autoppia_web_agents_subnet.validator.round_start.mixin import ValidatorRoundStartMixin
from autoppia_web_agents_subnet.validator.round_start.types import RoundStartResult
from autoppia_web_agents_subnet.validator.evaluation.mixin import ValidatorEvaluationMixin
from autoppia_web_agents_subnet.validator.settlement.mixin import ValidatorSettlementMixin
from autoppia_web_agents_subnet.platform.validator_mixin import ValidatorPlatformMixin

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_web_agents_subnet.opensource.sandbox_manager import SandboxManager
from autoppia_web_agents_subnet.validator.models import AgentInfo


class Validator(
    ValidatorRoundStartMixin,
    ValidatorEvaluationMixin,
    ValidatorSettlementMixin,
    ValidatorPlatformMixin,
    BaseValidatorNeuron,
):
    def __init__(self, config=None):
        super().__init__(config=config)

        self.version: str = SUBNET_IWA_VERSION

        self.agents_queue: queue.Queue[AgentInfo] = queue.Queue()
        self.agents_dict: dict[int, AgentInfo] = {}
        self.agents_on_first_handshake: list[int] = []
        self.should_update_weights: bool = False
        self._season_repo_owners: dict[str, set[str]] = {}
        self._season_competition_history: dict[int, dict] = {}

        try:
            self.sandbox_manager = SandboxManager()
            self.sandbox_manager.deploy_gateway()
        except Exception as e:
            import sys

            bt.logging.error(f"Sandbox manager failed to initialize/deploy gateway: {e}")
            sys.exit(1)

        # Season manager for task generation
        self.season_manager = SeasonManager()
        try:
            self.season_manager.TASKS_DIR = self._state_summary_root()
            self.season_manager.TASKS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Round manager for round timing and boundaries
        self.round_manager = RoundManager()

        bt.logging.info("load_state()")
        self.load_state()

    def _competition_state_path(self) -> Path:
        """Path where season competition state is persisted."""
        try:
            full_path = Path(str(self.config.neuron.full_path))
        except Exception:
            full_path = Path(".")
        full_path.mkdir(parents=True, exist_ok=True)
        return full_path / "season_competition_state.json"

    def _state_summary_root(self) -> Path:
        """Root path for per-round summary snapshots."""
        root = os.getenv("IWAP_BACKUP_DIR")
        if root:
            base = Path(root)
        else:
            try:
                base = Path(self.config.neuron.full_path).parent.parent
            except Exception:
                base = Path(".")
            base = base / "data"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _save_competition_state(self) -> None:
        """Persist season winner/history state to JSON (best-effort)."""
        state = getattr(self, "_season_competition_history", None)
        if not isinstance(state, dict):
            return

        serialized: dict[str, dict] = {}
        for season, season_data in state.items():
            try:
                season_i = int(season)
            except Exception:
                continue
            if not isinstance(season_data, dict):
                continue

            rounds_out: dict[str, dict] = {}
            rounds_in = season_data.get("rounds", {})
            if isinstance(rounds_in, dict):
                for round_key, round_data in rounds_in.items():
                    try:
                        round_i = int(round_key)
                    except Exception:
                        continue
                    if not isinstance(round_data, dict):
                        continue

                    winner_in = round_data.get("winner", {})
                    winner_uid = None
                    winner_reward = 0.0
                    if isinstance(winner_in, dict):
                        raw_uid = winner_in.get("miner_uid")
                        try:
                            winner_uid = int(raw_uid) if raw_uid is not None else None
                        except Exception:
                            winner_uid = None
                        try:
                            winner_reward = float(winner_in.get("reward", winner_in.get("score", 0.0)) or 0.0)
                        except Exception:
                            winner_reward = 0.0

                    miner_rewards_out: dict[str, float] = {}
                    miner_rewards_in = round_data.get("miner_rewards", round_data.get("miner_scores", {}))
                    if isinstance(miner_rewards_in, dict):
                        for uid, reward in miner_rewards_in.items():
                            try:
                                uid_i = int(uid)
                                reward_f = float(reward)
                            except Exception:
                                continue
                            miner_rewards_out[str(uid_i)] = reward_f

                    decision_out = {}
                    decision_in = round_data.get("decision", {})
                    if isinstance(decision_in, dict):
                        for key in (
                            "top_candidate_uid",
                            "top_candidate_reward",
                            "reigning_uid_before_round",
                            "reigning_reward_before_round",
                            "reigning_eligible_before_round",
                            "required_improvement_pct",
                            "required_reward_to_dethrone",
                            "dethroned",
                            "eligible_uids",
                        ):
                            if key in decision_in:
                                decision_out[key] = decision_in[key]

                    round_out = {
                        "winner": {
                            "miner_uid": winner_uid,
                            "reward": winner_reward,
                        },
                        "miner_rewards": miner_rewards_out,
                    }
                    if decision_out:
                        round_out["decision"] = decision_out
                    rounds_out[str(round_i)] = round_out

            summary_in = season_data.get("summary", {})
            if not isinstance(summary_in, dict):
                summary_in = {}

            best_by_miner_out: dict[str, float] = {}
            best_by_miner_in = summary_in.get("best_by_miner", {})
            if isinstance(best_by_miner_in, dict):
                for uid, reward in best_by_miner_in.items():
                    try:
                        uid_i = int(uid)
                        reward_f = float(reward)
                    except Exception:
                        continue
                    best_by_miner_out[str(uid_i)] = reward_f

            best_round_by_miner_out: dict[str, int] = {}
            best_round_by_miner_in = summary_in.get("best_round_by_miner", {})
            if isinstance(best_round_by_miner_in, dict):
                for uid, rnd in best_round_by_miner_in.items():
                    try:
                        uid_i = int(uid)
                        rnd_i = int(rnd)
                    except Exception:
                        continue
                    best_round_by_miner_out[str(uid_i)] = rnd_i

            current_winner_uid = summary_in.get("current_winner_uid")
            try:
                current_winner_uid = int(current_winner_uid) if current_winner_uid is not None else None
            except Exception:
                current_winner_uid = None

            summary_out = {
                "current_winner_uid": current_winner_uid,
                "current_winner_reward": float(summary_in.get("current_winner_reward", summary_in.get("current_winner_score", 0.0)) or 0.0),
                "required_improvement_pct": float(summary_in.get("required_improvement_pct", 0.0) or 0.0),
                "best_by_miner": best_by_miner_out,
                "best_round_by_miner": best_round_by_miner_out,
                "last_eligible_uids": [int(uid) for uid in (summary_in.get("last_eligible_uids", []) or []) if uid is not None],
            }

            serialized[str(season_i)] = {
                "rounds": rounds_out,
                "summary": summary_out,
            }

        payload = {
            "schema_version": 1,
            "seasons": serialized,
        }
        with self._competition_state_path().open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

        self._save_round_summary_snapshots(serialized)

    def _save_round_summary_snapshots(self, serialized: dict[str, dict]) -> None:
        """Persist per-round summary snapshots under data/season_<N>/round_<M>/summary_round.json."""
        try:
            base = self._state_summary_root()
        except Exception:
            return

        now = datetime.utcnow().isoformat()

        for season_key, season_payload in serialized.items():
            try:
                season_number = int(season_key)
            except Exception:
                continue
            if not isinstance(season_payload, dict):
                continue

            season_summary = season_payload.get("summary", {})
            if not isinstance(season_summary, dict):
                season_summary = {}

            rounds_payload = season_payload.get("rounds", {})
            if not isinstance(rounds_payload, dict):
                continue

            season_dir = base / f"season_{season_number}"
            for round_key, round_payload in rounds_payload.items():
                try:
                    round_number = int(round_key)
                except Exception:
                    continue
                if not isinstance(round_payload, dict):
                    continue
                round_dir = season_dir / f"round_{round_number}"
                logs_dir = round_dir / "logs"
                if not logs_dir.exists():
                    round_dir.mkdir(parents=True, exist_ok=True)
                summary_path = round_dir / "summary_round.json"
                round_summary = {**round_payload}

                pre_consensus = {
                    "schema_version": 1,
                    "season_number": season_number,
                    "round_number_in_season": round_number,
                    "saved_at_utc": now,
                    "round_summary": {
                        "winner": round_summary.get("winner", {}),
                        "miner_rewards": {str(k): float(v) for k, v in round_summary.get("miner_rewards", round_summary.get("miner_scores", {})).items()}
                        if isinstance(round_summary.get("miner_rewards", round_summary.get("miner_scores", {})), dict)
                        else {},
                        "decision": round_summary.get("decision", {}),
                    },
                    "season_summary": {
                        "current_winner_uid": season_summary.get("current_winner_uid"),
                        "current_winner_reward": season_summary.get("current_winner_reward", season_summary.get("current_winner_score", 0.0)),
                        "required_improvement_pct": season_summary.get("required_improvement_pct", 0.0),
                        "last_eligible_uids": season_summary.get("last_eligible_uids", []) or [],
                    },
                }

                snapshot = {
                    "schema_version": 1,
                    "season_number": season_number,
                    "round_number_in_season": round_number,
                    "saved_at_utc": now,
                    "pre_consensus": pre_consensus,
                    "post_consensus": None,
                    "ipfs_uploaded": None,
                    "ipfs_downloaded": None,
                    "round_summary": pre_consensus.get("round_summary", {}),
                    "season_summary": {
                        "current_winner_uid": season_summary.get("current_winner_uid"),
                        "current_winner_reward": season_summary.get("current_winner_reward", season_summary.get("current_winner_score", 0.0)),
                        "required_improvement_pct": season_summary.get("required_improvement_pct", 0.0),
                        "last_eligible_uids": season_summary.get("last_eligible_uids", []) or [],
                    },
                }
                with summary_path.open("w", encoding="utf-8") as f:
                    json.dump(snapshot, f, indent=2, sort_keys=True)

    def _load_competition_state(self) -> None:
        """Load season winner/history state from JSON (best-effort)."""
        path = self._competition_state_path()
        if not path.exists():
            return

        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        seasons_in = payload.get("seasons", {})
        if not isinstance(seasons_in, dict):
            return

        loaded: dict[int, dict] = {}
        for season_key, season_data in seasons_in.items():
            try:
                season_i = int(season_key)
            except Exception:
                continue
            if not isinstance(season_data, dict):
                continue

            # New shape:
            # seasons.<s>.rounds.<r>.{winner, miner_rewards}
            # seasons.<s>.summary.{current_winner_uid, current_winner_reward, best_by_miner, ...}
            rounds_loaded: dict[int, dict] = {}
            summary_loaded: dict = {
                "current_winner_uid": None,
                "current_winner_reward": 0.0,
                "required_improvement_pct": 0.0,
                "best_by_miner": {},
                "best_round_by_miner": {},
                "last_eligible_uids": [],
            }

            if "rounds" in season_data or "summary" in season_data:
                rounds_in = season_data.get("rounds", {})
                if isinstance(rounds_in, dict):
                    for round_key, round_data in rounds_in.items():
                        try:
                            round_i = int(round_key)
                        except Exception:
                            continue
                        if not isinstance(round_data, dict):
                            continue

                        winner_in = round_data.get("winner", {})
                        winner_uid = None
                        winner_reward = 0.0
                        if isinstance(winner_in, dict):
                            raw_uid = winner_in.get("miner_uid")
                            try:
                                winner_uid = int(raw_uid) if raw_uid is not None else None
                            except Exception:
                                winner_uid = None
                            try:
                                winner_reward = float(winner_in.get("reward", winner_in.get("score", 0.0)) or 0.0)
                            except Exception:
                                winner_reward = 0.0

                        miner_rewards_loaded: dict[int, float] = {}
                        miner_rewards_in = round_data.get("miner_rewards", round_data.get("miner_scores", {}))
                        if isinstance(miner_rewards_in, dict):
                            for uid_key, reward in miner_rewards_in.items():
                                try:
                                    uid_i = int(uid_key)
                                    reward_f = float(reward)
                                except Exception:
                                    continue
                                miner_rewards_loaded[uid_i] = reward_f

                        round_out = {
                            "winner": {"miner_uid": winner_uid, "reward": winner_reward},
                            "miner_rewards": miner_rewards_loaded,
                        }
                        decision_in = round_data.get("decision", {})
                        if isinstance(decision_in, dict):
                            round_out["decision"] = dict(decision_in)
                        rounds_loaded[round_i] = round_out

                summary_in = season_data.get("summary", {})
                if isinstance(summary_in, dict):
                    current_winner_uid = summary_in.get("current_winner_uid")
                    try:
                        current_winner_uid = int(current_winner_uid) if current_winner_uid is not None else None
                    except Exception:
                        current_winner_uid = None

                    best_by_miner_loaded: dict[int, float] = {}
                    for uid_key, reward in (summary_in.get("best_by_miner", {}) or {}).items():
                        try:
                            uid_i = int(uid_key)
                            reward_f = float(reward)
                        except Exception:
                            continue
                        best_by_miner_loaded[uid_i] = reward_f

                    best_round_by_miner_loaded: dict[int, int] = {}
                    for uid_key, rnd in (summary_in.get("best_round_by_miner", {}) or {}).items():
                        try:
                            uid_i = int(uid_key)
                            rnd_i = int(rnd)
                        except Exception:
                            continue
                        best_round_by_miner_loaded[uid_i] = rnd_i

                    summary_loaded = {
                        "current_winner_uid": current_winner_uid,
                        "current_winner_reward": float(summary_in.get("current_winner_reward", summary_in.get("current_winner_score", 0.0)) or 0.0),
                        "required_improvement_pct": float(summary_in.get("required_improvement_pct", 0.0) or 0.0),
                        "best_by_miner": best_by_miner_loaded,
                        "best_round_by_miner": best_round_by_miner_loaded,
                        "last_eligible_uids": [int(uid) for uid in (summary_in.get("last_eligible_uids", []) or []) if uid is not None],
                    }
            else:
                # Backward compatibility for old shape:
                # seasons.<s>.miners + seasons.<s>.round_winners
                miners_in = season_data.get("miners", {})
                if isinstance(miners_in, dict):
                    for uid_key, miner_data in miners_in.items():
                        try:
                            uid_i = int(uid_key)
                        except Exception:
                            continue
                        if not isinstance(miner_data, dict):
                            continue
                        best_score = float(miner_data.get("best_score", 0.0) or 0.0)
                        best_round = int(miner_data.get("best_round", 0) or 0)
                        summary_loaded["best_by_miner"][uid_i] = best_score
                        if best_round > 0:
                            summary_loaded["best_round_by_miner"][uid_i] = best_round
                        round_scores = miner_data.get("round_scores", {})
                        if isinstance(round_scores, dict):
                            for rnd_key, reward in round_scores.items():
                                try:
                                    rnd_i = int(rnd_key)
                                    reward_f = float(reward)
                                except Exception:
                                    continue
                                entry = rounds_loaded.get(rnd_i)
                                if not isinstance(entry, dict):
                                    entry = {"winner": {"miner_uid": None, "reward": 0.0}, "miner_rewards": {}}
                                entry["miner_rewards"][uid_i] = reward_f
                                rounds_loaded[rnd_i] = entry

                winners_in = season_data.get("round_winners", [])
                if isinstance(winners_in, list):
                    for winner in winners_in:
                        if not isinstance(winner, dict):
                            continue
                        try:
                            rnd_i = int(winner.get("round", 0) or 0)
                        except Exception:
                            continue
                        if rnd_i <= 0:
                            continue
                        entry = rounds_loaded.get(rnd_i)
                        if not isinstance(entry, dict):
                            entry = {"winner": {"miner_uid": None, "reward": 0.0}, "miner_rewards": {}}
                        raw_uid = winner.get("winner_uid")
                        try:
                            winner_uid = int(raw_uid) if raw_uid is not None else None
                        except Exception:
                            winner_uid = None
                        entry["winner"] = {
                            "miner_uid": winner_uid,
                            "reward": float(winner.get("winner_reward", winner.get("winner_score", 0.0)) or 0.0),
                        }
                        rounds_loaded[rnd_i] = entry

                current_winner_uid = season_data.get("current_winner_uid")
                try:
                    current_winner_uid = int(current_winner_uid) if current_winner_uid is not None else None
                except Exception:
                    current_winner_uid = None
                summary_loaded["current_winner_uid"] = current_winner_uid
                summary_loaded["current_winner_reward"] = float(season_data.get("current_winner_reward", season_data.get("current_winner_score", 0.0)) or 0.0)
                summary_loaded["required_improvement_pct"] = float(season_data.get("required_improvement_pct", 0.0) or 0.0)

            loaded[season_i] = {
                "rounds": rounds_loaded,
                "summary": summary_loaded,
            }

        self._season_competition_history = loaded

    def save_state(self):
        """Save base validator state + season competition history."""
        super().save_state()
        try:
            self._save_competition_state()
        except Exception as exc:
            bt.logging.warning(f"Failed to save competition state: {exc}")

    def load_state(self):
        """Load base validator state + season competition history + IWAP prev-round (for is_reused)."""
        try:
            super().load_state()
        except Exception as exc:
            bt.logging.warning(f"Could not load base state.npz (starting fresh): {exc}")
        try:
            self._load_competition_state()
        except Exception as exc:
            bt.logging.warning(f"Could not load competition state JSON (starting fresh): {exc}")
        try:
            if hasattr(self, "_load_iwap_prev_round_state") and callable(self._load_iwap_prev_round_state):
                self._load_iwap_prev_round_state()
        except Exception as exc:
            bt.logging.warning(f"Could not load IWAP prev-round state (starting fresh): {exc}")

    async def forward(self) -> None:
        """
        Forward pass for the validator.
        """
        if await self._wait_for_minimum_start_block():
            return

        round_size_epochs = float(getattr(self.round_manager, "round_size_epochs", ROUND_SIZE_EPOCHS) or ROUND_SIZE_EPOCHS)
        bt.logging.info(f"🚀 Starting round-based forward (epochs per round: {round_size_epochs:.1f})")
        start_result: RoundStartResult = await self._start_round()

        if not start_result.continue_forward:
            bt.logging.info(f"Round start skipped ({start_result.reason}); waiting for next boundary")
            await self._wait_until_specific_block(
                target_block=self.round_manager.target_block,
                target_description="round boundary block",
            )
            return

        # 1) Handshake & agent discovery
        await self._perform_handshake()

        # Late-start guard: if handshake consumed too much time and the round is
        # already at/near end, skip participation entirely for this round.
        try:
            current_block_after_handshake = self.block
            target_block = int(getattr(self.round_manager, "target_block", 0) or 0)
            remaining_blocks = max(target_block - current_block_after_handshake, 0)
            min_blocks_to_participate = int(
                getattr(
                    self.round_manager,
                    "SKIP_ROUND_MIN_BLOCKS_AFTER_HANDSHAKE",
                    10,
                )
                or 10
            )
            if target_block > 0 and remaining_blocks < min_blocks_to_participate:
                bt.logging.warning(
                    "Skipping round participation after handshake: "
                    f"remaining_blocks={remaining_blocks} < min_required={min_blocks_to_participate} "
                    f"(current_block={current_block_after_handshake}, target_block={target_block})"
                )
                self.round_manager.enter_phase(
                    RoundPhase.COMPLETE,
                    block=current_block_after_handshake,
                    note="Round skipped (late start after handshake)",
                    force=True,
                )
                await self._wait_until_specific_block(
                    target_block=target_block,
                    target_description="round boundary block",
                )
                return
        except Exception as exc:
            bt.logging.warning(f"Late-start guard check failed (continuing): {exc}")

        # Initialize IWAP round after handshake (we now know how many miners participate)
        current_block = self.block
        season_tasks = await self.round_manager.get_round_tasks(current_block, self.season_manager)
        n_tasks = len(season_tasks)

        # Build IWAP tasks before starting round
        if season_tasks and self.current_round_id:
            self.current_round_tasks = self._build_iwap_tasks(validator_round_id=self.current_round_id, tasks=season_tasks)

        await self._iwap_start_round(current_block=current_block, n_tasks=n_tasks)

        # Register miners in IWAP (creates validator_round_miners records)
        await self._iwap_register_miners()

        # 2) Evaluation phase
        agents_evaluated = await self._run_evaluation_phase()

        # 3) Settlement / weight update
        await self._run_settlement_phase(agents_evaluated=agents_evaluated)


if __name__ == "__main__":
    # Initialize IWA with default logging (best-effort)
    AppBootstrap()

    with Validator(config=config(role="validator")) as validator:
        heartbeat_seconds = 120
        sync_interval_seconds = max(60, int(os.getenv("HEARTBEAT_SYNC_INTERVAL_SECONDS", "1800")))
        last_sync_ts = time.monotonic()
        while True:
            bt.logging.debug(f"Heartbeat — validator running... {time.time()}")
            now = time.monotonic()
            if now - last_sync_ts >= sync_interval_seconds:
                try:
                    bt.logging.info(f"Heartbeat sync triggered (interval={sync_interval_seconds}s)")
                    validator.sync()
                    bt.logging.info("Heartbeat sync completed")
                except Exception as exc:
                    bt.logging.error(f"Heartbeat sync failed: {exc}")
                finally:
                    last_sync_ts = time.monotonic()
            time.sleep(heartbeat_seconds)
