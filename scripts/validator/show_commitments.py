#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bittensor import AsyncSubtensor  # type: ignore

from autoppia_web_agents_subnet.utils.commitments import read_all_plain_commitments
from autoppia_web_agents_subnet.utils.ipfs_client import IPFSError, aget_json
from autoppia_web_agents_subnet.validator.config import (
    AVG_TASK_DURATION_SECONDS,
    DZ_STARTING_BLOCK,
    ENABLE_DISTRIBUTED_CONSENSUS,
    IPFS_API_URL,
    IPFS_GATEWAYS,
    MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO,
    ROUND_SIZE_EPOCHS,
    SAFETY_BUFFER_EPOCHS,
)
from autoppia_web_agents_subnet.validator.round_manager import RoundManager

DEFAULT_NETUID = int(os.getenv("NETUID", "36"))
DEFAULT_NETWORK = os.getenv("SUBTENSOR_NETWORK", "finney")

ROUND_MANAGER = RoundManager(
    round_size_epochs=ROUND_SIZE_EPOCHS,
    avg_task_duration_seconds=AVG_TASK_DURATION_SECONDS,
    safety_buffer_epochs=SAFETY_BUFFER_EPOCHS,
    minimum_start_block=DZ_STARTING_BLOCK,
)
BLOCKS_PER_EPOCH = RoundManager.BLOCKS_PER_EPOCH
ROUND_BLOCK_LENGTH = ROUND_MANAGER.ROUND_BLOCK_LENGTH
BASE_START_BLOCK = DZ_STARTING_BLOCK if DZ_STARTING_BLOCK is not None else 0
SECONDS_PER_BLOCK = RoundManager.SECONDS_PER_BLOCK


@dataclass
class ValidatorCommitment:
    hotkey: str
    uid: Optional[int]
    stake_tao: float
    cid: Optional[str]
    round_number: Optional[int]
    epoch: Optional[int]
    target_epoch: Optional[int]
    payload: Optional[Dict[str, Any]] = None
    payload_hash: Optional[str] = None
    payload_error: Optional[str] = None


def _stake_to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        from bittensor.utils.balance import Balance  # type: ignore

        if isinstance(value, Balance):
            return float(value.tao)
    except Exception:
        pass

    for accessor in ("item",):
        if hasattr(value, accessor):
            try:
                return float(getattr(value, accessor)())
            except Exception:
                continue

    try:
        return float(value)
    except Exception:
        return 0.0


def _hotkey_to_uid_map(hotkeys: Sequence[str]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for idx, hk in enumerate(hotkeys or []):
        if hk and hk not in mapping:
            mapping[hk] = idx
    return mapping


def _compute_round_number(start_block: int) -> Optional[int]:
    if ROUND_BLOCK_LENGTH <= 0:
        return None
    try:
        offset = max(start_block - BASE_START_BLOCK, 0)
        return int(offset // ROUND_BLOCK_LENGTH) + 1
    except Exception:
        return None


def _format_minutes(block_delta: int) -> str:
    if block_delta <= 0:
        return "0m"
    minutes = (block_delta * SECONDS_PER_BLOCK) / 60.0
    if minutes >= 60.0:
        hours = minutes / 60.0
        return f"{hours:.1f}h"
    return f"{minutes:.1f}m"


async def _create_subtensor(network: Optional[str]) -> AsyncSubtensor:
    if network:
        st = AsyncSubtensor(network=network)  # type: ignore[arg-type]
    else:
        st = AsyncSubtensor()  # type: ignore[call-arg]
    init = getattr(st, "initialize", None)
    if callable(init):
        await init()
    return st


async def _fetch_payload(
    cid: str,
    *,
    api_url: Optional[str],
    gateways: Optional[Sequence[str]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    try:
        payload, _, sha_hex = await aget_json(cid, api_url=api_url, gateways=gateways)
        if isinstance(payload, dict):
            return payload, sha_hex, None
        return None, None, "payload is not a dict"
    except IPFSError as exc:
        return None, None, f"IPFS error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, None, f"{type(exc).__name__}: {exc}"


def _select_recent_rounds(
    commits: Dict[str, Any],
) -> Dict[int, List[Tuple[str, Dict[str, Any]]]]:
    grouped: Dict[int, List[Tuple[str, Dict[str, Any]]]] = {}
    for hotkey, entry in (commits or {}).items():
        if not isinstance(entry, dict):
            continue
        try:
            target_epoch = int(entry.get("pe"))
        except Exception:
            continue
        grouped.setdefault(target_epoch, []).append((hotkey, entry))
    return grouped


def _round_label(round_number: Optional[int], target_epoch: Optional[int]) -> str:
    if round_number is not None and target_epoch is not None:
        return f"round #{round_number} (target_epoch={target_epoch})"
    if target_epoch is not None:
        return f"target_epoch={target_epoch}"
    if round_number is not None:
        return f"round #{round_number}"
    return "unknown round"


def _score_summary(payload: Dict[str, Any]) -> Tuple[int, str]:
    scores = payload.get("scores")
    if not isinstance(scores, dict):
        return 0, "scores unavailable"

    parsed: List[Tuple[int, float]] = []
    for uid_str, score_val in scores.items():
        try:
            parsed.append((int(uid_str), float(score_val)))
        except Exception:
            continue

    count = len(parsed)
    if count == 0:
        return 0, "scores empty"

    top = sorted(parsed, key=lambda item: item[1], reverse=True)[:3]
    top_str = ", ".join(f"{uid}:{score:.4f}" for uid, score in top)
    return count, f"top {top_str}"


def _score_stats(
    scores: Any,
) -> Tuple[int, Optional[float], Optional[float], Optional[float]]:
    if not isinstance(scores, dict):
        return 0, None, None, None

    values: List[float] = []
    for value in scores.values():
        try:
            values.append(float(value))
        except Exception:
            continue

    count = len(values)
    if count == 0:
        return 0, None, None, None

    mean = sum(values) / count
    variance = sum((val - mean) ** 2 for val in values) / count
    stddev = math.sqrt(variance)
    return count, mean, stddev, variance


def _render_validator_table(
    validators: List[ValidatorCommitment],
    *,
    total_weight: float,
) -> Tuple[str, List[str]]:
    headers = [
        "validator",
        "uid",
        "round",
        "stake_tau",
        "weight_pct",
        "scores",
        "mean",
        "std",
        "var",
        "tasks",
        "agents",
        "sha12",
        "cid",
    ]

    rows: List[List[str]] = []
    extra: List[str] = []

    for item in validators:
        weight_pct = (item.stake_tao / total_weight) * 100.0 if total_weight else 0.0
        round_text = str(item.round_number) if item.round_number is not None else "-"
        stake_text = f"{item.stake_tao:,.2f}"
        weight_text = f"{weight_pct:5.2f}"

        cid_text = "-"
        if item.cid:
            cid_text = item.cid[:18] + "…" if len(item.cid) > 18 else item.cid

        sha_text = "-"
        if item.payload_hash:
            sha_text = (
                item.payload_hash[:12] + "…"
                if len(item.payload_hash) > 12
                else item.payload_hash
            )

        scores_count = 0
        mean = stddev = variance = None
        tasks = "-"
        agents = "-"
        top_line: Optional[str] = None

        if item.payload_error:
            extra.append(
                f"      {item.hotkey[:10]}… payload error: {item.payload_error}"
            )
        elif item.payload is None:
            extra.append(f"      {item.hotkey[:10]}… payload missing")
        else:
            payload = item.payload
            scores_count, top_line = _score_summary(payload)
            count_stats, mean, stddev, variance = _score_stats(payload.get("scores"))
            scores_count = count_stats
            tasks_val = payload.get("tasks_completed") or payload.get("n")
            if tasks_val is not None:
                tasks = str(tasks_val)
            agents_val = payload.get("agents")
            if agents_val is not None:
                agents = str(agents_val)
            if top_line:
                extra.append(f"      {item.hotkey[:10]}… {top_line}")

        mean_text = f"{mean:.4f}" if mean is not None else "-"
        std_text = f"{stddev:.4f}" if stddev is not None else "-"
        var_text = f"{variance:.4f}" if variance is not None else "-"
        scores_text = str(scores_count) if scores_count else "-"

        rows.append(
            [
                f"{item.hotkey[:10]}…",
                str(item.uid) if item.uid is not None else "?",
                round_text,
                stake_text,
                weight_text,
                scores_text,
                mean_text,
                std_text,
                var_text,
                tasks,
                agents,
                sha_text,
                cid_text,
            ]
        )

    if not rows:
        return "", extra

    col_widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(cell))

    def _fmt_row(row: List[str]) -> str:
        cells = [cell.ljust(col_widths[idx]) for idx, cell in enumerate(row)]
        return "    | " + " | ".join(cells) + " |"

    divider = "    +" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    table_lines = [divider, _fmt_row(headers), divider]
    for row in rows:
        table_lines.append(_fmt_row(row))
    table_lines.append(divider)

    return "\n".join(table_lines), extra


def _decode_weight_payload(raw: Any) -> Dict[int, int]:
    mapping: Dict[int, int] = {}
    if raw is None:
        return mapping

    if isinstance(raw, dict):
        if "uids" in raw and "weights" in raw:
            uids = raw.get("uids") or []
            weights = raw.get("weights") or []
            for uid, weight in zip(uids, weights):
                try:
                    mapping[int(uid)] = int(weight)
                except Exception:
                    continue
        elif "destinations" in raw and "values" in raw:
            uids = raw.get("destinations") or []
            weights = raw.get("values") or []
            for uid, weight in zip(uids, weights):
                try:
                    mapping[int(uid)] = int(weight)
                except Exception:
                    continue
        else:
            for key, value in raw.items():
                try:
                    mapping[int(key)] = int(value)
                except Exception:
                    continue
        return mapping

    if isinstance(raw, (list, tuple)):
        for entry in raw:
            if isinstance(entry, dict):
                uid = entry.get("uid") if "uid" in entry else entry.get("key")
                weight = entry.get("weight")
                if weight is None:
                    weight = entry.get("value")
                try:
                    mapping[int(uid)] = int(weight)
                except Exception:
                    continue
            elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                uid, weight = entry[0], entry[1]
                try:
                    mapping[int(uid)] = int(weight)
                except Exception:
                    continue
    return mapping


def _normalize_weights(raw_weights: Dict[int, int]) -> Dict[int, float]:
    if not raw_weights:
        return {}
    filtered = {uid: max(int(weight), 0) for uid, weight in raw_weights.items()}
    total = sum(filtered.values())
    if total <= 0:
        return {uid: 0.0 for uid in filtered}
    return {uid: weight / total for uid, weight in filtered.items()}


async def _load_weight_snapshot(
    st: AsyncSubtensor,
    *,
    netuid: int,
    block_candidates: Sequence[int],
) -> Tuple[Dict[int, Dict[int, float]], Optional[int], Optional[str]]:
    last_error: Optional[str] = None
    fallback_snapshot: Dict[int, Dict[int, float]] = {}
    fallback_block: Optional[int] = None

    for block in block_candidates:
        if block is None or block <= 0:
            continue
        try:
            entries = await st.weights(netuid=netuid, block=block)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue

        snapshot: Dict[int, Dict[int, float]] = {}
        for validator_uid, raw in entries:
            try:
                v_uid = int(validator_uid)
            except Exception:
                continue
            raw_map = _decode_weight_payload(raw)
            snapshot[v_uid] = _normalize_weights(raw_map)

        if snapshot:
            return snapshot, block, None

        if fallback_block is None:
            fallback_snapshot = snapshot
            fallback_block = block
        last_error = "no weights recorded"

    if fallback_block is not None:
        return fallback_snapshot, fallback_block, last_error

    return {}, None, last_error


def _format_weight_lines(
    *,
    validator_uid: int,
    normalized: Dict[int, float],
    block: int,
    limit: int = 5,
) -> List[str]:
    if not normalized:
        return [
            f"  • weights uid {validator_uid} @block {block}: no weights recorded",
        ]

    sorted_weights = sorted(
        normalized.items(),
        key=lambda item: item[1],
        reverse=True,
    )
    shown = min(limit, len(sorted_weights))
    header = (
        f"  • weights uid {validator_uid} @block {block} "
        f"(top {shown}/{len(sorted_weights)})"
    )
    lines = [header]
    for dest_uid, value in sorted_weights[:shown]:
        lines.append(
            f"      - dest {dest_uid}: {value:.4f} ({value * 100:.2f}%)"
        )
    remaining = len(sorted_weights) - shown
    if remaining > 0:
        lines.append(f"      … {remaining} additional destinations")
    return lines


async def inspect_rounds(
    *,
    rounds: int,
    netuid: int,
    network: Optional[str],
    min_stake: float,
    include_below: bool,
    ipfs_api: Optional[str],
    gateways: Optional[Sequence[str]],
) -> None:
    if rounds <= 0:
        rounds = 1

    async with await _create_subtensor(network) as st:
        current_block = await st.get_current_block()
        current_epoch = current_block / BLOCKS_PER_EPOCH
        current_bounds = ROUND_MANAGER.get_round_boundaries(current_block)
        cur_start_block = int(current_bounds["round_start_block"])
        cur_target_block = int(current_bounds["target_block"])
        cur_start_epoch = float(current_bounds["round_start_epoch"])
        cur_target_epoch = float(current_bounds["target_epoch"])
        cur_round = _compute_round_number(cur_start_block)
        cur_progress = ROUND_MANAGER.fraction_elapsed(current_block) * 100.0

        print("Current settlement window")
        print(
            f"  • current_block={current_block:,} "
            f"(epoch={current_epoch:.2f})"
        )
        print(
            "  • window_epochs="
            f"{cur_start_epoch:.2f}→{cur_target_epoch:.2f}"
        )
        print(
            "  • window_blocks="
            f"{cur_start_block:,}→{cur_target_block:,} "
            f"(len={ROUND_BLOCK_LENGTH:,})"
        )
        if cur_round is not None:
            print(f"  • round_index≈{cur_round}")
        print(f"  • progress≈{cur_progress:.1f}% of window")

        commits = await read_all_plain_commitments(st, netuid=netuid, block=None)
        if not commits:
            print("No commitments found on-chain.")
            return

        metagraph = await st.metagraph(netuid)

        raw_hotkeys = getattr(metagraph, "hotkeys", None)
        hotkeys: List[str] = list(raw_hotkeys) if raw_hotkeys is not None else []

        raw_stakes = getattr(metagraph, "stake", None)
        if raw_stakes is None:
            stakes_raw: List[Any] = []
        elif hasattr(raw_stakes, "tolist"):
            stakes_raw = list(raw_stakes.tolist())
        else:
            try:
                stakes_raw = list(raw_stakes)
            except TypeError:
                stakes_raw = [raw_stakes]

        hk_to_uid = _hotkey_to_uid_map(hotkeys)

        def stake_for_hotkey(hotkey: str) -> Tuple[Optional[int], float]:
            uid = hk_to_uid.get(hotkey)
            if uid is None:
                return None, 0.0
            try:
                stake_val = stakes_raw[uid]
            except Exception:
                stake_val = None
            return uid, _stake_to_float(stake_val)

        grouped = _select_recent_rounds(commits)
        if not grouped:
            print("No structured commitments (v4) detected.")
            return

        sorted_targets = sorted(grouped.keys(), reverse=True)
        selected_targets = sorted_targets[:rounds]

        for idx, target_epoch in enumerate(selected_targets, start=1):
            entries = grouped.get(target_epoch, [])
            if not entries:
                continue

            validators: List[ValidatorCommitment] = []
            reported_rounds: List[int] = []
            base_epochs: List[int] = []

            for hotkey, entry in entries:
                raw_epoch = entry.get("e")
                try:
                    epoch_val = int(raw_epoch) if raw_epoch is not None else None
                except Exception:
                    epoch_val = None

                raw_round = entry.get("r")
                round_int = raw_round if isinstance(raw_round, int) else None

                raw_cid = entry.get("c")
                cid_text = str(raw_cid) if raw_cid else None

                _, preview_stake = stake_for_hotkey(hotkey)
                if not include_below and preview_stake < min_stake:
                    continue

                uid, stake_tao = stake_for_hotkey(hotkey)

                validators.append(
                    ValidatorCommitment(
                        hotkey=hotkey,
                        uid=uid,
                        stake_tao=stake_tao,
                        cid=cid_text,
                        round_number=round_int,
                        epoch=epoch_val,
                        target_epoch=target_epoch,
                    )
                )
                if round_int is not None:
                    reported_rounds.append(round_int)
                if epoch_val is not None:
                    base_epochs.append(epoch_val)

            start_block = int(target_epoch * BLOCKS_PER_EPOCH - ROUND_BLOCK_LENGTH)
            target_block = int(target_epoch * BLOCKS_PER_EPOCH)
            start_epoch = start_block / BLOCKS_PER_EPOCH
            derived_round = _compute_round_number(start_block)
            label_round = reported_rounds[0] if reported_rounds else derived_round
            label = _round_label(label_round, target_epoch)

            if current_block < target_block:
                status = (
                    "active: "
                    + _format_minutes(target_block - current_block)
                    + " remaining"
                )
            else:
                status = (
                    "settled: finished "
                    + _format_minutes(current_block - target_block)
                    + " ago"
                )

            print(f"\n[{idx}] {label}")
            print(
                "  • window_epochs="
                f"{start_epoch:.2f}→{float(target_epoch):.2f}"
            )
            print(
                "  • window_blocks="
                f"{start_block:,}→{target_block:,} "
                f"(len={ROUND_BLOCK_LENGTH:,})"
            )
            print(f"  • status={status}")
            if base_epochs:
                base_mode = max(set(base_epochs), key=base_epochs.count)
                print(f"  • commitment_e≈{base_mode}")
            if derived_round is not None and (
                not reported_rounds or label_round != derived_round
            ):
                print(f"  • derived_round_index≈{derived_round}")

            if not validators:
                print(
                    f"  • No validators meet stake ≥ {min_stake:.2f} τ for this window"
                )
                continue

            payload_tasks: List[Tuple[ValidatorCommitment, asyncio.Task]] = []
            for item in validators:
                if not item.cid:
                    continue
                task = asyncio.create_task(
                    _fetch_payload(item.cid, api_url=ipfs_api, gateways=gateways)
                )
                payload_tasks.append((item, task))

            for item, task in payload_tasks:
                payload, sha_hex, error = await task
                item.payload = payload
                item.payload_hash = sha_hex
                item.payload_error = error

            validators.sort(key=lambda v: v.stake_tao, reverse=True)
            total_weight = sum(filter(None, (v.stake_tao for v in validators)))

            table_text, extra_lines = _render_validator_table(
                validators,
                total_weight=total_weight,
            )
            print(
                f"  • validators_considered={len(validators)} "
                f"(stake ≥ {min_stake:.2f} τ)"
            )
            if total_weight > 0:
                print(f"  • total_stake={total_weight:,.2f} τ")
            if table_text:
                print(table_text)
            for line in extra_lines:
                print(line)

            if target_block > current_block:
                print("  • weights unavailable (round still active)")
                continue

            candidates = [target_block]
            for offset in (12, 60, 120):
                candidate = target_block + offset
                if candidate <= current_block:
                    candidates.append(candidate)
            candidates.append(current_block)

            seen = set()
            block_candidates: List[int] = []
            for blk in candidates:
                if blk not in seen:
                    seen.add(blk)
                    block_candidates.append(blk)

            weights_map, weight_block, weight_error = await _load_weight_snapshot(
                st,
                netuid=netuid,
                block_candidates=block_candidates,
            )

            if weight_block is None:
                reason = weight_error or "unavailable"
                print(f"  • weights unavailable ({reason})")
                continue

            validator_uids = sorted(
                {v.uid for v in validators if v.uid is not None}
            )
            if not validator_uids:
                print(f"  • weights @block {weight_block}: no validator UIDs")
                continue

            for v_uid in validator_uids:
                normalized = weights_map.get(v_uid, {})
                lines = _format_weight_lines(
                    validator_uid=v_uid,
                    normalized=normalized,
                    block=weight_block,
                    limit=5,
                )
                for line in lines:
                    print(line)
            if weight_error and weights_map:
                print(f"  • weights note: {weight_error}")


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect recent validator settlement commitments and shared scores."
        ),
    )
    parser.add_argument(
        "-N",
        "--rounds",
        type=int,
        default=1,
        help="Number of recent settlement windows to display (default: 1).",
    )
    parser.add_argument(
        "--netuid",
        type=int,
        default=DEFAULT_NETUID,
        help=f"Subnet netuid (default: {DEFAULT_NETUID}).",
    )
    parser.add_argument(
        "--network",
        type=str,
        default=DEFAULT_NETWORK,
        help=f"Bittensor network to query (default: {DEFAULT_NETWORK}).",
    )
    parser.add_argument(
        "--min-stake",
        type=float,
        default=MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO,
        help=(
            "Minimum validator stake (τ) required to include a commitment. "
            "Defaults to configured threshold "
            f"({MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO})."
        ),
    )
    parser.add_argument(
        "--include-below",
        action="store_true",
        help="Show validators even if below the minimum stake threshold.",
    )
    parser.add_argument(
        "--ipfs-api",
        type=str,
        default=IPFS_API_URL,
        help="IPFS HTTP API base URL override.",
    )
    parser.add_argument(
        "--ipfs-gateways",
        type=str,
        default=None,
        help="Comma-separated list of IPFS gateways to try when fetching payloads.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    gateways = (
        [gw.strip() for gw in args.ipfs_gateways.split(",") if gw.strip()]
        if args.ipfs_gateways
        else IPFS_GATEWAYS
    )

    if not ENABLE_DISTRIBUTED_CONSENSUS:
        print("Distributed consensus is disabled; commitments may be absent.")

    try:
        asyncio.run(
            inspect_rounds(
                rounds=args.rounds,
                netuid=args.netuid,
                network=args.network,
                min_stake=args.min_stake,
                include_below=args.include_below,
                ipfs_api=args.ipfs_api,
                gateways=gateways,
            )
        )
    except KeyboardInterrupt:  # pragma: no cover - user abort
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}")


if __name__ == "__main__":
    main()
