"""
AlphaScanner: chain scanner for α-stake transfers to a payment address.
Delegates to metahash.validator.alpha_transfers.AlphaTransfersScanner when available.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from typing import Dict

import bittensor as bt

from autoppia_web_agents_subnet.validator.payment.config import (
    PAYMENT_SCAN_CHUNK,
    PAYMENT_SCAN_LOOKBACK_BLOCKS,
)


class AlphaScanner:
    """
    Scans chain for α-stake transfers to a payment address and returns amount sent by a given coldkey.
    Uses metahash.validator.alpha_transfers.AlphaTransfersScanner when available.
    """

    def __init__(self, subtensor: Any, *, rpc_lock: asyncio.Lock | None = None) -> None:
        self.subtensor = subtensor
        self._rpc_lock = rpc_lock or asyncio.Lock()

    async def scan(
        self,
        payment_address: str,
        coldkey: str,
        netuid: int = 36,
        from_block: int | None = None,
        to_block: int | None = None,
    ) -> int:
        """
        Return total amount_rao that coldkey sent to payment_address on netuid in [from_block, to_block].
        If from_block or to_block is None, uses defaults (current block and lookback).
        """
        if not (payment_address or "").strip() or not (coldkey or "").strip():
            return 0

        try:
            from metahash.validator.alpha_transfers import AlphaTransfersScanner
        except ImportError as e:
            bt.logging.warning(f"[AlphaScanner] AlphaTransfersScanner not available (install metahash): {e}")
            return 0

        to_b = to_block
        if to_b is None:
            try:
                block = self.subtensor.get_current_block()
                if inspect.iscoroutine(block):
                    block = await block
                to_b = int(block)
            except Exception:
                return 0
        from_b = from_block
        if from_b is None:
            lookback = max(1, PAYMENT_SCAN_LOOKBACK_BLOCKS)
            from_b = max(0, to_b - lookback)
        if from_b > to_b:
            return 0

        chunk = max(1, PAYMENT_SCAN_CHUNK)
        backend = AlphaTransfersScanner(
            self.subtensor,
            dest_coldkey=payment_address.strip(),
            target_subnet_id=netuid,
            allow_batch=True,
            rpc_lock=self._rpc_lock,
        )
        ck = coldkey.strip()
        total = 0
        for chunk_start in range(from_b, to_b + 1, chunk):
            chunk_end = min(to_b, chunk_start + chunk - 1)
            try:
                events = await backend.scan(chunk_start, chunk_end)
            except Exception as exc:
                bt.logging.warning(f"[AlphaScanner] scan failed for blocks {chunk_start}-{chunk_end}: {exc}")
                continue
            for ev in events:
                src = getattr(ev, "src_coldkey", None)
                if src and isinstance(src, str) and src.strip() == ck:
                    amt = int(getattr(ev, "amount_rao", 0) or 0)
                    if amt > 0:
                        total += amt
        return total


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
    """
    if from_block > to_block:
        return {}
    if not dest_coldkey or not dest_coldkey.strip():
        return {}

    try:
        from metahash.validator.alpha_transfers import AlphaTransfersScanner
    except ImportError as e:
        bt.logging.warning(f"[payment] AlphaTransfersScanner not available (install metahash): {e}")
        return {}

    chunk = chunk_size if chunk_size is not None else PAYMENT_SCAN_CHUNK
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
            bt.logging.warning(f"[payment] Scanner failed for blocks {chunk_start}-{chunk_end}: {exc}")
            continue
        for ev in events:
            src = getattr(ev, "src_coldkey", None)
            if src and isinstance(src, str) and src.strip():
                amt = int(getattr(ev, "amount_rao", 0) or 0)
                if amt > 0:
                    aggregated[src] = aggregated.get(src, 0) + amt

    return aggregated
