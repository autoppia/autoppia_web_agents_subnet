# ╭──────────────────────────────────────────────────────────────────────╮
# autoppia_web_agents_subnet/validator/epoch_validator.py                #
# (v2.5: 20-epoch rounds + CLOSEOUT window + TESTING bootstrap)          #
# ╰──────────────────────────────────────────────────────────────────────╯
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Tuple

import bittensor as bt
from bittensor import BLOCKTIME  # 12 s on Finney

from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.config import (
    EPOCH_LENGTH_OVERRIDE,
    TESTING,
    ROUND_SIZE_EPOCHS,   # NEW: default 20 in config
    CLOSEOUT_EPOCHS,     # NEW: stop launching forwards when <= N epochs remain in round
)


class EpochValidatorNeuron(BaseValidatorNeuron):
    """
    Validator base-class with robust epoch/round handling.

    • Rounds are windows of ROUND_SIZE_EPOCHS (default 20) chain epochs.
      Round index r = epoch_index // ROUND_SIZE_EPOCHS.

    • We launch a forward once at (most) every epoch **outside** the closeout
      window. The closeout window is when there are <= CLOSEOUT_EPOCHS epochs
      left until the end of the current 20-epoch round. Inside that window,
      the validator pauses new evaluations and simply waits for the next
      round boundary to start evaluating again.

    • TESTING mode bootstraps a forward immediately, then continues cadence.

    • Honors EPOCH_LENGTH_OVERRIDE for fast local testing. When override is
      active, avoid relying on real chain heads for set_weights alignment.
    """

    def __init__(self, *args, log_interval_blocks: int = 2, **kwargs):
        super().__init__(*args, **kwargs)
        self._log_interval_blocks = max(1, int(log_interval_blocks))
        self._epoch_len: Optional[int] = None
        self.epoch_end_block: Optional[int] = None
        self._override_active: bool = False
        self._bootstrapped: bool = False  # run forward immediately if TESTING

        # Configured round size and closeout window
        try:
            self._round_size = max(1, int(ROUND_SIZE_EPOCHS or 20))
        except Exception:
            self._round_size = 20

        try:
            self._closeout = max(0, int(CLOSEOUT_EPOCHS or 0))
        except Exception:
            self._closeout = 0

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

    def _round_meta(self, epoch_idx: int) -> Tuple[int, int, int]:
        """Return (round_index, round_start_epoch, round_end_epoch)."""
        r_idx = epoch_idx // self._round_size
        r_start = r_idx * self._round_size
        r_end = r_start + self._round_size - 1
        return r_idx, r_start, r_end

    def _epochs_until_round_end(self, epoch_idx: int) -> int:
        """How many epochs remain including the current one up to the round end."""
        _, _, r_end = self._round_meta(epoch_idx)
        return max(0, r_end - epoch_idx)

    async def _wait_for_next_head(self):
        """
        Sleep until the next epoch head. Re-evaluates remaining blocks periodically,
        resilient to override/tempo changes and validator shutdowns.
        """
        while not self.should_exit:
            ep_l = self._epoch_len or self._discover_epoch_length()
            blk = self.subtensor.get_current_block()
            target_head = blk - (blk % ep_l) + ep_l
            label = "override" if self._override_active else "chain"

            if blk >= target_head:
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
                sleep_blocks = max(1, min(30, remain // 2 or 1))
                await asyncio.sleep(sleep_blocks * BLOCKTIME * 0.95)

    async def _wait_epochs(self, n: int):
        """Wait for n epoch heads, one by one (tempo/override may change in-between)."""
        for _ in range(n):
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
        r_idx, r_start, r_end = self._round_meta(idx)
        till_end = self._epochs_until_round_end(idx)
        bt.logging.info(
            f"[status:{label}] Block {blk:,} | Epoch {idx} "
            f"[{into}/{ep_len} blocks] – next head in {left} blocks "
            f"(~{int(eta_s // 60)}m{int(eta_s % 60):02d}s) "
            f"| Round r={r_idx} [{r_start}..{r_end}], epochs_until_end={till_end}, closeout={self._closeout}"
        )

    def _at_head_apply(self):
        """Snapshot right at (or immediately after) a head and persist/log it."""
        self._epoch_len = None  # allow fresh detection at head boundary
        blk2, start2, end2, idx2, ep_len2 = self._epoch_snapshot()
        self._apply_epoch_state(blk2, start2, end2, idx2, ep_len2)

    async def _do_forward_async_wrapped(self):
        """Run a forward with pre/post sync and error handling."""
        try:
            self.sync()
            await self.concurrent_forward()
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
            f"| ROUND_SIZE_EPOCHS={self._round_size} | CLOSEOUT_EPOCHS={self._closeout}"
        )

        async def _loop():
            while not self.should_exit:
                # Log current position
                self._log_position()

                # Compute round info
                _blk, _start, _end, idx, _ep_len = self._epoch_snapshot()
                r_idx, r_start, r_end = self._round_meta(idx)
                epochs_left = self._epochs_until_round_end(idx)

                # --- TESTING bootstrap: run a forward immediately on first loop ---
                if TESTING and not self._bootstrapped:
                    self._apply_epoch_state(*self._epoch_snapshot())
                    self._bootstrapped = True

                    await self._do_forward_async_wrapped()

                    # Move to next head and continue cadence logic
                    await self._wait_for_next_head()
                    self._at_head_apply()
                    continue

                # Outside closeout window: run a forward once per epoch.
                if epochs_left > self._closeout:
                    # Wait until *next* head, then forward
                    await self._wait_for_next_head()
                    self._at_head_apply()
                    await self._do_forward_async_wrapped()
                    # Next loop iteration will re-evaluate whether we’re still outside closeout
                    continue

                # Inside closeout window (epochs_left <= closeout):
                # Pause new evaluations; wait until the ROUND boundary.
                bt.logging.info(
                    f"[round r={r_idx}] In closeout window (epochs_left={epochs_left} "
                    f"<= closeout={self._closeout}). Pausing forwards until next round boundary."
                )
                # Wait until we cross the round end; each head may change tempo/override.
                while not self.should_exit:
                    await self._wait_for_next_head()
                    self._at_head_apply()
                    # Recompute epoch index and round
                    _blk2, _st2, _en2, idx2, _l2 = self._epoch_snapshot()
                    r_idx2, r_start2, r_end2 = self._round_meta(idx2)
                    if r_idx2 != r_idx:
                        bt.logging.success(
                            f"[round r={r_idx}] Completed. New round r={r_idx2} "
                            f"([{r_start2}..{r_end2}]). Resuming evaluations."
                        )
                        break
                # Loop continues into next round, where we’ll launch forwards again.

        try:
            self.loop.run_until_complete(_loop())
        except KeyboardInterrupt:
            getattr(self, "axon", bt.logging).stop()
            bt.logging.success("Validator stopped by keyboard interrupt.")
