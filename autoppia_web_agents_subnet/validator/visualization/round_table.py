# autoppia_web_agents_subnet/validator/visualization/round_table.py
from __future__ import annotations

import shutil
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


MAX_TERMINAL_WIDTH = 118
HOTKEY_COLUMN_WIDTH = 9
HOTKEY_PREFIX_LEN = HOTKEY_COLUMN_WIDTH - 2  # allow room for ellipsis when rendered
BASE_COLUMN_WIDTH = 3 + 5 + HOTKEY_COLUMN_WIDTH + 6 + 10 + 11  # estimated from explicit widths below
VALIDATOR_COLUMN_WIDTH = 10
ELLIPSIS = "…"


def _derive_round_number(round_manager) -> Optional[int]:
    """Best-effort calculation of the human-readable round number."""

    try:
        block_length = int(getattr(round_manager, "ROUND_BLOCK_LENGTH", 0))
        if block_length <= 0:
            return None

        start_block = getattr(round_manager, "start_block", None)
        if start_block is None:
            try:
                boundaries = round_manager.get_current_boundaries()
                start_block = int(boundaries.get("round_start_block"))
            except Exception:  # noqa: BLE001
                start_block = None
        if start_block is None:
            return None

        base_block = getattr(round_manager, "minimum_start_block", None) or 0
        blocks_since_start = max(int(start_block) - int(base_block), 0)
        round_index = blocks_since_start // block_length
        return int(round_index + 1)
    except Exception:  # noqa: BLE001
        return None


def _chunk_indices(length: int, chunk_size: int) -> List[range]:
    if length <= 0:
        return [range(0)]
    ranges: List[range] = []
    for start in range(0, length, chunk_size):
        stop = min(start + chunk_size, length)
        ranges.append(range(start, stop))
    return ranges


def _coerce_score_mapping(raw: Optional[Any]) -> Dict[int, float]:
    """Normalize various score payload shapes into {uid: score}."""

    mapping: Dict[int, float] = {}
    if raw is None:
        return mapping

    try:
        if isinstance(raw, dict):
            candidate = raw
            # Some payloads wrap the scores under a named key (e.g. "avg_reward").
            if any(isinstance(k, str) and not k.isdigit() for k in candidate.keys()):
                for key in ("avg_reward", "scores", "final_score", "data"):
                    nested = candidate.get(key)
                    if isinstance(nested, dict):
                        candidate = nested
                        break
            for key, value in candidate.items():
                try:
                    uid = int(key)
                    mapping[uid] = float(value)
                except Exception:  # noqa: BLE001
                    continue
            return mapping

        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                uid = entry.get("uid") or entry.get("miner_uid")
                score_value = (
                    entry.get("avg_reward")
                    if entry.get("avg_reward") is not None
                    else entry.get("score")
                )
                if score_value is None:
                    score_value = entry.get("final_score")
                if uid is None or score_value is None:
                    continue
                try:
                    mapping[int(uid)] = float(score_value)
                except Exception:  # noqa: BLE001
                    continue
            return mapping

        if hasattr(raw, "to_dict"):
            return _coerce_score_mapping(raw.to_dict())
    except Exception:  # noqa: BLE001
        return mapping

    return mapping


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
    Columns: UID, Hotkey (truncated), AvgScore, AvgTime(s), FinalScore
    Sorted by Reward desc.
    """
    rows: list[dict[str, Any]] = []
    round_number = _derive_round_number(round_manager)

    # Decide which UIDs to show: if agg_scores provided, show only UIDs with final score > 0
    normalized_scores = _coerce_score_mapping(agg_scores)

    if normalized_scores:
        uids_to_show = {int(uid) for uid, sc in normalized_scores.items() if float(sc) > 0.0}
    else:
        uids_to_show = set(list(round_manager.round_rewards.keys()) + list(final_rewards.keys()))

    validators_info: List[Dict[str, Any]] = []
    scores_by_validator: Dict[str, Dict[int, float]] = {}
    if consensus_meta:
        validators_info = list(consensus_meta.get("validators") or [])
        scores_by_validator = dict(consensus_meta.get("scores_by_validator") or {})

    validators_hk_order: List[str] = [v.get("hotkey") for v in validators_info if isinstance(v, dict) and v.get("hotkey")]

    for uid in sorted(uids_to_show):
        hotkey = metagraph.hotkeys[uid] if uid < len(metagraph.hotkeys) else "<unknown>"
        coldkey = metagraph.coldkeys[uid] if uid < len(metagraph.coldkeys) else "<unknown>"
        avg_eval = _mean_safe(round_manager.round_eval_scores.get(uid, []))
        avg_time = _mean_safe(round_manager.round_times.get(uid, []))
        local_participated = bool(round_manager.round_rewards.get(uid)) or bool(round_manager.round_eval_scores.get(uid))
        final_score = float(normalized_scores.get(uid, 0.0))
        wta_reward = float(final_rewards.get(uid, 0.0))  # 1.0 for winner else 0.0

        # Per-validator scores for this UID, ordered by validators_hk_order
        per_val_scores = []
        if validators_hk_order:
            for hk in validators_hk_order:
                per_val_scores.append(float(scores_by_validator.get(hk, {}).get(uid, 0.0)))

        rows.append({
            "uid": int(uid),
            "hotkey": hotkey,
            "hotkey_prefix": hotkey[:HOTKEY_PREFIX_LEN],
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

    title_base = "Round Summary — Miners"
    if round_number is not None:
        title_base = f"{title_base} — Round {round_number}"

    if _RICH:
        min_table_width = BASE_COLUMN_WIDTH + VALIDATOR_COLUMN_WIDTH
        probe_console: Optional[Console] = None
        target_width = MAX_TERMINAL_WIDTH
        try:
            probe_console = Console()
            measured = probe_console.width or getattr(probe_console, "options", None)
            measured_width = getattr(measured, "max_width", None) if hasattr(measured, "max_width") else measured
            if measured_width:
                try:
                    measured_width = int(measured_width)
                except Exception:  # noqa: BLE001
                    measured_width = MAX_TERMINAL_WIDTH
            else:
                measured_width = MAX_TERMINAL_WIDTH
            target_width = min(MAX_TERMINAL_WIDTH, max(int(measured_width), min_table_width))
        except Exception:  # noqa: BLE001
            probe_console = None
            target_width = MAX_TERMINAL_WIDTH

        console_kwargs: Dict[str, Any] = {"width": target_width}
        if probe_console is not None:
            console_kwargs["force_terminal"] = probe_console.is_terminal
            console_kwargs["color_system"] = probe_console.color_system
        console = probe_console if (probe_console and probe_console.width == target_width) else Console(**console_kwargs)

        available_width = max(target_width - BASE_COLUMN_WIDTH, VALIDATOR_COLUMN_WIDTH)
        max_validator_cols = 0
        if validators_hk_order:
            max_validator_cols = max(1, available_width // VALIDATOR_COLUMN_WIDTH)
        validator_ranges = _chunk_indices(len(validators_hk_order), max_validator_cols or 1)

        # Header note with validators and stakes (weights used)
        if validators_info:
            try:
                hdr = ", ".join(
                    [
                        f"{v.get('hotkey', '')[:10]}…({float(v.get('stake') or 0.0):.0f}τ)"
                        for v in validators_info
                    ]
                )
                console.print(f"[bold]Aggregators:[/bold] {hdr}")
            except Exception:  # noqa: BLE001
                pass

        for part_idx, rng in enumerate(validator_ranges, start=1):
            title = title_base
            if len(validator_ranges) > 1:
                title = f"{title} (part {part_idx})"

            tbl = Table(
                title=f"[bold magenta]{title}[/bold magenta]",
                box=box.SIMPLE_HEAVY,
                header_style="bold cyan",
                expand=False,
                show_lines=False,
                padding=(0, 1),
            )

            tbl.add_column("#", justify="right", width=3)
            tbl.add_column("UID", justify="right", width=5)
            tbl.add_column("Hotkey", style="cyan", width=HOTKEY_COLUMN_WIDTH, overflow="ellipsis")
            tbl.add_column("Active", justify="center", width=6)
            tbl.add_column("LocalScore", justify="right", width=10)

            if validators_hk_order:
                for idx in rng:
                    validator = validators_info[idx]
                    hk = validator.get("hotkey", "")
                    trimmed = (hk or "")[:3]
                    header = f"{trimmed}{ELLIPSIS}" if hk and len(hk) > len(trimmed) else trimmed
                    tbl.add_column(header, justify="right", width=VALIDATOR_COLUMN_WIDTH)

            tbl.add_column("FinalScore", justify="right", width=11)

            for i, r in enumerate(rows, start=1):
                base_cols = [
                    str(i),
                    str(r["uid"]),
                    r["hotkey_prefix"],
                    ("yes" if (active_uids and r["uid"] in active_uids) else ("yes" if r["local"] else "no")),
                    f'{r["avg_eval"]:.4f}',
                ]
                pv_cols: List[str] = []
                if validators_hk_order and r.get("per_val_scores"):
                    pv_cols = [
                        f"{r['per_val_scores'][idx]:.4f}" if idx < len(r["per_val_scores"]) else "0.0000"
                        for idx in rng
                    ]
                tail_cols = [
                    f'{r["final_score"]:.4f}',
                ]
                tbl.add_row(*(base_cols + pv_cols + tail_cols))

            console.print(tbl)

        return f"{title_base} (n={len(rows)}, sections={len(validator_ranges)})."

    # Fallback plain text table
    header_base = ["#", "UID", "Hotkey", "Active", "LocalScore"]
    tail_headers = ["FinalScore"]
    validator_headers: List[str] = []
    for v in validators_info:
        hk = (v.get("hotkey", "") or "")
        trimmed = hk[:3]
        header = f"{trimmed}{ELLIPSIS}" if hk and len(hk) > len(trimmed) else trimmed
        validator_headers.append(header)

    terminal_cols = shutil.get_terminal_size((MAX_TERMINAL_WIDTH, 0)).columns
    target_width = min(MAX_TERMINAL_WIDTH, max(terminal_cols, BASE_COLUMN_WIDTH + VALIDATOR_COLUMN_WIDTH))
    available = max(target_width - BASE_COLUMN_WIDTH, VALIDATOR_COLUMN_WIDTH)
    max_validator_cols = max(1, available // VALIDATOR_COLUMN_WIDTH) if validator_headers else 1
    validator_ranges = _chunk_indices(len(validator_headers), max_validator_cols)

    lines: List[str] = []
    for part_idx, rng in enumerate(validator_ranges, start=1):
        title = title_base
        if len(validator_ranges) > 1:
            title = f"{title} (part {part_idx})"
        lines.append(title)

        headers = header_base + [validator_headers[i] for i in rng] + tail_headers
        hotkey_header_format = f"{{:<{HOTKEY_COLUMN_WIDTH}}}"
        validator_header_format = f"{{:>{VALIDATOR_COLUMN_WIDTH}}}"
        header_formats = [
            "{:>3}",
            "{:>5}",
            hotkey_header_format,
            "{:>6}",
            "{:>10}",
        ]
        header_formats.extend([validator_header_format] * len(rng))
        header_formats.extend(["{:>11}"])
        lines.append(" ".join(fmt.format(h) for fmt, h in zip(header_formats, headers)))

        for i, r in enumerate(rows, start=1):
            row_base = [
                i,
                r["uid"],
                (r["hotkey_prefix"] + ELLIPSIS) if len(r["hotkey"]) > HOTKEY_PREFIX_LEN else r["hotkey_prefix"],
                ("yes" if (active_uids and r["uid"] in active_uids) else ("yes" if r["local"] else "no")),
                f"{r['avg_eval']:.4f}",
            ]
            validator_values = []
            if validators_hk_order and r.get("per_val_scores"):
                validator_values = [
                    f"{r['per_val_scores'][idx]:.4f}" if idx < len(r["per_val_scores"]) else "0.0000"
                    for idx in rng
                ]
            tail_values = [f"{r['final_score']:.4f}"]

            values = row_base + validator_values + tail_values
            row_formats = [
                "{:>3}",
                "{:>5}",
                hotkey_header_format,
                "{:>6}",
                "{:>10}",
            ]
            row_formats.extend([validator_header_format] * len(validator_values))
            row_formats.extend(["{:>11}"])
            lines.append(" ".join(fmt.format(val) for fmt, val in zip(row_formats, values)))

        if part_idx < len(validator_ranges):
            lines.append("")

    text = "\n".join(lines)
    if to_console:
        print(text)
    return text
