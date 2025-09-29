# autoppia_web_agents_subnet/validator/forward.py
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bittensor as bt
import numpy as np
from numpy.typing import NDArray

from autoppia_web_agents_subnet.config import FORWARD_SLEEP_SECONDS, TIMEOUT, EVAL_SCORE_WEIGHT, TIME_WEIGHT
from autoppia_web_agents_subnet.validator.tasks import get_task_plan
from autoppia_web_agents_subnet.validator.synapse import send_synapse_to_miners_generic, collect_task_solutions_and_execution_times, send_feedback_synapse_to_miners
from autoppia_web_agents_subnet.protocol import StartRoundSynapse, TaskSynapse
from autoppia_web_agents_subnet.validator.rewards import blend_eval_and_time, reduce_rewards_to_averages, pad_or_trim, wta_rewards
from autoppia_web_agents_subnet.validator.eval import evaluate_task_solutions
from autoppia_web_agents_subnet.validator.models import TaskPlan, PerTaskResult, ScoredTask, EvalOutput
from autoppia_web_agents_subnet.validator.stats import ForwardStats
from autoppia_web_agents_subnet.validator.leaderboard import LeaderboardAPI, Phase, TaskInfo, TaskResult, AgentEvaluationRun, WeightsSnapshot, RoundResults
from autoppia_web_agents_subnet.utils.random import get_random_uids


class ForwardHandler:
    """Handles the forward loop logic for the validator."""

    def __init__(self, validator):
        self.validator = validator

    async def execute_forward(self) -> None:
        """Execute the main forward loop."""
        try:
            self.validator.forward_count += 1
            round_id = f"Round-{self.validator.forward_count}"
            bt.logging.info(f"[forward #{self.validator.forward_count}] start (version {self.validator.version})")
            t0 = time.time()

            # Events: initializing + round_start
            self.validator.lb.log_event_simple(validator_uid=int(self.validator.uid), round_id=round_id, phase=Phase.ROUND_START, message="Round starting.", extra={"version": self.validator.version})
            self.validator.lb.log_event_simple(validator_uid=int(self.validator.uid), round_id=round_id, phase=Phase.INITIALIZING, message="Forward loop starting.")

            # Full miner roster
            full_uid_array = get_random_uids(self.validator, k=self.validator.metagraph.n.item())
            full_uids: List[int] = full_uid_array.tolist()
            full_axons = [self.validator.metagraph.axons[uid] for uid in full_uids]

            if not full_uids:
                bt.logging.warning("No miners in metagraph; skipping forward.")
                return

            # Phase 0: notify start, then filter to ACTIVE miners only
            responders: Dict[int, StartRoundSynapse] = {}
            try:
                responders = await self.validator.notify_start_round(miner_uids=full_uids, axons=full_axons, round_id=round_id, note="Round starting", timeout=12)
            except Exception as e:
                bt.logging.warning(f"notify_start_round failed (continuing with zero responders): {e}")

            active_mask = [uid in responders for uid in full_uids]
            active_uids = [uid for uid, ok in zip(full_uids, active_mask) if ok]
            active_axons = [ax for ax, ok in zip(full_axons, active_mask) if ok]

            if not active_uids:
                self.validator.burn_all(uids=full_uids)
                elapsed = time.time() - t0
                self.validator.lb.log_event_simple(validator_uid=int(self.validator.uid), round_id=round_id, phase=Phase.ERROR, message="No active miners responded to StartRound; burn_all.", extra={"elapsed_sec": elapsed, "total_miners": len(full_uids)})
                if FORWARD_SLEEP_SECONDS > 0:
                    bt.logging.info(f"Sleeping {FORWARD_SLEEP_SECONDS}s…")
                    await asyncio.sleep(FORWARD_SLEEP_SECONDS)
                return

            # Miner metadata
            active_hotkeys = [self.validator.metagraph.hotkeys[uid] for uid in active_uids]
            active_coldkeys = [self.validator.metagraph.coldkeys[uid] for uid in active_uids]

            # Stats collector (for console table only)
            stats = ForwardStats(miner_uids=active_uids, miner_hotkeys=active_hotkeys, miner_coldkeys=active_coldkeys)
            stats.start(forward_id=self.validator.forward_count)

            # Phase 1: tasks plan
            self.validator.lb.log_event_simple(validator_uid=int(self.validator.uid), round_id=round_id, phase=Phase.GENERATING_TASKS, message="Generating Task Plan")
            task_plan: TaskPlan = await get_task_plan(prompts_per_use_case=1)

            max_tasks = self.validator._cap_one_per_use_case(task_plan)

            # Send tasks
            self.validator.lb.log_event_simple(validator_uid=int(self.validator.uid), round_id=round_id, phase=Phase.SENDING_TASKS, message=f"Sending {max_tasks} tasks to {len(active_uids)} miners.")
            per_task_results = await self.validator.send_tasks(task_plan=task_plan, miner_uids=active_uids, miner_axons=active_axons, max_tasks=max_tasks, timeout=TIMEOUT)

            # Evaluate
            self.validator.lb.log_event_simple(validator_uid=int(self.validator.uid), round_id=round_id, phase=Phase.EVALUATING_TASKS, message=f"Evaluating {len(per_task_results)} tasks.")
            eval_outputs = await self.validator.evaluate_tasks(per_task_results=per_task_results, n_miners=len(active_uids))
            rewards_active, scored_tasks = await self.validator.calculate_rewards(per_task_results=per_task_results, eval_outputs=eval_outputs, miner_uids=active_uids, eval_score_weight=EVAL_SCORE_WEIGHT, time_weight=TIME_WEIGHT)

            # Stats feed (console only)
            for st in scored_tasks:
                stats.record_batch(final_rewards=st.final_rewards, eval_scores=st.eval_scores, execution_times=st.execution_times)

            # Feedback
            self.validator.lb.log_event_simple(validator_uid=int(self.validator.uid), round_id=round_id, phase=Phase.SENDING_FEEDBACK, message="Sending per-miner feedback for scored tasks.")
            await self.validator.send_feedback(scored_tasks=scored_tasks, miner_uids=active_uids, miner_axons=active_axons)

            # Weights: WTA on active → map to full; zeros for non-responders
            raw_active_avg = rewards_active.copy()
            rewards_active_wta = wta_rewards(rewards_active)

            rewards_full_avg = np.zeros(len(full_uids), dtype=np.float32)
            rewards_full_wta = np.zeros(len(full_uids), dtype=np.float32)

            uid_to_idx_active = {uid: i for i, uid in enumerate(active_uids)}
            for i_full, uid in enumerate(full_uids):
                idx_active = uid_to_idx_active.get(uid, None)
                if idx_active is not None:
                    rewards_full_avg[i_full] = raw_active_avg[idx_active]
                    rewards_full_wta[i_full] = rewards_active_wta[idx_active]

            self.validator.lb.log_event_simple(validator_uid=int(self.validator.uid), round_id=round_id, phase=Phase.UPDATING_WEIGHTS, message="Updating weights on-chain (WTA).")
            self.validator.update_scores(rewards_full_wta, full_uids)
            self.validator.set_weights()
            self.validator.last_rewards = rewards_full_avg

            # Build + POST RoundResults once
            self.validator._build_and_post_round_results(round_id=round_id, started_at=t0, full_uids=full_uids, active_uids=active_uids, active_hotkeys=active_hotkeys, active_coldkeys=active_coldkeys, scored_tasks=scored_tasks, rewards_full_avg=rewards_full_avg, rewards_full_wta=rewards_full_wta)

            # Finish + console table
            summary = stats.finish()
            stats.render_table(summary, to_console=True)

            # Events: round_end + done
            elapsed = time.time() - t0
            self.validator.lb.log_event_simple(validator_uid=int(self.validator.uid), round_id=round_id, phase=Phase.ROUND_END, message=f"Round finished; elapsed {elapsed:.2f}s.", extra={"active_miners": len(active_uids), "total_miners": len(full_uids)})
            self.validator.lb.log_event_simple(validator_uid=int(self.validator.uid), round_id=round_id, phase=Phase.DONE, message="Forward complete.")

            if FORWARD_SLEEP_SECONDS > 0:
                bt.logging.info(f"Sleeping {FORWARD_SLEEP_SECONDS}s…")
                await asyncio.sleep(FORWARD_SLEEP_SECONDS)

        except Exception as err:
            bt.logging.error(f"Error in forward: {err}")
            try:
                round_id = f"Round-{self.validator.forward_count}"
                self.validator.lb.log_event_simple(validator_uid=int(self.validator.uid), round_id=round_id, phase=Phase.ERROR, message=f"Forward crashed: {err}")
            except Exception:
                pass
