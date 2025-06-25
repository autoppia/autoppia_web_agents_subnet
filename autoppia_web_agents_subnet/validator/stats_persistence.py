# stats_persistence.py  – snapshot por Coldkey > Web > Use-case
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple, Set

# Ajusta el import si tu estructura es distinta
from .leaderboard import LeaderboardTaskRecord

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
STATS_FILE = Path("coldkey_web_usecase_stats.json")  # snapshot
AggKey = Tuple[str, str, str]  # (coldkey, web, use_case)


# ---------------------------------------------------------------------------
# Data block
# ---------------------------------------------------------------------------
@dataclass
class StatBlock:
    tasks: int = 0
    successes: int = 0
    duration_sum: float = 0.0
    hotkeys: Set[str] = field(default_factory=set)  # unique hotkeys

    # helpers ---------------------------------------------------------------
    def add(self, success: bool, duration: float, hotkey: str) -> None:
        self.tasks += 1
        self.successes += int(success)
        self.duration_sum += duration
        self.hotkeys.add(hotkey)

    @property
    def success_rate(self) -> float:
        return self.successes / self.tasks if self.tasks else 0.0

    @property
    def avg_duration(self) -> float:
        return self.duration_sum / self.tasks if self.tasks else 0.0


# ---------------------------------------------------------------------------
# load / save helpers
# ---------------------------------------------------------------------------
def load_stats() -> Dict[AggKey, StatBlock]:
    if not STATS_FILE.exists():
        return {}

    try:
        raw = json.loads(STATS_FILE.read_text())
    except json.JSONDecodeError:
        return {}

    stats: Dict[AggKey, StatBlock] = {}
    for ck, webs in raw.get("stats", {}).items():
        for web, ucs in webs.items():
            for uc, data in ucs.items():
                stats[(ck, web, uc)] = StatBlock(
                    tasks=data["tasks"],
                    successes=data["successes"],
                    duration_sum=data["duration_sum"],
                    hotkeys=set(data["hotkeys"]),
                )
    return stats


def save_stats(stats: Dict[AggKey, StatBlock]) -> None:
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)

    # serialise as coldkey > web > use_case
    nested: Dict[str, Dict[str, Dict[str, Dict]]] = {}
    for (ck, web, uc), blk in stats.items():
        nested.setdefault(ck, {}).setdefault(web, {})[uc] = {
            "tasks": blk.tasks,
            "successes": blk.successes,
            "duration_sum": blk.duration_sum,
            "hotkeys": sorted(blk.hotkeys),
        }

    STATS_FILE.write_text(json.dumps({"stats": nested}, indent=2))


# ---------------------------------------------------------------------------
# live update
# ---------------------------------------------------------------------------
def update_coldkey_stats_json(records: List[LeaderboardTaskRecord]) -> None:
    """
    Actualiza el snapshot con el lote actual y **elimina** cualquier coldkey que
    no aparezca en el lote (se considera desaparecido).
    """
    stats = load_stats()

    # --- purgar coldkeys ausentes en el lote ---
    current_coldkeys: set[str] = {r.miner_coldkey for r in records}
    stats = {k: v for k, v in stats.items() if k[0] in current_coldkeys}

    # --- aplicar lote ---
    for rec in records:
        key = (rec.miner_coldkey, rec.web_project, rec.use_case)
        blk = stats.setdefault(key, StatBlock())
        blk.add(rec.success, rec.duration, rec.miner_hotkey)

    save_stats(stats)


# ---------------------------------------------------------------------------
# pretty print
# ---------------------------------------------------------------------------
from rich.console import Console
from rich.table import Table, box

console = Console(
    force_terminal=True,  # Trata la salida como si fuera un TTY
    color_system="truecolor",  # Usa el sistema de colores full
    no_color=False,  # Asegúrate de NO desactivar el color
)


def print_coldkey_resume() -> None:
    stats = load_stats()
    if not stats:
        console.print("[bold red]Snapshot vacío[/bold red]")
        return

    tbl = Table(
        title="[bold magenta]Snapshot by Coldkey / Web / Use-case[/bold magenta]",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
        expand=True,
    )

    # Texto ---------------------------------------------------------------
    tbl.add_column("Coldkey", style="cyan", ratio=6, overflow="ellipsis", no_wrap=True)
    tbl.add_column("Web", style="cyan", width=10, no_wrap=True)
    tbl.add_column("Use-case", style="cyan", width=12, no_wrap=True)

    # Números -------------------------------------------------------------
    tbl.add_column("Hotk", justify="right")
    tbl.add_column("Tasks", justify="right")
    tbl.add_column("Succ", justify="right")
    tbl.add_column("Rate %", justify="right")
    tbl.add_column("Avg s", justify="right")

    for (ck, web, uc), blk in sorted(stats.items()):
        tbl.add_row(
            ck,  # se recorta con ellipsis si hace falta
            web,
            uc,
            str(len(blk.hotkeys)),
            str(blk.tasks),
            str(blk.successes),
            f"{blk.success_rate*100:5.1f}",
            f"{blk.avg_duration:6.2f}",
        )

    console.print(tbl)
