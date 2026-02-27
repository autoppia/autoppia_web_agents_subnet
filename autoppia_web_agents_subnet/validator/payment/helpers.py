"""Pure helper/check functions for payment-per-eval logic."""

from __future__ import annotations

import inspect
import time
from typing import Any, Dict

import bittensor as bt

from autoppia_web_agents_subnet.validator.payment.cache import PaymentCacheStore
from autoppia_web_agents_subnet.validator.payment.config import (
    ALPHA_PER_EVAL, PAYMENT_CACHE_PATH, RAO_PER_ALPHA, PAYMENT_WALLET_SS58,
)
from autoppia_web_agents_subnet.validator.payment.scanner import (
    AlphaScanner, get_paid_alpha_per_coldkey_async,
)


def allowed_evaluations_from_paid_rao(paid_rao: int, alpha_per_eval: float) -> int:
    """Number of evaluations allowed for a given paid amount (rao) and cost per eval (alpha)."""
    if paid_rao <= 0 or alpha_per_eval <= 0:
        return 0
    rao_per_eval = int(alpha_per_eval * RAO_PER_ALPHA)
    if rao_per_eval <= 0:
        return 0
    return paid_rao // rao_per_eval


async def get_alpha_sent_by_miner(
    coldkey: str,
    *,
    payment_address: str | None = None, netuid: int = 36,
    from_block: int | None = None, to_block: int | None = None,
    subtensor: Any = None,
    season_start_block: int | None = None, season_duration_blocks: int | None = None,
    cache_path: str | None = None,
) -> int:
    """Return total amount_rao that coldkey sent to the payment address in the given block range."""
    if subtensor is None:
        return 0
    addr = (payment_address or "").strip() or PAYMENT_WALLET_SS58
    if not addr:
        return 0
    ck = (coldkey or "").strip()
    if not ck:
        return 0

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
                pass

    scanner = AlphaScanner(subtensor)
    return await scanner.scan(addr, ck, netuid=netuid, from_block=from_block, to_block=to_block)


async def get_coldkey_balance(
    coldkey: str,
    *,
    payment_address: str | None = None, netuid: int = 36,
    from_block: int | None = None, to_block: int | None = None,
    subtensor: Any = None,
    season_start_block: int | None = None, season_duration_blocks: int | None = None,
    cache_path: str | None = None,
) -> int:
    """Compatibility wrapper: returns total sent amount in rao for a coldkey."""
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



def _load_cache_entry(
    payment_address: str, netuid: int,
    season_start_block: int, season_duration_blocks: int,
    cache_path: str | None = None,
) -> tuple[PaymentCacheStore, Dict[str, Any], bool]:
    """Load a cache entry; returns (store, entry, existed)."""
    store = PaymentCacheStore(cache_path or PAYMENT_CACHE_PATH)
    entry, existed = store.load_entry(
        payment_address=payment_address, netuid=netuid,
        season_start_block=season_start_block, season_duration_blocks=season_duration_blocks,
    )
    return store, entry, existed


def get_consumed_evals(
    coldkey: str, *,
    payment_address: str | None = None, netuid: int = 36,
    season_start_block: int, season_duration_blocks: int,
    cache_path: str | None = None,
) -> int:
    """Return the number of evaluations consumed by *coldkey* in the current season."""
    addr = (payment_address or "").strip() or PAYMENT_WALLET_SS58
    if not addr:
        return 0
    ck = (coldkey or "").strip()
    if not ck:
        return 0
    try:
        _, entry, _ = _load_cache_entry(addr, netuid, season_start_block, season_duration_blocks, cache_path)
        return int(entry.get("consumed_evals_by_coldkey", {}).get(ck, 0) or 0)
    except Exception:
        return 0


def increment_consumed_evals(
    coldkey: str, *,
    payment_address: str | None = None, netuid: int = 36,
    season_start_block: int, season_duration_blocks: int,
    count: int = 1, cache_path: str | None = None,
) -> int:
    """Increment consumed evaluations for *coldkey* and persist. Returns new total."""
    addr = (payment_address or "").strip() or PAYMENT_WALLET_SS58
    if not addr:
        return 0
    ck = (coldkey or "").strip()
    if not ck:
        return 0
    try:
        store, entry, _ = _load_cache_entry(addr, netuid, season_start_block, season_duration_blocks, cache_path)
        consumed = entry.get("consumed_evals_by_coldkey", {})
        if not isinstance(consumed, dict):
            consumed = {}
        new_total = int(consumed.get(ck, 0) or 0) + max(0, int(count))
        consumed[ck] = new_total
        entry["consumed_evals_by_coldkey"] = consumed
        entry["updated_at_unix"] = int(time.time())
        store.save_entry(
            payment_address=addr, netuid=netuid,
            season_start_block=season_start_block, season_duration_blocks=season_duration_blocks,
            entry=entry,
        )
        return new_total
    except Exception:
        return 0


def get_all_consumed_evals(
    *, payment_address: str | None = None, netuid: int = 36,
    season_start_block: int, season_duration_blocks: int,
    cache_path: str | None = None,
) -> Dict[str, int]:
    """Return the full consumed_evals_by_coldkey map for this season."""
    addr = (payment_address or "").strip() or PAYMENT_WALLET_SS58
    if not addr:
        return {}
    try:
        _, entry, _ = _load_cache_entry(addr, netuid, season_start_block, season_duration_blocks, cache_path)
        consumed = entry.get("consumed_evals_by_coldkey", {})
        if not isinstance(consumed, dict):
            return {}
        return {str(k): int(v or 0) for k, v in consumed.items()}
    except Exception:
        return {}


def set_all_consumed_evals(
    consumed_map: Dict[str, int], *,
    payment_address: str | None = None, netuid: int = 36,
    season_start_block: int, season_duration_blocks: int,
    cache_path: str | None = None,
) -> None:
    """Overwrite the consumed_evals_by_coldkey map (used for crash recovery)."""
    addr = (payment_address or "").strip() or PAYMENT_WALLET_SS58
    if not addr:
        return
    try:
        store, entry, _ = _load_cache_entry(addr, netuid, season_start_block, season_duration_blocks, cache_path)
        normalized: Dict[str, int] = {}
        for ck, count in (consumed_map or {}).items():
            if not isinstance(ck, str):
                continue
            try:
                normalized[ck] = max(0, int(count or 0))
            except Exception:
                continue
        entry["consumed_evals_by_coldkey"] = normalized
        entry["updated_at_unix"] = int(time.time())
        store.save_entry(
            payment_address=addr, netuid=netuid,
            season_start_block=season_start_block, season_duration_blocks=season_duration_blocks,
            entry=entry,
        )
    except Exception:
        pass


def remaining_evaluations(
    paid_rao: int, consumed_evals: int, alpha_per_eval: float | None = None,
) -> int:
    """Compute remaining evaluations: allowed_from_payment - consumed."""
    cost = alpha_per_eval if alpha_per_eval is not None else ALPHA_PER_EVAL
    if cost <= 0:
        return 999_999  # Payment disabled — unlimited evaluations.
    allowed = allowed_evaluations_from_paid_rao(paid_rao, cost)
    return max(0, allowed - max(0, int(consumed_evals)))
