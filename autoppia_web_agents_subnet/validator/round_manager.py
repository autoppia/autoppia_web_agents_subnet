# autoppia_web_agents_subnet/validator/round_manager.py
from __future__ import annotations
import bittensor as bt
from typing import Dict, Any, List, Optional
import numpy as np
from autoppia_web_agents_subnet.utils.logging import ColoredLogger


class RoundManager:
    """
    Manages complete round lifecycle: timing, boundaries, and score accumulation.

    Combines:
    - Round timing and boundaries (from round_calculator.py)
    - Score accumulation and management (new)

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
    ROUND_BLOCK_LENGTH = BLOCKS_PER_EPOCH * 20  # 20 epochs ≈ 24 hours → 7,200 blocks

    def __init__(
        self,
        round_size_epochs: float,
        avg_task_duration_seconds: float,
        safety_buffer_epochs: float,
        minimum_start_block: Optional[int] = None,
    ):
        """
        Args:
            round_size_epochs: Round duration in epochs (e.g., 20 = ~24h, or 0.05 for testing)
            avg_task_duration_seconds: Average time to complete 1 task
            safety_buffer_epochs: Safety buffer in epochs (e.g., 0.5 = 36 min)
        """
        self.round_size_epochs = round_size_epochs
        self.avg_task_duration_seconds = avg_task_duration_seconds
        self.safety_buffer_epochs = safety_buffer_epochs
        self.minimum_start_block = minimum_start_block

        # Round state management
        self.round_rewards = {} 
        self.round_eval_scores = {}   
        self.round_times = {}

        # Track round start block
        self.start_block: int | None = None  

    @classmethod
    def block_to_epoch(cls, block: int) -> float:
        """Convert block number to epoch number."""
        return block / cls.BLOCKS_PER_EPOCH

    @classmethod
    def epoch_to_block(cls, epoch: float) -> int:
        """Convert epoch number to the first block of that epoch."""
        return int(epoch * cls.BLOCKS_PER_EPOCH)

    def start_new_round(self, current_block: int):
        """
        Initialize a new round.

        Args:
            current_block: The block when the round starts
        """
        if not self.can_start_round(current_block):
            blocks_remaining = self.blocks_until_allowed(current_block)
            next_block = (self.minimum_start_block + 1) if self.minimum_start_block is not None else None
            message = (
                f"Round start blocked. Current block {current_block} is not past minimum "
                f"{self.minimum_start_block}."
            )
            if next_block is not None:
                message += f" Next allowed block: {next_block} (≈{blocks_remaining} blocks remaining)."
            ColoredLogger.warning(message, ColoredLogger.YELLOW)
            raise RuntimeError("Round cannot start before minimum start block is reached")

        self.start_block = current_block
        self.reset_round()

        boundaries = self.get_round_boundaries(current_block)
        ColoredLogger.info("🔄 Starting new round", ColoredLogger.CYAN)
        ColoredLogger.info(f"   Start block: {current_block}", ColoredLogger.CYAN)
        ColoredLogger.info(f"   Target block: {boundaries['target_block']}", ColoredLogger.CYAN)
        ColoredLogger.info(f"   Round epoch: {boundaries['round_start_epoch']}", ColoredLogger.CYAN)
        ColoredLogger.info(f"   Target epoch: {boundaries['target_epoch']}", ColoredLogger.CYAN)

        # Calculate estimated duration
        blocks_remaining = boundaries['target_block'] - current_block
        estimated_minutes = (blocks_remaining * 12) / 60  # 12 seconds per block
        ColoredLogger.info(f"   Estimated duration: {estimated_minutes:.1f} min (~{blocks_remaining} blocks)", ColoredLogger.CYAN)

    def get_round_boundaries(self, current_block: int) -> Dict[str, Any]:
        """
        Calculate round boundaries for the given block.

        Returns:
            Dict with round_start_epoch, target_epoch, round_start_block, target_block
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
            'round_start_epoch': round_start_epoch,
            'target_epoch': target_epoch,
            'round_start_block': round_start_block,
            'target_block': target_block
        }

    def get_current_boundaries(self) -> Dict[str, Any]:
        """
        Get boundaries for the current round.

        Returns:
            Dict with round boundaries

        Raises:
            ValueError: If round not started
        """
        if self.start_block is None:
            raise ValueError("Round not started. Call start_new_round() first.")
        return self.get_round_boundaries(self.start_block)

    def should_send_next_task(self, current_block: int) -> bool:
        """
        Check if there's enough time to send another task.

        Args:
            current_block: Current block number

        Returns:
            True if there's enough time for another task

        Raises:
            ValueError: If round not started
        """
        if self.start_block is None:
            raise ValueError("Round not started. Call start_new_round() first.")

        boundaries = self.get_round_boundaries(self.start_block)
        total_round_blocks = self.round_size_epochs * self.BLOCKS_PER_EPOCH
        safety_buffer_blocks = self.safety_buffer_epochs * self.BLOCKS_PER_EPOCH
        absolute_limit_block = self.start_block + total_round_blocks - safety_buffer_blocks

        if current_block >= absolute_limit_block:
            return False

        blocks_until_limit = absolute_limit_block - current_block
        seconds_until_limit = blocks_until_limit * self.SECONDS_PER_BLOCK
        has_time = seconds_until_limit >= self.avg_task_duration_seconds

        return has_time

    def get_wait_info(self, current_block: int) -> Dict[str, Any]:
        """
        Get wait information for the current round.

        Args:
            current_block: Current block number

        Returns:
            Dict with current_epoch, target_epoch, blocks_remaining, etc.

        Raises:
            ValueError: If round not started
        """
        if self.start_block is None:
            raise ValueError("Round not started. Call start_new_round() first.")

        boundaries = self.get_round_boundaries(self.start_block)
        target_epoch = boundaries['target_epoch']
        current_epoch = self.block_to_epoch(current_block)

        blocks_remaining = boundaries['target_block'] - current_block
        seconds_remaining = blocks_remaining * self.SECONDS_PER_BLOCK
        minutes_remaining = seconds_remaining / 60

        return {
            'current_epoch': current_epoch,
            'target_epoch': target_epoch,
            'blocks_remaining': blocks_remaining,
            'seconds_remaining': seconds_remaining,
            'minutes_remaining': minutes_remaining,
            'reached_target': current_epoch >= target_epoch
        }

    def log_calculation_summary(self):
        """Log calculation summary for debugging."""
        ColoredLogger.info("📊 Round Manager Configuration:", ColoredLogger.CYAN)
        ColoredLogger.info(f"   Round size: {self.round_size_epochs} epochs", ColoredLogger.CYAN)
        ColoredLogger.info(f"   Safety buffer: {self.safety_buffer_epochs} epochs", ColoredLogger.CYAN)
        ColoredLogger.info(f"   Avg task duration: {self.avg_task_duration_seconds}s", ColoredLogger.CYAN)
        ColoredLogger.info(f"   Blocks per epoch: {self.BLOCKS_PER_EPOCH}", ColoredLogger.CYAN)
        ColoredLogger.info(f"   Seconds per block: {self.SECONDS_PER_BLOCK}s", ColoredLogger.CYAN)
        ColoredLogger.info(f"   Round block length: {self.ROUND_BLOCK_LENGTH}", ColoredLogger.CYAN)
        if self.minimum_start_block is not None:
            ColoredLogger.info(
                f"   Minimum start block: {self.minimum_start_block} (rounds allowed > this block)",
                ColoredLogger.CYAN,
            )

    def can_start_round(self, current_block: int) -> bool:
        """Return True when the chain height has passed the minimum start block gate."""
        if self.minimum_start_block is None:
            return True
        return current_block > self.minimum_start_block

    def blocks_until_allowed(self, current_block: int) -> int:
        """Return how many blocks remain before a new round may begin."""
        if self.minimum_start_block is None:
            return 0
        next_allowed_block = self.minimum_start_block + 1
        return max(next_allowed_block - current_block, 0)

    def calculate_round(self, current_block: int) -> int:
        """Return the human-visible round number based on days elapsed since launch block."""
        base_block = self.minimum_start_block or 0
        if current_block <= base_block:
            return 0

        blocks_since_start = current_block - base_block
        round_index = blocks_since_start // self.ROUND_BLOCK_LENGTH
        return int(round_index + 1)

    # ═══════════════════════════════════════════════════════════════════════════════
    # SCORE MANAGEMENT METHODS
    # ═══════════════════════════════════════════════════════════════════════════════

    def accumulate_rewards(self, miner_uids: List[int], rewards: List[float], eval_scores: List[float], execution_times: List[float]):
        """
        Accumulate scores for the round.

        Args:
            miner_uids: List of miner UIDs
            rewards: List of rewards for each miner
            execution_times: List of execution times for each miner
        """
        for i, uid in enumerate(miner_uids):
            if uid not in self.round_rewards:
                self.round_rewards[uid] = []
                self.round_eval_scores[uid] = []
                self.round_times[uid] = []

            self.round_rewards[uid].append(rewards[i])
            self.round_eval_scores[uid].append(eval_scores[i])
            self.round_times[uid].append(execution_times[i])

    def get_average_rewards(self) -> Dict[int, float]:
        """
        Calculate average scores for each miner.

        Returns:
            Dict mapping miner_uid to average score
        """
        avg_rewards = {}
        for uid, rewards in self.round_rewards.items():
            if rewards:
                avg_rewards[uid] = sum(rewards) / len(rewards)
            else:
                avg_rewards[uid] = 0.0
        return avg_rewards

    def get_round_stats(self) -> Dict[str, Any]:
        """
        Get round statistics.

        Returns:
            Dict with round statistics
        """
        total_miners = len(self.round_rewards)
        total_tasks = sum(len(reward) for reward in self.round_rewards.values())

        return {
            'total_miners': total_miners,
            'total_tasks': total_tasks,
            'miners_with_rewards': len([uid for uid, rewards in self.round_rewards.items() if rewards]),
            'round_rewards': self.round_rewards,
            'round_times': self.round_times,
            'round_eval_scores': self.round_eval_scores
        }

    def reset_round(self):
        """Reset round state for new round."""
        self.round_rewards = {}
        self.round_times = {}
        self.eval_scores = {}

    def log_round_summary(self):
        """Log round summary with statistics."""
        stats = self.get_round_stats()
        avg_rewards = self.get_average_rewards()

        ColoredLogger.info(f"Round stats: {stats['total_miners']} miners, {stats['total_tasks']} tasks", ColoredLogger.PURPLE)
        for uid, score in avg_rewards.items():
            ColoredLogger.info(f"  Miner {uid}: {score:.3f} (from {len(self.round_rewards[uid])} tasks)", ColoredLogger.PURPLE)
