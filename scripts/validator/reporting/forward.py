from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(numerator: float, denominator: float) -> float:
    return (numerator / denominator * 100.0) if denominator else 0.0


def _iter_records(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


@dataclass
class ForwardReportPaths:
    forward_jsonl: Path
    coldkey_snapshot: Path

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ForwardReportPaths":
        env = env or os.environ
        reports_dir = Path(env.get("REPORTS_DIR", "forward_reports"))
        forward_jsonl = reports_dir / "forward_summary.jsonl"
        coldkey_snapshot = Path(env.get("COLDKEY_SNAPSHOT", "coldkey_web_usecase_stats.json"))
        return cls(forward_jsonl=forward_jsonl, coldkey_snapshot=coldkey_snapshot)


@dataclass
class ForwardReportData:
    forwards_table: tuple[list[str], list[list[Any]]]
    coldkey_global_table: tuple[list[str], list[list[Any]]]
    coldkey_cwu_table: tuple[list[str], list[list[Any]]]
    last_forward_tasks: tuple[list[str], list[list[Any]]]
    task_summary: tuple[list[str], list[list[Any]]]


def _extract_forward_rows(records: Sequence[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    totals = {"forwards": 0, "tasks_sent": 0, "miner_successes": 0, "miner_attempts": 0, "forward_time_sum": 0.0}
    rows: list[list[Any]] = []

    for record in records:
        last_forward = record.get("last_forward", {})
        fid = _safe_int(last_forward.get("forward_id", -1))
        tasks_sent = _safe_int(last_forward.get("tasks_sent", 0))
        forward_time = _safe_float(last_forward.get("forward_time", 0.0))
        miner_successes = _safe_int(last_forward.get("miner_successes", 0))
        miner_attempts = _safe_int(last_forward.get("miner_attempts", 0))

        totals["forwards"] += 1
        totals["tasks_sent"] += tasks_sent
        totals["miner_successes"] += miner_successes
        totals["miner_attempts"] += miner_attempts
        totals["forward_time_sum"] += forward_time

        rows.append(
            [
                fid,
                tasks_sent,
                miner_successes,
                miner_attempts,
                f"{_pct(miner_successes, miner_attempts):.1f}%",
                f"{(forward_time / tasks_sent if tasks_sent else 0.0):.2f}s",
                f"{forward_time:.2f}s",
            ]
        )

    headers = ["Forward", "Tasks", "Successes", "Attempts", "Miner%", "Avg/task", "Forward Time"]
    total_row = [
        "TOTAL",
        totals["tasks_sent"],
        totals["miner_successes"],
        totals["miner_attempts"],
        f"{_pct(totals['miner_successes'], totals['miner_attempts']):.1f}%",
        f"{(totals['forward_time_sum'] / totals['tasks_sent'] if totals['tasks_sent'] else 0):.2f}s",
        f"{(totals['forward_time_sum'] / totals['forwards'] if totals['forwards'] else 0):.2f}s",
    ]

    return headers, rows + [total_row]


def _extract_last_tasks(records: Sequence[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    headers = ["Web", "Use-case", "Prompt"]
    if not records:
        return headers, []

    last = records[-1]
    tasks = last.get("tasks", []) or last.get("last_forward", {}).get("tasks", [])
    rows = [[task.get("web_project", ""), task.get("use_case", ""), task.get("prompt", "")] for task in tasks]
    return headers, rows


def _extract_task_summary(records: Sequence[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    headers = ["Web", "Use-case", "Tasks Sent"]
    if not records:
        return headers, []

    counts = Counter()
    for record in records:
        tasks = record.get("tasks", []) or record.get("last_forward", {}).get("tasks", [])
        for task in tasks:
            counts[(task.get("web_project", ""), task.get("use_case", ""))] += 1

    rows = [[web, use_case, total] for (web, use_case), total in counts.items()]
    return headers, rows


def _extract_coldkey_tables(snapshot_path: Path) -> tuple[tuple[list[str], list[list[Any]]], tuple[list[str], list[list[Any]]]]:
    headers_global = ["Coldkey", "Hotk", "Tasks", "Succ", "Rate %", "Avg s", "Avg Reward", "Avg Actions"]
    headers_cwu = ["Coldkey", "Web", "Use-case", "Hotk", "Tasks", "Succ", "Rate %", "Avg s", "Avg Actions"]

    if not snapshot_path.exists():
        return (headers_global, []), (headers_cwu, [])

    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return (headers_global, []), (headers_cwu, [])

    stats = data.get("stats", {})
    aggregate = defaultdict(lambda: {"tasks": 0, "succ": 0, "dur": 0.0, "reward": 0.0, "actions": 0, "hotkeys": set()})
    rows_cwu: list[list[Any]] = []

    for coldkey, webs in stats.items():
        for web, use_cases in webs.items():
            for use_case, block in use_cases.items():
                tasks = _safe_int(block.get("tasks", 0))
                successes = _safe_int(block.get("successes", 0))
                duration_sum = _safe_float(block.get("duration_sum", 0.0))
                reward_sum = _safe_float(block.get("reward_sum", 0.0))
                actions_sum = _safe_int(block.get("actions_sum", 0))
                hotkeys = set(block.get("hotkeys", []))

                rows_cwu.append(
                    [
                        coldkey,
                        web,
                        use_case,
                        len(hotkeys),
                        tasks,
                        successes,
                        f"{_pct(successes, tasks):.1f}%",
                        f"{(duration_sum / tasks if tasks else 0.0):.2f}",
                        f"{(actions_sum / tasks if tasks else 0.0):.1f}",
                    ]
                )

                agg_entry = aggregate[coldkey]
                agg_entry["tasks"] += tasks
                agg_entry["succ"] += successes
                agg_entry["dur"] += duration_sum
                agg_entry["reward"] += reward_sum
                agg_entry["actions"] += actions_sum
                agg_entry["hotkeys"] |= hotkeys

    rows_global: list[list[Any]] = []
    for coldkey, entry in sorted(aggregate.items()):
        tasks = entry["tasks"]
        successes = entry["succ"]
        duration_sum = entry["dur"]
        reward_sum = entry["reward"]
        actions_sum = entry["actions"]
        rows_global.append(
            [
                coldkey,
                len(entry["hotkeys"]),
                tasks,
                successes,
                f"{_pct(successes, tasks):.1f}%",
                f"{(duration_sum / tasks if tasks else 0.0):.2f}",
                f"{(reward_sum / tasks if tasks else 0.0):.2f}",
                f"{(actions_sum / tasks if tasks else 0.0):.1f}",
            ]
        )

    return (headers_global, rows_global), (headers_cwu, rows_cwu)


def build_forward_report_data(paths: ForwardReportPaths) -> ForwardReportData:
    """Load all table data needed for the hourly forward report email."""
    records = list(_iter_records(paths.forward_jsonl))

    forwards_table = _extract_forward_rows(records)
    last_forward_tasks = _extract_last_tasks(records)
    task_summary = _extract_task_summary(records)
    coldkey_global, coldkey_cwu = _extract_coldkey_tables(paths.coldkey_snapshot)

    return ForwardReportData(
        forwards_table=forwards_table,
        coldkey_global_table=coldkey_global,
        coldkey_cwu_table=coldkey_cwu,
        last_forward_tasks=last_forward_tasks,
        task_summary=task_summary,
    )
