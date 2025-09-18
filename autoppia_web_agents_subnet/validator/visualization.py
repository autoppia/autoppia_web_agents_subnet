# autoppia_web_agents_subnet/validator/visualization.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
from collections import defaultdict

from rich.console import Console
from rich.table import Table
from rich import box

from .leaderboard import LeaderboardTaskRecord
from .stats import load_stats, StatBlock

console = Console(force_terminal=True, color_system="truecolor", no_color=False)


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


# -------------------- leaderboard per-task UI -------------------
def print_leaderboard_table(records: List[LeaderboardTaskRecord], task_prompt: str, web_project: Optional[str]):
    info_table = Table(box=box.SIMPLE_HEAD, show_header=False, expand=True)
    info_table.add_column("Field", style="bold cyan", no_wrap=True, width=12)
    info_table.add_column("Value", style="cyan")
    info_table.add_row("Task:", task_prompt)
    info_table.add_row("Web Project:", web_project or "—")
    console.print(info_table)

    # Tabla resultados individuales
    results = Table(
        title="[bold magenta]Task Results[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
        padding=(0, 1),
    )
    results.add_column("Coldkey", style="cyan", width=20, no_wrap=True, overflow="ellipsis")
    results.add_column("Hotkey", style="cyan", width=20, no_wrap=True, overflow="ellipsis")
    results.add_column("Miner UID", style="green", justify="center", no_wrap=True, min_width=7)
    results.add_column("Success", justify="center", no_wrap=True, min_width=6)
    results.add_column("Actions", justify="right", no_wrap=True, min_width=6)
    results.add_column("Reward", justify="right", no_wrap=True, min_width=6)
    results.add_column("Duration (s)", justify="right", no_wrap=True, min_width=10)

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

    # Totales y promedios
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

    # Agrupado por coldkey
    coldkey_groups: dict[str, List[LeaderboardTaskRecord]] = defaultdict(list)
    for rec in records:
        coldkey_groups[rec.miner_coldkey].append(rec)

    coldkey_table = Table(
        title="[bold magenta]Tasks-Coldkey Summary[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
        padding=(0, 1),
    )
    coldkey_table.add_column("Coldkey", style="cyan", width=20, no_wrap=True, overflow="ellipsis")
    coldkey_table.add_column("Total hotkeys", justify="right", no_wrap=True, min_width=8)
    coldkey_table.add_column("Total tasks", justify="right", no_wrap=True, min_width=7)
    coldkey_table.add_column("Successes", justify="right", no_wrap=True, min_width=7)
    coldkey_table.add_column("Success %", justify="right", no_wrap=True, min_width=7)
    coldkey_table.add_column("Avg duration s", justify="right", no_wrap=True, min_width=10)
    coldkey_table.add_column("Avg reward", justify="right", no_wrap=True, min_width=8)
    coldkey_table.add_column("Avg actions", justify="right", no_wrap=True, min_width=8)

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


# ---------------- summary by coldkey/web/use-case UI ---------------
def print_coldkey_resume() -> None:
    stats = load_stats()
    if not stats:
        console.print("[bold red]Snapshot vacío[/bold red]")
        return

    tbl = Table(
        title="[bold magenta]Summary by Coldkey / Web / Use-case[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
        padding=(0, 1),
    )
    tbl.add_column("Coldkey", style="cyan", width=20, no_wrap=True, overflow="ellipsis")
    tbl.add_column("Web", style="cyan", no_wrap=True, min_width=8)
    tbl.add_column("Use-case", style="cyan", overflow="fold", min_width=12)
    tbl.add_column("Hotk", justify="right", no_wrap=True, min_width=4)
    tbl.add_column("Tasks", justify="right", no_wrap=True, min_width=5)
    tbl.add_column("Succ", justify="right", no_wrap=True, min_width=4)
    tbl.add_column("Rate %", justify="right", no_wrap=True, min_width=6)
    tbl.add_column("Avg reward", justify="right", no_wrap=True, min_width=8)
    tbl.add_column("Avg actions", justify="right", no_wrap=True, min_width=8)
    tbl.add_column("Avg s", justify="right", no_wrap=True, min_width=6)

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

    # Totales por coldkey
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
        title="[bold magenta]Per-Coldkey Total Tasks[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
        padding=(0, 1),
    )
    ck_tbl.add_column("Coldkey", style="cyan", width=20, no_wrap=True, overflow="ellipsis")
    ck_tbl.add_column("Hotk", justify="right", no_wrap=True, min_width=4)
    ck_tbl.add_column("Tasks", justify="right", no_wrap=True, min_width=5)
    ck_tbl.add_column("Succ", justify="right", no_wrap=True, min_width=4)
    ck_tbl.add_column("Rate %", justify="right", no_wrap=True, min_width=6)
    ck_tbl.add_column("Avg reward", justify="right", no_wrap=True, min_width=8)
    ck_tbl.add_column("Avg actions", justify="right", no_wrap=True, min_width=8)
    ck_tbl.add_column("Avg s", justify="right", no_wrap=True, min_width=6)

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
