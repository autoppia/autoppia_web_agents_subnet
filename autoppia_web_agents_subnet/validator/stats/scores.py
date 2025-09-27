afrom __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

import bittensor as bt
import numpy as np

from autoppia_web_agents_subnet.validator.stats import finalize_forward_stats as _finalize_forward_stats
from autoppia_web_agents_subnet.validator.forward_utils import save_forward_report
from autoppia_web_agents_subnet.validator.stats.visualization import print_forward_tables


@dataclass
class ForwardState:
    """Accumulators and counters for a forward."""
    n: int
    accumulated_rewards: np.ndarray = field(init=False)
    tasks_evaluated_per_miner: np.ndarray = field(init=False)

    # Global KPIs
    tasks_sent: int = 0
    tasks_success: int = 0
    sum_avg_response_times: float = 0.0
    miner_successes_total: int = 0
    miner_attempts_total: int = 0

    # For human/report output
    sent_tasks_records: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.accumulated_rewards = np.zeros(self.n, dtype=np.float32)
        self.tasks_evaluated_per_miner = np.zeros(self.n, dtype=np.int32)

    def merge(self, result: "EvalResult") -> None:
        """Merge an immutable evaluation result into the state."""
        self.accumulated_rewards += result.accumulated_rewards_delta
        self.tasks_evaluated_per_miner += result.tasks_evaluated_per_miner_delta
        self.tasks_sent += result.tasks_sent
        self.tasks_success += result.tasks_success
        self.sum_avg_response_times += result.sum_avg_response_times
        self.miner_successes_total += result.miner_successes_total
        self.miner_attempts_total += result.miner_attempts_total
        self.sent_tasks_records.extend(result.sent_tasks_records)


@dataclass(frozen=True)
class EvalResult:
    """Immutable result of evaluating a set of tasks."""
    accumulated_rewards_delta: np.ndarray
    tasks_evaluated_per_miner_delta: np.ndarray
    tasks_sent: int
    tasks_success: int
    sum_avg_response_times: float
    miner_successes_total: int
    miner_attempts_total: int
    sent_tasks_records: List[Dict[str, Any]]


async def update_scores_from_state(self, state: ForwardState) -> None:
    """Compute per-miner averages and update validator scores."""
    if state.tasks_sent == 0:
        bt.logging.warning("[update] no tasks processed; scores unchanged.")
        return

    counts = np.maximum(state.tasks_evaluated_per_miner, 1)
    average_rewards = state.accumulated_rewards / counts.astype(np.float32)

    bt.logging.info(
        f"Average rewards - Min: {average_rewards.min():.4f}, "
        f"Max: {average_rewards.max():.4f}, Mean: {average_rewards.mean():.4f}"
    )

    # Debug top slice
    rows = []
    for uid in range(self.metagraph.n):
        hk = self.metagraph.hotkeys[uid]
        ck = self.metagraph.coldkeys[uid]
        s = float(average_rewards[uid])
        rows.append((uid, hk, ck, s))
    rows.sort(key=lambda x: x[3], reverse=True)

    bt.logging.info("=== [FORWARD AVG] uid/hk/ck/avg_reward (sorted) ===")
    for uid, hk, ck, s in rows[:25]:
        bt.logging.info(f"[AVG] uid={uid:<3} hk={hk[:10]}… ck={ck[:10]}…  avg_reward={s:.6f}")

    async with self.lock:
        self.update_scores(average_rewards, list(range(self.metagraph.n)))

    bt.logging.info(f"[update] updated_uids={self.metagraph.n} with average rewards")


def finish_stats(self, t_forward_start: float, state: ForwardState, forward_id: int) -> None:
    """
    Finalize KPIs, persist summary + tasks, and print tables.
    """
    forward_time = time.time() - t_forward_start
    summary = _finalize_forward_stats(
        self,
        tasks_sent=state.tasks_sent,
        sum_avg_response_times=state.sum_avg_response_times,
        forward_time=forward_time,
        miner_successes=state.miner_successes_total,
        miner_attempts=state.miner_attempts_total,
        forward_id=forward_id,
    )

    # Persist JSONL: last_forward, totals, tasks
    try:
        save_forward_report(
            summary=summary,
            tasks=state.sent_tasks_records,
        )
    except Exception as e:
        bt.logging.warning(f"Could not save forward_summary.jsonl: {e}")

    print_forward_tables(self.validator_performance_stats)
    bt.logging.success("Forward cycle completed!")


# ───────────────────────────────────────────────
# Helper para guardar resumen por forward
# ───────────────────────────────────────────────
import os
import json
from pathlib import Path
from collections import Counter
import bittensor as bt


def save_forward_report(summary: dict, tasks: list[dict] | None = None) -> None:
    ...

    """
    Escribe una línea JSON con ÚNICAMENTE:
      {
        "last_forward": {
            ...campos snapshot del forward...,
            "tasks": [ {web_project, use_case, prompt}, ... ],
            "task_counts_by_type": [ {web, use_case, tasks}, ... ]
        },
        "totals": {
            ...campos acumulados...,
            "task_counts_by_type": [ {web, use_case, tasks}, ... ]
        }
      }
    """
    try:
        reports_dir = Path(os.getenv("REPORTS_DIR", "forward_reports"))
        reports_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = reports_dir / "forward_summary.jsonl"

        # --- snapshot base del forward y acumulados que vienen de summary ---
        last_forward = dict(summary.get("forward", {}))
        totals = dict(summary.get("totals", {}))

        # --- tasks del forward + conteo por tipo en ESTE forward ---
        tasks = tasks or []
        fwd_counts = Counter((t.get("web_project", ""), t.get("use_case", "")) for t in tasks)
        last_forward["tasks"] = tasks
        last_forward["task_counts_by_type"] = [{"web": w, "use_case": uc, "tasks": c} for (w, uc), c in sorted(fwd_counts.items())]

        # --- conteo ACUMULADO por tipo (leyendo JSONL anterior) ---
        total_counts = Counter()
        if jsonl_path.exists():
            for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                # soporta formatos previos (tasks a nivel raíz o en last_forward)
                prev_tasks = rec.get("tasks", []) or rec.get("last_forward", {}).get("tasks", [])
                for t in prev_tasks:
                    total_counts[(t.get("web_project", ""), t.get("use_case", ""))] += 1

        # sumar también las tasks de este forward
        for (w, uc), c in fwd_counts.items():
            total_counts[(w, uc)] += c

        totals["task_counts_by_type"] = [{"web": w, "use_case": uc, "tasks": c} for (w, uc), c in sorted(total_counts.items())]

        # --- construir registro SOLO con last_forward y totals ---
        record = {
            "last_forward": last_forward,
            "totals": totals,
        }

        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        bt.logging.info("forward_summary.jsonl actualizado (last_forward + totals + tasks en last_forward).")
    except Exception as e:
        bt.logging.warning(f"No pude guardar forward_summary.jsonl: {e}")
