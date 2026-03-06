"""Standard IPFS HTTP API backend (the original implementation)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional, Sequence, Tuple

from autoppia_web_agents_subnet.utils.storage.base import BaseIPFSClient

try:
    import requests  # type: ignore
    _HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    _HAVE_REQUESTS = False


class IPFSError(Exception):
    pass


def _minidumps(obj: Any, *, sort_keys: bool = True) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=sort_keys)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class StandardIPFSClient(BaseIPFSClient):
    """IPFS client that talks to a standard IPFS HTTP API node."""

    def __init__(
        self,
        api_url: str,
        gateways: Optional[Sequence[str]] = None,
    ) -> None:
        self._api_url = (api_url or "").rstrip("/")
        self._gateways = list(gateways or [])

    def add_bytes(
        self,
        data: bytes,
        *,
        filename: str = "commit.json",
        pin: bool = True,
    ) -> str:
        if not self._api_url:
            raise IPFSError("No IPFS API URL configured")
        if not _HAVE_REQUESTS:
            raise IPFSError("Python 'requests' is required for IPFS HTTP API")
        url = f"{self._api_url}/add"
        params = {
            "cid-version": "1",
            "hash": "sha2-256",
            "pin": "true" if pin else "false",
            "wrap-with-directory": "false",
            "quieter": "true",
        }
        files = {"file": (filename, data)}
        resp = requests.post(url, params=params, files=files, timeout=30)
        resp.raise_for_status()
        lines = [ln for ln in resp.text.strip().splitlines() if ln.strip()]
        last = json.loads(lines[-1])
        cid = last.get("Hash") or last.get("Cid") or last.get("Key")
        if not cid:
            raise IPFSError(f"IPFS /add returned no CID: {last}")
        return str(cid)

    def add_json(
        self,
        obj: Any,
        *,
        filename: str = "commit.json",
        pin: bool = True,
        sort_keys: bool = True,
    ) -> Tuple[str, str, int]:
        text = _minidumps(obj, sort_keys=sort_keys)
        b = text.encode("utf-8")
        cid = self.add_bytes(b, filename=filename, pin=pin)
        return cid, _sha256_hex(b), len(b)

    def cat(
        self,
        cid: str,
        *,
        timeout: float = 20.0,
    ) -> bytes:
        last_err: Optional[Exception] = None

        if self._api_url and _HAVE_REQUESTS:
            try:
                url = f"{self._api_url}/cat"
                resp = requests.post(url, params={"arg": cid}, timeout=timeout)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                last_err = e

        import urllib.request
        for gw in self._gateways:
            try:
                with urllib.request.urlopen(f"{gw.rstrip('/')}/{cid}", timeout=timeout) as r:
                    return r.read()
            except Exception as e:  # pragma: no cover
                last_err = e
                continue

        raise IPFSError(f"Failed to fetch CID {cid}: {last_err}")

    def get_json(
        self,
        cid: str,
        *,
        expected_sha256_hex: Optional[str] = None,
    ) -> Tuple[Any, bytes, str]:
        raw = self.cat(cid)
        obj = json.loads(raw.decode("utf-8"))
        norm = _minidumps(obj).encode("utf-8")
        h = _sha256_hex(norm)
        if expected_sha256_hex and h.lower() != expected_sha256_hex.lower():
            raise IPFSError(f"Hash mismatch for CID {cid}: expected {expected_sha256_hex}, got {h}")
        return obj, norm, h
