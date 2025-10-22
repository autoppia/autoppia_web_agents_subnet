from __future__ import annotations

from typing import Any, Dict, List, Optional

import bittensor as bt


class RoundPhaseValidatorMixin:
    """
    Phase-specific helpers for validator resume/rebuild.
    Holds logic that reconstructs accumulators and round aggregates
    from saved evaluation records after a crash.
    """

    def _rebuild_from_saved_evaluations(self) -> None:
        """Rebuild round accumulators and agent_run stats from saved evaluation records.

        Each record should be a dict: {
            'miner_uid': int,
            'task_id': str,
            'reward': float,
            'final_score': float,
            'exec_time': float,
        }
        """
        records = list(getattr(self, "_eval_records", []) or [])
        if not records:
            return
        try:
            bt.logging.info(
                f"Resume rebuild: restoring {len(records)} evaluation records"
            )
        except Exception:
            pass

        # Ensure accumulators exist for miners
        for rec in records:
            uid = int(rec.get("miner_uid")) if rec.get("miner_uid") is not None else None
            if uid is None:
                continue
            reward = float(rec.get("reward") or 0.0)
            score = float(rec.get("final_score") or 0.0)
            exec_time = float(rec.get("exec_time") or 0.0)

            acc = self.agent_run_accumulators.setdefault(
                uid, {"reward": 0.0, "score": 0.0, "execution_time": 0.0, "tasks": 0}
            )
            acc["reward"] += reward
            acc["score"] += score
            acc["execution_time"] += exec_time
            acc["tasks"] += 1

            # Update agent_run model snapshot if present
            run = getattr(self, "current_agent_runs", {}).get(uid)
            if run is not None:
                run.total_tasks = acc["tasks"]
                run.completed_tasks = acc["tasks"]
                run.total_reward = acc["reward"]
                run.average_reward = acc["reward"] / acc["tasks"] if acc["tasks"] else None
                run.average_score = acc["score"] / acc["tasks"] if acc["tasks"] else None
                run.average_execution_time = (
                    acc["execution_time"] / acc["tasks"] if acc["tasks"] else None
                )

            # Rebuild RoundManager aggregates directly
            try:
                rr = self.round_manager.round_rewards.setdefault(uid, [])
                rs = self.round_manager.round_eval_scores.setdefault(uid, [])
                rt = self.round_manager.round_times.setdefault(uid, [])
                rr.append(reward)
                rs.append(score)
                rt.append(exec_time)
            except Exception:
                # If round_manager is not initialized yet, caller will retry after init
                pass

