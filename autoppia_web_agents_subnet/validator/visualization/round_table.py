# autoppia_web_agents_subnet/validator/visualization/round_table.py
from __future__ import annotations

from typing import Dict, Any

import numpy as np

try:
    from rich.table import Table
    from rich.console import Console
    from rich import box
    _RICH = True
except Exception:
    _RICH = False


def _mean_safe(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(np.mean(np.asarray(values, dtype=np.float32)))


def render_round_summary_table(round_manager, final_rewards: Dict[int, float], metagraph: Any, *, to_console: bool = True) -> str:
    """
    Render a concise per-miner summary at end of round:
    Columns: UID, Hotkey(10), AvgScore, AvgTime(s), Reward (final)
    Sorted by Reward desc.
    """
    rows: list[dict[str, Any]] = []

    # Build rows for all miners that participated this round (or appear in final rewards)
    uids = set(list(round_manager.round_rewards.keys()) + list(final_rewards.keys()))
    for uid in sorted(uids):
        hotkey = metagraph.hotkeys[uid] if uid < len(metagraph.hotkeys) else "<unknown>"
        avg_eval = _mean_safe(round_manager.round_eval_scores.get(uid, []))
        avg_time = _mean_safe(round_manager.round_times.get(uid, []))
        avg_reward = _mean_safe(round_manager.round_rewards.get(uid, []))  # Pre-WTA reward (0.85*score + 0.15*time)
        wta_reward = float(final_rewards.get(uid, 0.0))  # Post-WTA reward (1.0 for winner)
        rows.append({
            "uid": int(uid),
            "hotkey": hotkey,
            "hotkey_prefix": hotkey[:10],
            "avg_eval": avg_eval,
            "avg_time": avg_time,
            "avg_reward": avg_reward,
            "wta_reward": wta_reward,
        })

    # Sort by WTA reward desc, then by avg_reward desc for tie-break
    rows.sort(key=lambda r: (r["wta_reward"], r["avg_reward"]), reverse=True)

    if not rows:
        text = "[no miners / no tasks this round]"
        if to_console and _RICH:
            Console().print(text)
        return text

    if _RICH:
        tbl = Table(
            title="[bold magenta]Round Summary — Miners[/bold magenta]",
            box=box.SIMPLE_HEAVY,
            header_style="bold cyan",
            expand=True,
            show_lines=False,
            padding=(0, 1),
        )
        tbl.add_column("#", justify="right", width=3)
        tbl.add_column("UID", justify="right", width=5)
        tbl.add_column("Hotkey", style="cyan", overflow="ellipsis")
        tbl.add_column("AvgScore", justify="right", width=10)
        tbl.add_column("AvgTime(s)", justify="right", width=10)
        tbl.add_column("AvgReward", justify="right", width=10)
        tbl.add_column("WTA_Reward", justify="right", width=10)

        for i, r in enumerate(rows, start=1):
            tbl.add_row(
                str(i),
                str(r["uid"]),
                r["hotkey_prefix"],
                f'{r["avg_eval"]:.4f}',
                f'{r["avg_time"]:.3f}',
                f'{r["avg_reward"]:.4f}',
                f'{r["wta_reward"]:.4f}',
            )

        console = Console()
        console.print(tbl)
        return f"Round Summary — Miners (n={len(rows)})."

    # Fallback plain text table
    lines = [
        "Round Summary — Miners",
        f'{"#":>3} {"UID":>5} {"HOTKEY":<12} {"AvgScore":>10} {"AvgTime(s)":>10} {"AvgReward":>10} {"WTA_Reward":>10}',
    ]
    for i, r in enumerate(rows, start=1):
        lines.append(
            f'{i:>3} {r["uid"]:>5} {r["hotkey_prefix"]:<12.12} '
            f'{r["avg_eval"]:>10.4f} {r["avg_time"]:>10.3f} {r["avg_reward"]:>10.4f} {r["wta_reward"]:>10.4f}'
        )
    text = "\n".join(lines)
    if to_console:
        print(text)
    return text
