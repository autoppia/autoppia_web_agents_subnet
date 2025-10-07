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
from autoppia_web_agents_subnet.config import TIMEOUT, EVAL_SCORE_WEIGHT, TIME_WEIGHT, ROUND_SIZE_EPOCHS, AVG_TASK_DURATION_SECONDS, SAFETY_BUFFER_EPOCHS, PROMPTS_PER_USECASE, PRE_GENERATED_TASKS
from autoppia_web_agents_subnet.validator.tasks import get_task_plan, collect_task_solutions_and_execution_times  # returns TaskPlan
from autoppia_web_agents_subnet.validator.synapse_handlers import send_synapse_to_miners_generic, send_feedback_synapse_to_miners
from autoppia_web_agents_subnet.synapses import StartRoundSynapse, TaskSynapse
from autoppia_web_agents_subnet.validator.rewards import blend_eval_and_time, reduce_rewards_to_averages, pad_or_trim, wta_rewards
from autoppia_web_agents_subnet.validator.eval import evaluate_task_solutions
from autoppia_web_agents_subnet.validator.models import TaskPlan, PerTaskResult, ScoredTask, EvalOutput, ProjectTaskBatch
from autoppia_web_agents_subnet.validator.leaderboard import LeaderboardAPI, TaskInfo, TaskResult, AgentEvaluationRun, WeightsSnapshot, RoundResults
from autoppia_web_agents_subnet.validator.round_calculator import RoundCalculator
from autoppia_web_agents_subnet.utils.random import get_random_uids
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

        # ⭐ Round system components
        self.round_calculator = RoundCalculator(
            round_size_epochs=ROUND_SIZE_EPOCHS,
            avg_task_duration_seconds=AVG_TASK_DURATION_SECONDS,
            safety_buffer_epochs=SAFETY_BUFFER_EPOCHS,
        )

        # ⭐ Accumulated scores for the entire round
        self.round_scores = {}  # {miner_uid: [score1, score2, ...]}
        self.round_times = {}   # {miner_uid: [time1, time2, ...]}

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
            miner_axons=list(axons),
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

            task_synapse = TaskSynapse(prompt=task.prompt, url=task.url, html="", screenshot="", actions=[], version=self.version)
            bt.logging.info(f"[Phase 1 - Send {sent+1}/{max_tasks}] Broadcasting to {len(miner_axons)} active miners: '{task_synapse.prompt}' (URL: {task_synapse.url})")

            responses = await send_synapse_to_miners_generic(validator=self, miner_axons=list(miner_axons), synapse=task_synapse, timeout=timeout, retries=1)

            solutions_aligned, exec_times_aligned = collect_task_solutions_and_execution_times(task, responses, list(miner_uids))
            per_task_results.append(PerTaskResult(project=project, task=task, solutions=solutions_aligned, execution_times=exec_times_aligned))
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

    # ═══════════════════════════════════════════════════════════════════════════════
    # MAIN FORWARD LOOP - Round-based system
    # ═══════════════════════════════════════════════════════════════════════════════
    async def forward(self) -> None:
        """
        Execute the complete forward loop for the round.
        This forward spans the ENTIRE round (~24h):
        1. Pre-generates all tasks at the beginning
        2. Dynamic loop: sends tasks one by one based on time remaining
        3. Accumulates scores from all miners
        4. When finished, WAIT until target epoch
        5. Calculates averages, applies WTA, sets weights
        """
        bt.logging.warning("")
        bt.logging.warning("🚀 STARTING ROUND-BASED FORWARD")
        bt.logging.warning("=" * 80)

        # Get current block and calculate round boundaries
        current_block = self.metagraph.block.item()
        boundaries = self.round_calculator.get_round_boundaries(current_block)

        bt.logging.info(f"Round boundaries: start={boundaries['round_start_epoch']}, target={boundaries['target_epoch']}")

        # Log configuration summary
        self.round_calculator.log_calculation_summary()

        # ═══════════════════════════════════════════════════════
        # PRE-GENERATION: Generate all tasks at the beginning
        # ═══════════════════════════════════════════════════════
        bt.logging.warning("")
        bt.logging.warning("🔄 PRE-GENERATING TASKS")
        bt.logging.warning("=" * 80)

        pre_generation_start = time.time()
        all_tasks = []

        # Generate all tasks in batches
        tasks_generated = 0
        while tasks_generated < PRE_GENERATED_TASKS:
            batch_start = time.time()

            # Generate a batch of tasks
            task_plan: TaskPlan = await get_task_plan(prompts_per_use_case=PROMPTS_PER_USECASE)

            # Extract individual tasks from the plan
            for project_task_batch in task_plan.batches:
                for task in project_task_batch.tasks:
                    if tasks_generated >= PRE_GENERATED_TASKS:
                        break
                    all_tasks.append((project_task_batch.project, task))
                    tasks_generated += 1

            batch_elapsed = time.time() - batch_start
            bt.logging.info(f"   Generated batch: {len(task_plan.batches)} projects in {batch_elapsed:.1f}s (total: {tasks_generated}/{PRE_GENERATED_TASKS})")

        pre_generation_elapsed = time.time() - pre_generation_start
        bt.logging.warning(f"✅ Pre-generation complete: {len(all_tasks)} tasks in {pre_generation_elapsed:.1f}s")
        bt.logging.warning("=" * 80)

        # ═══════════════════════════════════════════════════════
        # DYNAMIC LOOP: Execute tasks one by one based on time
        # ═══════════════════════════════════════════════════════
        bt.logging.warning("")
        bt.logging.warning("🔄 STARTING DYNAMIC TASK EXECUTION")
        bt.logging.warning("=" * 80)

        start_block = current_block
        task_index = 0
        tasks_completed = 0

        # Dynamic loop: consume pre-generated tasks and check AFTER evaluating
        while task_index < len(all_tasks):
            current_block = self.metagraph.block.item()
            current_epoch = self.round_calculator.block_to_epoch(current_block)
            boundaries = self.round_calculator.get_round_boundaries(start_block)
            wait_info = self.round_calculator.get_wait_info(current_block, start_block)

            bt.logging.info(
                f"📍 TASK {task_index + 1}/{len(all_tasks)} | "
                f"Epoch {current_epoch:.2f}/{boundaries['target_epoch']} | "
                f"Time remaining: {wait_info['minutes_remaining']:.1f} min"
            )

            # Execute single task
            success = await self._execute_single_task(all_tasks[task_index], task_index, start_block)
            if success:
                tasks_completed += 1
            task_index += 1

            # Dynamic check: should we send another task?
            if not self.round_calculator.should_send_next_task(current_block, start_block):
                bt.logging.warning("")
                bt.logging.warning("🛑 STOPPING TASK EXECUTION - SAFETY BUFFER REACHED")
                bt.logging.warning(f"   Reason: Insufficient time remaining for another task")
                bt.logging.warning(f"   Current epoch: {current_epoch:.2f}")
                bt.logging.warning(f"   Time remaining: {wait_info['seconds_remaining']:.0f}s")
                bt.logging.warning(f"   Safety buffer: {SAFETY_BUFFER_EPOCHS} epochs")
                bt.logging.warning(f"   Tasks completed: {tasks_completed}/{len(all_tasks)}")
                bt.logging.warning(f"   ⏳ Now waiting for target epoch to set weights...")
                break

        # ═══════════════════════════════════════════════════════
        # WAIT FOR TARGET EPOCH: Wait until the round ends
        # ═══════════════════════════════════════════════════════
        if tasks_completed < len(all_tasks):
            await self._wait_for_target_epoch(start_block)

        # ═══════════════════════════════════════════════════════
        # FINAL WEIGHTS: Calculate averages, apply WTA, set weights
        # ═══════════════════════════════════════════════════════
        await self._calculate_final_weights(tasks_completed)

    # ═══════════════════════════════════════════════════════════════════════════════
    # TASK EXECUTION HELPERS
    # ═══════════════════════════════════════════════════════════════════════════════
    async def _execute_single_task(self, task_data, task_index: int, start_block: int) -> bool:
        """Execute a single task and accumulate results"""
        project, task = task_data

        try:
            # Get active miners
            active_uids = get_random_uids(
                self.metagraph,
                k=min(5, len(self.metagraph.uids)),
            )
            active_axons = [self.metagraph.axons[uid] for uid in active_uids]

            # Send task
            boundaries = self.round_calculator.get_round_boundaries(start_block)
            task_synapse = StartRoundSynapse(
                version=self.version,
                round_id=f"round_{boundaries['round_start_epoch']}",
                validator_id=str(self.uid),
                total_prompts=1,
                prompts_per_use_case=PROMPTS_PER_USECASE,
            )

            responses = await self.dendrite(
                axons=active_axons,
                synapse=task_synapse,
                deserialize=True,
                timeout=60,
            )

            # Process responses and calculate rewards
            task_solutions, execution_times = collect_task_solutions_and_execution_times(
                task=task,
                responses=responses,
                miner_uids=list(active_uids),
            )

            # Evaluate task solutions
            eval_scores, test_results_matrices, evaluation_results = await evaluate_task_solutions(
                web_project=project,
                task=task,
                task_solutions=task_solutions,
                execution_times=execution_times,
            )

            # Calculate rewards
            rewards = eval_scores.tolist()

            # Accumulate scores for the round
            for i, uid in enumerate(active_uids):
                if uid not in self.round_scores:
                    self.round_scores[uid] = []
                    self.round_times[uid] = []
                self.round_scores[uid].append(rewards[i])
                self.round_times[uid].append(execution_times[i])

            # Send feedback to miners
            try:
                await send_feedback_synapse_to_miners(
                    validator=self,
                    miner_axons=list(active_axons),
                    miner_uids=list(active_uids),
                    task=task,
                    rewards=rewards,
                    execution_times=execution_times,
                    task_solutions=task_solutions,
                    test_results_matrices=test_results_matrices,
                    evaluation_results=evaluation_results,
                )
            except Exception as e:
                bt.logging.warning(f"Feedback failed: {e}")

            bt.logging.info(f"✅ Task {task_index + 1} completed")
            return True

        except Exception as e:
            bt.logging.error(f"Task execution failed: {e}")
            return False

    async def _wait_for_target_epoch(self, start_block: int):
        """Wait for the target epoch to set weights"""
        bt.logging.warning("")
        bt.logging.warning("⏳ WAITING FOR TARGET EPOCH")
        bt.logging.warning("=" * 80)

        boundaries = self.round_calculator.get_round_boundaries(start_block)
        target_epoch = boundaries['target_epoch']

        while True:
            current_block = self.metagraph.block.item()
            current_epoch = self.round_calculator.block_to_epoch(current_block)
            wait_info = self.round_calculator.get_wait_info(current_block, start_block)

            if wait_info["reached_target"]:
                bt.logging.warning(f"🎯 Target epoch {target_epoch} REACHED!")
                bt.logging.warning(f"   Current epoch: {current_epoch:.2f}")
                break

            bt.logging.info(f"⏳ Waiting... Current: {current_epoch:.2f}, Target: {target_epoch}, Remaining: {wait_info['minutes_remaining']:.1f} min")

            # Wait for next block
            await asyncio.sleep(12)  # Wait for next block

        bt.logging.warning("=" * 80)

    async def _calculate_final_weights(self, tasks_completed: int):
        """Calculate averages, apply WTA, set weights"""
        bt.logging.warning("")
        bt.logging.warning("🏁 CALCULATING FINAL WEIGHTS")
        bt.logging.warning("=" * 80)

        # Calculate average scores for each miner
        avg_scores = {}
        for uid, scores in self.round_scores.items():
            if scores:
                avg_scores[uid] = sum(scores) / len(scores)
            else:
                avg_scores[uid] = 0.0

        bt.logging.info(f"Round scores: {len(avg_scores)} miners with scores")
        for uid, score in avg_scores.items():
            bt.logging.info(f"  Miner {uid}: {score:.3f} (from {len(self.round_scores[uid])} tasks)")

        # Apply WTA to get final weights
        # Convert dict to numpy array for wta_rewards
        uids = list(avg_scores.keys())
        scores_array = np.array([avg_scores[uid] for uid in uids], dtype=np.float32)
        final_weights_array = wta_rewards(scores_array)

        # Convert back to dict
        final_weights = {uid: float(weight) for uid, weight in zip(uids, final_weights_array)}

        bt.logging.warning("")
        bt.logging.warning("🎯 FINAL WEIGHTS (WTA)")
        bt.logging.warning("=" * 80)
        for uid, weight in final_weights.items():
            if weight > 0:
                bt.logging.warning(f"  🏆 Miner {uid}: {weight:.3f}")
            else:
                bt.logging.info(f"  ❌ Miner {uid}: {weight:.3f}")

        # Set weights (store in validator for set_weights to use)
        self.last_rewards = np.zeros(len(self.metagraph.uids), dtype=np.float32)
        for uid, weight in final_weights.items():
            if uid < len(self.last_rewards):
                self.last_rewards[uid] = weight
        self.set_weights()

        bt.logging.warning("")
        bt.logging.warning("✅ ROUND COMPLETE")
        bt.logging.warning("=" * 80)
        bt.logging.warning(f"Tasks completed: {tasks_completed}")
        bt.logging.warning(f"Miners evaluated: {len(avg_scores)}")
        winner_uid = max(avg_scores.keys(), key=lambda k: avg_scores[k]) if avg_scores else None
        bt.logging.warning(f"Winner: {winner_uid}")


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
