# autoppia_web_agents_subnet/validator/stats_persistence.py
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple, Set, Any

from .leaderboard import LeaderboardTaskRecord

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
STATS_FILE = Path("coldkey_web_usecase_stats.json")  # snapshot file
AggKey = Tuple[str, str, str]  # (coldkey, web, use_case)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _actions_len(actions_obj: Any) -> int:
    """Robust length for actions (list / dict / None)."""
    if actions_obj is None:
        return 0
    if isinstance(actions_obj, list):
        return len(actions_obj)
    if isinstance(actions_obj, dict):
        if "actions" in actions_obj and isinstance(actions_obj["actions"], list):
            return len(actions_obj["actions"])
        return len(actions_obj)
    return 0


# ---------------------------------------------------------------------------
# Data block
# ---------------------------------------------------------------------------
@dataclass
class StatBlock:
    tasks: int = 0
    successes: int = 0
    duration_sum: float = 0.0
    reward_sum: float = 0.0  # NEW
    actions_sum: int = 0  # NEW
    hotkeys: Set[str] = field(default_factory=set)  # unique hotkeys

    # helpers ---------------------------------------------------------------
    def add(self, success: bool, duration: float, reward: float, actions_len: int, hotkey: str) -> None:
        self.tasks += 1
        self.successes += int(success)
        self.duration_sum += float(duration)
        self.reward_sum += float(reward)
        self.actions_sum += int(actions_len)
        self.hotkeys.add(hotkey)

    @property
    def success_rate(self) -> float:
        return self.successes / self.tasks if self.tasks else 0.0

    @property
    def avg_duration(self) -> float:
        return self.duration_sum / self.tasks if self.tasks else 0.0

    @property
    def avg_reward(self) -> float:
        return self.reward_sum / self.tasks if self.tasks else 0.0

    @property
    def avg_actions(self) -> float:
        return self.actions_sum / self.tasks if self.tasks else 0.0


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
                # backward-compatible: default 0 if old file
                stats[(ck, web, uc)] = StatBlock(
                    tasks=data.get("tasks", 0),
                    successes=data.get("successes", 0),
                    duration_sum=data.get("duration_sum", 0.0),
                    reward_sum=data.get("reward_sum", 0.0),
                    actions_sum=data.get("actions_sum", 0),
                    hotkeys=set(data.get("hotkeys", [])),
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
            "reward_sum": blk.reward_sum,  # NEW
            "actions_sum": blk.actions_sum,  # NEW
            "hotkeys": sorted(blk.hotkeys),
        }

    STATS_FILE.write_text(json.dumps({"stats": nested}, indent=2))


# ---------------------------------------------------------------------------
# live update
# ---------------------------------------------------------------------------
def update_coldkey_stats_json(records: List[LeaderboardTaskRecord]) -> None:
    """
    Update the snapshot with the current batch and PURGE any coldkeys
    not present in the batch.
    """
    stats = load_stats()

    # purge coldkeys not present in the batch
    current_coldkeys: set[str] = {r.miner_coldkey for r in records}
    stats = {k: v for k, v in stats.items() if k[0] in current_coldkeys}

    # apply batch
    for rec in records:
        key = (rec.miner_coldkey, rec.web_project, rec.use_case)
        blk = stats.setdefault(key, StatBlock())
        blk.add(
            success=rec.success,
            duration=rec.duration,
            reward=float(rec.score),
            actions_len=_actions_len(rec.actions),
            hotkey=rec.miner_hotkey,
        )

    save_stats(stats)


# ---------------------------------------------------------------------------
# pretty print
# ---------------------------------------------------------------------------
from rich.console import Console
from rich.table import Table, box

console = Console(
    force_terminal=True,
    color_system="truecolor",
    no_color=False,
)


def print_coldkey_resume() -> None:
    """
    Prints two tables:
      1) Per-coldkey totals (across all webs/use-cases)
      2) Snapshot by Coldkey / Web / Use-case (detailed)
    """
    stats = load_stats()
    if not stats:
        console.print("[bold red]Snapshot vacío[/bold red]")
        return

    # 1) Aggregate per coldkey
    agg_by_ck: Dict[str, StatBlock] = {}
    for (ck, web, uc), blk in stats.items():
        acc = agg_by_ck.setdefault(ck, StatBlock())
        # merge: sum fields and union hotkeys
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

    # 2) Detailed snapshot by Coldkey / Web / Use-case
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
