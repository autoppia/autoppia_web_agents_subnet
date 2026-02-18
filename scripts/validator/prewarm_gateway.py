#!/usr/bin/env python3
from __future__ import annotations


import bittensor as bt

from autoppia_web_agents_subnet.opensource.sandbox_manager import SandboxManager


def main() -> int:
    try:
        manager = SandboxManager()
        manager.deploy_gateway()
        bt.logging.info("Gateway prewarm complete.")
        return 0
    except Exception as exc:
        bt.logging.error(f"Gateway prewarm failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
