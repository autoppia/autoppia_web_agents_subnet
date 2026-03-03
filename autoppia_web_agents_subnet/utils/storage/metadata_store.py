"""
Evaluation metadata storage service.

Uploads structured evaluation data to S3 for building public datasets:
  - Steps input/output including browser state and screenshots
  - LLM requests from the gateway
  - Scores, times, costs of all evaluations and steps
  - Evaluation GIFs
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from autoppia_web_agents_subnet.utils.storage.base import BaseS3Client

logger = logging.getLogger(__name__)


class MetadataStore:
    """Uploads evaluation metadata to S3 in a structured layout.

    Bucket layout::

        s3://<bucket>/
        └── season_<N>/
            └── round_<R>/
                ├── round_metadata.json
                ├── evaluations/
                │   └── uid_<UID>/
                │       ├── evaluation_summary.json
                │       └── tasks/
                │           └── task_<ID>/
                │               ├── result.json
                │               ├── steps/
                │               │   ├── step_001.json
                │               │   └── step_001_screenshot.png
                │               └── recording.gif
                ├── llm_requests/
                │   └── request_<timestamp>.json
                └── consensus/
                    └── scores.json
    """

    def __init__(self, s3_client: BaseS3Client, bucket: str) -> None:
        self._s3 = s3_client
        self._bucket = bucket
        self._initialised = False

    def _ensure_bucket(self) -> None:
        if not self._initialised:
            try:
                self._s3.ensure_bucket(self._bucket)
                self._initialised = True
            except Exception as e:
                logger.warning(f"Failed to ensure S3 bucket {self._bucket}: {e}")

    def _prefix(self, season: int, round_num: int) -> str:
        return f"season_{season}/round_{round_num}"

    def upload_round_metadata(
        self,
        *,
        season: int,
        round_num: int,
        validator_uid: int,
        validator_hotkey: str,
        start_block: int,
        end_block: int,
        tasks_count: int,
        miners_evaluated: int,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Upload round-level metadata."""
        self._ensure_bucket()
        prefix = self._prefix(season, round_num)
        key = f"{prefix}/round_metadata.json"
        payload = {
            "season": season,
            "round": round_num,
            "validator_uid": validator_uid,
            "validator_hotkey": validator_hotkey,
            "start_block": start_block,
            "end_block": end_block,
            "tasks_count": tasks_count,
            "miners_evaluated": miners_evaluated,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(extra or {}),
        }
        try:
            return self._s3.upload_json(payload, bucket=self._bucket, key=key)
        except Exception as e:
            logger.error(f"Failed to upload round metadata: {e}")
            return None

    def upload_evaluation_summary(
        self,
        *,
        season: int,
        round_num: int,
        miner_uid: int,
        miner_hotkey: str,
        score: float,
        tasks_completed: int,
        total_time_seconds: float,
        total_cost_usd: float,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Upload evaluation summary for a single miner."""
        self._ensure_bucket()
        prefix = self._prefix(season, round_num)
        key = f"{prefix}/evaluations/uid_{miner_uid}/evaluation_summary.json"
        payload = {
            "miner_uid": miner_uid,
            "miner_hotkey": miner_hotkey,
            "score": score,
            "tasks_completed": tasks_completed,
            "total_time_seconds": total_time_seconds,
            "total_cost_usd": total_cost_usd,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(extra or {}),
        }
        try:
            return self._s3.upload_json(payload, bucket=self._bucket, key=key)
        except Exception as e:
            logger.error(f"Failed to upload evaluation summary for UID {miner_uid}: {e}")
            return None

    def upload_task_result(
        self,
        *,
        season: int,
        round_num: int,
        miner_uid: int,
        task_id: str,
        result: Dict[str, Any],
    ) -> Optional[str]:
        """Upload the result of a single task evaluation."""
        self._ensure_bucket()
        prefix = self._prefix(season, round_num)
        key = f"{prefix}/evaluations/uid_{miner_uid}/tasks/task_{task_id}/result.json"
        payload = {
            "task_id": task_id,
            "miner_uid": miner_uid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **result,
        }
        try:
            return self._s3.upload_json(payload, bucket=self._bucket, key=key)
        except Exception as e:
            logger.error(f"Failed to upload task result for UID {miner_uid} task {task_id}: {e}")
            return None

    def upload_step_data(
        self,
        *,
        season: int,
        round_num: int,
        miner_uid: int,
        task_id: str,
        step_number: int,
        step_data: Dict[str, Any],
    ) -> Optional[str]:
        """Upload input/output data for a single step."""
        self._ensure_bucket()
        prefix = self._prefix(season, round_num)
        key = f"{prefix}/evaluations/uid_{miner_uid}/tasks/task_{task_id}/steps/step_{step_number:03d}.json"
        payload = {
            "step_number": step_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **step_data,
        }
        try:
            return self._s3.upload_json(payload, bucket=self._bucket, key=key)
        except Exception as e:
            logger.error(f"Failed to upload step {step_number} data: {e}")
            return None

    def upload_screenshot(
        self,
        *,
        season: int,
        round_num: int,
        miner_uid: int,
        task_id: str,
        step_number: int,
        screenshot_bytes: bytes,
        fmt: str = "png",
    ) -> Optional[str]:
        """Upload a browser screenshot for a step."""
        self._ensure_bucket()
        prefix = self._prefix(season, round_num)
        key = f"{prefix}/evaluations/uid_{miner_uid}/tasks/task_{task_id}/steps/step_{step_number:03d}_screenshot.{fmt}"
        content_type = f"image/{fmt}"
        try:
            return self._s3.upload_bytes(
                screenshot_bytes,
                bucket=self._bucket,
                key=key,
                content_type=content_type,
            )
        except Exception as e:
            logger.error(f"Failed to upload screenshot for step {step_number}: {e}")
            return None

    def upload_evaluation_gif(
        self,
        *,
        season: int,
        round_num: int,
        miner_uid: int,
        task_id: str,
        gif_bytes: bytes,
    ) -> Optional[str]:
        """Upload an evaluation recording GIF."""
        self._ensure_bucket()
        prefix = self._prefix(season, round_num)
        key = f"{prefix}/evaluations/uid_{miner_uid}/tasks/task_{task_id}/recording.gif"
        try:
            return self._s3.upload_bytes(
                gif_bytes,
                bucket=self._bucket,
                key=key,
                content_type="image/gif",
            )
        except Exception as e:
            logger.error(f"Failed to upload evaluation GIF: {e}")
            return None

    def upload_llm_request(
        self,
        *,
        season: int,
        round_num: int,
        request_data: Dict[str, Any],
    ) -> Optional[str]:
        """Upload an LLM gateway request/response record."""
        self._ensure_bucket()
        prefix = self._prefix(season, round_num)
        ts = int(time.time() * 1000)
        key = f"{prefix}/llm_requests/request_{ts}.json"
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **request_data,
        }
        try:
            return self._s3.upload_json(payload, bucket=self._bucket, key=key)
        except Exception as e:
            logger.error(f"Failed to upload LLM request: {e}")
            return None

    def upload_consensus_scores(
        self,
        *,
        season: int,
        round_num: int,
        scores: Dict[int, float],
        validator_uid: int,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Upload final consensus scores for the round."""
        self._ensure_bucket()
        prefix = self._prefix(season, round_num)
        key = f"{prefix}/consensus/scores.json"
        payload = {
            "season": season,
            "round": round_num,
            "validator_uid": validator_uid,
            "scores": {str(uid): score for uid, score in scores.items()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(extra or {}),
        }
        try:
            return self._s3.upload_json(payload, bucket=self._bucket, key=key)
        except Exception as e:
            logger.error(f"Failed to upload consensus scores: {e}")
            return None


# Module-level convenience: lazily-initialised singleton
_metadata_store: Optional[MetadataStore] = None


def get_metadata_store() -> Optional[MetadataStore]:
    """Return the metadata store singleton, or None if S3 uploads are disabled."""
    global _metadata_store
    if _metadata_store is not None:
        return _metadata_store

    from autoppia_web_agents_subnet.validator.config import (
        S3_METADATA_UPLOAD_ENABLED,
        S3_METADATA_BUCKET,
    )
    if not S3_METADATA_UPLOAD_ENABLED:
        return None

    from autoppia_web_agents_subnet.utils.storage import get_s3_client
    _metadata_store = MetadataStore(
        s3_client=get_s3_client(),
        bucket=S3_METADATA_BUCKET,
    )
    return _metadata_store
