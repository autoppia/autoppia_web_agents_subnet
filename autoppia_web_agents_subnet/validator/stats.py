# stats_persistence.py  – snapshot por Coldkey > Web > Use-case
import json
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set
import bittensor as bt

# Ajusta el import si tu estructura es distinta
from .leaderboard import LeaderboardTaskRecord

from autoppia_web_agents_subnet.validator.config import STATS_FILE
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


def init_validator_performance_stats(validator) -> None:
    """
    Initialize a performance statistics dictionary on the validator if not present.
    This dictionary will track data across multiple forward calls.
    """
    if not hasattr(validator, "validator_performance_stats"):
        validator.validator_performance_stats = {
            "total_forwards_count": 0,  # how many forward passes occurred
            "total_forwards_time": 0.0,  # sum of all forward iteration times
            "total_tasks_generated": 0,  # how many tasks have been generated in total
            "total_generated_tasks_time": 0.0,  # total time spent generating tasks
            "total_processing_tasks_time": 0.0,  # total time spent in process_tasks
            "total_tasks_sent": 0,  # how many tasks have been sent overall (accum. from all forwards)
            "total_tasks_success": 0,  # tasks with at least one reward>0
            "total_tasks_wrong": 0,  # tasks with responses but no reward>0
            "total_tasks_no_response": 0,  # tasks with 0 valid responses
            "total_sum_of_avg_response_times": 0.0,  # sum of average miner solve times per task
            "total_sum_of_evaluation_times": 0.0,  # sum of times spent evaluating (score updates)
            "total_sum_of_avg_scores": 0.0,  # sum of average rewards per task
            "overall_tasks_processed": 0,  # total tasks processed for stats
        }


def update_validator_performance_stats(
    validator,
    tasks_count: int,
    num_success: int,
    num_wrong: int,
    num_no_response: int,
    sum_of_avg_response_times: float,
    sum_of_evaluation_times: float,
    sum_of_avg_scores: float,
) -> None:
    """
    Accumulates stats from a single batch of processed tasks into
    the validator's performance stats dictionary.
    """
    if not hasattr(validator, "validator_performance_stats"):
        init_validator_performance_stats(validator)

    vps = validator.validator_performance_stats

    # update global counters
    vps["total_tasks_sent"] += tasks_count
    vps["total_tasks_success"] += num_success
    vps["total_tasks_wrong"] += num_wrong
    vps["total_tasks_no_response"] += num_no_response

    # sums used to compute averages
    vps["total_sum_of_avg_response_times"] += sum_of_avg_response_times
    vps["total_sum_of_evaluation_times"] += sum_of_evaluation_times
    vps["total_sum_of_avg_scores"] += sum_of_avg_scores

    vps["overall_tasks_processed"] += tasks_count


def print_validator_performance_stats(validator) -> None:
    """
    Pretty-prints the validator performance stats using a Rich-styled table.
    """
    from rich.table import Table
    from rich.console import Console
    from rich import box

    vps = getattr(validator, "validator_performance_stats", None)
    if not vps:
        bt.logging.warning("No validator performance stats to display.")
        return

    # Compute derived stats
    total_forwards = vps["total_forwards_count"]
    avg_forward_time = (
        vps["total_forwards_time"] / total_forwards if total_forwards > 0 else 0.0
    )

    total_gen_tasks = vps["total_tasks_generated"]
    avg_task_gen_time = (
        vps["total_generated_tasks_time"] / total_gen_tasks
        if total_gen_tasks > 0
        else 0.0
    )

    overall_tasks = vps["overall_tasks_processed"]
    avg_processing_time_per_task = (
        vps["total_processing_tasks_time"] / overall_tasks if overall_tasks > 0 else 0.0
    )

    # success rate, etc
    tasks_sent = vps["total_tasks_sent"]
    tasks_success = vps["total_tasks_success"]
    tasks_wrong = vps["total_tasks_wrong"]
    tasks_no_resp = vps["total_tasks_no_response"]
    success_rate = (tasks_success / tasks_sent) if tasks_sent > 0 else 0.0

    avg_response_time = (
        vps["total_sum_of_avg_response_times"] / overall_tasks
        if overall_tasks > 0
        else 0.0
    )
    avg_evaluation_time = (
        vps["total_sum_of_evaluation_times"] / overall_tasks
        if overall_tasks > 0
        else 0.0
    )
    avg_score = (
        vps["total_sum_of_avg_scores"] / overall_tasks if overall_tasks > 0 else 0.0
    )

    console = Console()
    table = Table(
        title="[bold yellow]Validator Performance Stats[/bold yellow]",
        header_style="bold magenta",
        box=box.SIMPLE,
        expand=True,
    )
    table.add_column("Stat", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total Forwards", str(total_forwards))
    table.add_row("Average Forward Time (s)", f"{avg_forward_time:.2f}")

    table.add_row("Tasks Generated (total)", str(total_gen_tasks))
    table.add_row(
        "Total Time Generating Tasks (s)", f"{vps['total_generated_tasks_time']:.2f}"
    )
    table.add_row("Average Time per Generated Task (s)", f"{avg_task_gen_time:.2f}")

    table.add_row("Tasks Processed (total)", str(tasks_sent))
    table.add_row("Successfull tasks", str(tasks_success))
    table.add_row("Not Successfull Tasks", str(tasks_wrong))
    table.add_row("Tasks with No Response", str(tasks_no_resp))
    table.add_row("Success Rate", f"{(success_rate * 100):.2f}%")

    table.add_row("Avg Miner Solve Time (s)", f"{avg_response_time:.2f}")
    table.add_row("Avg Evaluation Time per Task (s)", f"{avg_evaluation_time:.4f}")
    table.add_row("Avg Score per Task", f"{avg_score:.4f}")

    table.add_row(
        "Total Time Processing Tasks (s)", f"{vps['total_processing_tasks_time']:.2f}"
    )
    table.add_row(
        "Average Processing Time per Task (s)", f"{avg_processing_time_per_task:.2f}"
    )

    console.print(table)
    console.print()  # extra newline
