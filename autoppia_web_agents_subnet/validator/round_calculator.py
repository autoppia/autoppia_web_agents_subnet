# autoppia_web_agents_subnet/validator/round_calculator.py
from __future__ import annotations
import bittensor as bt
from typing import Dict, Any


class RoundCalculator:
    """
    Automatically calculates how many tasks can be executed in a complete round.

    A round = ROUND_SIZE_EPOCHS epochs of Bittensor
    All validators synchronize at epoch multiples of ROUND_SIZE_EPOCHS.

    Example:
        If ROUND_SIZE_EPOCHS = 20:
        - Round 1: epochs 0-19 (target: 20)
        - Round 2: epochs 20-39 (target: 40)
        - Round 3: epochs 40-59 (target: 60)
    """

    # Bittensor constants
    BLOCKS_PER_EPOCH = 360
    SECONDS_PER_BLOCK = 12

    def __init__(
        self,
        round_size_epochs: int,
        avg_task_duration_seconds: float,
        safety_buffer_epochs: float,
    ):
        """
        Args:
            round_size_epochs: Round duration in epochs (e.g., 20 = ~24h)
            avg_task_duration_seconds: Average time to complete 1 task
            safety_buffer_epochs: Safety buffer in epochs (e.g., 0.5 = 36 min)
        """
        self.round_size_epochs = round_size_epochs
        self.avg_task_duration_seconds = avg_task_duration_seconds
        self.safety_buffer_epochs = safety_buffer_epochs

    @classmethod
    def block_to_epoch(cls, block: int) -> int:
        """Convert block number to epoch number."""
        return block // cls.BLOCKS_PER_EPOCH

    @classmethod
    def epoch_to_block(cls, epoch: int) -> int:
        """Convert epoch number to the first block of that epoch."""
        return epoch * cls.BLOCKS_PER_EPOCH

    def get_round_boundaries(self, current_block: int) -> Dict[str, int]:
        """
        Calculate the boundaries of the current round based on the current block.

        Rounds start at epoch multiples of round_size_epochs.
        Example with round_size_epochs=20:
            - Epoch 0-19 → round_start=0, target=20
            - Epoch 20-39 → round_start=20, target=40
            - Epoch 233 → round_start=220, target=240

        Args:
            current_block: Current blockchain block

        Returns:
            Dict with round boundaries
        """
        current_epoch = self.block_to_epoch(current_block)

        # Calculate round start (epoch multiple of round_size_epochs)
        round_start_epoch = (current_epoch // self.round_size_epochs) * self.round_size_epochs

        # Target epoch is the end of the round
        target_epoch = round_start_epoch + self.round_size_epochs

        # Convert to blocks
        round_start_block = self.epoch_to_block(round_start_epoch)
        target_block = self.epoch_to_block(target_epoch)

        return {
            "current_block": current_block,
            "current_epoch": current_epoch,
            "round_start_epoch": round_start_epoch,
            "round_start_block": round_start_block,
            "target_epoch": target_epoch,
            "target_block": target_block,
        }

    def should_send_next_task(self, current_block: int, start_block: int) -> bool:
        """
        Determine if there's enough time to send another task.

        Dynamically checks:
        1. Calculate absolute limit (start + round_size - safety_buffer)
        2. Compare current_block with that limit
        3. Verify if there's time for avg_task_duration

        Args:
            current_block: Current blockchain block
            start_block: Block where the round started

        Returns:
            True if there's time for another task, False otherwise
        """
        boundaries = self.get_round_boundaries(start_block)

        # Calculate absolute limit: start + round_size - safety_buffer
        total_round_blocks = self.round_size_epochs * self.BLOCKS_PER_EPOCH
        safety_buffer_blocks = self.safety_buffer_epochs * self.BLOCKS_PER_EPOCH
        absolute_limit_block = start_block + total_round_blocks - safety_buffer_blocks

        # Have we reached the absolute limit?
        if current_block >= absolute_limit_block:
            return False

        # Is there time for another task from now until the limit?
        blocks_until_limit = absolute_limit_block - current_block
        seconds_until_limit = blocks_until_limit * self.SECONDS_PER_BLOCK

        has_time = seconds_until_limit >= self.avg_task_duration_seconds

        return has_time

    def get_calculation_summary(self) -> Dict[str, Any]:
        """
        Return a summary of the round configuration.

        Returns:
            Dict with configuration info
        """
        total_blocks = self.round_size_epochs * self.BLOCKS_PER_EPOCH
        total_seconds = total_blocks * self.SECONDS_PER_BLOCK

        # Initial estimation (informational only)
        safety_buffer_seconds = self.safety_buffer_epochs * self.BLOCKS_PER_EPOCH * self.SECONDS_PER_BLOCK
        available_time = total_seconds - safety_buffer_seconds
        estimated_tasks = int(available_time / self.avg_task_duration_seconds)

        return {
            # Round config
            "round_size_epochs": self.round_size_epochs,
            "avg_task_duration_seconds": self.avg_task_duration_seconds,
            "safety_buffer_epochs": self.safety_buffer_epochs,
            "safety_buffer_seconds": int(safety_buffer_seconds),

            # Time calculations
            "total_blocks": total_blocks,
            "total_seconds": total_seconds,
            "total_hours": round(total_seconds / 3600, 2),
            "available_seconds": int(available_time),
            "available_hours": round(available_time / 3600, 2),

            # Initial estimation (not the real maximum, just reference)
            "estimated_tasks": estimated_tasks,
        }

    def should_wait_for_target(self, current_block: int, start_block: int) -> bool:
        """
        Determine if should wait for the target epoch.

        Args:
            current_block: Current block
            start_block: Block where the round started

        Returns:
            True if we've already reached or passed the target epoch
        """
        boundaries = self.get_round_boundaries(start_block)
        current_epoch = self.block_to_epoch(current_block)

        return current_epoch >= boundaries["target_epoch"]

    def get_wait_info(self, current_block: int, start_block: int) -> Dict[str, Any]:
        """
        Info about how much time is left until the target epoch.

        Args:
            current_block: Current block
            start_block: Block where the round started

        Returns:
            Dict with wait info
        """
        boundaries = self.get_round_boundaries(start_block)
        current_epoch = self.block_to_epoch(current_block)

        epochs_remaining = boundaries["target_epoch"] - current_epoch
        blocks_remaining = boundaries["target_block"] - current_block
        seconds_remaining = blocks_remaining * self.SECONDS_PER_BLOCK

        return {
            "current_epoch": current_epoch,
            "target_epoch": boundaries["target_epoch"],
            "epochs_remaining": epochs_remaining,
            "blocks_remaining": blocks_remaining,
            "seconds_remaining": seconds_remaining,
            "minutes_remaining": round(seconds_remaining / 60, 1),
            "reached_target": epochs_remaining <= 0,
        }

    def log_calculation_summary(self) -> None:
        """Log a summary of the round configuration."""
        summary = self.get_calculation_summary()

        bt.logging.info("=" * 80)
        bt.logging.info("📊 ROUND CONFIGURATION")
        bt.logging.info("=" * 80)
        bt.logging.info(f"Round Duration:")
        bt.logging.info(f"  • {summary['round_size_epochs']} epochs = {summary['total_hours']}h")
        bt.logging.info(f"  • Total blocks: {summary['total_blocks']:,}")
        bt.logging.info(f"  • Total time: {summary['total_seconds']:,}s")
        bt.logging.info("")
        bt.logging.info(f"Task Configuration (Dynamic):")
        bt.logging.info(f"  • Avg duration per task: {summary['avg_task_duration_seconds']}s ({summary['avg_task_duration_seconds']/60:.1f}min)")
        bt.logging.info(f"  • Safety buffer: {summary['safety_buffer_epochs']} epochs ({summary['safety_buffer_seconds']}s)")
        bt.logging.info(f"  • Available time: {summary['available_hours']:.1f}h ({summary['available_seconds']:,}s)")
        bt.logging.info("")
        bt.logging.info(f"Dynamic System:")
        bt.logging.info(f"  • Tasks are sent one by one")
        bt.logging.info(f"  • Before each task: checks if there's time remaining")
        bt.logging.info(f"  • Stops when: time_remaining < avg_task_duration + safety_buffer")
        bt.logging.info(f"  • Estimated tasks (reference): ~{summary['estimated_tasks']}")
        bt.logging.info("=" * 80)
