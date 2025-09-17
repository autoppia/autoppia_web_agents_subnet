# autoppia_web_agents_subnet/validator/forward_stats.py
from __future__ import annotations

from typing import Any, Dict
import bittensor as bt

# Pretty tables
from rich.console import Console
from rich.table import Table, box

console = Console(
    force_terminal=True,  # render as if TTY
    color_system="truecolor",  # full color
    no_color=False,
)


def init_validator_performance_stats(validator) -> None:
    """
    Initialize stats storage on the validator once.
    """
    if hasattr(validator, "validator_performance_stats"):
        return
    validator.validator_performance_stats = {
        # CUMULATIVE
        "total_forwards_count": 0,
        "total_forwards_time": 0.0,
        "total_tasks_sent": 0,
        "total_tasks_success": 0,
        "total_tasks_failed": 0,  # = sent - success
        "total_sum_of_avg_response_times": 0.0,  # sum of per-task avg(miner) times
        "overall_tasks_processed": 0,
        # LAST FORWARD SNAPSHOT
        "last_forward": {
            "tasks_sent": 0,
            "tasks_success": 0,
            "tasks_failed": 0,
            "avg_response_time_per_task": 0.0,
            "forward_time": 0.0,
        },
    }


def finalize_forward_stats(
    validator,
    *,
    tasks_sent: int,
    tasks_success: int,
    sum_avg_response_times: float,
    forward_time: float,
) -> Dict[str, Any]:
    """
    Finalize a single forward stats (snapshot + cumulative update).
    Returns a summary dict {"forward": {...}, "totals": {...}}.
    """
    stats = validator.validator_performance_stats
    tasks_failed = max(0, tasks_sent - tasks_success)
    avg_resp_time = (sum_avg_response_times / tasks_sent) if tasks_sent > 0 else 0.0

    # snapshot of this forward
    forward_snapshot = {
        "tasks_sent": tasks_sent,
        "tasks_success": tasks_success,
        "tasks_failed": tasks_failed,
        "avg_response_time_per_task": avg_resp_time,
        "forward_time": forward_time,
    }
    stats["last_forward"] = forward_snapshot

    # cumulative
    stats["total_forwards_count"] += 1
    stats["total_forwards_time"] += forward_time

    stats["total_tasks_sent"] += tasks_sent
    stats["total_tasks_success"] += tasks_success
    stats["total_tasks_failed"] += tasks_failed

    stats["total_sum_of_avg_response_times"] += sum_avg_response_times
    stats["overall_tasks_processed"] += tasks_sent

    # build totals summary
    totals_avg_resp = stats["total_sum_of_avg_response_times"] / stats["overall_tasks_processed"] if stats["overall_tasks_processed"] > 0 else 0.0
    totals_success_rate = stats["total_tasks_success"] / stats["total_tasks_sent"] if stats["total_tasks_sent"] > 0 else 0.0

    totals = {
        "forwards_count": stats["total_forwards_count"],
        "total_time": stats["total_forwards_time"],
        "tasks_sent": stats["total_tasks_sent"],
        "tasks_success": stats["total_tasks_success"],
        "tasks_failed": stats["total_tasks_failed"],
        "avg_response_time_per_task": totals_avg_resp,
        "success_rate": totals_success_rate,
    }

    return {"forward": forward_snapshot, "totals": totals}


def _format_secs(secs: float) -> str:
    if secs < 60:
        return f"{secs:.3f}s"
    m, s = divmod(secs, 60)
    if m < 60:
        return f"{int(m)}m {s:05.2f}s"
    h, m = divmod(int(m), 60)
    return f"{h}h {m}m {s:05.2f}s"


def print_validator_performance_stats(validator) -> None:
    """
    Pretty print last-forward (table) and cumulative totals (table).
    """
    s = validator.validator_performance_stats
    lf = s.get("last_forward", {})

    # ----- Forward summary table -----
    f_sent = int(lf.get("tasks_sent", 0))
    f_succ = int(lf.get("tasks_success", 0))
    f_fail = int(lf.get("tasks_failed", 0))
    f_rate = (f_succ / f_sent) if f_sent > 0 else 0.0
    f_avg_task = float(lf.get("avg_response_time_per_task", 0.0))
    f_time = float(lf.get("forward_time", 0.0))

    forward_tbl = Table(
        title="[bold magenta]Forward summary[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    forward_tbl.add_column("Sent", justify="right")
    forward_tbl.add_column("Success", justify="right", style="green")
    forward_tbl.add_column("Failed", justify="right", style="red")
    forward_tbl.add_column("Success %", justify="right")
    forward_tbl.add_column("Avg task time", justify="right")
    forward_tbl.add_column("Forward time", justify="right")

    forward_tbl.add_row(
        str(f_sent),
        str(f_succ),
        str(f_fail),
        f"{f_rate*100:5.1f}",
        _format_secs(f_avg_task),
        _format_secs(f_time),
    )

    # ----- Cumulative table -----
    total_sent = int(s.get("total_tasks_sent", 0))
    total_succ = int(s.get("total_tasks_success", 0))
    total_fail = int(s.get("total_tasks_failed", 0))
    overall_avg = s["total_sum_of_avg_response_times"] / s["overall_tasks_processed"] if s.get("overall_tasks_processed", 0) > 0 else 0.0
    success_rate = (total_succ / total_sent) if total_sent > 0 else 0.0
    fwd_count = int(s.get("total_forwards_count", 0))
    total_time = float(s.get("total_forwards_time", 0.0))

    totals_tbl = Table(
        title="[bold magenta]Cumulative totals[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    totals_tbl.add_column("Forwards", justify="right")
    totals_tbl.add_column("Total time", justify="right")
    totals_tbl.add_column("Sent", justify="right")
    totals_tbl.add_column("Success", justify="right", style="green")
    totals_tbl.add_column("Failed", justify="right", style="red")
    totals_tbl.add_column("Success %", justify="right")
    totals_tbl.add_column("Avg task time", justify="right")

    totals_tbl.add_row(
        str(fwd_count),
        _format_secs(total_time),
        str(total_sent),
        str(total_succ),
        str(total_fail),
        f"{success_rate*100:5.1f}",
        _format_secs(overall_avg),
    )

    # Print both tables
    console.print(forward_tbl)
    console.print(totals_tbl)
