# autoppia_web_agents_subnet/validator/stats.py
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Sequence, Dict, Any, Optional

import numpy as np

# Rich is optional; if not installed, we gracefully fallback to plain text
try:
    from rich.table import Table
    from rich.console import Console
    from rich import box
    _RICH = True
except Exception:
    _RICH = False


def _pad_or_trim(vec: np.ndarray, n: int, fill: float = 0.0) -> np.ndarray:
    """Safety: ensure length n."""
    out = np.full(n, fill, dtype=np.float32)
    m = min(n, int(vec.shape[0]))
    out[:m] = vec[:m].astype(np.float32)
    return out


@dataclass
class ForwardStats:
    """
    Collector for a single forward.
    - No dependency on bittensor; validator passes metadata and per-task arrays.
    - Aggregates per-miner sums and counts to produce averages for this forward.
    """
    miner_uids: Sequence[int]
    miner_hotkeys: Sequence[str]
    miner_coldkeys: Sequence[str]

    # internal accumulators
    _started_at: float = field(default=0.0, init=False)
    _forward_id: Optional[int] = field(default=None, init=False)
    _n: int = field(init=False)
    _tasks_sent: int = field(default=0, init=False)

    _sum_rewards: np.ndarray = field(init=False)
    _sum_eval_scores: np.ndarray = field(init=False)
    _sum_exec_times: np.ndarray = field(init=False)
    _counts: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self._n = len(self.miner_uids)
        if not (len(self.miner_hotkeys) == len(self.miner_coldkeys) == self._n):
            raise ValueError("miner_uids, miner_hotkeys, miner_coldkeys must have same length.")
        self._sum_rewards = np.zeros(self._n, dtype=np.float32)
        self._sum_eval_scores = np.zeros(self._n, dtype=np.float32)
        self._sum_exec_times = np.zeros(self._n, dtype=np.float32)
        self._counts = np.zeros(self._n, dtype=np.int32)

    # ---- lifecycle ----
    def start(self, forward_id: int | None = None) -> None:
        self._forward_id = forward_id
        self._started_at = time.time()

    def record_batch(
        self,
        *,
        final_rewards: np.ndarray,
        eval_scores: np.ndarray,
        execution_times: Sequence[float],
    ) -> None:
        """
        Record one task's per-miner results (aligned to miner_uids).
        Shapes must match N miners.
        """
        if self._started_at <= 0:
            # allow implicit start
            self.start(None)

        n = self._n
        # Safety-pad to N
        rewards = _pad_or_trim(np.asarray(final_rewards, dtype=np.float32), n, fill=0.0)
        evals = _pad_or_trim(np.asarray(eval_scores, dtype=np.float32), n, fill=0.0)
        times = _pad_or_trim(np.asarray(execution_times, dtype=np.float32), n, fill=0.0)

        # Aggregate
        self._sum_rewards += rewards
        self._sum_eval_scores += evals
        self._sum_exec_times += times
        # Count only positions we consider "valid contribution". Here: always +1 for the task;
        # if you want to count only nonnegative rewards or successful evals, tweak this mask.
        self._counts += 1
        self._tasks_sent += 1

    def finish(self) -> Dict[str, Any]:
        """
        Compute per-miner averages for this forward and return a summary dict:
        {
          "forward_id": ...,
          "duration_sec": ...,
          "tasks_sent": ...,
          "miners": [
            {
              "uid": int,
              "hotkey": str,
              "coldkey": str,
              "avg_reward": float,
              "avg_eval_score": float,
              "avg_execution_time": float,
              "sum_reward": float,  # included for convenience
            },
            ... sorted by avg_reward desc ...
          ]
        }
        """
        if self._tasks_sent == 0:
            duration = time.time() - self._started_at if self._started_at > 0 else 0.0
            return {
                "forward_id": self._forward_id,
                "duration_sec": duration,
                "tasks_sent": 0,
                "miners": [],
            }

        counts_safe = np.maximum(self._counts, 1).astype(np.float32)
        avg_reward = self._sum_rewards / counts_safe
        avg_eval = self._sum_eval_scores / counts_safe
        avg_time = self._sum_exec_times / counts_safe

        order = np.argsort(-avg_reward)  # desc by avg reward
        miners: List[Dict[str, Any]] = []
        for idx in order.tolist():
            miners.append({
                "uid": int(self.miner_uids[idx]),
                "hotkey": str(self.miner_hotkeys[idx]),
                "coldkey": str(self.miner_coldkeys[idx]),
                "avg_reward": float(avg_reward[idx]),
                "avg_eval_score": float(avg_eval[idx]),
                "avg_execution_time": float(avg_time[idx]),
                "sum_reward": float(self._sum_rewards[idx]),
            })

        duration = time.time() - self._started_at if self._started_at > 0 else 0.0
        return {
            "forward_id": self._forward_id,
            "duration_sec": duration,
            "tasks_sent": int(self._tasks_sent),
            "miners": miners,
        }

    # ---- rendering ----
    def render_table(self, summary: Dict[str, Any], *, to_console: bool = True) -> str:
        """
        Render an ordered miner table (by avg_reward desc).
        Returns a string; optionally also prints to console if rich is available.
        """
        rows = summary.get("miners", [])
        if not rows:
            text = "[no miners / no tasks this forward]"
            if to_console and _RICH:
                Console().print(text)
            return text

        if _RICH:
            tbl = Table(
                title="[bold magenta]This Forward — Miners by Avg Reward[/bold magenta]",
                box=box.SIMPLE_HEAVY,
                header_style="bold cyan",
                expand=True,
                show_lines=False,
                padding=(0, 1),
            )
            tbl.add_column("#", justify="right", width=3)
            tbl.add_column("UID", justify="right", width=5)
            tbl.add_column("Hotkey", style="cyan", overflow="ellipsis")
            tbl.add_column("Coldkey", style="cyan", overflow="ellipsis")
            tbl.add_column("AvgReward", justify="right", width=10)
            tbl.add_column("AvgEval", justify="right", width=10)
            tbl.add_column("AvgTime(s)", justify="right", width=10)

            for i, m in enumerate(rows, start=1):
                tbl.add_row(
                    str(i),
                    str(m["uid"]),
                    m["hotkey"],
                    m["coldkey"],
                    f'{m["avg_reward"]:.4f}',
                    f'{m["avg_eval_score"]:.4f}',
                    f'{m["avg_execution_time"]:.3f}',
                )

            meta = (
                f'[dim]forward_id={summary.get("forward_id")}  '
                f'tasks_sent={summary.get("tasks_sent")}  '
                f'duration={summary.get("duration_sec"):.2f}s[/dim]'
            )

            console = Console()
            console.print(tbl)
            console.print(meta)
            # Also return a simple string (in case caller wants it)
            return f"This Forward — Miners by Avg Reward (n={len(rows)})."

        # Fallback: plain text
        lines = [
            "This Forward — Miners by Avg Reward",
            f'forward_id={summary.get("forward_id")} tasks_sent={summary.get("tasks_sent")} '
            f'duration={summary.get("duration_sec"):.2f}s',
            "",
            f'{"#":>3} {"UID":>5} {"HOTKEY":<18} {"COLDKEY":<18} {"AvgReward":>10} {"AvgEval":>10} {"AvgTime(s)":>10}',
        ]
        for i, m in enumerate(rows, start=1):
            lines.append(
                f'{i:>3} {m["uid"]:>5} {m["hotkey"]:<18.18} {m["coldkey"]:<18.18} '
                f'{m["avg_reward"]:>10.4f} {m["avg_eval_score"]:>10.4f} {m["avg_execution_time"]:>10.3f}'
            )
        text = "\n".join(lines)
        if to_console:
            print(text)
        return text
