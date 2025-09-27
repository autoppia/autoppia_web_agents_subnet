# autoppia_web_agents_subnet/validator/validator.py
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bittensor as bt
import numpy as np
from numpy.typing import NDArray
from loguru import logger

from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.bittensor_config import config
from autoppia_web_agents_subnet.utils.random import get_random_uids

from autoppia_web_agents_subnet.config import (
    FORWARD_SLEEP_SECONDS,
    TIMEOUT,
    EVAL_SCORE_WEIGHT,
    TIME_WEIGHT,
)

from autoppia_web_agents_subnet.validator.tasks import get_task_plan  # returns TaskPlan
from autoppia_web_agents_subnet.validator.synapse import (
    send_synapse_to_miners_generic,
    collect_task_solutions_and_execution_times,
    send_feedback_synapse_to_miners,  # per-miner helper
)

from autoppia_web_agents_subnet.protocol import StartRoundSynapse, TaskSynapse

from autoppia_web_agents_subnet.validator.rewards import (
    blend_eval_and_time,
    reduce_rewards_to_averages,
    pad_or_trim,
    wta_rewards,
)

from autoppia_web_agents_subnet.validator.eval import evaluate_task_solutions

from autoppia_web_agents_subnet.validator.models import (
    TaskPlan,
    PerTaskResult,
    ScoredTask,
    EvalOutput,
)

from autoppia_web_agents_subnet.validator.stats import ForwardStats

from autoppia_web_agents_subnet.validator.leaderboard import (
    LeaderboardAPI,
    Phase,
    TaskInfo,
    TaskResult,
    AgentEvaluationRun,
    WeightsSnapshot,
    RoundResults,
)

# IWA
from autoppia_iwa_module.autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa_module.autoppia_iwa.src.bootstrap import AppBootstrap


SUCCESS_THRESHOLD = 0.0  # UI semantics for "success"


class Validator(BaseValidatorNeuron):
    def __init__(self, config=None):
        super().__init__(config=config)
        self.forward_count = 0
        self.last_rewards: np.ndarray | None = None
        self.last_round_responses: Dict[int, StartRoundSynapse] = {}
        self.version: str = __version__
        self.lb = LeaderboardAPI()  # Leaderboard client

        bt.logging.info("load_state()")
        self.load_state()

    # ─────────────────────────────────────────────────────────────────────
    # Phase 0: Round start notify
    # ─────────────────────────────────────────────────────────────────────
    async def notify_start_round(
        self,
        miner_uids: List[int],
        axons: Sequence[Any],
        round_id: str,
        note: Optional[str] = None,
        timeout: int = 12,
    ) -> Dict[int, StartRoundSynapse]:
        if not miner_uids or not axons or len(miner_uids) != len(axons):
            raise ValueError("notify_start_round(): miner_uids and axons must be non-empty and same length.")

        req = StartRoundSynapse(
            version=self.version,
            round_id=round_id,
            validator_id=str(self.wallet.hotkey.ss58_address) if hasattr(self, "wallet") else None,
            total_prompts=None,
            prompts_per_use_case=1,
            note=note,
        )

        responses = await send_synapse_to_miners_generic(
            validator=self,
            miner_axons=axons,
            synapse=req,
            timeout=timeout,
            retries=1,
        )

        out: Dict[int, StartRoundSynapse] = {}
        for uid, resp in zip(miner_uids, responses):
            if isinstance(resp, StartRoundSynapse):
                out[uid] = resp

        bt.logging.info(f"StartRound: {len(out)}/{len(miner_uids)} miners responded.")
        self.last_round_responses = out
        return out

    # ─────────────────────────────────────────────────────────────────────
    # Phase 1: Send tasks → collect aligned results (PerTaskResult)
    # ─────────────────────────────────────────────────────────────────────
    async def send_tasks(
        self,
        *,
        task_plan: TaskPlan,
        miner_uids: Sequence[int],
        miner_axons: Sequence[Any],
        max_tasks: int,
        timeout: int = TIMEOUT,
    ) -> List[PerTaskResult]:
        per_task_results: List[PerTaskResult] = []
        sent = 0

        for (project, task) in task_plan.iter_interleaved():
            if sent >= max_tasks:
                break

            task_synapse = TaskSynapse(
                prompt=task.prompt,
                url=task.url,
                html="",
                screenshot="",
                actions=[],
                version=self.version,
            )

            bt.logging.info(
                f"[Phase 1 - Send {sent+1}/{max_tasks}] Broadcasting to {len(miner_axons)} active miners: "
                f"'{task_synapse.prompt}' (URL: {task_synapse.url})"
            )

            responses = await send_synapse_to_miners_generic(
                validator=self,
                miner_axons=miner_axons,
                synapse=task_synapse,
                timeout=timeout,
                retries=1,
            )

            solutions_aligned, exec_times_aligned = collect_task_solutions_and_execution_times(
                task, responses, miner_uids
            )

            per_task_results.append(
                PerTaskResult(
                    project=project,
                    task=task,
                    solutions=solutions_aligned,
                    execution_times=exec_times_aligned,
                )
            )
            sent += 1

        return per_task_results

    # ─────────────────────────────────────────────────────────────────────
    # Phase 2A: Evaluate (only scoring & artifacts) — NO rewards here
    # ─────────────────────────────────────────────────────────────────────
    async def evaluate_tasks(
        self,
        *,
        per_task_results: List[PerTaskResult],
        n_miners: int,
    ) -> List[EvalOutput]:
        outputs: List[EvalOutput] = []

        for i, ptr in enumerate(per_task_results, start=1):
            try:
                eval_scores, test_results_matrices, evaluation_results = await evaluate_task_solutions(
                    web_project=ptr.project,
                    task=ptr.task,
                    task_solutions=ptr.solutions,
                    execution_times=ptr.execution_times,
                )
                eval_scores = pad_or_trim(eval_scores, n_miners)
                outputs.append(
                    EvalOutput(
                        eval_scores=eval_scores,
                        test_results_matrices=test_results_matrices,
                        evaluation_results=evaluation_results,
                    )
                )
            except Exception as e:
                bt.logging.error(f"[Phase 2A - Evaluate] failed on task {i}: {e}")
                outputs.append(
                    EvalOutput(
                        eval_scores=np.zeros(n_miners, dtype=np.float32),
                        test_results_matrices=[[] for _ in range(n_miners)],
                        evaluation_results=[{} for _ in range(n_miners)],
                    )
                )

        return outputs

    # ─────────────────────────────────────────────────────────────────────
    # Phase 2B: Blend eval + time → final rewards & averages
    # ─────────────────────────────────────────────────────────────────────
    async def calculate_rewards(
        self,
        *,
        per_task_results: List[PerTaskResult],
        eval_outputs: List[EvalOutput],
        miner_uids: Sequence[int],
        eval_score_weight: float = EVAL_SCORE_WEIGHT,
        time_weight: float = TIME_WEIGHT,
    ) -> Tuple[NDArray[np.float32], List[ScoredTask]]:
        n_miners = len(miner_uids)
        rewards_sum = np.zeros(n_miners, dtype=np.float32)
        counts = np.zeros(n_miners, dtype=np.int32)
        scored_tasks: List[ScoredTask] = []

        assert len(per_task_results) == len(eval_outputs), "Mismatched lengths in rewards calc."

        for i, (ptr, outcome) in enumerate(zip(per_task_results, eval_outputs), start=1):
            final_rewards = blend_eval_and_time(
                eval_scores=outcome.eval_scores,
                execution_times=ptr.execution_times,
                n_miners=n_miners,
                eval_score_weight=eval_score_weight,
                time_weight=time_weight,
            )

            rewards_sum += final_rewards
            counts += (final_rewards >= 0).astype(np.int32)

            scored_tasks.append(
                ScoredTask(
                    project=ptr.project,
                    task=ptr.task,
                    solutions=ptr.solutions,
                    execution_times=ptr.execution_times,
                    final_rewards=final_rewards,
                    test_results_matrices=outcome.test_results_matrices,
                    evaluation_results=outcome.evaluation_results,
                    eval_scores=outcome.eval_scores,
                )
            )

        avg_rewards = reduce_rewards_to_averages(rewards_sum, counts)
        return avg_rewards, scored_tasks

    # ─────────────────────────────────────────────────────────────────────
    # Phase 3: Feedback to active miners (per-miner)
    # ─────────────────────────────────────────────────────────────────────
    async def send_feedback(
        self,
        *,
        scored_tasks: List[ScoredTask],
        miner_uids: Sequence[int],
        miner_axons: Sequence[Any],
    ) -> None:
        miner_uids_list = list(miner_uids)
        miner_axons_list = list(miner_axons)

        for i, st in enumerate(scored_tasks, start=1):
            try:
                safe_solutions: List[TaskSolution] = [
                    s if s is not None else TaskSolution(actions=[]) for s in st.solutions
                ]

                await send_feedback_synapse_to_miners(
                    validator=self,
                    miner_axons=miner_axons_list,
                    miner_uids=miner_uids_list,
                    task=st.task,
                    rewards=st.final_rewards.tolist(),
                    execution_times=st.execution_times,
                    task_solutions=safe_solutions,
                    test_results_matrices=st.test_results_matrices,
                    evaluation_results=st.evaluation_results,
                )
            except Exception as e:
                bt.logging.warning(f"[Phase 3 - Feedback] send_feedback failed on task {i}: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # Helper: derive tasks-to-send cap
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def _cap_one_per_use_case(task_plan: TaskPlan) -> int:
        for attr in ("num_use_cases_total", "total_use_cases", "n_use_cases"):
            if hasattr(task_plan, attr):
                try:
                    v = int(getattr(task_plan, attr))
                    if v > 0:
                        return v
                except Exception:
                    pass
        try:
            v = int(getattr(task_plan, "size", 0))
            if v > 0:
                return v
        except Exception:
            pass
        try:
            v = int(len(task_plan))  # type: ignore[arg-type]
            if v > 0:
                return v
        except Exception:
            pass
        return 16

    # ─────────────────────────────────────────────────────────────────────
    # Helper: Build + POST RoundResults (hierarchical)
    # ─────────────────────────────────────────────────────────────────────
    def _build_and_post_round_results(
        self,
        *,
        round_id: str,
        started_at: float,
        full_uids: List[int],
        active_uids: List[int],
        active_hotkeys: List[str],
        active_coldkeys: List[str],
        scored_tasks: List[ScoredTask],
        rewards_full_avg: np.ndarray,
        rewards_full_wta: np.ndarray,
    ) -> None:
        """Builds a RoundResults object from current state and POSTs it once."""

        # 1) Winner (by WTA)
        winner_uid: Optional[int] = None
        try:
            winner_full_index = int(np.argmax(rewards_full_wta))
            winner_uid = int(full_uids[winner_full_index])
            winner_hotkey = self.metagraph.hotkeys[winner_uid]
            bt.logging.info(f"[forward #{self.forward_count}] WTA winner UID={winner_uid} hotkey={winner_hotkey}")
        except Exception:
            pass

        # 2) Minimal task list
        tasks_info: List[TaskInfo] = []
        for st in scored_tasks:
            t = st.task
            tasks_info.append(
                TaskInfo(
                    task_id=str(getattr(t, "id", "")),
                    prompt=str(getattr(t, "prompt", "")),
                    website=str(getattr(t, "url", "")),
                    web_project=str(getattr(t, "web_project_id", "")),
                    use_case=str(getattr(getattr(t, "use_case", None), "name", "")),
                )
            )

        # 3) Per-miner agent runs (aggregate + per-task)
        agent_runs: List[AgentEvaluationRun] = []
        for i_miner, uid in enumerate(active_uids):
            miner_task_results: List[TaskResult] = []

            per_miner_rewards: List[float] = []
            per_miner_eval_scores: List[float] = []
            per_miner_times: List[float] = []
            per_miner_time_scores: List[float] = []

            for st in scored_tasks:
                reward_i = float(st.final_rewards[i_miner]) if i_miner < len(st.final_rewards) else 0.0
                eval_i = float(st.eval_scores[i_miner]) if i_miner < len(st.eval_scores) else 0.0
                time_i = float(st.execution_times[i_miner]) if i_miner < len(st.execution_times) else 0.0
                time_score_i = time_i  # UI can normalize/invert

                sol_dict: Dict[str, Any] = {}
                try:
                    sol = st.solutions[i_miner]
                    if sol is not None:
                        sol_dict = sol.model_dump() if hasattr(sol, "model_dump") else getattr(sol, "__dict__", {})
                except Exception:
                    pass

                tr_i = st.test_results_matrices[i_miner] if i_miner < len(st.test_results_matrices) else []
                er_i = st.evaluation_results[i_miner] if i_miner < len(st.evaluation_results) else {}

                miner_task_results.append(
                    TaskResult(
                        task_id=str(getattr(st.task, "id", "")),
                        eval_score=eval_i,
                        execution_time=time_i,
                        time_score=time_score_i,
                        reward=reward_i,
                        solution=sol_dict,
                        test_results={"results": tr_i},
                        evaluation_result=er_i,
                    )
                )

                per_miner_rewards.append(reward_i)
                per_miner_eval_scores.append(eval_i)
                per_miner_times.append(time_i)
                per_miner_time_scores.append(time_score_i)

            denom = max(len(per_miner_rewards), 1)
            agent_runs.append(
                AgentEvaluationRun(
                    miner_uid=int(uid),
                    miner_hotkey=str(active_hotkeys[i_miner]),
                    miner_coldkey=str(active_coldkeys[i_miner]),
                    reward=float(np.mean(per_miner_rewards)) if denom > 0 else 0.0,
                    eval_score=float(np.mean(per_miner_eval_scores)) if denom > 0 else 0.0,
                    time_score=float(np.mean(per_miner_time_scores)) if denom > 0 else 0.0,
                    execution_time=float(np.mean(per_miner_times)) if denom > 0 else 0.0,
                    task_results=miner_task_results,
                )
            )

        # 4) RoundResults + POST
        ended_at = time.time()
        rr = RoundResults(
            validator_uid=int(self.uid),
            round_id=round_id,
            version=self.version,
            started_at=float(started_at),
            ended_at=float(ended_at),
            elapsed_sec=float(ended_at - started_at),
            n_active_miners=len(active_uids),
            n_total_miners=len(full_uids),
            tasks=tasks_info,
            agent_runs=agent_runs,
            weights=WeightsSnapshot(
                full_uids=[int(u) for u in full_uids],
                rewards_full_avg=[float(x) for x in rewards_full_avg],
                rewards_full_wta=[float(x) for x in rewards_full_wta],
                winner_uid=int(winner_uid) if winner_uid is not None else None,
            ),
            meta={"tasks_sent": len(scored_tasks)},
        )

        # Single POST (non-blocking)
        self.lb.post_round_results(rr, background=True)

    # ─────────────────────────────────────────────────────────────────────
    # Forward loop (drops StartRound non-responders; zeros elsewhere)
    # ─────────────────────────────────────────────────────────────────────
    async def forward(self) -> None:
        try:
            self.forward_count += 1
            round_id = f"Round-{self.forward_count}"
            bt.logging.info(f"[forward #{self.forward_count}] start (version {self.version})")
            t0 = time.time()

            # Events: initializing + round_start
            self.lb.log_event_simple(
                validator_uid=int(self.uid),
                round_id=round_id,
                phase=Phase.ROUND_START,
                message="Round starting.",
                extra={"version": self.version},
            )
            self.lb.log_event_simple(
                validator_uid=int(self.uid),
                round_id=round_id,
                phase=Phase.INITIALIZING,
                message="Forward loop starting.",
            )

            # Full miner roster
            full_uid_array = get_random_uids(self, k=self.metagraph.n.item())
            full_uids: List[int] = full_uid_array.tolist()
            full_axons = [self.metagraph.axons[uid] for uid in full_uids]

            if not full_uids:
                bt.logging.warning("No miners in metagraph; skipping forward.")
                return

            # Phase 0: notify start, then filter to ACTIVE miners only
            responders: Dict[int, StartRoundSynapse] = {}
            try:
                responders = await self.notify_start_round(
                    miner_uids=full_uids,
                    axons=full_axons,
                    round_id=round_id,
                    note="Round starting",
                    timeout=12,
                )
            except Exception as e:
                bt.logging.warning(f"notify_start_round failed (continuing with zero responders): {e}")

            active_mask = [uid in responders for uid in full_uids]
            active_uids = [uid for uid, ok in zip(full_uids, active_mask) if ok]
            active_axons = [ax for ax, ok in zip(full_axons, active_mask) if ok]

            if not active_uids:
                self.burn_all(uids=full_uids)
                elapsed = time.time() - t0
                self.lb.log_event_simple(
                    validator_uid=int(self.uid),
                    round_id=round_id,
                    phase=Phase.ERROR,
                    message="No active miners responded to StartRound; burn_all.",
                    extra={"elapsed_sec": elapsed, "total_miners": len(full_uids)},
                )
                if FORWARD_SLEEP_SECONDS > 0:
                    bt.logging.info(f"Sleeping {FORWARD_SLEEP_SECONDS}s…")
                    await asyncio.sleep(FORWARD_SLEEP_SECONDS)
                return

            # Miner metadata
            active_hotkeys = [self.metagraph.hotkeys[uid] for uid in active_uids]
            active_coldkeys = [self.metagraph.coldkeys[uid] for uid in active_uids]

            # Stats collector (for console table only)
            stats = ForwardStats(
                miner_uids=active_uids,
                miner_hotkeys=active_hotkeys,
                miner_coldkeys=active_coldkeys,
            )
            stats.start(forward_id=self.forward_count)

            # Phase 1: tasks plan
            self.lb.log_event_simple(
                validator_uid=int(self.uid),
                round_id=round_id,
                phase=Phase.GENERATING_TASKS,
                message="Generating Task Plan",
            )
            task_plan: TaskPlan = await get_task_plan(
                prompts_per_use_case=1,
            )

            max_tasks = self._cap_one_per_use_case(task_plan)

            # Send tasks
            self.lb.log_event_simple(
                validator_uid=int(self.uid),
                round_id=round_id,
                phase=Phase.SENDING_TASKS,
                message=f"Sending {max_tasks} tasks to {len(active_uids)} miners.",
            )
            per_task_results = await self.send_tasks(
                task_plan=task_plan,
                miner_uids=active_uids,
                miner_axons=active_axons,
                max_tasks=max_tasks,
                timeout=TIMEOUT,
            )

            # Evaluate
            self.lb.log_event_simple(
                validator_uid=int(self.uid),
                round_id=round_id,
                phase=Phase.EVALUATING_TASKS,
                message=f"Evaluating {len(per_task_results)} tasks.",
            )
            eval_outputs = await self.evaluate_tasks(
                per_task_results=per_task_results,
                n_miners=len(active_uids),
            )

            rewards_active, scored_tasks = await self.calculate_rewards(
                per_task_results=per_task_results,
                eval_outputs=eval_outputs,
                miner_uids=active_uids,
                eval_score_weight=EVAL_SCORE_WEIGHT,
                time_weight=TIME_WEIGHT,
            )

            # Stats feed (console only)
            for st in scored_tasks:
                stats.record_batch(
                    final_rewards=st.final_rewards,
                    eval_scores=st.eval_scores,
                    execution_times=st.execution_times,
                )

            # Feedback
            self.lb.log_event_simple(
                validator_uid=int(self.uid),
                round_id=round_id,
                phase=Phase.SENDING_FEEDBACK,
                message="Sending per-miner feedback for scored tasks.",
            )
            await self.send_feedback(
                scored_tasks=scored_tasks,
                miner_uids=active_uids,
                miner_axons=active_axons,
            )

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

            self.lb.log_event_simple(
                validator_uid=int(self.uid),
                round_id=round_id,
                phase=Phase.UPDATING_WEIGHTS,
                message="Updating weights on-chain (WTA).",
            )
            self.update_scores(rewards_full_wta, full_uids)
            self.set_weights()
            self.last_rewards = rewards_full_avg

            # Build + POST RoundResults once
            self._build_and_post_round_results(
                round_id=round_id,
                started_at=t0,
                full_uids=full_uids,
                active_uids=active_uids,
                active_hotkeys=active_hotkeys,
                active_coldkeys=active_coldkeys,
                scored_tasks=scored_tasks,
                rewards_full_avg=rewards_full_avg,
                rewards_full_wta=rewards_full_wta,
            )

            # Finish + console table
            summary = stats.finish()
            stats.render_table(summary, to_console=True)

            # Events: round_end + done
            elapsed = time.time() - t0
            self.lb.log_event_simple(
                validator_uid=int(self.uid),
                round_id=round_id,
                phase=Phase.ROUND_END,
                message=f"Round finished; elapsed {elapsed:.2f}s.",
                extra={"active_miners": len(active_uids), "total_miners": len(full_uids)},
            )
            self.lb.log_event_simple(
                validator_uid=int(self.uid),
                round_id=round_id,
                phase=Phase.DONE,
                message="Forward complete.",
            )

            if FORWARD_SLEEP_SECONDS > 0:
                bt.logging.info(f"Sleeping {FORWARD_SLEEP_SECONDS}s…")
                await asyncio.sleep(FORWARD_SLEEP_SECONDS)

        except Exception as err:
            bt.logging.error(f"Error in forward: {err}")
            try:
                round_id = f"Round-{self.forward_count}"
                self.lb.log_event_simple(
                    validator_uid=int(self.uid),
                    round_id=round_id,
                    phase=Phase.ERROR,
                    message=f"Forward crashed: {err}",
                )
            except Exception:
                pass


if __name__ == "__main__":
    # Initializing Dependency Injection In IWA
    app = AppBootstrap()

    # IWA logging works with loguru
    logger.remove()
    logger.add("logfile.log", level="INFO")
    logger.add(lambda msg: print(msg, end=""), level="WARNING")

    with Validator(config=config(role="validator")) as validator:
        while True:
            bt.logging.info(f"Validator running... {time.time()}")
            time.sleep(5)
