"""
Pure helper/check functions for payment-per-eval logic.
No chain interaction — only math and validation.
"""

from __future__ import annotations

import inspect
import time
from typing import Any

from autoppia_web_agents_subnet.validator.payment.cache import PaymentCacheStore
from autoppia_web_agents_subnet.validator.payment.config import (
    PAYMENT_CACHE_PATH,
    RAO_PER_ALPHA,
    PAYMENT_WALLET_SS58,
)
from autoppia_web_agents_subnet.validator.payment.scanner import (
    AlphaScanner,
    get_paid_alpha_per_coldkey_async,
)


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


async def get_alpha_sent_by_miner(
    coldkey: str,
    *,
    payment_address: str | None = None,
    netuid: int = 36,
    from_block: int | None = None,
    to_block: int | None = None,
    subtensor: Any = None,
    season_start_block: int | None = None,
    season_duration_blocks: int | None = None,
    cache_path: str | None = None,
) -> int:
    """
    Return total amount_rao that coldkey sent to the payment address in the optional block range.
    Uses AlphaScanner internally. subtensor is required; payment_address defaults to PAYMENT_WALLET_SS58.
    """
    if subtensor is None:
        return 0
    addr = (payment_address or "").strip() or PAYMENT_WALLET_SS58
    if not addr:
        return 0
    ck = (coldkey or "").strip()
    if not ck:
        return 0

    # If a season range is provided, use cache to process only new blocks.
    if season_start_block is not None and season_duration_blocks is not None:
        try:
            season_start = int(season_start_block)
            season_duration = int(season_duration_blocks)
        except Exception:
            season_start = None
            season_duration = None
        if season_start is not None and season_duration is not None and season_duration > 0:
            season_end = season_start + season_duration - 1
            if season_end < season_start:
                return 0

            resolved_to = to_block
            if resolved_to is None:
                block = getattr(subtensor, "get_current_block", None)
                if callable(block):
                    block = block()
                if inspect.iscoroutine(block):
                    block = await block
                if block is None:
                    return 0
                resolved_to = int(block)
            else:
                resolved_to = int(resolved_to)

            scan_to = min(int(season_end), int(resolved_to))
            if scan_to < season_start:
                return 0

            try:
                cache = PaymentCacheStore(cache_path or PAYMENT_CACHE_PATH)
                entry, exists = cache.load_entry(
                    payment_address=addr,
                    netuid=int(netuid),
                    season_start_block=season_start,
                    season_duration_blocks=season_duration,
                )
                totals = entry.get("totals_by_coldkey", {})
                if not isinstance(totals, dict):
                    totals = {}

                # First run for a season backfills from season start. Afterwards, only new blocks are scanned.
                if exists:
                    next_block = int(entry.get("last_processed_block", season_start - 1)) + 1
                    if from_block is not None:
                        next_block = max(next_block, int(from_block))
                else:
                    next_block = season_start

                if next_block <= scan_to:
                    delta = await get_paid_alpha_per_coldkey_async(
                        subtensor=subtensor,
                        from_block=int(next_block),
                        to_block=int(scan_to),
                        dest_coldkey=addr,
                        target_subnet_id=int(netuid),
                    )
                    for src, amount in delta.items():
                        if not isinstance(src, str):
                            continue
                        try:
                            delta_amount = int(amount or 0)
                        except Exception:
                            continue
                        if delta_amount <= 0:
                            continue
                        totals[src] = int(totals.get(src, 0) or 0) + delta_amount

                    entry["last_processed_block"] = int(scan_to)
                    entry["totals_by_coldkey"] = totals
                    entry["updated_at_unix"] = int(time.time())
                    cache.save_entry(
                        payment_address=addr,
                        netuid=int(netuid),
                        season_start_block=season_start,
                        season_duration_blocks=season_duration,
                        entry=entry,
                    )

                return int(totals.get(ck, 0) or 0)
            except Exception:
                # Cache is an optimization; if it fails, continue with direct scan.
                pass

    scanner = AlphaScanner(subtensor)
    return await scanner.scan(addr, ck, netuid=netuid, from_block=from_block, to_block=to_block)


async def get_coldkey_balance(
    coldkey: str,
    *,
    payment_address: str | None = None,
    netuid: int = 36,
    from_block: int | None = None,
    to_block: int | None = None,
    subtensor: Any = None,
    season_start_block: int | None = None,
    season_duration_blocks: int | None = None,
    cache_path: str | None = None,
) -> int:
    """
    Compatibility wrapper: returns total sent amount in rao for a coldkey.
    """
    return await get_alpha_sent_by_miner(
        coldkey,
        payment_address=payment_address,
        netuid=netuid,
        from_block=from_block,
        to_block=to_block,
        subtensor=subtensor,
        season_start_block=season_start_block,
        season_duration_blocks=season_duration_blocks,
        cache_path=cache_path,
    )
