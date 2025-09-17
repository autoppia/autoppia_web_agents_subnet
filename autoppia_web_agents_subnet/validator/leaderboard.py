import asyncio
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from collections import defaultdict

import numpy as np
import requests

LEADERBOARD_TASKS_ENDPOINT = "https://api-leaderboard.autoppia.com/tasks"


# =============================== DATA MODEL =================================
@dataclass
class LeaderboardTaskRecord:
    validator_uid: int
    miner_uid: int
    miner_coldkey: str
    miner_hotkey: str
    task_id: str
    task_prompt: str
    website: str
    web_project: str
    use_case: str
    actions: List[Dict[str, Any]]  # <--- era Dict; en tu flujo es lista de acciones
    success: bool = False
    score: float = 0.0
    duration: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        raw: Dict[str, Any] = asdict(self)
        cleaned: Dict[str, Any] = {}
        for k, v in raw.items():
            # Convert numpy types to native Python types
            if isinstance(v, np.generic):
                cleaned[k] = v.item()
            else:
                cleaned[k] = v
        return cleaned


# =============================== SENDER =====================================
def send_many_tasks_to_leaderboard(
    records: List[LeaderboardTaskRecord],
    endpoint: str = LEADERBOARD_TASKS_ENDPOINT,
    timeout: int = 30,
) -> requests.Response:
    """
    POST multiple task records in one go to the leaderboard service.
    Hits the /tasks/bulk/ endpoint with a JSON array.
    """
    bulk_url = f"{endpoint}/bulk/"
    payload = [r.to_dict() for r in records]
    headers = {"Content-Type": "application/json"}
    resp = requests.post(bulk_url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp


async def send_many_tasks_to_leaderboard_async(
    records: List[LeaderboardTaskRecord],
    endpoint: str = LEADERBOARD_TASKS_ENDPOINT,
    timeout: int = 30,
) -> None:
    """
    Async wrapper: dispatch send_many_tasks_to_leaderboard in a thread so it
    doesn’t block your event loop.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        send_many_tasks_to_leaderboard,
        records,
        endpoint,
        timeout,
    )


# =============================== VISUALIZATION ===============================
from rich.console import Console
from rich.table import Table
from rich import box

console = Console(
    force_terminal=True,  # Trata la salida como si fuera un TTY
    color_system="truecolor",  # Usa el sistema de colores full
    no_color=False,  # Asegúrate de NO desactivar el color
)


def _actions_len(actions_obj: Any) -> int:
    """Robusto ante list/dict/None para contar acciones."""
    if actions_obj is None:
        return 0
    if isinstance(actions_obj, list):
        return len(actions_obj)
    if isinstance(actions_obj, dict):
        # a veces llega como {"actions": [...]} o algo similar
        if "actions" in actions_obj and isinstance(actions_obj["actions"], list):
            return len(actions_obj["actions"])
        # fallback: contamos claves
        return len(actions_obj)
    return 0


def print_leaderboard_table(records: List[LeaderboardTaskRecord], task_prompt: str, web_project: Optional[str]):
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
    results.add_column("Coldkey", style="cyan", ratio=4, overflow="fold")
    results.add_column("Hotkey", style="cyan", ratio=4, overflow="fold")
    results.add_column("Miner UID", style="green", ratio=1, justify="center", no_wrap=True)
    results.add_column("Success", ratio=1, justify="center")
    results.add_column("Actions", ratio=1, justify="right")  # <--- NUEVO
    results.add_column("Reward", ratio=1, justify="right")  # <--- NUEVO
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

    # ────────── Métricas finales del lote ──────────
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
    coldkey_table.add_column("Coldkey", style="cyan", width=15, overflow="ellipsis", no_wrap=True)
    coldkey_table.add_column("Total hotkeys", justify="right")
    coldkey_table.add_column("Total tasks", justify="right")
    coldkey_table.add_column("Successes", justify="right")
    coldkey_table.add_column("Success rate %", justify="right")
    coldkey_table.add_column("Avg duration s", justify="right")
    coldkey_table.add_column("Avg reward", justify="right")  # <--- NUEVO
    coldkey_table.add_column("Avg actions", justify="right")  # <--- NUEVO

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
