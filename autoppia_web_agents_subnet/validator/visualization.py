# autoppia_web_agents_subnet/validator/visualization.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
from collections import defaultdict

from rich.console import Console
from rich.table import Table
from rich import box

# Local deps
from .leaderboard import LeaderboardTaskRecord
from .forward_stats import load_stats

console = Console(
    force_terminal=True,  # render as if TTY
    color_system="truecolor",  # full color
    no_color=False,
)


# --------------------------- helpers ---------------------------
def _format_secs(secs: float) -> str:
    if secs < 60:
        return f"{secs:.3f}s"
    m, s = divmod(secs, 60)
    if m < 60:
        return f"{int(m)}m {s:05.2f}s"
    h, m = divmod(int(m), 60)
    return f"{h}h {m}m {s:05.2f}s"


def _actions_len(obj: Any) -> int:
    if obj is None:
        return 0
    if isinstance(obj, list):
        return len(obj)
    if isinstance(obj, dict):
        if "actions" in obj and isinstance(obj["actions"], list):
            return len(obj["actions"])
        return len(obj)
    return 0


# ---------------------- forward summary UI ---------------------
def print_forward_tables(stats: Dict[str, Any]) -> None:
    """Accepts validator.validator_performance_stats and prints two tables."""
    lf = stats.get("last_forward", {})

    # Forward summary
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

    # Cumulative
    total_sent = int(stats.get("total_tasks_sent", 0))
    total_succ = int(stats.get("total_tasks_success", 0))
    total_fail = int(stats.get("total_tasks_failed", 0))
    overall_avg = stats["total_sum_of_avg_response_times"] / stats["overall_tasks_processed"] if stats.get("overall_tasks_processed", 0) > 0 else 0.0
    success_rate = (total_succ / total_sent) if total_sent > 0 else 0.0
    fwd_count = int(stats.get("total_forwards_count", 0))
    total_time = float(stats.get("total_forwards_time", 0.0))

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

    console.print(forward_tbl)
    console.print(totals_tbl)


# -------------------- leaderboard per-task UI -------------------
def print_leaderboard_table(records: List[LeaderboardTaskRecord], task_prompt: str, web_project: Optional[str]):
    # Task info
    info_table = Table(box=box.SIMPLE_HEAD, show_header=False, expand=True)
    info_table.add_column("Field", style="bold cyan", no_wrap=True, width=12)
    info_table.add_column("Value", style="cyan")
    info_table.add_row("Task:", task_prompt)
    info_table.add_row("Web Project:", web_project or "—")
    console.print(info_table)

    # Miner results
    results = Table(
        title="[bold magenta]Leaderboard Results[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    results.add_column("Coldkey", style="cyan", ratio=4, overflow="fold")
    results.add_column("Hotkey", style="cyan", ratio=4, overflow="fold")
    results.add_column("Miner UID", style="green", ratio=1, justify="center", no_wrap=True)
    results.add_column("Success", ratio=1, justify="center")
    results.add_column("Actions", ratio=1, justify="right")
    results.add_column("Reward", ratio=1, justify="right")
    results.add_column("Duration (s)", ratio=1, justify="right", overflow="fold")

    for rec in records:
        acts = _actions_len(rec.actions)
        results.add_row(
            rec.miner_coldkey,
            rec.miner_hotkey,
            str(rec.miner_uid),
            "[green]✅[/green]" if rec.success else "[red]❌[/red]",
            str(acts),
            f"{rec.score:.2f}",
            f"{rec.duration:.2f}",
        )
    console.print(results)

    # Batch metrics
    total = len(records)
    successes = sum(1 for r in records if r.success)
    rate = (successes / total * 100) if total else 0.0
    avg_dur = (sum(r.duration for r in records) / total) if total else 0.0
    avg_reward = (sum(r.score for r in records) / total) if total else 0.0
    avg_actions = (sum(_actions_len(r.actions) for r in records) / total) if total else 0.0

    console.print(
        f"[bold white]Total successes:[/bold white] {successes}/{total}   "
        f"[bold white]Success rate:[/bold white] {rate:.1f}%   "
        f"[bold white]Avg duration:[/bold white] {avg_dur:.2f}s   "
        f"[bold white]Avg reward:[/bold white] {avg_reward:.2f}   "
        f"[bold white]Avg actions:[/bold white] {avg_actions:.2f}",
        style="yellow",
    )

    # Per-coldkey averages
    from collections import defaultdict

    coldkey_groups: dict[str, List[LeaderboardTaskRecord]] = defaultdict(list)
    for rec in records:
        coldkey_groups[rec.miner_coldkey].append(rec)

    coldkey_table = Table(
        title="[bold magenta]Per-Coldkey Averages[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    coldkey_table.add_column("Coldkey", style="cyan", width=15, overflow="ellipsis", no_wrap=True)
    coldkey_table.add_column("Total hotkeys", justify="right")
    coldkey_table.add_column("Total tasks", justify="right")
    coldkey_table.add_column("Successes", justify="right")
    coldkey_table.add_column("Success rate %", justify="right")
    coldkey_table.add_column("Avg duration s", justify="right")
    coldkey_table.add_column("Avg reward", justify="right")
    coldkey_table.add_column("Avg actions", justify="right")

    for coldkey, ck_records in coldkey_groups.items():
        total_ck_tasks = len(ck_records)
        total_ck_successes = sum(1 for r in ck_records if r.success)
        success_rate_ck = (total_ck_successes / total_ck_tasks * 100) if total_ck_tasks else 0.0
        avg_duration_ck = (sum(r.duration for r in ck_records) / total_ck_tasks) if total_ck_tasks else 0.0
        avg_reward_ck = (sum(r.score for r in ck_records) / total_ck_tasks) if total_ck_tasks else 0.0
        avg_actions_ck = (sum(_actions_len(r.actions) for r in ck_records) / total_ck_tasks) if total_ck_tasks else 0.0
        unique_hotkeys = {r.miner_hotkey for r in ck_records}
        total_hotkeys_ck = len(unique_hotkeys)

        coldkey_table.add_row(
            coldkey,
            str(total_hotkeys_ck),
            str(total_ck_tasks),
            str(total_ck_successes),
            f"{success_rate_ck:.1f}",
            f"{avg_duration_ck:.2f}",
            f"{avg_reward_ck:.2f}",
            f"{avg_actions_ck:.2f}",
        )

    console.print(coldkey_table)


# ---------------- snapshot by coldkey/web/use-case UI ---------------
def print_coldkey_resume() -> None:
    stats = load_stats()
    if not stats:
        console.print("[bold red]Snapshot vacío[/bold red]")
        return

    # Per-coldkey totals
    from .forward_stats import StatBlock  # reuse class for simple aggregation

    agg_by_ck: Dict[str, StatBlock] = {}
    for (ck, web, uc), blk in stats.items():
        acc = agg_by_ck.setdefault(ck, StatBlock())
        acc.tasks += blk.tasks
        acc.successes += blk.successes
        acc.duration_sum += blk.duration_sum
        acc.reward_sum += blk.reward_sum
        acc.actions_sum += blk.actions_sum
        acc.hotkeys |= blk.hotkeys

    ck_tbl = Table(
        title="[bold magenta]Per-Coldkey Totals[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    ck_tbl.add_column("Coldkey", style="cyan", ratio=6, overflow="ellipsis", no_wrap=True)
    ck_tbl.add_column("Hotk", justify="right")
    ck_tbl.add_column("Tasks", justify="right")
    ck_tbl.add_column("Succ", justify="right")
    ck_tbl.add_column("Rate %", justify="right")
    ck_tbl.add_column("Avg reward", justify="right")
    ck_tbl.add_column("Avg actions", justify="right")
    ck_tbl.add_column("Avg s", justify="right")

    for ck, acc in sorted(agg_by_ck.items()):
        ck_tbl.add_row(
            ck,
            str(len(acc.hotkeys)),
            str(acc.tasks),
            str(acc.successes),
            f"{acc.success_rate*100:5.1f}",
            f"{acc.avg_reward:6.2f}",
            f"{acc.avg_actions:6.2f}",
            f"{acc.avg_duration:6.2f}",
        )
    console.print(ck_tbl)

    # Detailed snapshot by Coldkey / Web / Use-case
    tbl = Table(
        title="[bold magenta]Snapshot by Coldkey / Web / Use-case[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    tbl.add_column("Coldkey", style="cyan", ratio=6, overflow="ellipsis", no_wrap=True)
    tbl.add_column("Web", style="cyan", width=10, no_wrap=True)
    tbl.add_column("Use-case", style="cyan", width=14, overflow="ellipsis", no_wrap=True)
    tbl.add_column("Hotk", justify="right")
    tbl.add_column("Tasks", justify="right")
    tbl.add_column("Succ", justify="right")
    tbl.add_column("Rate %", justify="right")
    tbl.add_column("Avg reward", justify="right")
    tbl.add_column("Avg actions", justify="right")
    tbl.add_column("Avg s", justify="right")

    for (ck, web, uc), blk in sorted(stats.items()):
        tbl.add_row(
            ck,
            web,
            uc,
            str(len(blk.hotkeys)),
            str(blk.tasks),
            str(blk.successes),
            f"{blk.success_rate*100:5.1f}",
            f"{blk.avg_reward:6.2f}",
            f"{blk.avg_actions:6.2f}",
            f"{blk.avg_duration:6.2f}",
        )

    console.print(tbl)
