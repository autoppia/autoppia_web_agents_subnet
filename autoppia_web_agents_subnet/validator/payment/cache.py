"""
Local JSON cache for payment scanning.
Stores cumulative sent-amounts per coldkey and last processed block per season range.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any
from typing import Dict
from typing import Tuple

CACHE_SCHEMA_VERSION = 1


def _empty_store() -> Dict[str, Any]:
    return {"version": CACHE_SCHEMA_VERSION, "entries": {}}


def _entry_key(
    payment_address: str,
    netuid: int,
    season_start_block: int,
    season_duration_blocks: int,
) -> str:
    return f"{payment_address}|{netuid}|{season_start_block}|{season_duration_blocks}"


def _default_entry(
    payment_address: str,
    netuid: int,
    season_start_block: int,
    season_duration_blocks: int,
) -> Dict[str, Any]:
    return {
        "payment_address": payment_address,
        "netuid": int(netuid),
        "season_start_block": int(season_start_block),
        "season_duration_blocks": int(season_duration_blocks),
        "last_processed_block": int(season_start_block) - 1,
        "totals_by_coldkey": {},
        "updated_at_unix": int(time.time()),
    }


class PaymentCacheStore:
    def __init__(self, path: str) -> None:
        self.path = path

    def _read_store(self) -> Dict[str, Any]:
        if not self.path:
            return _empty_store()
        try:
            with open(self.path, "r", encoding="utf-8") as infile:
                raw = json.load(infile)
        except FileNotFoundError:
            return _empty_store()
        except Exception:
            return _empty_store()

        if not isinstance(raw, dict):
            return _empty_store()
        entries = raw.get("entries", {})
        if not isinstance(entries, dict):
            entries = {}
        return {"version": CACHE_SCHEMA_VERSION, "entries": entries}

    def _write_store(self, store: Dict[str, Any]) -> None:
        if not self.path:
            return
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".payment_cache_", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as outfile:
                json.dump(store, outfile, sort_keys=True, separators=(",", ":"))
            os.replace(tmp_path, self.path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def load_entry(
        self,
        *,
        payment_address: str,
        netuid: int,
        season_start_block: int,
        season_duration_blocks: int,
    ) -> Tuple[Dict[str, Any], bool]:
        key = _entry_key(payment_address, netuid, season_start_block, season_duration_blocks)
        store = self._read_store()
        existing = store.get("entries", {}).get(key)
        if not isinstance(existing, dict):
            return _default_entry(payment_address, netuid, season_start_block, season_duration_blocks), False

        entry = _default_entry(payment_address, netuid, season_start_block, season_duration_blocks)
        try:
            entry["last_processed_block"] = int(existing.get("last_processed_block", entry["last_processed_block"]))
        except Exception:
            pass
        totals = existing.get("totals_by_coldkey", {})
        if isinstance(totals, dict):
            normalized: Dict[str, int] = {}
            for ck, amount in totals.items():
                if not isinstance(ck, str):
                    continue
                try:
                    normalized[ck] = int(amount or 0)
                except Exception:
                    continue
            entry["totals_by_coldkey"] = normalized
        try:
            entry["updated_at_unix"] = int(existing.get("updated_at_unix", entry["updated_at_unix"]))
        except Exception:
            pass
        return entry, True

    def save_entry(
        self,
        *,
        payment_address: str,
        netuid: int,
        season_start_block: int,
        season_duration_blocks: int,
        entry: Dict[str, Any],
    ) -> None:
        key = _entry_key(payment_address, netuid, season_start_block, season_duration_blocks)
        store = self._read_store()
        if "entries" not in store or not isinstance(store["entries"], dict):
            store["entries"] = {}
        store["entries"][key] = entry
        self._write_store(store)
