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
    title = f"[bold]Task:[/bold] {task_prompt}\n[bold]Site:[/bold] {web_project}"
    table = Table(title=title, box=box.SIMPLE_HEAVY)

    table.add_column("Miner UID", justify="right", style="cyan", no_wrap=True)
    table.add_column("Success", justify="center")

    # Rows
    for rec in records:
        table.add_row(
            str(rec.miner_uid), "[green]✅[/green]" if rec.success else "[red]❌[/red]"
        )

    console.print(table)

    # Metrics
    total = len(records)
    successes = sum(1 for r in records if r.success)
    rate = (successes / total * 100) if total else 0.0
    avg_duration = (sum(r.duration for r in records) / total) if total else 0.0

    # Sum up
    console.print(
        f"[bold]Total successes:[/bold] {successes}/{total}   "
        f"[bold]Success rate:[/bold] {rate:.1f}%   "
        f"[bold]Avg duration:[/bold] {avg_duration:.2f}s",
        style="yellow",
    )
