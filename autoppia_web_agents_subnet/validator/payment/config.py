"""
Payment module configuration — self-contained defaults.
Override via environment variables. No dependency on validator config.
"""

from __future__ import annotations

import os

RAO_PER_ALPHA = 10**9

PAYMENT_WALLET_SS58: str = os.getenv("PAYMENT_WALLET_SS58", "").strip()
ALPHA_PER_EVAL: float = float(os.getenv("ALPHA_PER_EVAL", "10.0"))
PAYMENT_SCAN_CHUNK: int = int(os.getenv("PAYMENT_SCAN_CHUNK", "512"))
PAYMENT_SUBNET_ID: int = int(os.getenv("PAYMENT_SUBNET_ID", "36"))
PAYMENT_SCAN_LOOKBACK_BLOCKS: int = int(os.getenv("PAYMENT_SCAN_LOOKBACK_BLOCKS", "50000"))
