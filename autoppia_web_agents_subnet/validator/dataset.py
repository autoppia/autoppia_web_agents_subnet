from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import bittensor as bt


@dataclass
class RoundDatasetCollector:
    """
    Collects per-round tasks and miner solutions for IPFS publication and later verification.

    Notes:
    - Stores minimal JSON-ready structures only (no GIFs or binary blobs).
    - Tasks are stored once per task_id (with tests and specs) for deterministic re-evaluation.
    - Solutions store action dicts and identify miner_uid and task_id.
    - Evals store the eval_score computed by the evaluator (deterministic across validators).
    """

    # Mapping: task_id -> task JSON (with tests/specs included)
    tasks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Mapping: task_id -> web_project_id (string)
    task_projects: Dict[str, str] = field(default_factory=dict)
    # Flat list of solution records
    solutions: List[Dict[str, Any]] = field(default_factory=list)
    # Mapping: (task_id, miner_uid) -> eval_score/time
    evals: Dict[Tuple[str, int], Tuple[float, float]] = field(default_factory=dict)

    def add_task(self, *, project, task) -> None:
        try:
            tid = getattr(task, "id", None)
            if not tid:
                return
            if tid in self.tasks:
                return

            # Prefer nested_model_dump to include test objects cleanly
            task_json = None
            try:
                if hasattr(task, "nested_model_dump"):
                    task_json = task.nested_model_dump()
                elif hasattr(task, "model_dump"):
                    task_json = task.model_dump()
            except Exception:
                task_json = None
            if not isinstance(task_json, dict):
                return

            # Attach minimal linkage to project
            project_id = getattr(project, "id", None) or getattr(project, "name", None) or ""
            self.task_projects[str(tid)] = str(project_id)

            # Keep deterministic fields; rely on nested_model_dump/model_dump for full structure
            self.tasks[str(tid)] = task_json
        except Exception as e:
            bt.logging.debug(f"RoundDatasetCollector.add_task failed: {e}")

    def add_solutions(
        self,
        *,
        task_id: str,
        task_solutions: List[Any],
        eval_scores: List[float],
        execution_times: List[float],
        miner_uids: List[int],
    ) -> None:
        n = min(len(task_solutions), len(eval_scores), len(execution_times), len(miner_uids))
        for i in range(n):
            sol = task_solutions[i]
            uid = int(miner_uids[i])
            # Serialize actions to JSON-safe dicts; tolerate mixed models
            action_dicts: List[Dict[str, Any]] = []
            try:
                actions = getattr(sol, "actions", []) or []
                for a in actions:
                    if hasattr(a, "model_dump"):
                        action_dicts.append(a.model_dump(mode="json", exclude_none=True))
                    elif hasattr(a, "__dict__"):
                        action_dicts.append(dict(a.__dict__))
                    else:
                        action_dicts.append({"type": getattr(a, "type", "unknown")})
            except Exception:
                action_dicts = []

            self.solutions.append(
                {
                    "task_id": str(task_id),
                    "miner_uid": uid,
                    "actions": action_dicts,
                }
            )
            try:
                es = float(eval_scores[i])
            except Exception:
                es = 0.0
            try:
                et = float(execution_times[i])
            except Exception:
                et = 0.0
            self.evals[(str(task_id), uid)] = (es, et)

    def build_dataset(
        self,
        *,
        round_meta: Dict[str, Any],
        validator_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build dataset JSON. The caller should pass round and validator metadata fields.
        round_meta: {r, epoch_start, epoch_end}
        validator_meta: {uid, hotkey, version, validator_round_id}
        """
        # Flatten evals into a list for easy sampling
        eval_entries: List[Dict[str, Any]] = []
        for (tid, uid), (score, exec_t) in self.evals.items():
            eval_entries.append(
                {
                    "task_id": str(tid),
                    "miner_uid": int(uid),
                    "eval_score": float(score),
                    "time": float(exec_t),
                }
            )

        # Compact tasks: move project ids into tasks entries
        tasks_list: List[Dict[str, Any]] = []
        for tid, tj in self.tasks.items():
            item = dict(tj)
            item["id"] = tid
            proj_id = self.task_projects.get(tid)
            if proj_id is not None:
                item["web_project_id"] = proj_id
            tasks_list.append(item)

        ds = {
            "v": 1,
            "round": {
                "r": round_meta.get("r"),
                "epoch_start": round_meta.get("epoch_start"),
                "epoch_end": round_meta.get("epoch_end"),
            },
            "validator": {
                "uid": validator_meta.get("uid"),
                "hotkey": validator_meta.get("hotkey"),
                "version": validator_meta.get("version"),
                "validator_round_id": validator_meta.get("validator_round_id"),
            },
            "tasks": tasks_list,
            "solutions": self.solutions,
            "evals": eval_entries,
        }
        return ds

