from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
import uuid
from typing import Dict, Iterable, List, Optional

import httpx

from . import models

logger = logging.getLogger(__name__)


def _uuid_suffix(length: int = 12) -> str:
    return uuid.uuid4().hex[:length]


def generate_validator_round_id() -> str:
    return f"validator_round_{_uuid_suffix()}"


def generate_agent_run_id(miner_uid: Optional[int]) -> str:
    suffix = _uuid_suffix()
    prefix = f"agent_run_{miner_uid}_" if miner_uid is not None else "agent_run_"
    return f"{prefix}{suffix}"


def generate_evaluation_id(task_id: str, miner_uid: Optional[int]) -> str:
    suffix = _uuid_suffix()
    miner_part = f"{miner_uid}_" if miner_uid is not None else ""
    return f"evaluation_{miner_part}{task_id}_{suffix}"


def generate_task_solution_id(task_id: str, miner_uid: Optional[int]) -> str:
    suffix = _uuid_suffix()
    miner_part = f"{miner_uid}_" if miner_uid is not None else ""
    return f"task_solution_{miner_part}{task_id}_{suffix}"


class IWAPClient:
    """
    HTTP client used to push progressive round data to the dashboard backend.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = 30.0,
        client: Optional[httpx.AsyncClient] = None,
        backup_dir: Optional[Path] = None,
    ) -> None:
        resolved_base_url = base_url or os.getenv("IWAP_API_BASE_URL", "http://217.154.10.168:8000")
        self._client = client or httpx.AsyncClient(base_url=resolved_base_url.rstrip("/"), timeout=timeout)
        self._owns_client = client is None
        self._backup_dir = Path(backup_dir or os.getenv("IWAP_BACKUP_DIR", "iwap_payloads"))
        try:
            self._backup_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.warning("Unable to create IWAP backup directory at %s", self._backup_dir, exc_info=True)
            self._backup_dir = None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def start_round(
        self,
        *,
        validator_identity: models.ValidatorIdentityIWAP,
        validator_round: models.ValidatorRoundIWAP,
        validator_snapshot: models.ValidatorSnapshotIWAP,
    ) -> None:
        payload = {
            "validator_identity": validator_identity.to_payload(),
            "validator_round": validator_round.to_payload(),
            "validator_snapshot": validator_snapshot.to_payload(),
        }
        logger.info(
            "IWAP start_round prepared for validator_round_id=%s round_number=%s",
            validator_round.validator_round_id,
            validator_round.round_number,
        )
        await self._post("/api/v1/validator-rounds/start", payload, context="start_round")

    async def set_tasks(
        self,
        *,
        validator_round_id: str,
        tasks: Iterable[models.TaskIWAP],
    ) -> None:
        task_payloads = [task.to_payload() for task in tasks]
        payload = {"tasks": task_payloads}
        logger.info(
            "IWAP set_tasks prepared for validator_round_id=%s tasks=%s",
            validator_round_id,
            len(task_payloads),
        )
        await self._post(f"/api/v1/validator-rounds/{validator_round_id}/tasks", payload, context="set_tasks")

    async def start_agent_run(
        self,
        *,
        validator_round_id: str,
        agent_run: models.AgentRunIWAP,
        miner_identity: models.MinerIdentityIWAP,
        miner_snapshot: models.MinerSnapshotIWAP,
    ) -> None:
        payload = {
            "agent_run": agent_run.to_payload(),
            "miner_identity": miner_identity.to_payload(),
            "miner_snapshot": miner_snapshot.to_payload(),
        }
        logger.info(
            "IWAP start_agent_run prepared for validator_round_id=%s agent_run_id=%s miner_uid=%s",
            validator_round_id,
            agent_run.agent_run_id,
            miner_identity.uid,
        )
        await self._post(
            f"/api/v1/validator-rounds/{validator_round_id}/agent-runs/start",
            payload,
            context="start_agent_run",
        )

    async def add_evaluation(
        self,
        *,
        validator_round_id: str,
        agent_run_id: str,
        task: models.TaskIWAP,
        task_solution: models.TaskSolutionIWAP,
        evaluation_result: models.EvaluationResultIWAP,
    ) -> None:
        """
        Submit a TaskSolution + EvaluationResult bundle for persistence.
        """
        payload = {
            "task": task.to_payload(),
            "task_solution": task_solution.to_payload(),
            "evaluation": {
                # Minimal evaluation stub for backward compatibility.
                "evaluation_id": evaluation_result.evaluation_id,
                "validator_round_id": evaluation_result.validator_round_id,
                "task_id": evaluation_result.task_id,
                "task_solution_id": evaluation_result.task_solution_id,
                "agent_run_id": evaluation_result.agent_run_id,
                "validator_uid": evaluation_result.validator_uid,
                "validator_hotkey": task_solution.validator_hotkey,
                "miner_uid": evaluation_result.miner_uid,
                "miner_hotkey": task_solution.miner_hotkey,
                "miner_agent_key": task_solution.miner_agent_key,
                "final_score": evaluation_result.final_score,
                "raw_score": evaluation_result.raw_score or evaluation_result.final_score,
                "evaluation_time": evaluation_result.evaluation_time,
                "summary": evaluation_result.metadata or {},
            },
            "evaluation_result": evaluation_result.to_payload(),
        }
        logger.info(
            "IWAP add_evaluation prepared for validator_round_id=%s agent_run_id=%s task_solution_id=%s",
            validator_round_id,
            agent_run_id,
            task_solution.solution_id,
        )
        await self._post(
            f"/api/v1/validator-rounds/{validator_round_id}/agent-runs/{agent_run_id}/evaluations",
            payload,
            context="add_evaluation",
        )

    async def finish_round(
        self,
        *,
        validator_round_id: str,
        finish_request: models.FinishRoundIWAP,
    ) -> None:
        logger.info(
            "IWAP finish_round prepared for validator_round_id=%s summary=%s",
            validator_round_id,
            finish_request.summary,
        )
        await self._post(
            f"/api/v1/validator-rounds/{validator_round_id}/finish",
            finish_request.to_payload(),
            context="finish_round",
        )

    async def _post(self, path: str, payload: Dict[str, object], *, context: str) -> None:
        self._backup_payload(context, payload)
        try:
            logger.info("IWAP %s POST %s started", context, path)
            response = await self._client.post(path, json=payload)
            response.raise_for_status()
            logger.info(
                "IWAP %s POST %s succeeded with status %s",
                context,
                path,
                response.status_code,
            )
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            logger.error("IWAP %s failed (%s): %s", context, exc.response.status_code, body)
            raise
        except Exception:
            logger.exception("IWAP %s failed unexpectedly", context)
            raise

    def _backup_payload(self, context: str, payload: Dict[str, object]) -> None:
        if not self._backup_dir:
            return
        timestamp = datetime.utcnow().isoformat().replace(":", "-")
        filename = f"{timestamp}_{context}.json"
        target = self._backup_dir / filename
        try:
            with target.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except Exception:
            logger.warning("Failed to persist IWAP backup payload at %s", target, exc_info=True)


def build_miner_identity(
    *,
    miner_uid: Optional[int],
    miner_hotkey: Optional[str],
    miner_coldkey: Optional[str] = None,
    agent_key: Optional[str] = None,
) -> models.MinerIdentityIWAP:
    return models.MinerIdentityIWAP(
        uid=miner_uid,
        hotkey=miner_hotkey,
        coldkey=miner_coldkey,
        agent_key=agent_key,
    )


def build_miner_snapshot(
    *,
    validator_round_id: str,
    miner_uid: Optional[int],
    miner_hotkey: Optional[str],
    miner_coldkey: Optional[str],
    agent_key: Optional[str],
    handshake_payload: Optional[object],
    now_ts: float,
) -> models.MinerSnapshotIWAP:
    """
    Create a MinerSnapshotIWAP from handshake data.
    """
    agent_name = getattr(handshake_payload, "agent_name", None) or (
        f"Miner {miner_uid}" if miner_uid is not None else "Benchmark Agent"
    )
    image_url = getattr(handshake_payload, "agent_image", None)
    github_url = getattr(handshake_payload, "github_url", None)
    description = getattr(handshake_payload, "agent_version", None)

    return models.MinerSnapshotIWAP(
        validator_round_id=validator_round_id,
        miner_uid=miner_uid,
        miner_hotkey=miner_hotkey,
        miner_coldkey=miner_coldkey,
        agent_key=agent_key,
        agent_name=agent_name,
        image_url=image_url,
        github_url=github_url,
        description=description,
        is_sota=agent_key is not None and miner_uid is None,
        first_seen_at=now_ts,
        last_seen_at=now_ts,
    )
