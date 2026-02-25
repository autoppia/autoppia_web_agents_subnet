"""
Payment-per-eval: AlphaScanner and service to query α-stake sent by a coldkey to a payment address.
Uses AlphaTransfersScanner from metahash when available.
"""

from __future__ import annotations

import asyncio
import inspect
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
        If from_block or to_block is None, uses config defaults (current block and lookback).
        """
        if not (payment_address or "").strip() or not (coldkey or "").strip():
            return 0

        try:
            from metahash.validator.alpha_transfers import AlphaTransfersScanner
        except ImportError as e:
            bt.logging.warning(
                f"[AlphaScanner] AlphaTransfersScanner not available (install metahash): {e}"
            )
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
            lookback = max(
                1,
                int(getattr(validator_config, "PAYMENT_SCAN_LOOKBACK_BLOCKS", 50000) or 50000),
            )
            min_start = int(getattr(validator_config, "MINIMUM_START_BLOCK", 0) or 0)
            from_b = max(min_start, to_b - lookback)
        if from_b > to_b:
            return 0

        chunk = max(
            1,
            int(getattr(validator_config, "PAYMENT_SCAN_CHUNK", 512) or 512),
        )
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
                bt.logging.warning(
                    f"[AlphaScanner] scan failed for blocks {chunk_start}-{chunk_end}: {exc}"
                )
                continue
            for ev in events:
                src = getattr(ev, "src_coldkey", None)
                if src and isinstance(src, str) and src.strip() == ck:
                    amt = int(getattr(ev, "amount_rao", 0) or 0)
                    if amt > 0:
                        total += amt
        return total


async def get_alpha_sent_by_miner(
    coldkey: str,
    *,
    payment_address: str | None = None,
    netuid: int = 36,
    from_block: int | None = None,
    to_block: int | None = None,
    subtensor: Any = None,
) -> int:
    """
    Return total amount_rao that coldkey sent to the payment address in the optional block range.
    Uses AlphaScanner internally. subtensor is required; payment_address defaults to config.
    """
    if subtensor is None:
        return 0
    addr = (payment_address or "").strip() or (
        (getattr(validator_config, "PAYMENT_WALLET_SS58", None) or "").strip()
    )
    if not addr:
        return 0
    scanner = AlphaScanner(subtensor)
    return await scanner.scan(addr, coldkey, netuid=netuid, from_block=from_block, to_block=to_block)


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
