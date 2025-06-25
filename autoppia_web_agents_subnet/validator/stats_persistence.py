# stats_persistence.py
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, List, Set

# Ajusta el import a tu estructura real
from .leaderboard import (
    LeaderboardTaskRecord,
)  # ← cambia “.” si el módulo está en otro paquete

# -----------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------
STATS_FILE = Path("coldkey_usecase_stats.json")  # (sin la ‘k’ duplicada)
AggKey = Tuple[str, str]  # (coldkey, use_case)


# -----------------------------------------------------------------------
# Data block
# -----------------------------------------------------------------------
@dataclass
class StatBlock:
    tasks: int = 0
    successes: int = 0
    duration_sum: float = 0.0
    hotkeys: Set[str] = None  # unique hotkeys for coldkey

    def __post_init__(self):
        if self.hotkeys is None:
            self.hotkeys = set()

    def add(self, success: bool, duration: float, hotkey: str) -> None:
        self.tasks += 1
        if success:
            self.successes += 1
        self.duration_sum += duration
        self.hotkeys.add(hotkey)

    @property
    def avg_duration(self) -> float:
        return self.duration_sum / self.tasks if self.tasks else 0.0


# -----------------------------------------------------------------------
# load / save helpers
# -----------------------------------------------------------------------
def load_stats() -> Dict[AggKey, StatBlock]:
    """Load snapshot; return empty dict if file is missing/empty."""
    if not STATS_FILE.exists():
        return {}

    with STATS_FILE.open() as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError:
            return {}

    stats: Dict[AggKey, StatBlock] = {}
    for key, data in raw.get("stats", {}).items():
        coldkey, use_case = key.split("|", 1)
        stats[(coldkey, use_case)] = StatBlock(
            tasks=data["tasks"],
            successes=data["successes"],
            duration_sum=data["duration_sum"],
            hotkeys=set(data["hotkeys"]),
        )
    return stats


def save_stats(stats: Dict[AggKey, StatBlock]) -> None:
    """Overwrite the JSON snapshot with current state."""
    # Crea la carpeta si no existe
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)

    STATS_FILE.write_text(
        json.dumps(
            {
                "stats": {
                    f"{ck}|{uc}": {
                        "tasks": blk.tasks,
                        "successes": blk.successes,
                        "duration_sum": blk.duration_sum,
                        "hotkeys": sorted(blk.hotkeys),
                    }
                    for (ck, uc), blk in stats.items()
                    if blk.tasks > 0
                }
            },
            indent=2,
        )
    )


# -----------------------------------------------------------------------
# live update
# -----------------------------------------------------------------------
def update_coldkey_stats_json(records: List[LeaderboardTaskRecord]) -> None:
    """Add a new batch of tasks to the snapshot (no time-based reset)."""
    stats = load_stats()

    for rec in records:
        key = (rec.miner_coldkey, rec.use_case)
        blk = stats.setdefault(key, StatBlock())
        blk.add(rec.success, rec.duration, rec.miner_hotkey)

    save_stats(stats)


# -----------------------------------------------------------------------
# pretty print with Rich
# -----------------------------------------------------------------------
from rich.console import Console
from rich.table import Table, box


def print_coldkey_resume() -> None:
    stats = load_stats()
    if not stats:
        Console().print("[bold red]Snapshot vacío[/bold red]")
        return

    tbl = Table(
        title="[bold magenta]Snapshot by Coldkey & Use-Case[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )
    tbl.add_column("Coldkey", style="cyan", width=15, overflow="ellipsis", no_wrap=True)
    tbl.add_column(
        "Use-case", style="cyan", width=18, overflow="ellipsis", no_wrap=True
    )
    tbl.add_column("Hotkeys", justify="right")
    tbl.add_column("Tasks", justify="right")
    tbl.add_column("Successes", justify="right")
    tbl.add_column("Success %", justify="right")
    tbl.add_column("Avg dur s", justify="right")

    for (ck, uc), blk in sorted(stats.items()):
        rate = blk.successes / blk.tasks * 100 if blk.tasks else 0.0
        tbl.add_row(
            ck[:15] + ("…" if len(ck) > 15 else ""),
            uc[:18] + ("…" if len(uc) > 18 else ""),
            str(len(blk.hotkeys)),
            str(blk.tasks),
            str(blk.successes),
            f"{rate:.1f}",
            f"{blk.avg_duration:.2f}",
        )

    Console().print(tbl)
