# autoppia_web_agents_subnet/validator/stats.py
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set

# Para snapshot por coldkey/web/use-case
STATS_FILE = Path("coldkey_web_usecase_stats.json")
AggKey = Tuple[str, str, str]  # (coldkey, web, use_case)


# ========================== Forward (en memoria) =============================
def init_validator_performance_stats(validator) -> None:
    """
    Inicializa el storage en memoria de métricas por forward (si no existe).
    """
    if hasattr(validator, "validator_performance_stats"):
        return
    validator.validator_performance_stats = {
        # ACUMULADO
        "total_forwards_count": 0,
        "total_forwards_time": 0.0,
        "total_tasks_sent": 0,
        "total_tasks_success": 0,
        "total_tasks_failed": 0,
        "total_sum_of_avg_response_times": 0.0,
        "overall_tasks_processed": 0,
        # ÚLTIMO FORWARD (snapshot)
        "last_forward": {
            "tasks_sent": 0,
            "tasks_success": 0,
            "tasks_failed": 0,
            "avg_response_time_per_task": 0.0,
            "forward_time": 0.0,
        },
    }


def finalize_forward_stats(
    validator,
    *,
    tasks_sent: int,
    tasks_success: int,
    sum_avg_response_times: float,
    forward_time: float,
) -> Dict[str, Any]:
    """
    Cierra las métricas de un forward: snapshot + actualización de acumulados.
    Devuelve {"forward": {...}, "totals": {...}}.
    """
    stats = validator.validator_performance_stats
    tasks_failed = max(0, tasks_sent - tasks_success)
    avg_resp_time = (sum_avg_response_times / tasks_sent) if tasks_sent > 0 else 0.0

    # Snapshot del forward
    forward_snapshot = {
        "tasks_sent": tasks_sent,
        "tasks_success": tasks_success,
        "tasks_failed": tasks_failed,
        "avg_response_time_per_task": avg_resp_time,
        "forward_time": forward_time,
    }
    stats["last_forward"] = forward_snapshot

    # Acumulado
    stats["total_forwards_count"] += 1
    stats["total_forwards_time"] += forward_time
    stats["total_tasks_sent"] += tasks_sent
    stats["total_tasks_success"] += tasks_success
    stats["total_tasks_failed"] += tasks_failed
    stats["total_sum_of_avg_response_times"] += sum_avg_response_times
    stats["overall_tasks_processed"] += tasks_sent

    totals_avg_resp = stats["total_sum_of_avg_response_times"] / stats["overall_tasks_processed"] if stats["overall_tasks_processed"] > 0 else 0.0
    totals_success_rate = stats["total_tasks_success"] / stats["total_tasks_sent"] if stats["total_tasks_sent"] > 0 else 0.0
    totals = {
        "forwards_count": stats["total_forwards_count"],
        "total_time": stats["total_forwards_time"],
        "tasks_sent": stats["total_tasks_sent"],
        "tasks_success": stats["total_tasks_success"],
        "tasks_failed": stats["total_tasks_failed"],
        "avg_response_time_per_task": totals_avg_resp,
        "success_rate": totals_success_rate,
    }
    return {"forward": forward_snapshot, "totals": totals}


# ====================== Snapshot Coldkey/Web/Use-case ========================
def _actions_len(actions_obj: Any) -> int:
    """Tamaño robusto de acciones (list / dict / None)."""
    if actions_obj is None:
        return 0
    if isinstance(actions_obj, list):
        return len(actions_obj)
    if isinstance(actions_obj, dict):
        if "actions" in actions_obj and isinstance(actions_obj["actions"], list):
            return len(actions_obj["actions"])
        return len(actions_obj)
    return 0


@dataclass
class StatBlock:
    tasks: int = 0
    successes: int = 0
    duration_sum: float = 0.0
    reward_sum: float = 0.0
    actions_sum: int = 0
    hotkeys: Set[str] = field(default_factory=set)

    def add(self, *, success: bool, duration: float, reward: float, actions_len: int, hotkey: str) -> None:
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

    nested: Dict[str, Dict[str, Dict[str, Dict]]] = {}
    for (ck, web, uc), blk in stats.items():
        nested.setdefault(ck, {}).setdefault(web, {})[uc] = {
            "tasks": blk.tasks,
            "successes": blk.successes,
            "duration_sum": blk.duration_sum,
            "reward_sum": blk.reward_sum,
            "actions_sum": blk.actions_sum,
            "hotkeys": sorted(blk.hotkeys),
        }

    STATS_FILE.write_text(json.dumps({"stats": nested}, indent=2))


# Para mantener la firma que usas en forward_utils.py
from .leaderboard import LeaderboardTaskRecord


def update_coldkey_stats_json(records: List[LeaderboardTaskRecord]) -> None:
    """
    Actualiza el snapshot con el lote actual y PURGA cualquier coldkey que no
    aparezca en el lote.
    """
    stats = load_stats()

    # purgar coldkeys ausentes
    current_coldkeys: set[str] = {r.miner_coldkey for r in records}
    stats = {k: v for k, v in stats.items() if k[0] in current_coldkeys}

    # aplicar lote
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
