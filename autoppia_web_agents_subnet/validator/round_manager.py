# autoppia_web_agents_subnet/validator/round_manager.py
from __future__ import annotations
import bittensor as bt
from typing import Dict, Any, List
import numpy as np


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

    def __init__(
        self,
        round_size_epochs: float,
        avg_task_duration_seconds: float,
        safety_buffer_epochs: float,
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
        self.start_block = current_block
        self.reset_round()

        boundaries = self.get_round_boundaries(current_block)
        bt.logging.info("🔄 Starting new round")
        bt.logging.info(f"   Start block: {current_block}")
        bt.logging.info(f"   Round epoch: {boundaries['round_start_epoch']}")
        bt.logging.info(f"   Target epoch: {boundaries['target_epoch']}")

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
        bt.logging.info("📊 Round Manager Configuration:")
        bt.logging.info(f"   Round size: {self.round_size_epochs} epochs")
        bt.logging.info(f"   Safety buffer: {self.safety_buffer_epochs} epochs")
        bt.logging.info(f"   Avg task duration: {self.avg_task_duration_seconds}s")
        bt.logging.info(f"   Blocks per epoch: {self.BLOCKS_PER_EPOCH}")
        bt.logging.info(f"   Seconds per block: {self.SECONDS_PER_BLOCK}s")

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

        bt.logging.info(f"Round stats: {stats['total_miners']} miners, {stats['total_tasks']} tasks")
        for uid, score in avg_rewards.items():
            bt.logging.info(f"  Miner {uid}: {score:.3f} (from {len(self.round_rewards[uid])} tasks)")
