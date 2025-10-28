from __future__ import annotations

from typing import Dict, Optional, Tuple

import bittensor as bt

from autoppia_web_agents_subnet.validator.consensus import (
    publish_round_snapshot,
    publish_scores_snapshot,
    aggregate_scores_from_commitments,
)


class ConsensusManager:
    """
    Shared consensus utilities for screening and final phases.
    """

    async def publish_midround(self, *, validator, tasks_completed: int) -> Optional[str]:
        """Publish a mid-round snapshot (screening) to IPFS + chain."""
        try:
            st = await validator._get_async_subtensor()
            round_number = await validator.round_manager.calculate_round(validator.block)
            return await publish_round_snapshot(
                validator=validator,
                st=st,
                round_number=round_number,
                tasks_completed=tasks_completed,
            )
        except Exception as e:
            bt.logging.warning(f"publish_midround failed: {e}")
            return None

    async def publish_final(self, *, validator, tasks_completed: int, scores: Dict[int, float]) -> Optional[str]:
        """Publish final scores snapshot to IPFS + chain."""
        try:
            st = await validator._get_async_subtensor()
            round_number = await validator.round_manager.calculate_round(validator.block)
            return await publish_scores_snapshot(
                validator=validator,
                st=st,
                round_number=round_number,
                tasks_completed=tasks_completed,
                scores=scores,
            )
        except Exception as e:
            bt.logging.warning(f"publish_final failed: {e}")
            return None

    async def aggregate_current_window(self, *, validator) -> Tuple[Dict[int, float], Dict]:
        """Aggregate scores from commitments for the current round window."""
        bounds = validator.round_manager.get_current_boundaries()
        st = await validator._get_async_subtensor()
        return await aggregate_scores_from_commitments(
            validator=validator,
            st=st,
            start_epoch=bounds["round_start_epoch"],
            target_epoch=bounds["target_epoch"],
        )

    async def aggregate_previous_window(self, *, validator) -> Tuple[Dict[int, float], Dict]:
        """Aggregate scores from commitments for the previous round window."""
        bounds = validator.round_manager.get_current_boundaries()
        prev_target_epoch = float(bounds["round_start_epoch"])  # end of previous
        round_len_epochs = float(validator.round_manager.round_size_epochs)
        prev_start_epoch = max(prev_target_epoch - round_len_epochs, 0.0)
        st = await validator._get_async_subtensor()
        return await aggregate_scores_from_commitments(
            validator=validator,
            st=st,
            start_epoch=prev_start_epoch,
            target_epoch=prev_target_epoch,
        )
