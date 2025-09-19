# autoppia_web_agents_subnet/validator/stats.py
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set


# ========================== Forward (in-memory) =============================
def init_validator_performance_stats(validator) -> None:
    """
    Inicializa el diccionario de stats si no existe. Los campos
    están alineados con la UI de print_forward_tables.
    """
    if hasattr(validator, "validator_performance_stats"):
        return

    validator.validator_performance_stats = {
        # ACUMULADO (para la tabla Cumulative)
        "total_forwards_count": 0,
        "total_forwards_time": 0.0,
        "total_tasks_sent": 0,
        # NUEVOS acumuladores para "Miners OK" (ok/attempts) y su %
        "total_miners_successes": 0,
        "total_miners_attempts": 0,
        # Snapshot del último forward (para la tabla Forward summary)
        "last_forward": {
            "forward_id": 0,  # id del forward (ej. self.forward_count)
            "tasks_sent": 0,  # tareas enviadas en ese forward
            "forward_time": 0.0,  # tiempo total del forward (s)
            "avg_time_per_task": 0.0,  # media de tiempo por tarea (s)
            "miner_successes": 0,  # miners OK (ok)
            "miner_attempts": 0,  # miners attempts (attempts)
        },
    }


def finalize_forward_stats(
    validator,
    *,
    tasks_sent: int,
    sum_avg_response_times: float,  # suma de avg_miner_time por tarea (para media por tarea)
    forward_time: float,  # tiempo total del forward (s)
    miner_successes: int = 0,  # miners OK (sumados en el forward)
    miner_attempts: int = 0,  # miners intentos (sumados en el forward)
    forward_id: int | None = None,  # id del forward (self.forward_count)
) -> Dict[str, Any]:
    """
    Actualiza acumulados y snapshot del último forward.
    Devuelve un pequeño resumen por si el caller lo quiere loguear.
    """
    stats = validator.validator_performance_stats

    # Medias
    avg_time_per_task = (sum_avg_response_times / tasks_sent) if tasks_sent > 0 else 0.0

    # --- Snapshot del último forward ---
    stats["last_forward"] = {
        "forward_id": int(forward_id) if forward_id is not None else int(stats.get("total_forwards_count", 0) + 1),
        "tasks_sent": int(tasks_sent),
        "forward_time": float(forward_time),
        "avg_time_per_task": float(avg_time_per_task),
        "miner_successes": int(miner_successes),
        "miner_attempts": int(miner_attempts),
    }

    # --- Acumulados ---
    stats["total_forwards_count"] += 1
    stats["total_forwards_time"] += float(forward_time)
    stats["total_tasks_sent"] += int(tasks_sent)

    stats["total_miners_successes"] += int(miner_successes)
    stats["total_miners_attempts"] += int(miner_attempts)

    # (Opcional) Devolver un resumen útil
    totals = {
        "forwards_count": stats["total_forwards_count"],
        "total_time": stats["total_forwards_time"],
        "tasks_sent": stats["total_tasks_sent"],
        "miners_ok": stats["total_miners_successes"],
        "miners_attempts": stats["total_miners_attempts"],
    }
    return {"forward": stats["last_forward"], "totals": totals}


# ====================== Snapshot Coldkey/Web/Use-case ========================
STATS_FILE = Path("coldkey_web_usecase_stats.json")
AggKey = Tuple[str, str, str]  # (coldkey, web, use_case)


def _actions_len(actions_obj: Any) -> int:
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


# Import tardío para evitar ciclos
from .leaderboard_api.leaderboard import LeaderboardTaskRecord


def update_coldkey_stats_json(records: List[LeaderboardTaskRecord]) -> None:
    """
    Aplica el lote actual de records y purga coldkeys no presentes,
    acumulando tasks, successes, duration_sum, reward_sum y actions_sum.
    """
    stats = load_stats()
    current_coldkeys: set[str] = {r.miner_coldkey for r in records}
    stats = {k: v for k, v in stats.items() if k[0] in current_coldkeys}

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
