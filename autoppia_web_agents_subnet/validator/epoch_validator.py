# ╭──────────────────────────────────────────────────────────────────────╮
# metahash/validator/epoch_validator.py                                  #
# (v2.4: EPOCH_LENGTH_OVERRIDE + ROUND_EPOCHS_DURATION + TESTING bootstrap)
# ╰──────────────────────────────────────────────────────────────────────╯
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Tuple

import bittensor as bt
from bittensor import BLOCKTIME  # 12 s on Finney

from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.config import EPOCH_LENGTH_OVERRIDE, TESTING, ROUND_EPOCHS_DURATION


class EpochValidatorNeuron(BaseValidatorNeuron):
    """
    Validator base-class with robust epoch rollover handling.

    New:
      • Honors ROUND_EPOCHS_DURATION: number of epoch heads to wait between forwards.
      • Clean bootstrap in TESTING mode (immediate forward once, then apply cadence).
      • Handles EPOCH_LENGTH_OVERRIDE for fast local testing.

    ⚠️ If you use overrides you are *not* aligned to real chain epoch heads.
       Avoid on-chain set_weights in that mode.
    """

    def __init__(self, *args, log_interval_blocks: int = 2, **kwargs):
        super().__init__(*args, **kwargs)
        self._log_interval_blocks = max(1, int(log_interval_blocks))
        self._epoch_len: Optional[int] = None
        self.epoch_end_block: Optional[int] = None
        self._override_active: bool = False
        self._bootstrapped: bool = False  # run forward immediately if TESTING

        try:
            self._round_epochs = max(1, int(ROUND_EPOCHS_DURATION or 1))
        except Exception:
            self._round_epochs = 1

    # ----------------------- helpers ---------------------------------- #
    def _discover_epoch_length(self) -> int:
        """Return current epoch length, preferring override when set."""
        try:
            override = int(EPOCH_LENGTH_OVERRIDE or 0)
        except Exception:
            override = 0

        if override > 0:
            self._override_active = True
            length = max(1, override)
            if self._epoch_len != length:
                bt.logging.info(
                    f"[epoch] using EPOCH_LENGTH_OVERRIDE = {length} blocks (TESTING={TESTING})"
                )
            self._epoch_len = length
            return length

        self._override_active = False
        tempo = self.subtensor.tempo(self.config.netuid) or 360
        try:
            head = self.subtensor.get_current_block()
            next_head = self.subtensor.get_next_epoch_start_block(self.config.netuid)
            if next_head is None:
                raise ValueError("RPC returned None for next epoch start")
            derived = next_head - (head - head % tempo)
            # Chain implementations often report tempo/tempo+1 windows.
            length = derived if derived in (tempo, tempo + 1) else tempo + 1
        except Exception as e:
            bt.logging.warning(f"[epoch] RPC error while probing length: {e}")
            length = tempo + 1

        if self._epoch_len != length:
            bt.logging.info(f"[epoch] detected length = {length} (chain mode)")
        self._epoch_len = length
        return length

    def _epoch_snapshot(self) -> Tuple[int, int, int, int, int]:
        """(blk, start, end, idx, len) using current or discovered epoch length."""
        blk = self.subtensor.get_current_block()
        ep_l = self._epoch_len or self._discover_epoch_length()
        start = blk - (blk % ep_l)
        end = start + ep_l - 1
        idx = blk // ep_l
        self.epoch_end_block = end
        return blk, start, end, idx, ep_l

    def _apply_epoch_state(self, blk: int, start: int, end: int, idx: int, ep_len: int):
        """Persist epoch fields to the instance and log the head."""
        self.epoch_start_block = start
        self.epoch_end_block = end
        self.epoch_index = idx
        self.epoch_tempo = ep_len
        label = "override" if self._override_active else "chain"
        head_time = datetime.utcnow().strftime("%H:%M:%S")
        bt.logging.success(
            f"[epoch {idx} @ {label}] head at block {blk:,} ({head_time} UTC) – len={ep_len}"
        )

    async def _wait_for_next_head(self):
        """
        Sleep until the next epoch head. Re-evaluates remaining blocks periodically,
        resilient to override/tempo changes and validator shutdowns.
        """
        # Capture a fresh target based on the *current* view.
        while not self.should_exit:
            ep_l = self._epoch_len or self._discover_epoch_length()
            blk = self.subtensor.get_current_block()
            target_head = blk - (blk % ep_l) + ep_l
            label = "override" if self._override_active else "chain"

            if blk >= target_head:
                # Already at or past a head boundary—advance once more to avoid
                # double-firing within the same height.
                target_head += ep_l

            while not self.should_exit:
                cur = self.subtensor.get_current_block()
                if cur >= target_head:
                    return
                remain = max(0, target_head - cur)
                eta_s = remain * BLOCKTIME
                bt.logging.info(
                    f"[status:{label}] Block {cur:,} | {remain} blocks → next head "
                    f"(~{int(eta_s // 60)}m{int(eta_s % 60):02d}s) | len={ep_l}"
                )
                # Sleep proportionally but wake up often enough to react quickly.
                sleep_blocks = max(1, min(30, remain // 2 or 1))
                await asyncio.sleep(sleep_blocks * BLOCKTIME * 0.95)
            # Loop outer to rebuild target if we were interrupted.

    async def _wait_epochs(self, n: int):
        """Wait for n epoch heads, one by one (tempo/override may change in-between)."""
        for i in range(n):
            if self.should_exit:
                return
            await self._wait_for_next_head()
            # After each head, reset cached epoch length to allow re-probing next time.
            self._epoch_len = None

    def _log_position(self):
        blk, start, _end, idx, ep_len = self._epoch_snapshot()
        next_head = start + ep_len
        into = blk - start
        left = max(1, next_head - blk)
        eta_s = left * BLOCKTIME
        label = "override" if self._override_active else "chain"
        bt.logging.info(
            f"[status:{label}] Block {blk:,} | Epoch {idx} "
            f"[{into}/{ep_len} blocks] – next {label} head in {left} blocks "
            f"(~{int(eta_s // 60)}m{int(eta_s % 60):02d}s)"
        )

    def _at_head_apply(self):
        """Snapshot right at (or immediately after) a head and persist/log it."""
        self._epoch_len = None  # allow fresh detection at head boundary
        blk2, start2, end2, idx2, ep_len2 = self._epoch_snapshot()
        self._apply_epoch_state(blk2, start2, end2, idx2, ep_len2)

    def _do_forward_sync_wrapped(self):
        """DRY: sync → forward → sync with error handling & step bump."""
        try:
            self.sync()
            return self.concurrent_forward()
        except Exception as err:
            bt.logging.error(f"forward() raised: {err}")
        finally:
            try:
                self.sync()
            except Exception as e:
                bt.logging.warning(f"wallet sync failed: {e}")
            self.step += 1

    # ----------------------- main loop -------------------------------- #
    def run(self):  # noqa: D401
        bt.logging.info(
            f"EpochValidator starting at block {self.block:,} (netuid {self.config.netuid}) "
            f"| ROUND_EPOCHS_DURATION={self._round_epochs}"
        )

        async def _loop():
            while not self.should_exit:
                # Initial status line for the current position.
                self._log_position()

                # --- TESTING bootstrap: run a forward immediately on first loop ---
                if TESTING and not self._bootstrapped:
                    blk, start, end, idx, ep_len = self._epoch_snapshot()
                    self._apply_epoch_state(blk, start, end, idx, ep_len)
                    self._bootstrapped = True

                    # Run the forward once right now.
                    await self._do_forward_sync_wrapped()

                    # Then wait N epoch heads before the next forward.
                    await self._wait_epochs(self._round_epochs)
                    # Apply state *at* head and forward again.
                    self._at_head_apply()
                    await self._do_forward_sync_wrapped()
                    # Continue the loop cadence (wait N heads between each forward).
                    continue

                # Normal cadence: wait N epoch heads, then forward.
                await self._wait_epochs(self._round_epochs)
                self._at_head_apply()
                await self._do_forward_sync_wrapped()

        try:
            self.loop.run_until_complete(_loop())
        except KeyboardInterrupt:
            getattr(self, "axon", bt.logging).stop()
            bt.logging.success("Validator stopped by keyboard interrupt.")
