from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

import bittensor as bt

from autoppia_web_agents_subnet.validator.models import TaskWithProject
from autoppia_web_agents_subnet.validator.config import ROUND_SIZE_EPOCHS, IWAP_API_BASE_URL
from autoppia_web_agents_subnet.platform.iwa import models as iwa_models
from autoppia_web_agents_subnet.platform.iwa import main as iwa_main


class ValidatorPlatformMixin:
    """
    Shared IWAP integration helpers extracted from the validator loop.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.iwap_client = iwa_main.IWAPClient(base_url=IWAP_API_BASE_URL)
        self.current_round_id: Optional[str] = None
        self.current_round_tasks: Dict[str, iwa_models.TaskIWAP] = {}
        self.current_agent_runs: Dict[int, iwa_models.AgentRunIWAP] = {}
        self.current_miner_snapshots: Dict[int, iwa_models.MinerSnapshotIWAP] = {}
        self.round_handshake_payloads: Dict[int, Any] = {}
        self.round_start_timestamp: float = 0.0
        self.agent_run_accumulators: Dict[int, Dict[str, float]] = {}

    def _generate_validator_round_id(self) -> str:
        return iwa_main.generate_validator_round_id()

    def _build_validator_identity(self) -> iwa_models.ValidatorIdentityIWAP:
        coldkey = getattr(getattr(self.wallet, "coldkeypub", None), "ss58_address", None)
        return iwa_models.ValidatorIdentityIWAP(
            uid=int(self.uid),
            hotkey=self.wallet.hotkey.ss58_address,
            coldkey=coldkey,
        )

    def _metagraph_numeric(self, attribute: str, uid: int) -> Optional[float]:
        collection = getattr(self.metagraph, attribute, None)
        if collection is None:
            return None
        try:
            value = collection[uid]
            if hasattr(value, "item"):
                return float(value.item())
            return float(value)
        except Exception:
            return None

    def _build_validator_snapshot(self, validator_round_id: str) -> iwa_models.ValidatorSnapshotIWAP:
        stake = self._metagraph_numeric("S", self.uid)
        vtrust = (
            self._metagraph_numeric("v_trust", self.uid)
            or self._metagraph_numeric("vtrust", self.uid)
        )
        metadata: Dict[str, Any] = {"source": "autoppia_validator"}

        return iwa_models.ValidatorSnapshotIWAP(
            validator_round_id=validator_round_id,
            validator_uid=int(self.uid),
            validator_hotkey=self.wallet.hotkey.ss58_address,
            name=getattr(self.config.neuron, "name", None),
            stake=stake,
            vtrust=vtrust,
            image_url=None,
            version=self.version,
            metadata=metadata,
        )

    def _build_iwap_tasks(
        self,
        *,
        validator_round_id: str,
        tasks: List[TaskWithProject],
    ) -> Dict[str, iwa_models.TaskIWAP]:
        task_map: Dict[str, iwa_models.TaskIWAP] = {}
        for index, task_item in enumerate(tasks):
            task = task_item.task
            project = task_item.project
            task_id = getattr(task, "id", None) or f"{validator_round_id}_task_{index:04d}"

            specifications = {}
            if hasattr(task, "specifications") and task.specifications is not None:
                try:
                    specifications = task.specifications.model_dump(mode="json", exclude_none=True)  # type: ignore[attr-defined]
                except Exception:
                    specifications = dict(getattr(task, "specifications", {}) or {})

            tests: List[Dict[str, Any]] = []
            for test in getattr(task, "tests", []) or []:
                if hasattr(test, "model_dump"):
                    tests.append(test.model_dump(mode="json", exclude_none=True))
                else:
                    tests.append(dict(test))

            use_case_payload: Dict[str, Any] = {}
            if getattr(task, "use_case", None) is not None:
                use_case = getattr(task, "use_case")
                if hasattr(use_case, "serialize"):
                    try:
                        use_case_payload = use_case.serialize()
                    except Exception:
                        use_case_payload = {}
                elif hasattr(use_case, "model_dump"):
                    use_case_payload = use_case.model_dump(mode="json", exclude_none=True)

            relevant_data = getattr(task, "relevant_data", {}) or {}
            if not isinstance(relevant_data, dict):
                relevant_data = {"value": relevant_data}

            task_model = iwa_models.TaskIWAP(
                task_id=task_id,
                validator_round_id=validator_round_id,
                sequence=index,
                scope="local",
                is_web_real=bool(getattr(task, "is_web_real", False)),
                web_project_id=getattr(project, "id", None),
                url=getattr(task, "url", getattr(project, "frontend_url", "")),
                prompt=getattr(task, "prompt", ""),
                html=getattr(task, "html", "") or "",
                clean_html=getattr(task, "clean_html", "") or "",
                specifications=specifications,
                tests=tests,
                relevant_data=relevant_data,
                use_case=use_case_payload,
                should_record=bool(getattr(task, "should_record", False)),
                interactive_elements=None,
                screenshot=getattr(task, "screenshot", None),
                screenshot_description=getattr(task, "screenshot_description", None),
                milestones=None,
                success_criteria=getattr(task, "success_criteria", None),
            )
            task_map[task_id] = task_model
        return task_map

    async def _iwap_start_round(self, *, current_block: int, n_tasks: int) -> None:
        if not self.current_round_id:
            return

        validator_identity = self._build_validator_identity()
        validator_snapshot = self._build_validator_snapshot(self.current_round_id)
        boundaries = self.round_manager.get_current_boundaries()
        max_epochs = max(1, int(round(ROUND_SIZE_EPOCHS))) if ROUND_SIZE_EPOCHS else 1
        start_epoch_raw = boundaries["round_start_epoch"]
        start_epoch = math.floor(start_epoch_raw)
        round_metadata: Dict[str, Any] = {
            "round_start_epoch_raw": start_epoch_raw,
            "target_epoch": boundaries.get("target_epoch"),
        }

        validator_round = iwa_models.ValidatorRoundIWAP(
            validator_round_id=self.current_round_id,
            round_number=1,
            validator_uid=int(self.uid),
            validator_hotkey=validator_identity.hotkey,
            validator_coldkey=validator_identity.coldkey,
            start_block=current_block,
            start_epoch=start_epoch,
            max_epochs=max_epochs,
            max_blocks=self.round_manager.BLOCKS_PER_EPOCH,
            n_tasks=n_tasks,
            n_miners=len(self.active_miner_uids),
            n_winners=max(1, len(self.active_miner_uids)) if self.active_miner_uids else 1,
            started_at=self.round_start_timestamp or time.time(),
            summary={"tasks": n_tasks},
            metadata=round_metadata,
        )

        try:
            await self.iwap_client.start_round(
                validator_identity=validator_identity,
                validator_round=validator_round,
                validator_snapshot=validator_snapshot,
            )
            await self.iwap_client.set_tasks(
                validator_round_id=self.current_round_id,
                tasks=self.current_round_tasks.values(),
            )
        except Exception:
            bt.logging.warning("Unable to start IWAP round ingestion", exc_info=True)
            return

        coldkeys = getattr(self.metagraph, "coldkeys", [])
        now_ts = time.time()
        for miner_uid in self.active_miner_uids:
            miner_hotkey = None
            try:
                miner_hotkey = self.metagraph.hotkeys[miner_uid]
            except Exception:
                pass

            miner_coldkey = None
            try:
                if coldkeys:
                    miner_coldkey = coldkeys[miner_uid]
            except Exception:
                miner_coldkey = None

            handshake_payload = self.round_handshake_payloads.get(miner_uid)

            miner_identity = iwa_main.build_miner_identity(
                miner_uid=miner_uid,
                miner_hotkey=miner_hotkey,
                miner_coldkey=miner_coldkey,
                agent_key=None,
            )
            miner_snapshot = iwa_main.build_miner_snapshot(
                validator_round_id=self.current_round_id,
                miner_uid=miner_uid,
                miner_hotkey=miner_hotkey,
                miner_coldkey=miner_coldkey,
                agent_key=None,
                handshake_payload=handshake_payload,
                now_ts=now_ts,
            )

            agent_run_id = iwa_main.generate_agent_run_id(miner_uid)
            agent_run = iwa_models.AgentRunIWAP(
                agent_run_id=agent_run_id,
                validator_round_id=self.current_round_id,
                validator_uid=int(self.uid),
                validator_hotkey=validator_identity.hotkey,
                miner_uid=miner_uid,
                miner_hotkey=miner_hotkey,
                miner_agent_key=None,
                is_sota=False,
                version=getattr(handshake_payload, "agent_version", None),
                started_at=now_ts,
                metadata={"handshake_note": getattr(handshake_payload, "note", None)},
            )

            try:
                await self.iwap_client.start_agent_run(
                    validator_round_id=self.current_round_id,
                    agent_run=agent_run,
                    miner_identity=miner_identity,
                    miner_snapshot=miner_snapshot,
                )
                self.current_agent_runs[miner_uid] = agent_run
                self.current_miner_snapshots[miner_uid] = miner_snapshot
                self.agent_run_accumulators[miner_uid] = {
                    "reward": 0.0,
                    "score": 0.0,
                    "execution_time": 0.0,
                    "tasks": 0,
                }
            except Exception:
                bt.logging.warning(
                    f"Unable to start IWAP agent run for miner {miner_uid}",
                    exc_info=True,
                )

    async def _iwap_submit_task_results(
        self,
        *,
        task_item: TaskWithProject,
        task_solutions,
        eval_scores,
        test_results_matrices,
        evaluation_results,
        execution_times,
        rewards: List[float],
    ) -> None:
        if not self.current_round_id or not self.current_round_tasks:
            return

        task = task_item.task
        task_id = getattr(task, "id", None)
        if task_id is None:
            return

        task_payload = self.current_round_tasks.get(task_id)
        if task_payload is None:
            return

        validator_hotkey = self.wallet.hotkey.ss58_address

        for idx, miner_uid in enumerate(self.active_miner_uids):
            if idx >= len(task_solutions):
                break

            agent_run = self.current_agent_runs.get(miner_uid)
            if agent_run is None:
                continue

            miner_hotkey = None
            try:
                miner_hotkey = self.metagraph.hotkeys[miner_uid]
            except Exception:
                miner_hotkey = None

            solution = task_solutions[idx]
            actions_payload: List[Dict[str, Any]] = []
            for action in getattr(solution, "actions", []) or []:
                if hasattr(action, "model_dump"):
                    actions_payload.append(action.model_dump(mode="json", exclude_none=True))
                elif hasattr(action, "__dict__"):
                    actions_payload.append(dict(action.__dict__))
                else:
                    actions_payload.append({"type": getattr(action, "type", "unknown")})

            task_solution_id = iwa_main.generate_task_solution_id(task_id, miner_uid)
            evaluation_id = iwa_main.generate_evaluation_id(task_id, miner_uid)
            final_score = float(eval_scores[idx]) if idx < len(eval_scores) else 0.0
            evaluation_meta = evaluation_results[idx] if idx < len(evaluation_results) else {}
            if not isinstance(evaluation_meta, dict):
                evaluation_meta = {}
            test_matrix = test_results_matrices[idx] if idx < len(test_results_matrices) else []
            exec_time = float(execution_times[idx]) if idx < len(execution_times) else 0.0
            reward_value = rewards[idx] if idx < len(rewards) else final_score

            task_solution_payload = iwa_models.TaskSolutionIWAP(
                solution_id=task_solution_id,
                task_id=task_id,
                agent_run_id=agent_run.agent_run_id,
                validator_round_id=self.current_round_id,
                validator_uid=int(self.uid),
                validator_hotkey=validator_hotkey,
                miner_uid=miner_uid,
                miner_hotkey=miner_hotkey,
                miner_agent_key=None,
                actions=actions_payload,
                web_agent_id=getattr(solution, "web_agent_id", None),
                recording=getattr(solution, "recording", None),
            )

            evaluation_result_payload = iwa_models.EvaluationResultIWAP(
                evaluation_id=evaluation_id,
                validator_round_id=self.current_round_id,
                agent_run_id=agent_run.agent_run_id,
                task_id=task_id,
                task_solution_id=task_solution_id,
                validator_uid=int(self.uid),
                miner_uid=miner_uid,
                final_score=final_score,
                test_results_matrix=test_matrix or [],
                execution_history=evaluation_meta.get("execution_history", []),
                feedback=evaluation_meta.get("feedback"),
                web_agent_id=getattr(solution, "web_agent_id", None),
                raw_score=evaluation_meta.get("raw_score", final_score),
                evaluation_time=evaluation_meta.get("evaluation_time", exec_time),
                stats=evaluation_meta.get("stats"),
                gif_recording=evaluation_meta.get("gif_recording"),
                metadata=evaluation_meta,
            )

            try:
                await self.iwap_client.add_evaluation(
                    validator_round_id=self.current_round_id,
                    agent_run_id=agent_run.agent_run_id,
                    task=task_payload,
                    task_solution=task_solution_payload,
                    evaluation_result=evaluation_result_payload,
                )
            except Exception:
                bt.logging.warning(
                    f"Failed to submit IWAP evaluation for miner {miner_uid} task {task_id}",
                    exc_info=True,
                )

            accumulators = self.agent_run_accumulators.setdefault(
                miner_uid,
                {"reward": 0.0, "score": 0.0, "execution_time": 0.0, "tasks": 0},
            )
            accumulators["reward"] += float(reward_value)
            accumulators["score"] += float(final_score)
            accumulators["execution_time"] += exec_time
            accumulators["tasks"] += 1

            agent_run.total_tasks = accumulators["tasks"]
            agent_run.completed_tasks = accumulators["tasks"]
            agent_run.total_reward = accumulators["reward"]
            agent_run.average_reward = accumulators["reward"] / accumulators["tasks"]
            agent_run.average_score = accumulators["score"] / accumulators["tasks"]
            agent_run.average_execution_time = accumulators["execution_time"] / accumulators["tasks"]

    async def _finish_iwap_round(
        self,
        *,
        avg_rewards: Dict[int, float],
        final_weights: Dict[int, float],
        tasks_completed: int,
    ) -> None:
        if not self.current_round_id:
            return

        ended_at = time.time()
        for agent_run in self.current_agent_runs.values():
            agent_run.ended_at = ended_at
            agent_run.elapsed_sec = max(0.0, ended_at - agent_run.started_at)

        sorted_miners = sorted(avg_rewards.items(), key=lambda item: item[1], reverse=True)
        winners: List[iwa_models.RoundWinnerIWAP] = []
        winner_scores: List[float] = []
        for rank, (uid, score) in enumerate(sorted_miners[:3], start=1):
            miner_hotkey = None
            try:
                miner_hotkey = self.metagraph.hotkeys[uid]
            except Exception:
                miner_hotkey = None
            winners.append(
                iwa_models.RoundWinnerIWAP(
                    miner_uid=uid,
                    miner_hotkey=miner_hotkey,
                    rank=rank,
                    score=float(score),
                )
            )
            winner_scores.append(float(score))

        weights_payload = {str(uid): float(weight) for uid, weight in final_weights.items()}
        summary = {
            "tasks_completed": tasks_completed,
            "active_miners": len(avg_rewards),
        }

        finish_request = iwa_models.FinishRoundIWAP(
            status="completed",
            winners=winners,
            winner_scores=winner_scores,
            weights=weights_payload,
            ended_at=ended_at,
            summary=summary,
        )

        try:
            await self.iwap_client.finish_round(
                validator_round_id=self.current_round_id,
                finish_request=finish_request,
            )
        finally:
            self._reset_iwap_round_state()

    def _reset_iwap_round_state(self) -> None:
        self.current_round_id = None
        self.current_round_tasks = {}
        self.current_agent_runs = {}
        self.current_miner_snapshots = {}
        self.round_handshake_payloads = {}
        self.round_start_timestamp = 0.0
        self.agent_run_accumulators = {}
