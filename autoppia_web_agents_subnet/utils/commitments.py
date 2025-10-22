from __future__ import annotations

import json
from typing import Any, Dict, Optional

from bittensor import AsyncSubtensor  # type: ignore


# Limit plain-commit payloads to a small size (we aim to store only CID objects)
MAX_COMMIT_BYTES = 16 * 1024  # 16 KiB


def _json_dump_compact(data: Any) -> str:
    s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    b = s.encode("utf-8")
    if len(b) > MAX_COMMIT_BYTES:
        raise ValueError(
            f"JSON payload too large: {len(b)} bytes (limit {MAX_COMMIT_BYTES}). "
            "Store less history or compress further."
        )
    return s


def _maybe_json_load(s: Optional[Any]) -> Any:
    if s is None:
        return None
    if isinstance(s, (bytes, bytearray)):
        try:
            s = s.decode("utf-8")
        except Exception:
            return s
    if not isinstance(s, str):
        return s

    text = s.strip()
    if not text:
        return text

    attempts = 0
    candidate: Any = text
    while attempts < 3 and isinstance(candidate, str):
        try:
            decoded = json.loads(candidate)
        except Exception:
            return candidate if attempts else s
        if not isinstance(decoded, str):
            return decoded
        if decoded == candidate:
            return decoded
        candidate = decoded.strip()
        attempts += 1
    return candidate


async def write_plain_commitment_json(
    st: AsyncSubtensor,
    *,
    wallet,
    data: Any,
    netuid: int,
    period: Optional[int] = None,
) -> bool:
    payload = _json_dump_compact(data)
    return await st.commit(wallet=wallet, netuid=netuid, data=payload, period=period)


async def read_plain_commitment(
    st: AsyncSubtensor,
    *,
    netuid: int,
    uid: Optional[int] = None,
    hotkey_ss58: Optional[str] = None,
    block: Optional[int] = None,
) -> Any:
    if uid is None and not hotkey_ss58:
        raise ValueError("Provide either `uid` or `hotkey_ss58`")

    if uid is None:
        uid = await st.get_uid_for_hotkey_on_subnet(hotkey_ss58, netuid)  # type: ignore[arg-type]
        if uid is None:
            return None

    raw: str = await st.get_commitment(netuid=netuid, uid=uid, block=block)
    return _maybe_json_load(raw)


async def read_all_plain_commitments(
    st: AsyncSubtensor,
    *,
    netuid: int,
    block: Optional[int] = None,
) -> Dict[str, Any]:
    commits = await st.get_all_commitments(netuid=netuid, block=block, reuse_block=False)
    return {hk: _maybe_json_load(v) for hk, v in commits.items()}


async def upsert_my_plain_json(
    st: AsyncSubtensor,
    *,
    wallet,
    netuid: int,
    payload: Any,
    period: Optional[int] = None,
) -> bool:
    return await write_plain_commitment_json(st, wallet=wallet, data=payload, netuid=netuid, period=period)


async def read_my_plain_json(
    st: AsyncSubtensor,
    *,
    wallet,
    netuid: int,
    block: Optional[int] = None,
) -> Any:
    uid = await st.get_uid_for_hotkey_on_subnet(wallet.hotkey.ss58_address, netuid)
    if uid is None:
        return None
    return await read_plain_commitment(st, netuid=netuid, uid=uid, block=block)

