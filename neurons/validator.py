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
from autoppia_web_agents_subnet.utils.random import get_random_uids
from autoppia_web_agents_subnet.config import (
    FORWARD_SLEEP_SECONDS,
    TIMEOUT,
    EVAL_SCORE_WEIGHT,
    TIME_WEIGHT,
)
from autoppia_web_agents_subnet.validator.tasks import get_tasks  # returns TaskPlan
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
)
from autoppia_web_agents_subnet.validator.eval import evaluate_task_solutions
from autoppia_web_agents_subnet.validator.models import (
    TaskPlan,
    PerTaskResult,
    ScoredTask,
    EvalOutput,
)
from autoppia_web_agents_subnet.bittensor_config import config
from autoppia_iwa_module.autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa_module.autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_web_agents_subnet.validator.stats.main import ForwardStats


class Validator(BaseValidatorNeuron):
    def __init__(self, config=None):
        super().__init__(config=config)
        self.forward_count = 0
        self.last_rewards: np.ndarray | None = None
        self.last_round_responses: Dict[int, StartRoundSynapse] = {}
        self.version: str = __version__

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
            # We run “one task per use-case across projects”; this is informational for miners
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
        """
        Broadcast tasks to miners.

        Returns:
          List[PerTaskResult] — one item per sent task, each already aligned to `miner_uids`.
        """
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

            # Already aligned to miner_uids by the helper:
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
    # NEW Phase 2A: Evaluate (only scoring & artifacts) — NO rewards here
    # ─────────────────────────────────────────────────────────────────────
    async def evaluate_tasks(
        self,
        *,
        per_task_results: List[PerTaskResult],
        n_miners: int,
    ) -> List[EvalOutput]:
        """
        Evalúa cada PerTaskResult y devuelve una lista de EvalOutput con:
          - eval_scores (vector alineado a los uids activos, tamaño n_miners)
          - test_results_matrices (por-miner)
          - evaluation_results (por-miner)
        NO realiza blending ni calcula recompensas aquí.
        """
        outputs: List[EvalOutput] = []

        for i, ptr in enumerate(per_task_results, start=1):
            try:
                eval_scores, test_results_matrices, evaluation_results = await evaluate_task_solutions(
                    web_project=ptr.project,
                    task=ptr.task,
                    task_solutions=ptr.solutions,
                    execution_times=ptr.execution_times,
                )
                # Garantiza tamaño n_miners por seguridad
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
    # (separated from evaluation; it consumes EvalOutput)
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
        """
        Mezcla eval_scores + execution_times por tarea para producir:
          - avg_rewards: vector promedio por-miner (alineado a miner_uids)
          - scored: List[ScoredTask] (con artifacts para feedback)
        """
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
    # Helper: derive “one per use-case across all projects” cap from TaskPlan
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def _cap_one_per_use_case(task_plan: TaskPlan) -> int:
        """
        Try to compute the number of tasks equal to (#use_cases across all projects),
        with robust fallbacks so we don't need to modify tasks.py.
        """
        # Preferred explicit fields if TaskPlan provides them:
        for attr in ("num_use_cases_total", "total_use_cases", "n_use_cases"):
            if hasattr(task_plan, attr):
                try:
                    v = int(getattr(task_plan, attr))
                    if v > 0:
                        return v
                except Exception:
                    pass

        # Fallback: if TaskPlan has a 'size' / '__len__'
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

        # Last resort: a safe, small cap to avoid sending too many
        return 16

    # ─────────────────────────────────────────────────────────────────────
    # Forward loop (drops StartRound non-responders; zeros elsewhere)
    # ─────────────────────────────────────────────────────────────────────
    async def forward(self) -> None:
        try:
            self.forward_count += 1
            bt.logging.info(f"[forward #{self.forward_count}] start (version {self.version})")
            t0 = time.time()

            # Full miner roster in a deterministic random order
            full_uid_array = get_random_uids(self, k=self.metagraph.n.item())
            full_uids: List[int] = full_uid_array.tolist()
            full_axons = [self.metagraph.axons[uid] for uid in full_uids]

            if not full_uids:
                bt.logging.warning("No miners in metagraph; skipping forward.")
                return

            # Phase 0: notify start, then filter to ACTIVE miners only
            round_id = f"Round-{self.forward_count}"
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

            # Build miner metadata for stats (only ACTIVE miners)
            active_hotkeys = [self.metagraph.hotkeys[uid] for uid in active_uids]
            active_coldkeys = [self.metagraph.coldkeys[uid] for uid in active_uids]

            # Init per-forward stats collector (decoupled module)
            stats = ForwardStats(
                miner_uids=active_uids,
                miner_hotkeys=active_hotkeys,
                miner_coldkeys=active_coldkeys,
            )
            stats.start(forward_id=self.forward_count)

            # Phase 1: tasks (“one per use-case across all projects”)
            # We ask for prompts_per_use_case=1 and let TaskPlan provide all use-cases.
            task_plan: TaskPlan = await get_tasks(
                total_prompts=10**9,            # effectively “no cap”; we’ll cap below
                prompts_per_use_case=1,
            )

            if task_plan.empty():
                bt.logging.warning("No tasks generated – burn_all and return.")
                self.burn_all(uids=full_uids)
                elapsed = time.time() - t0
                bt.logging.info(f"[forward #{self.forward_count}] no tasks; took {elapsed:.2f}s.")
                if FORWARD_SLEEP_SECONDS > 0:
                    bt.logging.info(f"Sleeping {FORWARD_SLEEP_SECONDS}s…")
                    await asyncio.sleep(FORWARD_SLEEP_SECONDS)
                return

            if not active_uids:
                bt.logging.warning("No active miners responded to StartRound; burn_all and return.")
                self.burn_all(uids=full_uids)
                elapsed = time.time() - t0
                bt.logging.info(f"[forward #{self.forward_count}] no active miners; took {elapsed:.2f}s.")
                if FORWARD_SLEEP_SECONDS > 0:
                    bt.logging.info(f"Sleeping {FORWARD_SLEEP_SECONDS}s…")
                    await asyncio.sleep(FORWARD_SLEEP_SECONDS)
                return

            max_tasks = self._cap_one_per_use_case(task_plan)

            # Phase 1: send tasks only to ACTIVE miners
            per_task_results = await self.send_tasks(
                task_plan=task_plan,
                miner_uids=active_uids,
                miner_axons=active_axons,
                max_tasks=max_tasks,
                timeout=TIMEOUT,
            )

            # Phase 2A: EVALUATE (get eval_scores + artifacts; NO rewards)
            eval_outputs = await self.evaluate_tasks(
                per_task_results=per_task_results,
                n_miners=len(active_uids),
            )

            # Phase 2B: BLEND → per-task final rewards, then average
            rewards_active, scored_tasks = await self.calculate_rewards(
                per_task_results=per_task_results,
                eval_outputs=eval_outputs,
                miner_uids=active_uids,
                eval_score_weight=EVAL_SCORE_WEIGHT,
                time_weight=TIME_WEIGHT,
            )

            # Feed stats collector (one record per task)
            for st in scored_tasks:
                stats.record_batch(
                    final_rewards=st.final_rewards,   # aligned to active_uids
                    eval_scores=st.eval_scores,       # aligned to active_uids
                    execution_times=st.execution_times,
                )

            # Phase 3: per-miner feedback for ACTIVE miners
            await self.send_feedback(
                scored_tasks=scored_tasks,
                miner_uids=active_uids,
                miner_axons=active_axons,
            )

            # --- Winner-Takes-All transform on averaged ACTIVE rewards ---
            from autoppia_web_agents_subnet.validator.rewards import wta_rewards
            raw_active_avg = rewards_active.copy()
            rewards_active_wta = wta_rewards(rewards_active)

            # Expand active rewards to full vector (both raw avg and WTA)
            rewards_full_avg = np.zeros(len(full_uids), dtype=np.float32)
            rewards_full_wta = np.zeros(len(full_uids), dtype=np.float32)

            uid_to_idx_active = {uid: i for i, uid in enumerate(active_uids)}
            for i_full, uid in enumerate(full_uids):
                idx_active = uid_to_idx_active.get(uid, None)
                if idx_active is not None:
                    rewards_full_avg[i_full] = raw_active_avg[idx_active]
                    rewards_full_wta[i_full] = rewards_active_wta[idx_active]
                # else: stays 0.0 for non-active miners

            # Use WTA for on-chain updates, keep dense avg locally for inspection/metrics
            self.update_scores(rewards_full_wta, full_uids)
            self.set_weights()
            self.last_rewards = rewards_full_avg  # keep the dense vector for analysis

            # Log the round winner (deterministic on ties: first max)
            try:
                winner_full_index = int(np.argmax(rewards_full_wta))
                winner_uid = full_uids[winner_full_index]
                winner_hotkey = self.metagraph.hotkeys[winner_uid]
                bt.logging.info(f"[forward #{self.forward_count}] WTA winner UID={winner_uid} hotkey={winner_hotkey}")
            except Exception:
                pass

            # Finish + render the per-forward ordered table (by avg_reward)
            summary = stats.finish()
            stats.render_table(summary, to_console=True)

            elapsed = time.time() - t0
            bt.logging.info(
                f"[forward #{self.forward_count}] updated {len(full_uids)} UIDs "
                f"({len(active_uids)} active); took {elapsed:.2f}s."
            )

            if FORWARD_SLEEP_SECONDS > 0:
                bt.logging.info(f"Sleeping {FORWARD_SLEEP_SECONDS}s…")
                await asyncio.sleep(FORWARD_SLEEP_SECONDS)

        except Exception as err:
            bt.logging.error(f"Error in forward: {err}")


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
