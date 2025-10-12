# autoppia_web_agents_subnet/validator/visualization/weights_table.py
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


def render_weights_table(processed_weight_uids: np.ndarray, processed_weights: np.ndarray, metagraph: Any, *, to_console: bool = True) -> str:
    """
    Render a clear weights table showing UID, Hotkey, and Final Weight.
    Only shows miners with non-zero weights, sorted by weight desc.
    """
    rows: list[dict[str, Any]] = []

    # Build rows for miners with non-zero weights
    for uid, weight in zip(processed_weight_uids, processed_weights):
        if weight > 0:  # Only show non-zero weights
            hotkey = metagraph.hotkeys[uid] if uid < len(metagraph.hotkeys) else "<unknown>"
            rows.append({
                "uid": int(uid),
                "hotkey": hotkey,
                "hotkey_prefix": hotkey[:15],  # Show first 15 chars
                "weight": float(weight),
            })

    # Sort by weight desc
    rows.sort(key=lambda r: r["weight"], reverse=True)

    if not rows:
        text = "[no miners with non-zero weights]"
        if to_console and _RICH:
            Console().print(text)
        return text

    if _RICH:
        tbl = Table(
            title="[bold green]🏆 Final Weights (On-Chain)[/bold green]",
            box=box.SIMPLE_HEAVY,
            header_style="bold cyan",
            expand=True,
            show_lines=False,
            padding=(0, 1),
        )
        tbl.add_column("#", justify="right", width=3)
        tbl.add_column("UID", justify="right", width=5)
        tbl.add_column("Hotkey", style="cyan", overflow="ellipsis")
        tbl.add_column("Weight", justify="right", width=10)

        for i, r in enumerate(rows, start=1):
            # Highlight winner with gold color
            weight_style = "bold yellow" if i == 1 and r["weight"] > 0.9 else "white"
            tbl.add_row(
                str(i),
                str(r["uid"]),
                r["hotkey_prefix"],
                f'[{weight_style}]{r["weight"]:.6f}[/{weight_style}]',
            )

        console = Console()
        console.print(tbl)
        return f"Final Weights — {len(rows)} miners with non-zero weights."

    # Fallback plain text table
    lines = [
        "🏆 Final Weights (On-Chain)",
        f'{"#":>3} {"UID":>5} {"HOTKEY":<18} {"Weight":>10}',
    ]
    for i, r in enumerate(rows, start=1):
        lines.append(
            f'{i:>3} {r["uid"]:>5} {r["hotkey_prefix"]:<18.18} {r["weight"]:>10.6f}'
        )
    text = "\n".join(lines)
    if to_console:
        print(text)
    return text
