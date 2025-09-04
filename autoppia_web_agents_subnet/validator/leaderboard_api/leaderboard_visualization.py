from typing import List
from .leaderboard_tasks import LeaderboardTaskRecord


# ------------------------------------ VISUALIZATION ------------------------------------#
from rich.console import Console
from rich.table import Table
from rich import box
from typing import List, Optional
from collections import defaultdict

console = Console(
    force_terminal=True,  # Trata la salida como si fuera un TTY
    color_system="truecolor",  # Usa el sistema de colores full
    no_color=False,  # Asegúrate de NO desactivar el color
)


def print_leaderboard_table(
    records: List[LeaderboardTaskRecord], task_prompt: str, web_project: Optional[str]
):
    # ────────── Tabla 1: Task Info ──────────
    info_table = Table(box=box.SIMPLE_HEAD, show_header=False, expand=True)
    info_table.add_column("Field", style="bold cyan", no_wrap=True, width=12)
    info_table.add_column("Value", style="cyan")
    info_table.add_row("Task:", task_prompt)
    info_table.add_row("Web Project:", web_project or "—")
    console.print(info_table)

    # ────────── Tabla 2: Miner Results ──────────
    results = Table(
        title="[bold magenta]Leaderboard Results[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    # Aseguramos que la columna Hotkey se expanda al máximo:
    results.add_column("Coldkey", style="cyan", ratio=4, overflow="fold")
    results.add_column("Hotkey", style="cyan", ratio=4, overflow="fold")
    results.add_column(
        "Miner UID", style="green", ratio=1, justify="center", no_wrap=True
    )
    results.add_column("Success", ratio=1, justify="center")
    results.add_column("Duration (s)", ratio=1, justify="center", overflow="fold")

    for rec in records:
        results.add_row(
            rec.miner_coldkey,
            rec.miner_hotkey,
            str(rec.miner_uid),
            "[green]✅[/green]" if rec.success else "[red]❌[/red]",
            f"{rec.duration:.2f}",
        )
    console.print(results)

    # ────────── Métricas finales ──────────
    total = len(records)
    successes = sum(1 for r in records if r.success)
    rate = (successes / total * 100) if total else 0.0
    avg_dur = (sum(r.duration for r in records) / total) if total else 0.0

    console.print(
        f"[bold white]Total successes:[/bold white] {successes}/{total}   "
        f"[bold white]Success rate:[/bold white] {rate:.1f}%   "
        f"[bold white]Avg duration:[/bold white] {avg_dur:.2f}s",
        style="yellow",
    )

    # ────────── Métricas por Coldkey ──────────

    coldkey_groups: dict[str, List[LeaderboardTaskRecord]] = defaultdict(list)
    for rec in records:
        coldkey_groups[rec.miner_coldkey].append(rec)

    coldkey_table = Table(
        title="[bold magenta]Per-Coldkey Averages[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    coldkey_table.add_column(
        "Coldkey",
        style="cyan",
        width=15,
        overflow="ellipsis",
        no_wrap=True,
    )
    coldkey_table.add_column("Total hotkeys", justify="right")
    coldkey_table.add_column("Total tasks", justify="right")
    coldkey_table.add_column("Successes", justify="right")
    coldkey_table.add_column("Success rate %", justify="right")
    coldkey_table.add_column("Avg duration s", justify="right")

    for coldkey, ck_records in coldkey_groups.items():
        total_ck_tasks = len(ck_records)
        total_ck_successes = sum(1 for r in ck_records if r.success)
        success_rate_ck = (
            total_ck_successes / total_ck_tasks * 100 if total_ck_tasks else 0.0
        )
        avg_duration_ck = (
            sum(r.duration for r in ck_records) / total_ck_tasks
            if total_ck_tasks
            else 0.0
        )
        # número único de hotkeys asociadas a este coldkey
        unique_hotkeys = {r.miner_hotkey for r in ck_records}
        total_hotkeys_ck = len(unique_hotkeys)

        coldkey_table.add_row(
            coldkey,
            str(total_hotkeys_ck),
            str(total_ck_tasks),
            str(total_ck_successes),
            f"{success_rate_ck:.1f}",
            f"{avg_duration_ck:.2f}",
        )

    console.print(coldkey_table)
