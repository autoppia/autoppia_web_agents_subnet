# autoppia_web_agents_subnet/validator/leaderboard/data_processor.py
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import bittensor as bt
import numpy as np

from .api_client import TaskInfo, TaskResult, AgentEvaluationRun, WeightsSnapshot, RoundResults


class DataProcessor:
    """
    Processes and prepares data for leaderboard posting.
    Combines data preparation and results building functionality.
    """

    def prepare_round_data(
        self,
        validator,
        start_block: int,
        tasks_completed: int,
        avg_scores: Dict[int, float],
        final_weights: Dict[int, float],
        round_manager,
    ) -> Dict[str, Any]:
        """
        Prepare all data needed for leaderboard posting.
        SIMPLIFIED to work with available data.
        """
        boundaries = round_manager.get_round_boundaries(start_block)
        round_id = f"round_{boundaries['round_start_epoch']}"

        # Get all UIDs and active UIDs
        full_uids = list(range(len(validator.metagraph.uids)))
        active_uids = list(avg_scores.keys())

        # Get hotkeys and coldkeys for active miners
        active_hotkeys = [validator.metagraph.hotkeys[uid] for uid in active_uids]
        active_coldkeys = [validator.metagraph.coldkeys[uid] for uid in active_uids]

        # Convert scores to numpy arrays for leaderboard
        rewards_full_avg = np.zeros(len(full_uids), dtype=np.float32)
        rewards_full_wta = np.zeros(len(full_uids), dtype=np.float32)

        for uid in active_uids:
            if uid < len(rewards_full_avg):
                rewards_full_avg[uid] = avg_scores[uid]
                rewards_full_wta[uid] = final_weights[uid]

        return {
            "round_id": round_id,
            "started_at": time.time() - (start_block * 12),  # Approximate start time
            "full_uids": full_uids,
            "active_uids": active_uids,
            "active_hotkeys": active_hotkeys,
            "active_coldkeys": active_coldkeys,
            "rewards_full_avg": rewards_full_avg,
            "rewards_full_wta": rewards_full_wta,
            "tasks_completed": tasks_completed,
        }

    def build_round_results(
        self,
        validator,
        round_data: Dict[str, Any],
    ) -> RoundResults:
        """
        Builds a RoundResults object from prepared data.
        """
        # 1) Winner (by WTA)
        winner_uid = self._find_winner(validator, round_data)

        # 2) Task information (simplified - no individual tasks)
        tasks_info = self._build_tasks_info_simple(round_data)

        # 3) Agent runs (simplified - using available data)
        agent_runs = self._build_agent_runs_simple(validator, round_data)

        # 4) Build final RoundResults
        ended_at = time.time()
        rr = RoundResults(
            validator_uid=int(validator.uid),
            round_id=round_data["round_id"],
            version=validator.version,
            started_at=float(round_data["started_at"]),
            ended_at=float(ended_at),
            elapsed_sec=float(ended_at - round_data["started_at"]),
            n_active_miners=len(round_data["active_uids"]),
            n_total_miners=len(round_data["full_uids"]),
            tasks=tasks_info,
            agent_runs=agent_runs,
            weights=WeightsSnapshot(
                full_uids=[int(u) for u in round_data["full_uids"]],
                rewards_full_avg=[float(x) for x in round_data["rewards_full_avg"]],
                rewards_full_wta=[float(x) for x in round_data["rewards_full_wta"]],
                winner_uid=int(winner_uid) if winner_uid is not None else None,
            ),
            meta={"tasks_sent": round_data.get("tasks_completed", 0)},
        )

        return rr

    def _find_winner(self, validator, round_data: Dict[str, Any]) -> Optional[int]:
        """Find the winner UID by WTA"""
        winner_uid: Optional[int] = None
        try:
            winner_full_index = int(np.argmax(round_data["rewards_full_wta"]))
            winner_uid = int(round_data["full_uids"][winner_full_index])
            winner_hotkey = validator.metagraph.hotkeys[winner_uid]
            bt.logging.info(f"[forward #{validator.forward_count}] WTA winner UID={winner_uid} hotkey={winner_hotkey}")
        except Exception:
            pass
        return winner_uid

    def _build_tasks_info_simple(self, round_data: Dict[str, Any]) -> List[TaskInfo]:
        """Build simplified task information"""
        tasks_info: List[TaskInfo] = []

        # Create a simple task info for the round
        tasks_info.append(
            TaskInfo(
                task_id=f"round_{round_data['round_id']}",
                prompt=f"Round with {round_data.get('tasks_completed', 0)} tasks",
                website="",
                web_project="",
                use_case="round_evaluation",
            )
        )

        return tasks_info

    def _build_agent_runs_simple(self, validator, round_data: Dict[str, Any]) -> List[AgentEvaluationRun]:
        """Build agent runs using available data - SIMPLIFIED VERSION"""
        agent_runs: List[AgentEvaluationRun] = []

        for i_miner, uid in enumerate(round_data["active_uids"]):
            # Get scores from available data
            avg_score = round_data["rewards_full_avg"][uid] if uid < len(round_data["rewards_full_avg"]) else 0.0
            final_weight = round_data["rewards_full_wta"][uid] if uid < len(round_data["rewards_full_wta"]) else 0.0

            # Create simple task result for the round
            miner_task_results: List[TaskResult] = []
            miner_task_results.append(
                TaskResult(
                    task_id=f"round_{round_data['round_id']}",
                    eval_score=float(avg_score),
                    execution_time=0.0,  # No individual timing available
                    time_score=0.0,
                    reward=float(avg_score),
                    solution={},
                    test_results={"results": []},
                    evaluation_result={},
                )
            )

            # Create agent run
            agent_runs.append(
                AgentEvaluationRun(
                    miner_uid=int(uid),
                    miner_hotkey=str(round_data["active_hotkeys"][i_miner]),
                    miner_coldkey=str(round_data["active_coldkeys"][i_miner]),
                    reward=float(avg_score),
                    eval_score=float(avg_score),
                    time_score=0.0,
                    execution_time=0.0,
                    task_results=miner_task_results,
                )
            )

        return agent_runs
