# autoppia_web_agents_subnet/validator/leaderboard/leaderboard_sender.py
from __future__ import annotations

from typing import Any, Dict

import bittensor as bt

from .api_client import LeaderboardAPI
from .data_processor import DataProcessor


class LeaderboardSender:
    """
    Main leaderboard integration class.
    Orchestrates data preparation and results building for leaderboard posting.
    """

    def __init__(self):
        self.api_client = LeaderboardAPI()  # HTTP client
        self.data_processor = DataProcessor()  # Data processing

    def post_round_results(
        self,
        validator,
        start_block: int,
        tasks_completed: int,
        avg_scores: Dict[int, float],
        final_weights: Dict[int, float],
        round_manager,
    ) -> None:
        """
        Post round results to leaderboard API.
        This is the main entry point for leaderboard integration.
        """
        try:
            # 1. Prepare round data
            round_data = self.data_processor.prepare_round_data(
                validator=validator,
                start_block=start_block,
                tasks_completed=tasks_completed,
                avg_scores=avg_scores,
                final_weights=final_weights,
                round_manager=round_manager,
            )

            # 2. Build round results
            round_results = self.data_processor.build_round_results(
                validator=validator,
                round_data=round_data,
            )

            # 3. Post to leaderboard API
            self._post_to_api(round_results)

        except Exception as e:
            bt.logging.warning(f"Leaderboard posting failed: {e}")

    def _post_to_api(self, round_results) -> None:
        """Post results to leaderboard API"""
        self.api_client.post_round_results(round_results, background=True)
