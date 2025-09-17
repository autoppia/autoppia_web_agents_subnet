# autoppia_web_agents_subnet/validator/utils.py
from __future__ import annotations
from typing import Any, Dict
import bittensor as bt


def init_validator_performance_stats(validator) -> None:
    """
    Initializes stats storage on the validator once.
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


def print_validator_performance_stats(validator) -> None:
    """
    Pretty print last-forward and cumulative stats.
    """
    s = validator.validator_performance_stats
    lf = s.get("last_forward", {})
    bt.logging.info(
        "[Forward summary] "
        f"sent={lf.get('tasks_sent',0)} | "
        f"success={lf.get('tasks_success',0)} | "
        f"failed={lf.get('tasks_failed',0)} | "
        f"avg_task_time={lf.get('avg_response_time_per_task',0.0):.3f}s | "
        f"forward_time={lf.get('forward_time',0.0):.3f}s"
    )

    # cumulative
    total_sent = s.get("total_tasks_sent", 0)
    total_succ = s.get("total_tasks_success", 0)
    total_fail = s.get("total_tasks_failed", 0)
    overall_avg = s["total_sum_of_avg_response_times"] / s["overall_tasks_processed"] if s.get("overall_tasks_processed", 0) > 0 else 0.0
    success_rate = (total_succ / total_sent) if total_sent > 0 else 0.0

    bt.logging.info(
        "[Cumulative] "
        f"forwards={s.get('total_forwards_count',0)} | "
        f"total_time={s.get('total_forwards_time',0.0):.3f}s | "
        f"sent={total_sent} | success={total_succ} | failed={total_fail} | "
        f"avg_task_time={overall_avg:.3f}s | success_rate={success_rate:.3%}"
    )
