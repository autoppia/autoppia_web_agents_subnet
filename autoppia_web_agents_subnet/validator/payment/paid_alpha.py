"""
Payment-per-eval: aggregate α-stake transfers to the payments wallet per coldkey.
Uses AlphaTransfersScanner from metahash when available to scan chain events.
"""

from __future__ import annotations

import asyncio
from typing import Any
from typing import Dict

import bittensor as bt

from autoppia_web_agents_subnet.validator import config as validator_config

RAO_PER_ALPHA = 10**9


def allowed_evaluations_from_paid_rao(paid_rao: int, alpha_per_eval: float) -> int:
    """
    Number of evaluations allowed for a given paid amount (rao) and cost per eval (alpha).
    """
    if paid_rao <= 0 or alpha_per_eval <= 0:
        return 0
    rao_per_eval = int(alpha_per_eval * RAO_PER_ALPHA)
    if rao_per_eval <= 0:
        return 0
    return paid_rao // rao_per_eval


async def get_paid_alpha_per_coldkey_async(
    subtensor: Any,
    from_block: int,
    to_block: int,
    dest_coldkey: str,
    target_subnet_id: int,
    *,
    rpc_lock: asyncio.Lock | None = None,
    chunk_size: int | None = None,
) -> Dict[str, int]:
    """
    Scan chain for α-stake transfers to dest_coldkey on target_subnet_id;
    return mapping coldkey_ss58 -> total amount_rao transferred.
    Requires metahash.validator.alpha_transfers (AlphaTransfersScanner).
    """
    if from_block > to_block:
        return {}
    if not dest_coldkey or not dest_coldkey.strip():
        return {}

    try:
        from metahash.validator.alpha_transfers import AlphaTransfersScanner
    except ImportError as e:
        bt.logging.warning(
            f"[payment] AlphaTransfersScanner not available (install metahash for payment gating): {e}"
        )
        return {}

    chunk = chunk_size
    if chunk is None:
        chunk = int(getattr(validator_config, "PAYMENT_SCAN_CHUNK", 512) or 512)
    chunk = max(1, chunk)

    lock = rpc_lock or asyncio.Lock()
    scanner = AlphaTransfersScanner(
        subtensor,
        dest_coldkey=dest_coldkey.strip(),
        target_subnet_id=target_subnet_id,
        allow_batch=True,
        rpc_lock=lock,
    )

    aggregated: Dict[str, int] = {}
    for chunk_start in range(from_block, to_block + 1, chunk):
        chunk_end = min(to_block, chunk_start + chunk - 1)
        try:
            events = await scanner.scan(chunk_start, chunk_end)
        except Exception as exc:
            bt.logging.warning(
                f"[payment] Scanner failed for blocks {chunk_start}-{chunk_end}: {exc}"
            )
            continue
        for ev in events:
            src = getattr(ev, "src_coldkey", None)
            if src and isinstance(src, str) and src.strip():
                amt = int(getattr(ev, "amount_rao", 0) or 0)
                if amt > 0:
                    aggregated[src] = aggregated.get(src, 0) + amt

    return aggregated
