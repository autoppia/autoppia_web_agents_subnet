#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def get_subtensor(network: str | None, endpoint: str | None):
    import bittensor as bt

    kwargs = {}
    if network:
        kwargs["network"] = network
    if endpoint:
        kwargs["endpoint"] = endpoint
    return bt.subtensor(**kwargs)


def next_7am_europe_madrid(now: datetime) -> datetime:
    tz = ZoneInfo("Europe/Madrid")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc).astimezone(tz)
    else:
        now = now.astimezone(tz)
    target = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if target <= now:
        target = (target + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute DZ_STARTING_BLOCK for 7:00 AM Europe/Madrid")
    parser.add_argument("--seconds-per-block", type=float, default=float(os.getenv("SECONDS_PER_BLOCK", 12.0)), help="Average seconds per block (default 12)")
    parser.add_argument("--network", type=str, default=os.getenv("SUBTENSOR_NETWORK") or os.getenv("BITTENSOR_NETWORK") or None, help="Bittensor network, e.g., finney")
    parser.add_argument("--endpoint", type=str, default=os.getenv("SUBTENSOR_ENDPOINT") or os.getenv("BITTENSOR_ENDPOINT") or None, help="Subtensor endpoint url")
    parser.add_argument("--apply", action="store_true", help="Apply the computed block to validator/config.py in-place")
    args = parser.parse_args()

    st = get_subtensor(args.network, args.endpoint)
    current_block = int(getattr(st, "block"))

    now = datetime.now(timezone.utc)
    target_local = next_7am_europe_madrid(now)
    delta_seconds = (target_local - now.astimezone(target_local.tzinfo)).total_seconds()
    delta_blocks = int(math.ceil(delta_seconds / float(args.seconds_per_block)))
    target_block = current_block + max(delta_blocks, 0)

    print("Current block:", current_block)
    print("Now (UTC):", now.isoformat())
    print("Target (Europe/Madrid 07:00):", target_local.isoformat())
    print("Seconds per block:", args.seconds_per_block)
    print("Delta seconds:", int(delta_seconds))
    print("Delta blocks (ceil):", delta_blocks)
    print("Recommended DZ_STARTING_BLOCK:", target_block)

    if args.apply:
        # Patch autoppia_web_agents_subnet/validator/config.py in-place
        import pathlib
        import re

        repo_root = pathlib.Path(__file__).resolve().parents[1]
        config_path = repo_root / "autoppia_web_agents_subnet" / "validator" / "config.py"
        text = config_path.read_text(encoding="utf-8")
        # Match underscores in numeric literal as used in config (e.g., 6_716_460)
        new_text = re.sub(
            r"(DZ_STARTING_BLOCK_PROD\s*=\s*)[0-9_]+",
            r"\1" + f"{int(target_block):_}",
            text,
            count=1,
        )
        if text == new_text:
            print("No change written (pattern not found or already up to date).")
        else:
            config_path.write_text(new_text, encoding="utf-8")
            print(f"Updated {config_path} -> DZ_STARTING_BLOCK_PROD={target_block}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
