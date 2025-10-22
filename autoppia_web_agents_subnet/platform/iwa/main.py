from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time as dtime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import httpx
import bittensor as bt

from autoppia_web_agents_subnet.validator.config import MAX_AGENT_NAME_LENGTH

from . import models

logger = logging.getLogger(__name__)

VALIDATOR_HOTKEY_HEADER = "x-validator-hotkey"
VALIDATOR_SIGNATURE_HEADER = "x-validator-signature"


def _uuid_suffix(length: int = 12) -> str:
    return uuid.uuid4().hex[:length]


def generate_validator_round_id(round_number: Optional[int] = None) -> str:
    """
    Generate a unique validator round ID.

    Args:
        round_number: Optional round number to include in the ID (e.g., 1, 2, 3...)

    Returns:
        Round ID in format: validator_round_{number}_{random_id} or validator_round_{random_id}
    """
    if round_number is not None:
        return f"validator_round_{round_number}_{_uuid_suffix()}"
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
        auth_provider: Optional[Callable[[], Dict[str, str]]] = None,
    ) -> None:
        resolved_base_url = (base_url or os.getenv("IWAP_API_BASE_URL", "http://217.154.10.168:8080")).rstrip("/")
        self._client = client or httpx.AsyncClient(base_url=resolved_base_url, timeout=timeout)
        self._owns_client = client is None
        self._backup_dir = Path(backup_dir or os.getenv("IWAP_BACKUP_DIR", "iwap_bakcup_dir"))
        self._auth_provider = auth_provider
        logger.info("IWAP client initialized with base_url=%s", self._client.base_url)
        try:
            self._backup_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.warning("Unable to create IWAP backup directory at %s", self._backup_dir, exc_info=True)
            self._backup_dir = None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def set_auth_provider(self, provider: Optional[Callable[[], Dict[str, str]]]) -> None:
        self._auth_provider = provider

    def _resolve_auth_headers(self) -> Dict[str, str]:
        if not self._auth_provider:
            return {}
        try:
            headers = dict(self._auth_provider())
        except Exception:
            logger.exception("IWAP auth provider failed to generate headers")
            raise
        sanitized: Dict[str, str] = {}
        for key, value in headers.items():
            if value is None:
                continue
            sanitized[str(key)] = str(value)
        return sanitized

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
        # Prepare JSON data (without GIF)
        json_data = {
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

        # Prepare files (GIF as binary)
        files = {}
        if evaluation_result.gif_recording:
            try:
                # Convert base64 GIF to binary
                import base64
                gif_binary = base64.b64decode(evaluation_result.gif_recording)
                files["gif_recording"] = gif_binary
                logger.info(f"🎬 GIF prepared for multipart: {len(gif_binary)} bytes")
            except Exception as e:
                logger.warning(f"⚠️  Failed to decode GIF for multipart: {e}")

        # 🔍 DEBUG: Log complete payload before sending
        bt.logging.info("=" * 80)
        bt.logging.info("📤 COMPLETE PAYLOAD BEFORE SENDING TO API")
        bt.logging.info("=" * 80)
        bt.logging.info(f"📍 Endpoint: POST /api/v1/validator-rounds/{validator_round_id}/agent-runs/{agent_run_id}/evaluations")
        bt.logging.info("")
        bt.logging.info("📄 FULL JSON PAYLOAD:")
        try:
            payload_str = json.dumps(_sanitize_json(json_data), indent=2, ensure_ascii=False)
        except Exception:
            # Last-resort fallback to avoid crashing logging on non-serializable objects
            payload_str = json.dumps({"error": "non-serializable-payload"})
        for line in payload_str.split('\n'):
            bt.logging.info(line)
        bt.logging.info("")
        if files:
            bt.logging.info("📁 MULTIPART FILES:")
            for key, file_data in files.items():
                bt.logging.info(f"   - {key}: {len(file_data)} bytes (binary GIF)")
        bt.logging.info("=" * 80)

        logger.info(
            "IWAP add_evaluation prepared for validator_round_id=%s agent_run_id=%s task_solution_id=%s",
            validator_round_id,
            agent_run_id,
            task_solution.solution_id,
        )

        # Use multipart if we have files, otherwise use regular JSON
        if files:
            await self._post_multipart(
                f"/api/v1/validator-rounds/{validator_round_id}/agent-runs/{agent_run_id}/evaluations",
                json_data,
                files,
                context="add_evaluation",
            )
        else:
            await self._post(
                f"/api/v1/validator-rounds/{validator_round_id}/agent-runs/{agent_run_id}/evaluations",
                json_data,
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

    async def auth_check(self) -> None:
        logger.info("IWAP auth_check prepared")
        await self._post("/api/v1/validator-rounds/auth-check", {}, context="auth_check")

    async def upload_evaluation_gif(self, evaluation_id: str, gif_bytes: bytes) -> Optional[str]:
        if not gif_bytes:
            raise ValueError("GIF payload is empty")

        path = f"/api/v1/evaluations/{evaluation_id}/gif"
        filename = f"{evaluation_id}.gif"
        logger.info(
            "🎬 IWAP: Uploading GIF to API - evaluation_id=%s filename=%s payload_bytes=%s",
            evaluation_id,
            filename,
            len(gif_bytes),
        )

        try:
            response = await self._client.post(
                path,
                files={"gif": (filename, gif_bytes, "image/gif")},
            )
            response.raise_for_status()
            logger.info(f"🎬 IWAP: GIF upload request successful - status_code={response.status_code}")
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            logger.error(
                "❌ IWAP: GIF upload failed - POST %s returned %s: %s",
                path,
                exc.response.status_code,
                body,
            )
            raise
        except Exception as e:
            logger.exception(f"❌ IWAP: GIF upload failed unexpectedly - POST {path}: {str(e)}")
            raise

        try:
            payload = response.json()
            logger.info(f"🎬 IWAP: GIF upload response payload: {payload}")
        except Exception as e:
            logger.warning(f"⚠️  IWAP: Received non-JSON response for evaluation_id={evaluation_id}: {str(e)}")
            return None

        gif_url = None
        if isinstance(payload, dict):
            data_section = payload.get("data")
            if isinstance(data_section, dict):
                gif_url = data_section.get("gifUrl")
                logger.info(f"🎬 IWAP: Extracted GIF URL from response: {gif_url}")

        if gif_url:
            logger.info(f"✅ IWAP: GIF upload completed successfully - URL: {gif_url}")
        else:
            logger.warning(f"⚠️  IWAP: GIF upload completed but no URL returned for evaluation_id={evaluation_id}")
        return gif_url

    async def _post(self, path: str, payload: Dict[str, object], *, context: str) -> None:
        sanitized_payload = _sanitize_json(payload)
        self._backup_payload(context, sanitized_payload)
        request = self._client.build_request("POST", path, json=sanitized_payload)
        auth_headers = self._resolve_auth_headers()
        if auth_headers:
            request.headers.update(auth_headers)
        target_url = str(request.url)

        # 🔍 DEBUG: Log HTTP request details
        logger.info("🌐 HTTP REQUEST DETAILS:")
        logger.info(f"   Method: POST")
        logger.info(f"   URL: {target_url}")
        logger.info(f"   Context: {context}")
        logger.info(f"   Headers: {dict(request.headers)}")
        try:
            logger.info(f"   Payload keys: {list(sanitized_payload.keys())}")
            logger.info(f"   Payload size: {len(str(sanitized_payload))} chars")
        except Exception:
            logger.info("   Payload: <unprintable>")

        try:
            logger.info("IWAP %s POST %s started", context, target_url)
            response = await self._client.send(request)
            response.raise_for_status()
            logger.info(
                "IWAP %s POST %s succeeded with status %s",
                context,
                target_url,
                response.status_code,
            )
            # 🔍 DEBUG: Log response details
            logger.info(f"   Response status: {response.status_code}")
            logger.info(f"   Response headers: {dict(response.headers)}")
            if response.text:
                logger.info(f"   Response body (first 500 chars): {response.text[:500]}")
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            logger.error("IWAP %s POST %s failed (%s): %s", context, target_url, exc.response.status_code, body)
            raise
        except Exception:
            logger.exception("IWAP %s POST %s failed unexpectedly", context, target_url)
            raise

    async def _post_multipart(self, path: str, data: Dict[str, Any], files: Dict[str, bytes], *, context: str) -> None:
        """
        Send multipart/form-data request with JSON data and binary files.
        """
        import io

        # Create multipart form data
        boundary = "----formdata-autoppia-iwap"
        body_parts = []

        # Add JSON data fields
        sanitized_data = _sanitize_json(data)
        for key, value in sanitized_data.items():
            body_parts.append(f"--{boundary}")
            body_parts.append(f"Content-Disposition: form-data; name=\"{key}\"")
            body_parts.append("Content-Type: application/json")
            body_parts.append("")
            body_parts.append(json.dumps(value))
            body_parts.append("")

        # Add binary files
        for key, file_data in files.items():
            body_parts.append(f"--{boundary}")
            body_parts.append(f"Content-Disposition: form-data; name=\"{key}\"; filename=\"{key}.gif\"")
            body_parts.append("Content-Type: image/gif")
            body_parts.append("")
            # Add binary data
            body_parts.append(file_data)
            body_parts.append("")

        # Close boundary
        body_parts.append(f"--{boundary}--")

        # Join all parts
        body = b"\r\n".join([
            part.encode('utf-8') if isinstance(part, str) else part 
            for part in body_parts
        ])

        # Build request
        request = self._client.build_request("POST", path, content=body)
        request.headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

        auth_headers = self._resolve_auth_headers()
        if auth_headers:
            request.headers.update(auth_headers)

        target_url = str(request.url)

        # 🔍 DEBUG: Log multipart request details
        logger.info("🌐 MULTIPART REQUEST DETAILS:")
        logger.info(f"   Method: POST")
        logger.info(f"   URL: {target_url}")
        logger.info(f"   Context: {context}")
        logger.info(f"   Content-Type: multipart/form-data; boundary={boundary}")
        logger.info(f"   Data fields: {list(sanitized_data.keys())}")
        logger.info(f"   File fields: {list(files.keys())}")
        logger.info(f"   Total body size: {len(body)} bytes")
        for key, file_data in files.items():
            logger.info(f"   File {key}: {len(file_data)} bytes")

        try:
            logger.info("IWAP %s POST %s started (multipart)", context, target_url)
            response = await self._client.send(request)
            response.raise_for_status()
            logger.info(
                "IWAP %s POST %s succeeded with status %s",
                context,
                target_url,
                response.status_code,
            )
            # 🔍 DEBUG: Log response details
            logger.info(f"   Response status: {response.status_code}")
            logger.info(f"   Response headers: {dict(response.headers)}")
            if response.text:
                logger.info(f"   Response body (first 500 chars): {response.text[:500]}")
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            logger.error("IWAP %s POST %s failed (%s): %s", context, target_url, exc.response.status_code, body)
            raise
        except Exception:
            logger.exception("IWAP %s POST %s failed unexpectedly", context, target_url)
            raise

    def _backup_payload(self, context: str, payload: Dict[str, object]) -> None:
        if not self._backup_dir:
            return
        timestamp = datetime.utcnow().isoformat().replace(":", "-")
        filename = f"{timestamp}_{context}.json"
        target = self._backup_dir / filename
        try:
            with target.open("w", encoding="utf-8") as fh:
                json.dump(_sanitize_json(payload), fh, ensure_ascii=False, indent=2)
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


def _normalized_optional(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
    raw_name = getattr(handshake_payload, "agent_name", None)
    if raw_name is None or not str(raw_name).strip():
        agent_name = "Benchmark Agent" if miner_uid is None else "Unknown"
    else:
        agent_name = str(raw_name).strip()

    if MAX_AGENT_NAME_LENGTH and len(agent_name) > MAX_AGENT_NAME_LENGTH:
        agent_name = agent_name[:MAX_AGENT_NAME_LENGTH]

    image_url = _normalized_optional(getattr(handshake_payload, "agent_image", None))
    github_url = _normalized_optional(getattr(handshake_payload, "github_url", None))
    description = _normalized_optional(getattr(handshake_payload, "agent_version", None))

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


def _sanitize_json(obj: Any) -> Any:
    """
    Recursively convert complex Python objects into JSON-serializable forms.

    - datetime/date/time -> ISO strings
    - Enum -> value (or name if value not serializable)
    - bytes/bytearray -> base64 text
    - set/tuple -> list
    - dataclasses -> asdict
    - pydantic models -> model_dump(mode="json", exclude_none=True)
    - objects with __dict__ -> dict of public attrs
    """
    from base64 import b64encode

    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, (datetime, date, dtime)):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)

    if isinstance(obj, Enum):
        try:
            return _sanitize_json(obj.value)
        except Exception:
            return obj.name

    if isinstance(obj, (bytes, bytearray)):
        try:
            return b64encode(obj).decode("ascii")
        except Exception:
            return str(obj)

    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_json(item) for item in obj]

    if isinstance(obj, dict):
        return {str(k): _sanitize_json(v) for k, v in obj.items() if v is not None}

    # Dataclasses
    if is_dataclass(obj):
        try:
            return _sanitize_json(asdict(obj))
        except Exception:
            return str(obj)

    # Pydantic BaseModel (duck-typed)
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json", exclude_none=True)
        except Exception:
            try:
                return dict(obj)
            except Exception:
                return str(obj)

    # Fallback: try to use __dict__
    if hasattr(obj, "__dict__"):
        try:
            return {k: _sanitize_json(v) for k, v in vars(obj).items() if not k.startswith("_")}
        except Exception:
            return str(obj)

    # Final fallback
    return str(obj)
