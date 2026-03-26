from __future__ import annotations

import asyncio
import re
import time

import bittensor as bt
import numpy as np

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator import config as validator_config
from autoppia_web_agents_subnet.validator.config import BURN_AMOUNT_PERCENTAGE, BURN_UID
from autoppia_web_agents_subnet.validator.round_manager import RoundPhase
from autoppia_web_agents_subnet.validator.settlement.consensus import (
    aggregate_scores_from_commitments,
    publish_round_snapshot,
)
from autoppia_web_agents_subnet.validator.settlement.rewards import wta_rewards
from autoppia_web_agents_subnet.validator.visualization.round_table import (
    render_round_summary_table,
)


def _eligibility_status_is_valid(status: object) -> bool:
    return str(status or "").strip().lower() in {"handshake_valid", "reused", "evaluated"}


def _eligible_uids_from_status_map(raw_statuses: object) -> set[int]:
    eligible: set[int] = set()
    if not isinstance(raw_statuses, dict):
        return eligible
    for uid_raw, status_raw in raw_statuses.items():
        if not _eligibility_status_is_valid(status_raw):
            continue
        try:
            eligible.add(int(uid_raw))
        except Exception:
            continue
    return eligible


def _eligible_uids_from_consensus_payloads(raw_payloads: object) -> set[int]:
    eligible: set[int] = set()
    if not isinstance(raw_payloads, list):
        return eligible
    for payload_entry in raw_payloads:
        if not isinstance(payload_entry, dict):
            continue
        payload = payload_entry.get("payload")
        if not isinstance(payload, dict):
            continue
        miners = payload.get("miners")
        if isinstance(miners, list):
            for miner_raw in miners:
                if not isinstance(miner_raw, dict):
                    continue
                uid_raw = miner_raw.get("uid", miner_raw.get("miner_uid"))
                try:
                    eligible.add(int(uid_raw))
                except Exception:
                    continue
            continue
        miner_metrics = payload.get("miner_metrics")
        if not isinstance(miner_metrics, dict):
            continue
        for uid_raw, metric_raw in miner_metrics.items():
            if not isinstance(metric_raw, dict):
                continue
            eligible_flag = metric_raw.get("eligible_this_round")
            if eligible_flag is True or _eligibility_status_is_valid(metric_raw.get("eligibility_status")):
                try:
                    eligible.add(int(metric_raw.get("miner_uid", uid_raw)))
                except Exception:
                    continue
    return eligible


class ValidatorSettlementMixin:
    """Consensus and weight-finalization helpers shared across phases."""

    async def _run_settlement_phase(self, *, agents_evaluated: int = 0) -> None:
        """
        Complete the round:
        - If we're past the round end: no IPFS/consensus/finish/set_weights; just cleanup and wait for next round.
        - Otherwise: publish consensus snapshot, wait for 97%, aggregate, set weights, wait for round end.
        """
        round_end_block = getattr(self, "_settlement_round_target_block", None) or self.round_manager.target_block
        current_block = getattr(self, "block", None)
        if round_end_block is not None and current_block is not None and current_block > round_end_block:
            ColoredLogger.info(
                f"Round ended before settlement (block {current_block} > {round_end_block}); skipping IPFS/consensus/finish/set_weights for this round.",
                ColoredLogger.YELLOW,
            )
            await self._try_upload_round_log_checkpoint(
                reason="settlement_late_skip",
                force=True,
                min_interval_seconds=0.0,
            )
            self.round_manager.enter_phase(
                RoundPhase.COMPLETE,
                block=current_block,
                note="Round skipped (ended before settlement)",
                force=True,
            )
            await self._wait_until_specific_block(
                target_block=round_end_block,
                target_description="round end block",
            )
            for attr in ("_settlement_round_start_block", "_settlement_round_target_block", "_settlement_round_fetch_block"):
                if hasattr(self, attr):
                    delattr(self, attr)
            self.round_manager.log_phase_history()
            try:
                reset = getattr(self, "_reset_iwap_round_state", None)
                if callable(reset):
                    reset()
            except Exception:
                pass
            return

        agents_dict = getattr(self, "agents_dict", None)
        if not isinstance(agents_dict, dict):
            agents_dict = {}

        raw_handshake_uids = getattr(self, "agents_on_first_handshake", [])
        handshake_uids = [uid for uid in raw_handshake_uids if isinstance(uid, int)] if isinstance(raw_handshake_uids, list | tuple | set) else []

        self.should_update_weights = all(bool(getattr(agents_dict.get(uid), "evaluated", False)) for uid in handshake_uids)

        if not self.should_update_weights:
            ColoredLogger.info(
                "Not all agents from first handshake were evaluated; keeping original weights.",
                ColoredLogger.CYAN,
            )
            self.set_weights()
            self.round_manager.enter_phase(
                RoundPhase.COMPLETE,
                block=self.block,
                note="Round finalized without weight update",
                force=True,
            )
        else:
            st = await self._get_async_subtensor()
            # Snapshot payloads are built from current/best run data inside publish_round_snapshot().
            await publish_round_snapshot(self, st=st, scores={})
            await self._try_upload_round_log_checkpoint(
                reason="settlement_snapshot_published",
                force=True,
                min_interval_seconds=0.0,
            )

            fetch_fraction = float(
                getattr(
                    validator_config,
                    "FETCH_IPFS_VALIDATOR_PAYLOADS_CALCULATE_WEIGHT_AT_ROUND_FRACTION",
                    0.97,
                )
                or 0.97
            )
            fetch_fraction = max(0.0, min(1.0, fetch_fraction))
            # Use boundaries saved at round start so we wait for *this* round's 97% and end,
            # not the next round's (if block has advanced past round end, sync_boundaries would give next round).
            fetch_block = getattr(self, "_settlement_round_fetch_block", None)
            target_block = getattr(self, "_settlement_round_target_block", None)
            if fetch_block is None or target_block is None:
                if self.round_manager.start_block is None:
                    self.round_manager.sync_boundaries(self.block)
                start_block = int(self.round_manager.start_block or self.block)
                target_block = int(self.round_manager.target_block or self.round_manager.settlement_block or start_block)
                fetch_block = int(start_block + int(self.round_manager.round_block_length * fetch_fraction))
                fetch_block = max(start_block, min(fetch_block, target_block))
            else:
                fetch_block = int(fetch_block)
                target_block = int(target_block)

            await self._wait_until_specific_block(
                target_block=fetch_block,
                target_description=f"consensus fetch block ({fetch_fraction:.0%} of round)",
            )
            await self._try_upload_round_log_checkpoint(
                reason="settlement_fetch_block_reached",
                force=True,
                min_interval_seconds=0.0,
            )

            try:
                scores, details = await aggregate_scores_from_commitments(self, st=st)
                # Persist consensus artifacts for finish_round payload building
                # (ipfs_downloaded + post_consensus_evaluation reporting).
                self._agg_scores_cache = scores
                self._agg_meta_cache = details
                try:
                    apply_reuse_policy = getattr(self, "_apply_post_consensus_reuse_policy", None)
                    if callable(apply_reuse_policy):
                        apply_reuse_policy(details)
                except Exception:
                    bt.logging.warning("Failed to apply post-consensus reuse policy", exc_info=True)
                await self._try_upload_round_log_checkpoint(
                    reason="settlement_consensus_aggregated",
                    force=True,
                    min_interval_seconds=0.0,
                )
            except Exception as e:
                ColoredLogger.error(f"Error aggregating scores from commitments: {e}", ColoredLogger.RED)
                scores = {}
                self._agg_scores_cache = {}
                self._agg_meta_cache = {}
                await self._try_upload_round_log_checkpoint(
                    reason="settlement_consensus_failed",
                    force=True,
                    min_interval_seconds=0.0,
                )
            await self._calculate_final_weights(consensus_rewards=scores)
            await self._try_upload_round_log_checkpoint(
                reason="settlement_weights_finalized",
                force=True,
                min_interval_seconds=0.0,
            )
            self.round_manager.enter_phase(
                RoundPhase.COMPLETE,
                block=self.block,
                note="Round finalized with weight update",
                force=True,
            )

        round_end_block = getattr(self, "_settlement_round_target_block", None) or self.round_manager.target_block
        await self._wait_until_specific_block(
            target_block=round_end_block,
            target_description="round end block",
        )

        # Clear saved boundaries so next round gets fresh ones
        for attr in ("_settlement_round_start_block", "_settlement_round_target_block", "_settlement_round_fetch_block"):
            if hasattr(self, attr):
                delattr(self, attr)

        self.round_manager.log_phase_history()

        # Always reset IWAP in-memory state at the end of the round so the next
        # round starts clean. Some settlement paths (e.g. burn/no rewards, or
        # skipping weight updates) intentionally bypass IWAP finish_round, which
        # otherwise performs this reset.
        try:
            reset = getattr(self, "_reset_iwap_round_state", None)
            if callable(reset):
                reset()
        except Exception:
            pass

    async def _wait_until_specific_block(self, target_block: int, target_description: str) -> None:
        current_block = self.block
        if current_block >= target_block:
            return

        self.round_manager.enter_phase(
            RoundPhase.WAITING,
            block=current_block,
            note=f"Waiting for target {target_description} to reach block {target_block}",
        )
        last_log_time = time.time()
        # Prevent indefinite hangs if chain reads fail persistently.
        blocks_to_wait = max(target_block - current_block, 0)
        expected_wait_s = max(60, blocks_to_wait * self.round_manager.SECONDS_PER_BLOCK)
        deadline = time.monotonic() + max(expected_wait_s * 3, 300)
        consecutive_errors = 0
        while True:
            if time.monotonic() > deadline:
                await self._try_upload_round_log_checkpoint(
                    reason=f"wait_timeout:{target_description}",
                    force=True,
                    min_interval_seconds=0.0,
                )
                raise TimeoutError(f"Timed out waiting for {target_description} at block {target_block}; last observed block={current_block}")
            try:
                current_block = self.get_current_block(fresh=True)
                consecutive_errors = 0
                if current_block >= target_block:
                    ColoredLogger.success(
                        f"🎯 Target {target_description} reached at block {target_block}",
                        ColoredLogger.GREEN,
                    )
                    break

                blocks_remaining = max(target_block - current_block, 0)
                minutes_remaining = (blocks_remaining * self.round_manager.SECONDS_PER_BLOCK) / 60
                now = time.time()

                if now - last_log_time >= 12:
                    ColoredLogger.info(
                        (f"Waiting — {target_description} — ~{minutes_remaining:.1f}m left — holding until block {target_block}"),
                        ColoredLogger.BLUE,
                    )
                    await self._try_upload_round_log_checkpoint(
                        reason=f"wait_progress:{target_description}",
                        force=False,
                        min_interval_seconds=None,
                    )
                    last_log_time = now
            except Exception as exc:
                consecutive_errors += 1
                bt.logging.warning(f"Failed to read current block during finalize wait: {exc}")
                if consecutive_errors >= 5:
                    await self._try_upload_round_log_checkpoint(
                        reason=f"wait_block_read_failure:{target_description}",
                        force=True,
                        min_interval_seconds=0.0,
                    )
                    raise RuntimeError(f"Failed to read current block 5 times while waiting for {target_description}") from exc

            await asyncio.sleep(12)

    async def _burn_all(
        self,
        *,
        reason: str,
        weights: np.ndarray | None = None,
        success_message: str | None = None,
        success_color: str = ColoredLogger.RED,
    ) -> None:
        """Override on-chain weights with burn-style weights and finalize the round."""
        n = self.metagraph.n
        self.round_manager.enter_phase(
            RoundPhase.FINALIZING,
            block=self.block,
            note=f"Burn all triggered ({reason})",
        )

        if weights is None:
            try:
                burn_uid = int(BURN_UID)
            except Exception:
                burn_uid = 5
            burn_idx = burn_uid if 0 <= burn_uid < n else min(5, n - 1)
            weights = np.zeros(n, dtype=np.float32)
            weights[burn_idx] = 1.0
            success_message = success_message or f"✅ Burn complete (weight to UID {burn_idx})"
        else:
            if not isinstance(weights, np.ndarray):
                weights = np.asarray(weights, dtype=np.float32)
            elif weights.dtype != np.float32:
                weights = weights.astype(np.float32)
            success_message = success_message or "✅ Burn complete"

        all_uids = list(range(n))
        self.update_scores(rewards=weights, uids=all_uids)
        self.set_weights()

        # Best-effort: still close the IWAP round even when we burn (e.g. all miners failed),
        # otherwise the dashboard can remain stuck in "started" forever.
        try:
            final_weights = {uid: float(weights[uid]) for uid in range(len(weights)) if float(weights[uid]) > 0.0}
        except Exception:
            final_weights = {}

        avg_rewards: dict[int, float] = {}
        try:
            run_uids = list(getattr(self, "current_agent_runs", {}).keys() or [])
        except Exception:
            run_uids = []
        if not run_uids:
            try:
                run_uids = list(getattr(self, "active_miner_uids", []) or [])
            except Exception:
                run_uids = []

        try:
            agents_dict = getattr(self, "agents_dict", None) or {}
        except Exception:
            agents_dict = {}

        for uid in run_uids:
            try:
                info = agents_dict.get(int(uid))
            except Exception:
                info = None
            try:
                avg_rewards[int(uid)] = float(getattr(info, "score", 0.0) or 0.0)
            except Exception:
                avg_rewards[int(uid)] = 0.0

        tasks_total = 0
        try:
            tasks_total = len(getattr(self, "current_round_tasks", {}) or {})
        except Exception:
            tasks_total = 0

        finish_success = False
        try:
            finish_success = await self._finish_iwap_round(
                avg_rewards=avg_rewards,
                final_weights=final_weights,
                tasks_completed=int(tasks_total or 0),
            )
        except Exception as exc:
            bt.logging.warning(f"IWAP finish_round failed during burn-all ({reason}) ({type(exc).__name__}: {exc}); continuing locally.")
            finish_success = False

        if finish_success:
            ColoredLogger.success(success_message or "✅ Burn complete", success_color)
        else:
            ColoredLogger.warning(
                f"⚠️ IWAP finish_round did not complete during burn-all ({reason}); proceeding locally.",
                ColoredLogger.YELLOW,
            )

    async def _calculate_final_weights(self, consensus_rewards: dict[int, float]):
        """
        Calculate and set final weights using season-best winner persistence.

        Winner policy:
        - Track per-miner historical round consensus rewards within the current season.
        - Keep each miner's best consensus reward in the season.
        - Keep the current season winner until another miner beats that winner
          by more than LAST_WINNER_BONUS_PCT (e.g. 5%).
        """
        round_number = getattr(self, "_current_round_number", None)

        if round_number is not None:
            ColoredLogger.info(f"🏁 Finishing Round: {int(round_number)}", ColoredLogger.GOLD)
        else:
            ColoredLogger.info("🏁 Finishing current round", ColoredLogger.GOLD)

        # Resolve season/round identifiers for per-season tracking.
        current_block = int(getattr(self, "block", 0) or 0)
        round_start_block = int(getattr(self, "_settlement_round_start_block", 0) or getattr(getattr(self, "round_manager", None), "start_block", 0) or current_block)
        season_number = 0
        try:
            season_number = int(getattr(getattr(self, "season_manager", None), "season_number", 0) or 0)
        except Exception:
            season_number = 0
        if season_number <= 0:
            try:
                round_id = str(getattr(self, "current_round_id", "") or "")
                match = re.match(r"^validator_round_(\d+)_(\d+)_", round_id)
                if match:
                    season_number = int(match.group(1))
            except Exception:
                season_number = 0
        if season_number <= 0:
            try:
                sm = getattr(self, "season_manager", None)
                if sm is not None and hasattr(sm, "get_season_number"):
                    season_number = int(sm.get_season_number(round_start_block))
            except Exception:
                season_number = 0

        round_number_in_season = 0
        try:
            round_number_in_season = int(getattr(getattr(self, "round_manager", None), "round_number", 0) or 0)
        except Exception:
            round_number_in_season = 0

        burn_reason: str | None = None
        burn_pct = float(max(0.0, min(1.0, BURN_AMOUNT_PERCENTAGE)))
        if burn_pct >= 1.0:
            ColoredLogger.warning(
                "🔥 BURN_AMOUNT_PERCENTAGE=1: forcing burn and skipping consensus",
                ColoredLogger.RED,
            )
            burn_reason = "burn (forced)"

        # Normalize incoming consensus rewards.
        round_rewards: dict[int, float] = {}
        for uid, raw_reward in (consensus_rewards or {}).items():
            try:
                uid_i = int(uid)
                reward_f = float(raw_reward)
            except Exception:
                continue
            if not np.isfinite(reward_f):
                continue
            round_rewards[uid_i] = reward_f
        valid_rewards = {uid: reward for uid, reward in round_rewards.items() if reward > 0.0}
        local_eligible_uids = _eligible_uids_from_status_map(getattr(self, "eligibility_status_by_uid", None) or {})
        agg_meta = getattr(self, "_agg_meta_cache", None) or {}
        consensus_eligible_uids = _eligible_uids_from_consensus_payloads(
            agg_meta.get("downloaded_payloads", []) if isinstance(agg_meta, dict) else [],
        )
        eligible_uids = consensus_eligible_uids or local_eligible_uids or set(round_rewards.keys())

        # Persistent in-memory season history. Real validator persists this to disk
        # (best-effort) via _save_competition_state.
        season_history = getattr(self, "_season_competition_history", None)
        if not isinstance(season_history, dict):
            season_history = {}
            self._season_competition_history = season_history

        try:
            required_improvement_pct = max(float(getattr(validator_config, "LAST_WINNER_BONUS_PCT", 0.0)), 0.0)
        except Exception:
            required_improvement_pct = 0.0

        season_key = int(season_number)
        season_state = season_history.get(season_key)
        if not isinstance(season_state, dict):
            season_state = {}
        rounds_state = season_state.get("rounds")
        if not isinstance(rounds_state, dict):
            rounds_state = {}
        summary_state = season_state.get("summary")
        if not isinstance(summary_state, dict):
            summary_state = {}

        best_by_miner = summary_state.get("best_by_miner")
        if not isinstance(best_by_miner, dict):
            best_by_miner = {}
        best_round_by_miner = summary_state.get("best_round_by_miner")
        if not isinstance(best_round_by_miner, dict):
            best_round_by_miner = {}
        best_snapshot_by_miner = summary_state.get("best_snapshot_by_miner")
        if not isinstance(best_snapshot_by_miner, dict):
            best_snapshot_by_miner = {}

        stats_by_miner = agg_meta.get("stats_by_miner", {}) if isinstance(agg_meta, dict) else {}

        def _snapshot_for_uid(uid: int, reward: float, *, weight: float | None = None, fallback: dict | None = None) -> dict:
            stats = stats_by_miner.get(int(uid), {}) if isinstance(stats_by_miner, dict) else {}
            if not isinstance(stats, dict):
                stats = {}
            base = fallback if isinstance(fallback, dict) else {}
            snapshot = {
                "uid": int(uid),
                "reward": float(reward),
                "score": float(stats.get("avg_eval_score", base.get("score", 0.0)) or 0.0),
                "time": float(stats.get("avg_eval_time", base.get("time", 0.0)) or 0.0),
                "cost": float(stats.get("avg_cost", base.get("cost", 0.0)) or 0.0),
            }
            if weight is not None:
                snapshot["weight"] = float(weight)
            return snapshot

        def _previous_round_leader_after_snapshot() -> dict | None:
            previous_round = int(round_key) - 1
            if previous_round <= 0:
                return None
            previous_entry = rounds_state.get(previous_round) or rounds_state.get(str(previous_round))
            if not isinstance(previous_entry, dict):
                return None
            previous_post = previous_entry.get("post_consensus_json")
            if not isinstance(previous_post, dict):
                return None
            previous_summary = previous_post.get("summary")
            if not isinstance(previous_summary, dict):
                return None
            leader_after = previous_summary.get("leader_after_round")
            return dict(leader_after) if isinstance(leader_after, dict) else None

        if round_number_in_season > 0:
            round_key = int(round_number_in_season)
        else:
            existing_rounds: list[int] = []
            for rk in rounds_state:
                try:
                    existing_rounds.append(int(rk))
                except Exception:
                    continue
            round_key = (max(existing_rounds) + 1) if existing_rounds else 1

        # Update per-miner best-of-season index and capture this round consensus rewards.
        miner_rewards_for_round: dict[int, float] = {}
        for uid, reward in round_rewards.items():
            uid_i = int(uid)
            reward_f = float(reward)
            miner_rewards_for_round[uid_i] = reward_f

            prev_best_raw = best_by_miner.get(uid_i)
            prev_best: float | None
            try:
                prev_best = float(prev_best_raw) if prev_best_raw is not None else None
            except Exception:
                prev_best = None

            if reward_f > 0.0:
                if prev_best is None or reward_f > prev_best:
                    best_by_miner[uid_i] = reward_f
                    best_round_by_miner[uid_i] = int(round_key)
                    best_snapshot_by_miner[uid_i] = _snapshot_for_uid(uid_i, reward_f)
                elif uid_i not in best_round_by_miner:
                    best_round_by_miner[uid_i] = int(round_key)
                elif uid_i not in best_snapshot_by_miner:
                    best_snapshot_by_miner[uid_i] = _snapshot_for_uid(uid_i, reward_f)

        # Resolve current contender by best season reward.
        best_uid: int | None = None
        best_reward = 0.0
        for uid, best in best_by_miner.items():
            try:
                uid_i = int(uid)
                best_f = float(best or 0.0)
            except Exception:
                continue
            if eligible_uids and uid_i not in eligible_uids:
                continue
            if best_f > best_reward:
                best_reward = best_f
                best_uid = uid_i

        leader_before_snapshot = None
        reigning_uid: int | None = None
        reigning_reward = 0.0

        previous_leader_after = _previous_round_leader_after_snapshot()
        if isinstance(previous_leader_after, dict):
            try:
                reigning_uid = int(previous_leader_after.get("uid")) if previous_leader_after.get("uid") is not None else None
            except Exception:
                reigning_uid = None
            if reigning_uid is not None:
                try:
                    reigning_reward = float(previous_leader_after.get("reward", 0.0) or 0.0)
                except Exception:
                    reigning_reward = 0.0
                if reigning_reward > 0.0:
                    leader_before_snapshot = dict(previous_leader_after)
                else:
                    reigning_uid = None

        if reigning_uid is None:
            reigning_uid_raw = summary_state.get("current_winner_uid")
            try:
                reigning_uid = int(reigning_uid_raw) if reigning_uid_raw is not None else None
            except Exception:
                reigning_uid = None

            if reigning_uid is not None:
                try:
                    reigning_reward = float(summary_state.get("current_winner_reward", summary_state.get("current_winner_score", 0.0)) or 0.0)
                except Exception:
                    reigning_reward = 0.0
                if reigning_reward <= 0.0:
                    try:
                        reigning_reward = float(best_by_miner.get(reigning_uid, 0.0) or 0.0)
                    except Exception:
                        reigning_reward = 0.0
                if reigning_reward <= 0.0:
                    reigning_uid = None
                else:
                    current_winner_snapshot = summary_state.get("current_winner_snapshot")
                    if isinstance(current_winner_snapshot, dict) and current_winner_snapshot.get("uid") == reigning_uid:
                        leader_before_snapshot = dict(current_winner_snapshot)
                    else:
                        existing_snapshot = best_snapshot_by_miner.get(reigning_uid) or best_snapshot_by_miner.get(str(reigning_uid))
                        leader_before_snapshot = _snapshot_for_uid(
                            reigning_uid,
                            reigning_reward,
                            fallback=existing_snapshot if isinstance(existing_snapshot, dict) else None,
                        )

        reigning_is_eligible = bool(reigning_uid is not None and reigning_uid in eligible_uids)

        challenger_uid: int | None = None
        challenger_reward = 0.0
        if eligible_uids and reigning_uid is not None:
            ranked_uids = sorted(
                (int(uid) for uid in eligible_uids),
                key=lambda uid: (
                    float(best_by_miner.get(uid, 0.0) or 0.0),
                    -int(uid),
                ),
                reverse=True,
            )
            for uid_i in ranked_uids:
                if int(uid_i) == int(reigning_uid):
                    continue
                challenger_uid = int(uid_i)
                challenger_reward = float(best_by_miner.get(uid_i, 0.0) or 0.0)
                break

        winner_uid: int | None = None
        winner_reward = 0.0
        dethroned = False
        required_reward_to_dethrone: float | None = None

        if eligible_uids and best_uid is not None and best_reward > 0.0:
            winner_uid = best_uid
            winner_reward = best_reward

            if reigning_is_eligible and reigning_uid is not None and reigning_reward > 0.0:
                winner_uid = reigning_uid
                winner_reward = reigning_reward
                if challenger_uid is not None:
                    required_reward_to_dethrone = float(reigning_reward * (1.0 + required_improvement_pct))
                    if challenger_reward > required_reward_to_dethrone:
                        dethroned = True
                        winner_uid = challenger_uid
                        winner_reward = challenger_reward
        elif not eligible_uids:
            winner_uid = None
            winner_reward = 0.0

        # Keep backward-compatible field used in tests and logs.
        self._last_round_winner_uid = winner_uid

        candidate_snapshot = None
        if challenger_uid is not None:
            existing_snapshot = best_snapshot_by_miner.get(challenger_uid) or best_snapshot_by_miner.get(str(challenger_uid))
            candidate_snapshot = _snapshot_for_uid(challenger_uid, challenger_reward, fallback=existing_snapshot if isinstance(existing_snapshot, dict) else None)

        round_entry = {
            "winner": {
                "miner_uid": int(winner_uid) if winner_uid is not None else None,
                "reward": float(winner_reward),
            },
            "miner_rewards": {int(uid): float(reward) for uid, reward in miner_rewards_for_round.items()},
            # Backward-compatible alias used by older tests/report consumers.
            "miner_scores": {int(uid): float(reward) for uid, reward in miner_rewards_for_round.items()},
            "decision": {
                "top_candidate_uid": int(challenger_uid) if challenger_uid is not None else None,
                "top_candidate_reward": float(challenger_reward),
                "reigning_uid_before_round": int(reigning_uid) if reigning_uid is not None else None,
                "reigning_reward_before_round": float(reigning_reward),
                "reigning_eligible_before_round": bool(reigning_is_eligible),
                "required_improvement_pct": float(required_improvement_pct),
                "required_reward_to_dethrone": float(required_reward_to_dethrone) if required_reward_to_dethrone is not None else None,
                "dethroned": bool(dethroned),
                "eligible_uids": sorted(int(uid) for uid in eligible_uids),
            },
        }
        rounds_state[int(round_key)] = round_entry

        summary_state["current_winner_uid"] = int(winner_uid) if winner_uid is not None else None
        summary_state["current_winner_reward"] = float(winner_reward)
        summary_state["required_improvement_pct"] = float(required_improvement_pct)
        summary_state["best_by_miner"] = {int(uid): float(score) for uid, score in best_by_miner.items()}
        summary_state["best_round_by_miner"] = {int(uid): int(rnd) for uid, rnd in best_round_by_miner.items()}
        summary_state["best_snapshot_by_miner"] = {int(uid): snap for uid, snap in best_snapshot_by_miner.items()}
        summary_state["last_eligible_uids"] = sorted(int(uid) for uid in eligible_uids)

        if (not valid_rewards) or burn_reason:
            season_state["rounds"] = rounds_state
            season_state["summary"] = summary_state
            season_history[season_key] = season_state
            try:
                persist_fn = getattr(self, "_save_competition_state", None)
                if callable(persist_fn):
                    persist_fn()
            except Exception:
                pass
            await self._burn_all(
                reason=burn_reason or "burn (no rewards)",
            )
            return

        avg_rewards_array = np.zeros(self.metagraph.n, dtype=np.float32)
        for uid, reward in valid_rewards.items():
            if 0 <= int(uid) < self.metagraph.n:
                avg_rewards_array[int(uid)] = float(reward)

        # Build season-best reward array and call WTA for observability/tests.
        season_best_array = np.zeros(self.metagraph.n, dtype=np.float32)
        for uid, best in best_by_miner.items():
            try:
                uid_i = int(uid)
                best_f = float(best or 0.0)
            except Exception:
                continue
            if 0 <= uid_i < self.metagraph.n:
                season_best_array[uid_i] = best_f
        _ = wta_rewards(season_best_array)

        if winner_uid is None or not (0 <= int(winner_uid) < self.metagraph.n):
            await self._burn_all(reason="burn (no eligible winner)")
            return

        final_rewards_array = np.zeros(self.metagraph.n, dtype=np.float32)
        final_rewards_array[int(winner_uid)] = 1.0

        if reigning_uid is not None and int(winner_uid) == int(reigning_uid):
            ColoredLogger.info(
                f"🏆 Keeping season leader UID {winner_uid} | best_reward={winner_reward:.4f} | required_overtake={required_improvement_pct:.2%}",
                ColoredLogger.GOLD,
            )
        elif dethroned:
            ColoredLogger.info(
                f"🥇 New season leader UID {winner_uid} | reward={winner_reward:.4f} | beat previous by > {required_improvement_pct:.2%}",
                ColoredLogger.GOLD,
            )
        # Antes de set_weights: SIEMPRE repartimos entre 2 destinos:
        #   - BURN_UID (ej. 5): BURN_AMOUNT_PERCENTAGE (ej. 0.8 = 80%)
        #   - Ganador de la season: (1 - BURN_AMOUNT_PERCENTAGE) (ej. 0.2 = 20%)
        winner_percentage = 1.0 - burn_pct
        burn_idx = int(BURN_UID) if 0 <= int(BURN_UID) < len(final_rewards_array) else min(5, len(final_rewards_array) - 1)
        if burn_pct > 0.0:
            final_rewards_array = final_rewards_array.astype(np.float32) * winner_percentage
            # += por si winner == burn_idx (sumar en vez de sobrescribir)
            final_rewards_array[burn_idx] = float(final_rewards_array[burn_idx]) + float(burn_pct)
        bt.logging.info(f"🎯 WEIGHT DISTRIBUTION | Winner UID {winner_uid}: {winner_percentage:.1%} | Burn UID {burn_idx}: {burn_pct:.1%} | BURN_AMOUNT_PERCENTAGE={BURN_AMOUNT_PERCENTAGE}")
        final_rewards_dict = {uid: float(final_rewards_array[uid]) for uid in range(len(final_rewards_array)) if float(final_rewards_array[uid]) > 0.0}
        leader_after_snapshot = None
        if winner_uid is not None:
            existing_snapshot = best_snapshot_by_miner.get(winner_uid) or best_snapshot_by_miner.get(str(winner_uid))
            leader_after_snapshot = _snapshot_for_uid(
                int(winner_uid),
                float(winner_reward),
                weight=float(final_rewards_dict.get(int(winner_uid), 0.0)),
                fallback=existing_snapshot if isinstance(existing_snapshot, dict) else None,
            )
            summary_state["current_winner_snapshot"] = {k: v for k, v in leader_after_snapshot.items() if k != "weight"}
        else:
            summary_state["current_winner_snapshot"] = None

        round_entry["post_consensus_json"] = {
            "season": int(season_number),
            "round": int(round_key),
            "miners": [],
            "summary": {
                "season": int(season_number),
                "round": int(round_key),
                "percentage_to_dethrone": float(required_improvement_pct),
                "dethroned": bool(dethroned),
                "leader_before_round": leader_before_snapshot,
                "candidate_this_round": candidate_snapshot,
                "leader_after_round": leader_after_snapshot,
            },
        }
        season_state["rounds"] = rounds_state
        season_state["summary"] = summary_state
        season_history[season_key] = season_state
        try:
            persist_fn = getattr(self, "_save_competition_state", None)
            if callable(persist_fn):
                persist_fn()
        except Exception:
            pass

        if not final_rewards_dict:
            self._last_round_winner_uid = None

        render_round_summary_table(
            self.round_manager,
            final_rewards_dict,
            self.metagraph,
            to_console=True,
        )

        self.update_scores(rewards=final_rewards_array, uids=list(range(self.metagraph.n)))
        self.set_weights()

        # Send final results to IWAP
        try:
            # Count real task outcomes from the local current runs, not successful miners.
            tasks_completed = 0
            for miner_uid in getattr(self, "current_agent_runs", {}) or {}:
                current_run = self._current_round_run_payload(int(miner_uid))
                if not isinstance(current_run, dict):
                    continue
                tasks_completed += int(current_run.get("tasks_success", 0) or 0)

            finish_success = await self._finish_iwap_round(
                avg_rewards=valid_rewards,
                final_weights={uid: float(final_rewards_array[uid]) for uid in range(len(final_rewards_array)) if float(final_rewards_array[uid]) > 0.0},
                tasks_completed=tasks_completed,
            )

            if finish_success:
                ColoredLogger.success("✅ Final weights submitted to IWAP successfully", ColoredLogger.GREEN)
            else:
                ColoredLogger.warning(
                    "⚠️ IWAP finish_round failed; weights set on-chain but dashboard not updated.",
                    ColoredLogger.YELLOW,
                )
        except Exception as exc:
            ColoredLogger.error(f"Error finishing IWAP round: {exc}", ColoredLogger.RED)
            finish_success = False

        self._log_round_completion(
            color=ColoredLogger.GREEN if finish_success else ColoredLogger.YELLOW,
            reason="completed",
        )

        # Tear down any per-miner sandboxes to keep footprint low between rounds.
        try:
            manager = getattr(self, "sandbox_manager", None)
            if manager is not None:
                manager.cleanup_all_agents()
        except Exception:
            pass

    def _log_round_completion(self, *, color: str, reason: str) -> None:
        """Small helper for consistent round completion logs."""
        ColoredLogger.info(
            f"Round completion | reason={reason}",
            color,
        )


# Backward-compat alias expected by tests
SettlementMixin = ValidatorSettlementMixin
