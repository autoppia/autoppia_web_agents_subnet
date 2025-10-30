from __future__ import annotations

import base64
from binascii import Error as BinasciiError
from typing import Any, Dict, List, Optional

import bittensor as bt

from autoppia_web_agents_subnet.platform import client as iwa_main
from autoppia_web_agents_subnet.platform import models as iwa_models
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator.config import (
    VALIDATOR_IMAGE,
    VALIDATOR_NAME,
)
from autoppia_web_agents_subnet.validator.models import TaskWithProject


# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

IWAP_PHASE_ICON = "🛰️"


def log_iwap_phase(
    phase: str,
    message: str,
    *,
    level: str = "info",
    exc_info: bool = False,
) -> None:
    """
    Log IWAP events in the format: IWAP | [Phase X] [action] message

    Args:
        phase: The phase/context name (e.g., "start_round", "Phase 1", etc.)
        message: The message to log
        level: Log level (info, success, warning, error, debug)
        exc_info: Whether to include exception traceback
    """
    # Map contexts to phases
    phase_map = {
        "start_round": "Phase 0",
        "set_tasks": "Phase 2",
        "start_agent_run": "Phase 3",
        "add_evaluation": "Phase 4",
        "finish_round": "Phase 5",
    }

    # Get the phase number if applicable
    phase_label = phase_map.get(phase, phase)

    # Format: IWAP | [Phase X] [context] message
    # If phase is already like "Phase 1", just use it
    if phase.startswith("Phase"):
        prefix = f"IWAP | [{phase}] {message}"
    elif phase in phase_map:
        # For API calls: IWAP | [Phase X] [context] message
        prefix = f"IWAP | [{phase_label}] [{phase}] {message}"
    else:
        # For other cases
        prefix = f"IWAP | [{phase}] {message}"

    if level == "success":
        # Use green color for IWAP success messages
        ColoredLogger.success(prefix, color=ColoredLogger.GREEN)
    elif level == "warning":
        ColoredLogger.warning(prefix)
    elif level == "error":
        bt.logging.error(prefix, exc_info=exc_info)
    elif level == "debug":
        # Use gold color for IWAP debug messages
        ColoredLogger.info(prefix, color=ColoredLogger.GOLD)
    else:
        # Default INFO in gold too for consistency
        ColoredLogger.info(prefix, color=ColoredLogger.GOLD)


def log_ipfs_event(
    action: str,
    message: str,
    *,
    level: str = "info",
    exc_info: bool = False,
) -> None:
    """
    Log IPFS events in the format: IPFS | [action] message

    Args:
        action: The action being performed (e.g., "UPLOAD", "DOWNLOAD", "PUBLISH")
        message: The message to log
        level: Log level (info, success, warning, error, debug)
        exc_info: Whether to include exception traceback
    """
    # Format as "IPFS | [ACTION] message"
    if message.startswith("["):
        prefix = f"IPFS | {message}"
    else:
        prefix = f"IPFS | [{action}] {message}"

    if level == "success":
        # Use green color for IPFS success messages
        ColoredLogger.success(prefix, color=ColoredLogger.GREEN)
    elif level == "warning":
        ColoredLogger.warning(prefix)
    elif level == "error":
        bt.logging.error(prefix, exc_info=exc_info)
    elif level == "debug":
        # Use gold color for IPFS debug messages
        ColoredLogger.info(prefix, color=ColoredLogger.GOLD)
    else:
        # Default INFO in gold too for consistency
        ColoredLogger.info(prefix, color=ColoredLogger.GOLD)


def log_gif_event(
    message: str,
    *,
    level: str = "info",
    exc_info: bool = False,
) -> None:
    """
    Log GIF upload events in the format: IWAP | [Phase 4] [GIF] message

    Args:
        message: The message to log
        level: Log level (info, success, warning, error, debug)
        exc_info: Whether to include exception traceback
    """
    prefix = f"IWAP | [Phase 4] [GIF] {message}"

    if level == "success":
        # Use green color for GIF success messages
        ColoredLogger.success(prefix, color=ColoredLogger.GREEN)
    elif level == "warning":
        ColoredLogger.warning(prefix)
    elif level == "error":
        bt.logging.error(prefix, exc_info=exc_info)
    elif level == "debug":
        # Use gold color for GIF debug messages
        ColoredLogger.info(prefix, color=ColoredLogger.GOLD)
    else:
        # Default INFO in gold too for consistency
        ColoredLogger.info(prefix, color=ColoredLogger.GOLD)


# ──────────────────────────────────────────────────────────────────────────────
# Auth
# ──────────────────────────────────────────────────────────────────────────────


def build_iwap_auth_headers(wallet, message: str) -> Dict[str, str]:
    hotkey = getattr(getattr(wallet, "hotkey", None), "ss58_address", None)
    if not hotkey:
        raise RuntimeError("Validator hotkey is unavailable for IWAP authentication")

    if not message:
        return {}

    message_bytes = message.encode("utf-8")
    signature_bytes = wallet.hotkey.sign(message_bytes)
    signature_b64 = base64.b64encode(signature_bytes).decode("ascii")
    return {
        iwa_main.VALIDATOR_HOTKEY_HEADER: hotkey,
        iwa_main.VALIDATOR_SIGNATURE_HEADER: signature_b64,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Metrics
# ──────────────────────────────────────────────────────────────────────────────


def metagraph_numeric(metagraph, attribute: str, uid: int) -> Optional[float]:
    collection = getattr(metagraph, attribute, None)
    if collection is None:
        bt.logging.debug(f"Metagraph attribute '{attribute}' is unavailable when reading uid={uid}")
        return None
    try:
        value = collection[uid]
        if hasattr(value, "item"):
            return float(value.item())
        return float(value)
    except Exception as exc:  # noqa: BLE001
        bt.logging.debug(f"Failed to coerce metagraph attribute '{attribute}' for uid={uid}: {exc}")
        return None


def normalized_stake_tao(metagraph, uid: int) -> Optional[float]:
    raw_stake = metagraph_numeric(metagraph, "S", uid)
    if raw_stake is None:
        bt.logging.warning(f"Stake not available in metagraph for uid={uid}")
        return None

    try:
        rao_per_tao = float(getattr(getattr(bt, "utils", None), "RAO_PER_TAO", 1_000_000_000))
        if not rao_per_tao:
            raise ValueError("Invalid RAO_PER_TAO constant")
    except Exception as exc:  # noqa: BLE001
        bt.logging.warning(f"Unable to read RAO_PER_TAO constant ({exc}); defaulting to 1e9")
        rao_per_tao = 1_000_000_000

    normalized = raw_stake / rao_per_tao
    from autoppia_web_agents_subnet.utils.log_colors import iwap_tag

    bt.logging.debug(iwap_tag("stake", f"Validator stake normalised for uid={uid}: raw={raw_stake} (RAO) -> {normalized} (TAO)"))
    return normalized


def validator_vtrust(metagraph, uid: int) -> Optional[float]:
    attribute_order = [
        "validator_trust",
        "validator_performance",
        "v_trust",
        "vtrust",
    ]
    for attribute in attribute_order:
        value = metagraph_numeric(metagraph, attribute, uid)
        if value is not None:
            from autoppia_web_agents_subnet.utils.log_colors import iwap_tag

            bt.logging.debug(iwap_tag("vtrust", f"Validator vtrust for uid={uid} resolved via '{attribute}' -> {value}"))
            return value
    from autoppia_web_agents_subnet.utils.log_colors import iwap_tag

    bt.logging.warning(iwap_tag("vtrust", f"Validator vtrust metric not found in metagraph for uid={uid} (checked: {', '.join(attribute_order)})"))
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Snapshots & Payload Builders
# ──────────────────────────────────────────────────────────────────────────────


def build_validator_identity(validator) -> iwa_models.ValidatorIdentityIWAP:
    coldkey = getattr(getattr(validator.wallet, "coldkeypub", None), "ss58_address", None)
    return iwa_models.ValidatorIdentityIWAP(
        uid=int(validator.uid),
        hotkey=validator.wallet.hotkey.ss58_address,
        coldkey=coldkey,
    )


def build_validator_snapshot(validator, validator_round_id: str) -> iwa_models.ValidatorSnapshotIWAP:
    stake = normalized_stake_tao(validator.metagraph, validator.uid)
    vtrust = validator_vtrust(validator.metagraph, validator.uid)
    metadata: Dict[str, Any] = {"source": "autoppia_validator"}

    if stake is None:
        bt.logging.warning(f"Validator snapshot stake is unavailable for uid={validator.uid}; snapshot will omit stake")

    if vtrust is None:
        bt.logging.warning(f"Validator snapshot vtrust is unavailable for uid={validator.uid}; snapshot will omit vtrust")

    return iwa_models.ValidatorSnapshotIWAP(
        validator_round_id=validator_round_id,
        validator_uid=int(validator.uid),
        validator_hotkey=validator.wallet.hotkey.ss58_address,
        name=VALIDATOR_NAME,
        stake=stake,
        vtrust=vtrust,
        image_url=VALIDATOR_IMAGE,
        version=validator.version,
        metadata=metadata,
    )


def build_iwap_tasks(*, validator_round_id: str, tasks: List[TaskWithProject]) -> Dict[str, iwa_models.TaskIWAP]:
    task_map: Dict[str, iwa_models.TaskIWAP] = {}
    for index, task_item in enumerate(tasks):
        task = task_item.task
        project = task_item.project
        task_id = getattr(task, "id", None) or f"{validator_round_id}_task_{index:04d}"

        specifications = {}
        if hasattr(task, "specifications") and task.specifications is not None:
            try:
                specifications = task.specifications.model_dump(mode="json", exclude_none=True)  # type: ignore[attr-defined]
            except Exception:
                specifications = dict(getattr(task, "specifications", {}) or {})

        tests: List[Dict[str, Any]] = []
        for test in getattr(task, "tests", []) or []:
            if hasattr(test, "model_dump"):
                tests.append(test.model_dump(mode="json", exclude_none=True))
            else:
                tests.append(dict(test))

        use_case_payload: Dict[str, Any] = {}
        if getattr(task, "use_case", None) is not None:
            use_case = getattr(task, "use_case")
            if hasattr(use_case, "serialize"):
                try:
                    use_case_payload = use_case.serialize()
                except Exception:
                    use_case_payload = {}
            elif hasattr(use_case, "model_dump"):
                use_case_payload = use_case.model_dump(mode="json", exclude_none=True)

        relevant_data = getattr(task, "relevant_data", {}) or {}
        if not isinstance(relevant_data, dict):
            relevant_data = {"value": relevant_data}

        task_model = iwa_models.TaskIWAP(
            task_id=task_id,
            validator_round_id=validator_round_id,
            sequence=index,
            scope="local",
            is_web_real=bool(getattr(task, "is_web_real", False)),
            web_project_id=getattr(project, "id", None),
            url=getattr(task, "url", getattr(project, "frontend_url", "")),
            prompt=getattr(task, "prompt", ""),
            html=getattr(task, "html", "") or "",
            clean_html=getattr(task, "clean_html", "") or "",
            specifications=specifications,
            tests=tests,
            relevant_data=relevant_data,
            use_case=use_case_payload,
            should_record=bool(getattr(task, "should_record", False)),
            interactive_elements=None,
            screenshot=getattr(task, "screenshot", None),
            screenshot_description=getattr(task, "screenshot_description", None),
            milestones=None,
            success_criteria=getattr(task, "success_criteria", None),
        )
        task_map[task_id] = task_model
    return task_map


# ──────────────────────────────────────────────────────────────────────────────
# GIF extraction
# ──────────────────────────────────────────────────────────────────────────────


def extract_gif_bytes(payload: Optional[object]) -> Optional[bytes]:
    if payload is None:
        bt.logging.debug("🛰️ IWAP GIF extraction: no payload provided")
        return None

    if isinstance(payload, (bytes, bytearray)):
        raw_source = bytes(payload)
    elif isinstance(payload, str):
        text = payload.strip()
        if not text:
            bt.logging.warning("🛰️ IWAP GIF extraction failed: string payload is empty after strip")
            return None
        raw_source = text.encode("utf-8")
    else:
        bt.logging.warning(
            "🛰️ IWAP GIF extraction failed: unsupported payload type %s",
            type(payload).__name__,
        )
        return None

    try:
        decoded = base64.b64decode(raw_source, validate=True)
    except (BinasciiError, ValueError) as exc:  # noqa: BLE001
        bt.logging.warning("🛰️ IWAP GIF extraction failed: base64 decode error %s", exc)
        return None

    if decoded.startswith((b"GIF87a", b"GIF89a")):
        bt.logging.debug("🛰️ IWAP GIF extraction decoded GIF successfully (bytes=%s)", len(decoded))
        return decoded
    bt.logging.warning("🛰️ IWAP GIF extraction failed: decoded payload missing GIF header")
    return None
