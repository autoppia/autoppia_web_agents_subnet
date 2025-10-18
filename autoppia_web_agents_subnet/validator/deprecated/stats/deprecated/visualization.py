# autoppia_web_agents_subnet/validator/visualization.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
from collections import defaultdict

from rich.console import Console
from rich.table import Table
from rich import box

from ..leaderboard_deprecated.deprecated.leaderboard import LeaderboardTaskRecord
from ..stats import load_stats, StatBlock  # StatBlock con avg_* calculados

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


# ---------------------- forward summary UI ---------------------
def print_forward_tables(stats: Dict[str, Any]) -> None:
    from rich.console import Console
    import shutil

    # Detectar ancho de terminal
    try:
        terminal_width = shutil.get_terminal_size().columns
    except Exception:
        terminal_width = 80

    console = Console(width=terminal_width, force_terminal=True)

    lf = stats.get("last_forward", {})

    # ------------ Forward summary (del ÚLTIMO forward) ------------
    # Campos:
    # - Forward ID
    # - Tareas enviadas en ese forward
    # - Time total
    # - AVG time per task
    # - Miners OK -> "ok/attempts"
    # - Miner %
    fwd_id = int(lf.get("forward_id", stats.get("total_forwards_count", 0)))
    f_sent = int(lf.get("tasks_sent", 0))
    f_time = float(lf.get("forward_time", 0.0))
    f_avg_per_task = float(lf.get("avg_time_per_task", 0.0))
    f_min_ok = int(lf.get("miner_successes", 0))
    f_min_att = int(lf.get("miner_attempts", 0))
    f_min_rate = (f_min_ok / f_min_att) if f_min_att > 0 else 0.0

    forward_tbl = Table(
        title="[bold magenta]Forward summary[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
        show_lines=False,
        padding=(0, 1),
    )
    forward_tbl.add_column("ID#", justify="right", width=5)  # Forward ID
    forward_tbl.add_column("Tasks Sent", justify="right", width=6)  # Tareas enviadas
    forward_tbl.add_column("Total Time", justify="right", width=9)  # Time total
    forward_tbl.add_column("Avg/task", justify="right", width=9)  # AVG time per task
    forward_tbl.add_column("Miner.OK", justify="right", width=9)  # "ok/attempts"
    forward_tbl.add_column("Miner%", justify="right", width=7)  # Porcentaje

    forward_tbl.add_row(
        str(fwd_id),
        str(f_sent),
        _format_secs(f_time),
        f"{f_avg_per_task:.2f}s",
        f"{f_min_ok}/{f_min_att}",
        f"{(f_min_rate*100):.2f}%",
    )
    console.print(forward_tbl)

    # ----------------- Cumulative totals (acumulado) -----------------
    total_fwds = int(stats.get("total_forwards_count", 0))
    total_time = float(stats.get("total_forwards_time", 0.0))
    avg_time_per_fwd = (total_time / total_fwds) if total_fwds > 0 else 0.0

    total_sent = int(stats.get("total_tasks_sent", 0))
    avg_tasks_per_fwd = (total_sent / total_fwds) if total_fwds > 0 else 0.0

    total_min_ok = int(stats.get("total_miners_successes", 0))
    total_min_att = int(stats.get("total_miners_attempts", 0))
    total_min_rate = (total_min_ok / total_min_att) if total_min_att > 0 else 0.0

    totals_tbl = Table(
        title="[bold magenta]Cumulative totals[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
        show_lines=False,
        padding=(0, 1),
    )
    totals_tbl.add_column("Fwds", justify="right", width=6)  # total de forwards
    totals_tbl.add_column("Time", justify="right", width=9)  # total de tiempo
    totals_tbl.add_column("Avg/fwd", justify="right", width=9)  # avg de tiempo por forward
    totals_tbl.add_column("Tasks", justify="right", width=7)  # total tareas enviadas
    totals_tbl.add_column("Tasks/fwd", justify="right", width=10)  # avg tareas por forward
    totals_tbl.add_column("Miner.OK", justify="right", width=9)  # ok/attempts acumulado
    totals_tbl.add_column("Miner%", justify="right", width=7)  # porcentaje acumulado

    totals_tbl.add_row(
        str(total_fwds),
        _format_secs(total_time),
        f"{avg_time_per_fwd:.2f}s",
        str(total_sent),
        f"{avg_tasks_per_fwd:.2f}",
        f"{total_min_ok}/{total_min_att}",
        f"{(total_min_rate*100):.2f}%",
    )
    console.print(totals_tbl)


# -------------------- leaderboard per-task UI -------------------
def print_leaderboard_table(records: List[LeaderboardTaskRecord], task_prompt: str, web_project: Optional[str]):
    from rich.console import Console
    import shutil

    # Detectar el ancho REAL de la terminal
    try:
        terminal_width = shutil.get_terminal_size().columns
    except:
        terminal_width = 80

    # Usar el ancho real detectado
    console = Console(width=terminal_width, force_terminal=True)

    info_table = Table(box=box.SIMPLE_HEAD, show_header=False, expand=True)
    info_table.add_column("Field", style="bold cyan", no_wrap=True, width=12)
    info_table.add_column("Value", style="cyan")
    info_table.add_row("Task:", task_prompt)
    info_table.add_row("Web Project:", web_project or "—")
    console.print(info_table)

    results = Table(
        title="[bold magenta]Task Results[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
        show_lines=False,
        padding=(0, 1),
    )

    # Columnas ajustadas para que quepan en 80 caracteres
    results.add_column("Coldkey", style="cyan", width=12, no_wrap=True, overflow="ellipsis")
    results.add_column("Hotkey", style="cyan", width=12, no_wrap=True, overflow="ellipsis")
    results.add_column("UID", style="green", justify="center", width=4)
    results.add_column("✓", justify="center", width=3)
    results.add_column("Act", justify="right", width=4)
    results.add_column("Rew", justify="right", width=6)
    results.add_column("Dur", justify="right", width=6)

    for rec in records:
        acts = _actions_len(rec.actions)
        results.add_row(
            rec.miner_coldkey[:10] + ".." if len(rec.miner_coldkey) > 12 else rec.miner_coldkey,
            rec.miner_hotkey[:10] + ".." if len(rec.miner_hotkey) > 12 else rec.miner_hotkey,
            str(rec.miner_uid),
            "✅" if rec.success else "❌",
            f"{acts:.1f}",
            f"{rec.score:.2f}",
            f"{rec.duration:.1f}",
        )
    console.print(results)

    total = len(records)
    successes = sum(1 for r in records if r.success)
    rate = (successes / total * 100) if total else 0.0
    avg_dur = (sum(r.duration for r in records) / total) if total else 0.0
    avg_reward = (sum(r.score for r in records) / total) if total else 0.0
    avg_actions = (sum(_actions_len(r.actions) for r in records) / total) if total else 0.0

    console.print(
        f"[bold white]Total successes:[/bold white] {successes}/{total}   "
        f"[bold white]Success rate:[/bold white] {rate:.2f}%   "
        f"[bold white]Avg duration:[/bold white] {avg_dur:.2f}s   "
        f"[bold white]Avg reward:[/bold white] {avg_reward:.2f}   "
        f"[bold white]Avg actions:[/bold white] {avg_actions:.1f}",
        style="yellow",
    )

    coldkey_groups: dict[str, List[LeaderboardTaskRecord]] = defaultdict(list)
    for rec in records:
        coldkey_groups[rec.miner_coldkey].append(rec)

    coldkey_table = Table(
        title="[bold magenta]Tasks-Coldkey Summary[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
        show_lines=False,
        padding=(0, 1),
    )
    coldkey_table.add_column("Coldkey", style="cyan", width=14, no_wrap=True, overflow="ellipsis")
    coldkey_table.add_column("Hotkeys", justify="right", width=8)
    coldkey_table.add_column("Tasks", justify="right", width=6)
    coldkey_table.add_column("OK", justify="right", width=4)
    coldkey_table.add_column("OK%", justify="right", width=6)
    coldkey_table.add_column("Dur", justify="right", width=6)
    coldkey_table.add_column("Rew", justify="right", width=6)
    coldkey_table.add_column("Act", justify="right", width=6)

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
            coldkey[:12] + ".." if len(coldkey) > 14 else coldkey,
            str(total_hotkeys_ck),
            str(total_ck_tasks),
            str(total_ck_successes),
            f"{success_rate_ck:.2f}%",
            f"{avg_duration_ck:.1f}",
            f"{avg_reward_ck:.2f}",
            f"{avg_actions_ck:.1f}",
        )

    console.print(coldkey_table)


# ---------------- summary by coldkey/web/use-case UI ---------------
def print_coldkey_resume() -> None:
    from rich.console import Console
    import shutil

    # Detectar ancho de terminal
    try:
        terminal_width = shutil.get_terminal_size().columns
    except:
        terminal_width = 80

    console = Console(width=terminal_width, force_terminal=True)

    stats = load_stats()
    if not stats:
        console.print("[bold red]Snapshot vacío[/bold red]")
        return

    # -----------Detalle (Coldkey / Web / Use-case)----------------
    tbl = Table(
        title="[bold magenta]Summary by Coldkey/Web/Use-case[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
        padding=(0, 1),
    )
    # Columnas reducidas para 80 chars
    tbl.add_column("Coldkey", style="cyan", width=12, no_wrap=True, overflow="ellipsis")
    tbl.add_column("Web", style="cyan", width=6, no_wrap=True, overflow="ellipsis")
    tbl.add_column("Use", style="cyan", width=6, overflow="ellipsis")
    tbl.add_column("HK", justify="right", width=3)
    tbl.add_column("Tsk", justify="right", width=4)
    tbl.add_column("OK", justify="right", width=3)
    tbl.add_column("OK%", justify="right", width=5)
    tbl.add_column("Rew", justify="right", width=5)
    tbl.add_column("Act", justify="right", width=5)
    tbl.add_column("Dur", justify="right", width=5)

    for (ck, web, uc), blk in sorted(stats.items()):
        tbl.add_row(
            ck[:10] + ".." if len(ck) > 12 else ck,
            web[:6],
            uc[:6],
            str(len(blk.hotkeys)),
            str(blk.tasks),
            str(blk.successes),
            f"{blk.success_rate*100:.2f}",
            f"{blk.avg_reward:.2f}",
            f"{blk.avg_actions:.1f}",
            f"{blk.avg_duration:.1f}",
        )

    console.print(tbl)

    # ----------Per-coldkey total tasks-----------------
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
    # Columnas reducidas para 80 chars
    ck_tbl.add_column("Coldkey", style="cyan", width=14, no_wrap=True, overflow="ellipsis")
    ck_tbl.add_column("HK", justify="right", width=3)
    ck_tbl.add_column("Tasks", justify="right", width=5)
    ck_tbl.add_column("OK", justify="right", width=4)
    ck_tbl.add_column("OK%", justify="right", width=6)
    ck_tbl.add_column("Rew", justify="right", width=6)
    ck_tbl.add_column("Act", justify="right", width=6)
    ck_tbl.add_column("Dur", justify="right", width=6)

    for ck, acc in sorted(agg_by_ck.items()):
        ck_tbl.add_row(
            ck[:12] + ".." if len(ck) > 14 else ck,
            str(len(acc.hotkeys)),
            str(acc.tasks),
            str(acc.successes),
            f"{acc.success_rate*100:.2f}%",
            f"{acc.avg_reward:.2f}",
            f"{acc.avg_actions:.1f}",
            f"{acc.avg_duration:.1f}",
        )
    console.print(ck_tbl)
