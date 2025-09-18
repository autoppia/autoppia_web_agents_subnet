# autoppia_web_agents_subnet/validator/visualization.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
from collections import defaultdict

from rich.console import Console
from rich.table import Table
from rich import box

from .leaderboard import LeaderboardTaskRecord
from .stats import load_stats, StatBlock  # StatBlock con avg_* calculados

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
    lf = stats.get("last_forward", {})

    # ------------Forward summary-----------------
    # intents = éxitos + fallos + sin respuesta (si no vienen, cae a 0)
    f_sent = int(lf.get("tasks_sent", 0))
    f_succ = int(lf.get("tasks_success", 0))
    f_fail = int(lf.get("tasks_failed", 0))
    f_rate = (f_succ / max(1, f_sent)) if f_sent > 0 else 0.0
    f_avg_task = float(lf.get("avg_response_time_per_task", 0.0))
    f_time = float(lf.get("forward_time", 0.0))

    # “Solutions OK / %” (más claro que “Miner OK”)
    # “Miner OK / %” usando lo que guarda finalize_forward_stats
    sols_ok = int(lf.get("miner_successes", 0))
    sols_attempts = int(lf.get("miner_attempts", 0))
    sols_rate = (sols_ok / sols_attempts) if sols_attempts > 0 else 0.0

    forward_tbl = Table(
        title="[bold magenta]Forward summary[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
        show_lines=False,
        padding=(0, 1),
    )
    forward_tbl.add_column("Sent", justify="right", no_wrap=True, min_width=6)
    forward_tbl.add_column("Success", justify="right", style="green", no_wrap=True, min_width=8)
    forward_tbl.add_column("Failed", justify="right", style="red", no_wrap=True, min_width=8)
    forward_tbl.add_column("Success %", justify="right", no_wrap=True, min_width=9)
    forward_tbl.add_column("Miner OK", justify="right", no_wrap=True, min_width=12)
    forward_tbl.add_column("Miner %", justify="right", no_wrap=True, min_width=11)
    forward_tbl.add_column("Avg task", justify="right", no_wrap=True, min_width=9)
    forward_tbl.add_column("Forward time", justify="right", no_wrap=True, min_width=12)

    forward_tbl.add_row(
        str(f_sent),
        str(f_succ),
        str(f_fail),
        f"{f_rate*100:4.1f}",
        f"{sols_ok}/{sols_attempts}",
        f"{sols_rate*100:4.1f}",
        _format_secs(f_avg_task),
        _format_secs(f_time),
    )
    console.print(forward_tbl)

    # -----------------Cumulative---------------------
    total_sent = int(stats.get("total_tasks_sent", 0))
    total_succ = int(stats.get("total_tasks_success", 0))
    total_fail = int(stats.get("total_tasks_failed", 0))
    overall_avg = stats["total_sum_of_avg_response_times"] / stats["overall_tasks_processed"] if stats.get("overall_tasks_processed", 0) > 0 else 0.0
    success_rate = (total_succ / max(1, total_sent)) if total_sent > 0 else 0.0

    # Acumulado de soluciones (éxitos/total enviados)
    sols_total_ok = total_succ
    sols_total_attempts = total_sent
    sols_total_rate = (sols_total_ok / max(1, sols_total_attempts)) if sols_total_attempts > 0 else 0.0

    totals_tbl = Table(
        title="[bold magenta]Cumulative totals[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
        show_lines=False,
        padding=(0, 1),
    )
    totals_tbl.add_column("Forwards", justify="right", no_wrap=True, min_width=8)
    totals_tbl.add_column("Total time", justify="right", no_wrap=True, min_width=12)
    totals_tbl.add_column("Sent", justify="right", no_wrap=True, min_width=6)
    totals_tbl.add_column("Success", justify="right", style="green", no_wrap=True, min_width=8)
    totals_tbl.add_column("Failed", justify="right", style="red", no_wrap=True, min_width=8)
    totals_tbl.add_column("Success %", justify="right", no_wrap=True, min_width=9)
    totals_tbl.add_column("Miner", justify="right", no_wrap=True, min_width=11)
    totals_tbl.add_column("Miner %", justify="right", no_wrap=True, min_width=11)
    totals_tbl.add_column("Avg task", justify="right", no_wrap=True, min_width=9)

    totals_tbl.add_row(
        str(int(stats.get("total_forwards_count", 0))),
        _format_secs(float(stats.get("total_forwards_time", 0.0))),
        str(total_sent),
        str(total_succ),
        str(total_fail),
        f"{success_rate*100:4.1f}",
        f"{sols_total_ok}/{sols_total_attempts}",
        f"{sols_total_rate*100:4.1f}",
        _format_secs(overall_avg),
    )
    console.print(totals_tbl)


# -------------------- leaderboard per-task UI -------------------
def print_leaderboard_table(records: List[LeaderboardTaskRecord], task_prompt: str, web_project: Optional[str]):
    from rich.console import Console
    import shutil

    # Detectar el ancho REAL de la terminal
    try:
        terminal_width = shutil.get_terminal_size().columns
        print(f"Terminal detectada: {terminal_width} columnas")
    except:
        terminal_width = 100
        print(f"No pude detectar terminal, usando: {terminal_width} columnas")

    # Usar el ancho real detectado
    console = Console(width=terminal_width, force_terminal=True)
    print(f"Rich configurado con: {console.width} columnas\n")

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

    # Columnas ajustadas para que quepan en ~100 caracteres
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
            str(acts),
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
        f"[bold white]Success rate:[/bold white] {rate:.1f}%   "
        f"[bold white]Avg duration:[/bold white] {avg_dur:.2f}s   "
        f"[bold white]Avg reward:[/bold white] {avg_reward:.2f}   "
        f"[bold white]Avg actions:[/bold white] {avg_actions:.2f}",
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
            f"{success_rate_ck:.0f}%",
            f"{avg_duration_ck:.1f}",
            f"{avg_reward_ck:.2f}",
            f"{avg_actions_ck:.1f}",
        )

    console.print(coldkey_table)


# ---------------- summary by coldkey/web/use-case UI ---------------
def print_coldkey_resume() -> None:
    stats = load_stats()
    if not stats:
        console.print("[bold red]Snapshot vacío[/bold red]")
        return

    # -----------Detalle (Coldkey / Web / Use-case)----------------
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
    tbl.add_column("Avg reward", justify="right", no_wrap=True, min_width=9)
    tbl.add_column("Avg actions", justify="right", no_wrap=True, min_width=9)
    tbl.add_column("Avg s", justify="right", no_wrap=True, min_width=6)

    for (ck, web, uc), blk in sorted(stats.items()):
        tbl.add_row(
            ck,
            web,
            uc,
            str(len(blk.hotkeys)),
            str(blk.tasks),
            str(blk.successes),
            f"{blk.success_rate*100:4.1f}",
            f"{blk.avg_reward:6.2f}",
            f"{blk.avg_actions:6.2f}",
            f"{blk.avg_duration:6.2f}",
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
    ck_tbl.add_column("Coldkey", style="cyan", width=20, no_wrap=True, overflow="ellipsis")
    ck_tbl.add_column("Hotk", justify="right", no_wrap=True, min_width=4)
    ck_tbl.add_column("Tasks", justify="right", no_wrap=True, min_width=5)
    ck_tbl.add_column("Succ", justify="right", no_wrap=True, min_width=4)
    ck_tbl.add_column("Rate %", justify="right", no_wrap=True, min_width=6)
    ck_tbl.add_column("Avg reward", justify="right", no_wrap=True, min_width=9)
    ck_tbl.add_column("Avg actions", justify="right", no_wrap=True, min_width=9)
    ck_tbl.add_column("Avg s", justify="right", no_wrap=True, min_width=6)

    for ck, acc in sorted(agg_by_ck.items()):
        ck_tbl.add_row(
            ck,
            str(len(acc.hotkeys)),
            str(acc.tasks),
            str(acc.successes),
            f"{acc.success_rate*100:4.1f}",
            f"{acc.avg_reward:6.2f}",
            f"{acc.avg_actions:6.2f}",
            f"{acc.avg_duration:6.2f}",
        )
    console.print(ck_tbl)
