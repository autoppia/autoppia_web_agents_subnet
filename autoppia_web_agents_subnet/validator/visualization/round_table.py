# autoppia_web_agents_subnet/validator/visualization/round_table.py
from __future__ import annotations

from typing import Dict, Any, Optional, List, Set

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


def render_round_summary_table(
    round_manager,
    final_rewards: Dict[int, float],  # WTA rewards mapping (1.0 to winner)
    metagraph: Any,
    *,
    to_console: bool = True,
    agg_scores: Optional[Dict[int, float]] = None,  # aggregated final scores per UID
    consensus_meta: Optional[Dict[str, Any]] = None,  # {validators: [...], scores_by_validator: {hk:{uid:score}}}
    active_uids: Optional[Set[int]] = None,
) -> str:
    """
    Render a concise per-miner summary at end of round:
    Columns: UID, Hotkey(10), AvgScore, AvgTime(s), Reward (final)
    Sorted by Reward desc.
    """
    rows: list[dict[str, Any]] = []

    # Decide which UIDs to show: if agg_scores provided, show only UIDs with final score > 0
    if agg_scores:
        uids_to_show = {int(uid) for uid, sc in agg_scores.items() if float(sc) > 0.0}
    else:
        round_rewards_keys = list(getattr(round_manager, 'round_rewards', {}).keys())
        uids_to_show = set(round_rewards_keys + list(final_rewards.keys()))

    validators_info: List[Dict[str, Any]] = []
    scores_by_validator: Dict[str, Dict[int, float]] = {}
    if consensus_meta:
        validators_info = list(consensus_meta.get("validators") or [])
        scores_by_validator = dict(consensus_meta.get("scores_by_validator") or {})

    validators_hk_order: List[str] = [v.get("hotkey") for v in validators_info if isinstance(v, dict) and v.get("hotkey")]

    for uid in sorted(uids_to_show):
        hotkey = metagraph.hotkeys[uid] if uid < len(metagraph.hotkeys) else "<unknown>"
        coldkey = metagraph.coldkeys[uid] if uid < len(metagraph.coldkeys) else "<unknown>"
        avg_eval = _mean_safe(getattr(round_manager, 'round_eval_scores', {}).get(uid, []))
        avg_time = _mean_safe(getattr(round_manager, 'round_times', {}).get(uid, []))
        local_participated = bool(getattr(round_manager, 'round_rewards', {}).get(uid)) or bool(getattr(round_manager, 'round_eval_scores', {}).get(uid))
        final_score = float((agg_scores or {}).get(uid, 0.0))
        wta_reward = float(final_rewards.get(uid, 0.0))  # 1.0 for winner else 0.0

        # Per-validator scores for this UID, ordered by validators_hk_order
        per_val_scores = []
        if validators_hk_order:
            for hk in validators_hk_order:
                per_val_scores.append(float(scores_by_validator.get(hk, {}).get(uid, 0.0)))

        rows.append({
            "uid": int(uid),
            "hotkey": hotkey,
            "hotkey_prefix": hotkey[:10],
            "local": local_participated,
            "avg_eval": avg_eval,
            "avg_time": avg_time,
            "final_score": final_score,
            "wta_reward": wta_reward,
            "per_val_scores": per_val_scores,
        })

    # Sort by WTA reward desc, then by avg_eval desc for tie-break
    rows.sort(key=lambda r: (r["wta_reward"], r["avg_eval"]), reverse=True)

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
        # Header note with validators and stakes (weights used)
        if validators_info:
            try:
                from rich.console import Console as _C
                hdr = ", ".join(
                    [
                        f"{v.get('hotkey', '')[:10]}…({float(v.get('stake') or 0.0):.0f}τ)"
                        for v in validators_info
                    ]
                )
                _C().print(f"[bold]Aggregators:[/bold] {hdr}")
                # Add a short legend for the duplicate column
                _C().print("[dim]Legend: Dup = tasks penalized as duplicate this round[/dim]")
            except Exception:
                pass

        tbl.add_column("#", justify="right", width=3)
        tbl.add_column("UID", justify="right", width=5)
        tbl.add_column("Hotkey", style="cyan", overflow="ellipsis")
        tbl.add_column("Active", justify="center", width=6)
        tbl.add_column("LocalScore", justify="right", width=10)
        tbl.add_column("Dup", justify="center", width=5)
        # Per-validator dynamic columns
        if validators_hk_order:
            for idx, v in enumerate(validators_info, start=1):
                hk = v.get("hotkey", "")
                stake = float(v.get("stake") or 0.0)
                header = f"V{idx}:{hk[:6]}…({stake:.0f}τ)"
                tbl.add_column(header, justify="right", width=12)
        tbl.add_column("FinalScore", justify="right", width=11)
        tbl.add_column("WTA", justify="right", width=6)

        for i, r in enumerate(rows, start=1):
            dup_count = 0
            try:
                dup_count = int(getattr(round_manager, 'round_duplicate_counts', {}).get(r["uid"], 0))
            except Exception:
                dup_count = 0

            base_cols = [
                str(i),
                str(r["uid"]),
                r["hotkey_prefix"],
                ("yes" if (active_uids and r["uid"] in active_uids) else ("yes" if r["local"] else "no")),
                f'{r["avg_eval"]:.4f}',
                ("-" if dup_count <= 0 else str(dup_count)),
            ]
            pv_cols = []
            if validators_hk_order and r.get("per_val_scores"):
                pv_cols = [f"{val:.4f}" for val in r["per_val_scores"]]
            tail_cols = [
                f'{r["final_score"]:.4f}',
                f'{r["wta_reward"]:.4f}',
            ]
            tbl.add_row(*(base_cols + pv_cols + tail_cols))

        console = Console()
        console.print(tbl)
        return f"Round Summary — Miners (n={len(rows)})."

    # Fallback plain text table
    # Plain text fallback
    header = [
        "#", "UID", "HOTKEY", "Active", "LocalScore", "Dup",
    ]
    if validators_info:
        header.extend([f"V{idx}:{v.get('hotkey','')[:6]}…({float(v.get('stake') or 0.0):.0f}τ)" for idx, v in enumerate(validators_info, start=1)])
    header.extend(["FinalScore", "WTA"])

    lines = [
        "Round Summary — Miners",
        "Legend: Dup = tasks penalized as duplicate this round",
        " ".join([f"{h:>12}" for h in header]),
    ]
    for i, r in enumerate(rows, start=1):
        try:
            dup_count = int(getattr(round_manager, 'round_duplicate_counts', {}).get(r['uid'], 0))
        except Exception:
            dup_count = 0

        fields = [
            f"{i:>3}", f"{r['uid']:>5}", f"{r['hotkey_prefix']:<12.12}",
            ("yes" if (active_uids and r["uid"] in active_uids) else ("yes" if r["local"] else "no")),
            f"{r['avg_eval']:.4f}",
            ("-" if dup_count <= 0 else str(dup_count)),
        ]
        if validators_hk_order and r.get("per_val_scores"):
            fields.extend([f"{val:.4f}" for val in r["per_val_scores"]])
        fields.extend([f"{r['final_score']:.4f}", f"{r['wta_reward']:.4f}"])
        lines.append(" ".join([f"{x:>12}" for x in fields]))
    text = "\n".join(lines)
    if to_console:
        print(text)
    return text
