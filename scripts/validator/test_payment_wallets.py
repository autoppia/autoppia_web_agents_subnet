#!/usr/bin/env python3
"""
End-to-end verification script for payment functionality.
Takes two source wallets + destination wallet + block range/subnet,
prints paid amounts + allowed evals + clear pass/fail output.

Usage:
  python scripts/validator/test_payment_wallets.py \
    --src-wallet-1 5Alice... \
    --src-wallet-2 5Bob... \
    --dest-wallet  5Treasury... \
    --netuid 36 \
    --from-block 100000 \
    --to-block   200000 \
    --alpha-per-eval 10 \
    [--subtensor-network finney]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from autoppia_web_agents_subnet.validator.payment import (
    AlphaScanner,
    RAO_PER_ALPHA,
    allowed_evaluations_from_paid_rao,
)


def _alpha_from_rao(rao: int) -> float:
    return rao / RAO_PER_ALPHA


async def run_check(
    src_wallets: list[str],
    dest_wallet: str,
    netuid: int,
    from_block: int,
    to_block: int,
    alpha_per_eval: float,
    network: str,
) -> bool:
    import bittensor as bt

    print(f"Connecting to subtensor ({network})...")
    try:
        async with bt.AsyncSubtensor(network=network) as st:
            current_block = await st.get_current_block()
            print(f"Connected. Current block: {current_block}")

            if to_block <= 0:
                to_block_resolved = current_block
            else:
                to_block_resolved = to_block

            scanner = AlphaScanner(st)
            all_pass = True

            for i, src in enumerate(src_wallets, 1):
                print(f"\n{'='*60}")
                print(f"Source wallet {i}: {src}")
                print(f"Dest wallet:     {dest_wallet}")
                print(f"Netuid:          {netuid}")
                print(f"Block range:     [{from_block}, {to_block_resolved}]")

                paid_rao = await scanner.scan(
                    dest_wallet, src, netuid=netuid, from_block=from_block, to_block=to_block_resolved
                )
                paid_alpha = _alpha_from_rao(paid_rao)
                evals = allowed_evaluations_from_paid_rao(paid_rao, alpha_per_eval)

                print(f"Paid:            {paid_rao} rao ({paid_alpha:.4f} α)")
                print(f"Alpha per eval:  {alpha_per_eval}")
                print(f"Allowed evals:   {evals}")

                if paid_rao > 0 and evals > 0:
                    print(f"Result:          PASS (paid >= {alpha_per_eval} α, {evals} eval(s) allowed)")
                elif paid_rao > 0:
                    print(f"Result:          FAIL (paid {paid_alpha:.4f} α < {alpha_per_eval} α per eval)")
                    all_pass = False
                else:
                    print(f"Result:          FAIL (no transfers found)")
                    all_pass = False

            print(f"\n{'='*60}")
            if all_pass:
                print("OVERALL: PASS — all source wallets have paid enough for at least 1 eval")
            else:
                print("OVERALL: FAIL — one or more source wallets did not pay enough")
            return all_pass
    except Exception as exc:
        print(f"ERROR: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test payment wallets end-to-end")
    parser.add_argument("--src-wallet-1", required=True, help="First source coldkey SS58")
    parser.add_argument("--src-wallet-2", required=True, help="Second source coldkey SS58")
    parser.add_argument("--dest-wallet", required=True, help="Destination payment wallet SS58")
    parser.add_argument("--netuid", type=int, default=36, help="Subnet netuid (default: 36)")
    parser.add_argument("--from-block", type=int, default=0, help="Start block (0 = use config lookback)")
    parser.add_argument("--to-block", type=int, default=0, help="End block (0 = current block)")
    parser.add_argument("--alpha-per-eval", type=float, default=10.0, help="Alpha required per eval (default: 10)")
    parser.add_argument("--subtensor-network", default="finney", help="Subtensor network (default: finney)")
    args = parser.parse_args()

    src_wallets = [args.src_wallet_1, args.src_wallet_2]
    passed = asyncio.run(
        run_check(
            src_wallets=src_wallets,
            dest_wallet=args.dest_wallet,
            netuid=args.netuid,
            from_block=args.from_block if args.from_block > 0 else None,
            to_block=args.to_block,
            alpha_per_eval=args.alpha_per_eval,
            network=args.subtensor_network,
        )
    )
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
