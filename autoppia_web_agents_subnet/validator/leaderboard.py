import asyncio
from dataclasses import dataclass, asdict
from typing import Any, Dict, List

import numpy as np
import requests

LEADERBOARD_TASKS_ENDPOINT = "https://api-leaderboard.autoppia.com/tasks"


@dataclass
class LeaderboardTaskRecord:
    validator_uid: int
    miner_uid: int
    miner_hotkey: str
    task_id: str
    task_prompt: str
    website: str
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
    # Esto se ejecuta en un ThreadPoolExecutor, no bloquea el loop principal
    await loop.run_in_executor(
        None,
        send_many_tasks_to_leaderboard,
        records,
        endpoint,
        timeout,
    )


##------------------------------------VISUALIZATION------------------------------------##
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


def print_leaderboard_table(
    records: List[LeaderboardTaskRecord], task_prompt: str, web_project: str | None
):
    # Título con prompt + sitio
    title = (
        f"[bold white]Task:[/bold white] {task_prompt}    "
        f"[bold white]Site:[/bold white] {web_project}"
    )

    # Tabla ligera, que se expande al ancho de la terminal
    table = Table(
        title=title,
        box=box.SIMPLE,
        show_header=True,
        header_style="bold magenta",
        expand=True,
    )

    table.add_column("Hotkey", justify="center", style="green")
    table.add_column("Miner UID", justify="center", style="cyan", no_wrap=True)
    table.add_column("Success", justify="center")
    table.add_column("Duration (s)", justify="center")

    # Filas
    for rec in records:
        table.add_row(
            rec.miner_hotkey,
            str(rec.miner_uid),
            "[green]✅[/green]" if rec.success else "[red]❌[/red]",
            f"{rec.duration:.2f}",
        )

    console.print(table)

    # Métricas al pie
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
