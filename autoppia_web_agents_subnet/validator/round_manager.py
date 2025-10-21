# autoppia_web_agents_subnet/validator/round_manager.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.config import IWAP_API_BASE_URL, TESTING


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

        # Calculate round block length based on round_size_epochs (not hardcoded)
        self.ROUND_BLOCK_LENGTH = int(self.BLOCKS_PER_EPOCH * self.round_size_epochs)

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

        🌐 GLOBAL SYNCHRONIZATION:
        This method ensures ALL validators synchronize to the same epoch boundaries,
        regardless of when they start. The round boundaries are calculated from
        ABSOLUTE EPOCH MULTIPLES, not from each validator's start time.

        Example with ROUND_SIZE_EPOCHS = 20:
            Validator A starts at epoch 18,640.0 → Round ends at 18,660
            Validator B starts at epoch 18,642.5 (2.5 epochs late) → Round STILL ends at 18,660
            Validator C starts at epoch 18,655.0 (15 epochs late) → Round STILL ends at 18,660

        All validators set weights at the SAME TIME (epoch 18,660), ensuring fair competition.

        Returns:
            Dict with round_start_epoch, target_epoch, round_start_block, target_block
        """
        import bittensor as bt

        current_epoch = self.block_to_epoch(current_block)

        # 🔑 KEY: Calculate round start as GLOBAL epoch multiple (not relative to start)
        # This ensures all validators synchronize to the same epoch boundaries
        round_start_epoch = (current_epoch // self.round_size_epochs) * self.round_size_epochs

        # Target epoch is the end of the round (GLOBAL deadline for ALL validators)
        target_epoch = round_start_epoch + self.round_size_epochs

        # Convert to blocks
        round_start_block = self.epoch_to_block(round_start_epoch)
        target_block = self.epoch_to_block(target_epoch)

        # 🔍 CRITICAL DEBUG: Verify global sync calculations
        bt.logging.info("=" * 80)
        bt.logging.info("🌐 GLOBAL SYNC CALCULATION (Modulo-based)")
        bt.logging.info("=" * 80)
        bt.logging.info(f"📍 Current block:      {current_block:,}")
        bt.logging.info(f"📍 Current epoch:      {current_epoch:.4f}")
        bt.logging.info("")
        bt.logging.info(f"🔢 ROUND_SIZE_EPOCHS:  {self.round_size_epochs}")
        bt.logging.info(f"🔢 Modulo calculation: ({current_epoch:.4f} // {self.round_size_epochs}) × {self.round_size_epochs}")
        bt.logging.info(f"🔢 Result:             {current_epoch // self.round_size_epochs:.0f} × {self.round_size_epochs} = {round_start_epoch:.4f}")
        bt.logging.info("")
        bt.logging.info(f"🎯 Round start epoch:  {round_start_epoch:.4f} (Block {round_start_block:,})")
        bt.logging.info(f"🎯 Round end epoch:    {target_epoch:.4f} (Block {target_block:,})")
        bt.logging.info(f"⏱️  Round duration:     {target_epoch - round_start_epoch:.2f} epochs ({(target_block - round_start_block):,} blocks)")
        bt.logging.info("")
        bt.logging.info(f"✅ ALL validators will end at epoch {target_epoch:.4f} regardless of start time")
        bt.logging.info("=" * 80)

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
        if TESTING:
            return True
        if self.minimum_start_block is None:
            return True
        return current_block > self.minimum_start_block

    def blocks_until_allowed(self, current_block: int) -> int:
        """Return how many blocks remain before a new round may begin."""
        if self.minimum_start_block is None:
            return 0
        next_allowed_block = self.minimum_start_block + 1
        return max(next_allowed_block - current_block, 0)

    async def calculate_round(self, current_block: int) -> int:
        """Return the human-visible round number based on days elapsed since launch block."""
        if TESTING:
            testing_round = await self._calculate_round_from_backend()
            if testing_round is not None:
                return testing_round

        base_block = self.minimum_start_block or 0
        if current_block <= base_block:
            return 0

        blocks_since_start = current_block - base_block
        round_index = blocks_since_start // self.ROUND_BLOCK_LENGTH
        return int(round_index + 1)

    async def _calculate_round_from_backend(self) -> Optional[int]:
        """Use the dashboard rounds endpoint to derive the next round number when testing."""
        base_url = (IWAP_API_BASE_URL or "").rstrip("/")
        if not base_url:
            return None

        url = f"{base_url}/api/v1/rounds"
        params = {
            "limit": 1,
            "page": 1,
            "sortBy": "round",
            "sortOrder": "desc",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            ColoredLogger.warning(
                f"Unable to fetch rounds from backend ({url}): {exc}",
                ColoredLogger.YELLOW,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            ColoredLogger.warning(
                f"Unexpected error when fetching rounds from backend ({url}): {exc}",
                ColoredLogger.YELLOW,
            )
            return None

        try:
            payload = response.json()
        except ValueError:
            ColoredLogger.warning(
                f"Received non-JSON response from backend rounds endpoint ({url})",
                ColoredLogger.YELLOW,
            )
            return None

        entries = self._extract_round_entries(payload)
        if not entries:
            # No prior rounds recorded; start from first round.
            return 1

        latest_entry = entries[0]
        round_value = self._extract_round_value(latest_entry)
        if round_value is None:
            return None
        return round_value + 1

    @staticmethod
    def _extract_round_entries(payload: Any) -> List[Dict[str, Any]]:
        """Normalize rounds API responses into a list of round dictionaries."""
        def _coerce(obj: Any) -> List[Dict[str, Any]]:
            if isinstance(obj, list):
                return [item for item in obj if isinstance(item, dict)]
            if isinstance(obj, dict):
                candidates = []
                for key in ("rounds", "data", "entries"):
                    if key in obj:
                        nested = _coerce(obj[key])
                        if nested:
                            candidates.extend(nested)
                if candidates:
                    return candidates
                # No known keys – treat the dict itself as a single entry if it looks like one.
                if {"round", "roundNumber", "round_number", "id"}.intersection(obj.keys()):
                    return [obj]
            return []

        extracted = _coerce(payload)
        return extracted

    @staticmethod
    def _extract_round_value(entry: Dict[str, Any]) -> Optional[int]:
        """Attempt to pull an integer round number from a round entry."""
        for key in ("round", "roundNumber", "round_number", "id"):
            value = entry.get(key)
            if isinstance(value, bool):  # Avoid treating booleans as integers
                continue
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                digits = "".join(ch for ch in value if ch.isdigit())
                if digits:
                    try:
                        return int(digits)
                    except ValueError:
                        continue
        return None

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
