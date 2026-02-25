"""
Pure helper/check functions for payment-per-eval logic.
No chain interaction — only math and validation.
"""

from __future__ import annotations

from typing import Any

from autoppia_web_agents_subnet.validator.payment.config import (
    RAO_PER_ALPHA,
    PAYMENT_WALLET_SS58,
)
from autoppia_web_agents_subnet.validator.payment.scanner import AlphaScanner


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
    scanner = AlphaScanner(subtensor)
    return await scanner.scan(addr, coldkey, netuid=netuid, from_block=from_block, to_block=to_block)
