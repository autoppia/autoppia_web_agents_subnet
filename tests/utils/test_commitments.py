"""
Unit tests for autoppia_web_agents_subnet.utils.commitments.

Tests _json_dump_compact and _maybe_json_load (pure helpers).
Requires bittensor to be installed (module imports it).
"""

import json

import pytest

pytest.importorskip("bittensor")


@pytest.mark.unit
class TestJsonDumpCompact:
    def test_json_dump_compact_returns_compact_json(self):
        from autoppia_web_agents_subnet.utils.commitments import _json_dump_compact

        data = {"a": 1, "b": "x"}
        out = _json_dump_compact(data)
        assert out == json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        assert json.loads(out) == data

    def test_json_dump_compact_raises_when_too_large(self):
        from autoppia_web_agents_subnet.utils.commitments import MAX_COMMIT_BYTES, _json_dump_compact

        # JSON is '{"key":"' + big + '"}' (8 + len(big) + 2 bytes); need total > MAX_COMMIT_BYTES
        big = "x" * (MAX_COMMIT_BYTES - 5)
        data = {"key": big}
        with pytest.raises(ValueError) as exc_info:
            _json_dump_compact(data)
        assert "too large" in str(exc_info.value).lower()
        assert str(MAX_COMMIT_BYTES) in str(exc_info.value)


@pytest.mark.unit
class TestMaybeJsonLoad:
    def test_maybe_json_load_none(self):
        from autoppia_web_agents_subnet.utils.commitments import _maybe_json_load

        assert _maybe_json_load(None) is None

    def test_maybe_json_load_bytes_decodes(self):
        from autoppia_web_agents_subnet.utils.commitments import _maybe_json_load

        payload = b'{"a":1}'
        assert _maybe_json_load(payload) == {"a": 1}

    def test_maybe_json_load_str_json(self):
        from autoppia_web_agents_subnet.utils.commitments import _maybe_json_load

        assert _maybe_json_load('{"x": 2}') == {"x": 2}
        assert _maybe_json_load("3") == 3

    def test_maybe_json_load_non_string_returns_unchanged(self):
        from autoppia_web_agents_subnet.utils.commitments import _maybe_json_load

        obj = {"already": "dict"}
        assert _maybe_json_load(obj) is obj

    def test_maybe_json_load_empty_string_returns_empty_string(self):
        from autoppia_web_agents_subnet.utils.commitments import _maybe_json_load

        assert _maybe_json_load("") == ""
        assert _maybe_json_load("   ") == ""

    def test_maybe_json_load_strip_whitespace(self):
        from autoppia_web_agents_subnet.utils.commitments import _maybe_json_load

        assert _maybe_json_load('  {"a":1}  ') == {"a": 1}


@pytest.mark.unit
@pytest.mark.asyncio
class TestAsyncCommitmentHelpers:
    async def test_write_plain_commitment_json_calls_subtensor_commit(self):
        from autoppia_web_agents_subnet.utils.commitments import write_plain_commitment_json

        class DummySubtensor:
            def __init__(self):
                self.calls = []

            async def commit(self, *, wallet, netuid, data, period=None):
                self.calls.append(
                    {
                        "wallet": wallet,
                        "netuid": netuid,
                        "data": data,
                        "period": period,
                    }
                )
                return True

        st = DummySubtensor()

        class Wallet:
            pass

        wallet = Wallet()
        payload = {"a": 1, "b": "x"}

        ok = await write_plain_commitment_json(
            st,
            wallet=wallet,
            data=payload,
            netuid=42,
            period=7,
        )

        assert ok is True
        assert len(st.calls) == 1
        call = st.calls[0]
        assert call["wallet"] is wallet
        assert call["netuid"] == 42
        assert call["period"] == 7
        # The payload stored should be compact JSON
        assert json.loads(call["data"]) == payload

    async def test_read_plain_commitment_requires_uid_or_hotkey(self):
        from autoppia_web_agents_subnet.utils.commitments import read_plain_commitment

        class DummySubtensor:
            async def get_uid_for_hotkey_on_subnet(self, *_, **__):
                return None

            async def get_commitment(self, *_, **__):
                return "{}"

        st = DummySubtensor()

        with pytest.raises(ValueError):
            await read_plain_commitment(st, netuid=1)

    async def test_read_plain_commitment_by_uid_and_hotkey(self):
        from autoppia_web_agents_subnet.utils.commitments import read_plain_commitment

        class DummySubtensor:
            def __init__(self):
                self.uid_lookups = []

            async def get_uid_for_hotkey_on_subnet(self, hotkey, netuid):
                self.uid_lookups.append((hotkey, netuid))
                return 3

            async def get_commitment(self, *, netuid, uid, block=None):
                # Return a JSON string
                assert uid == 3
                assert netuid == 99
                assert block == 123
                return '{"x": 5}'

        st = DummySubtensor()

        # Lookup by hotkey
        result = await read_plain_commitment(
            st,
            netuid=99,
            hotkey_ss58="hotkey",
            block=123,
        )
        assert result == {"x": 5}
        assert st.uid_lookups == [("hotkey", 99)]

        # Directly by uid (no lookup)
        result2 = await read_plain_commitment(
            st,
            netuid=99,
            uid=3,
            block=123,
        )
        assert result2 == {"x": 5}

    async def test_read_plain_commitment_returns_none_when_uid_not_found(self):
        from autoppia_web_agents_subnet.utils.commitments import read_plain_commitment

        class DummySubtensor:
            async def get_uid_for_hotkey_on_subnet(self, *_, **__):
                return None

            async def get_commitment(self, *_, **__):
                raise AssertionError("Should not be called when uid is None")

        st = DummySubtensor()
        result = await read_plain_commitment(
            st,
            netuid=10,
            hotkey_ss58="missing",
            block=None,
        )
        assert result is None

    async def test_read_all_plain_commitments_decodes_values(self):
        from autoppia_web_agents_subnet.utils.commitments import read_all_plain_commitments

        class DummySubtensor:
            async def get_all_commitments(self, *, netuid, block=None, reuse_block=False):
                assert netuid == 7
                assert block == 100
                assert reuse_block is False
                return {
                    "hk1": '{"a":1}',
                    "hk2": "3",
                    "hk3": "not-json",
                }

        st = DummySubtensor()
        result = await read_all_plain_commitments(st, netuid=7, block=100)

        # hk1 decodes to dict, hk2 to int, hk3 stays as string
        assert result["hk1"] == {"a": 1}
        assert result["hk2"] == 3
        assert result["hk3"] == "not-json"

    async def test_upsert_and_read_my_plain_json(self):
        from autoppia_web_agents_subnet.utils.commitments import (
            read_my_plain_json,
            upsert_my_plain_json,
        )

        class DummyWallet:
            class Hotkey:
                def __init__(self, addr: str):
                    self.ss58_address = addr

            def __init__(self, addr: str):
                self.hotkey = self.Hotkey(addr)

        class DummySubtensor:
            def __init__(self):
                self.commits = {}

            async def commit(self, *, wallet, netuid, data, period=None):
                self.commits.setdefault(netuid, {})[wallet.hotkey.ss58_address] = data
                return True

            async def get_uid_for_hotkey_on_subnet(self, hotkey, netuid):
                # Just return a deterministic UID (not used by read_my_plain_json which
                # delegates to read_plain_commitment)
                return 0

            async def get_commitment(self, *, netuid, uid, block=None):
                # For read_my_plain_json we ignore uid and just use stored payload
                # keyed by netuid; this keeps the dummy implementation simple.
                payloads = self.commits.get(netuid, {})
                # Take any stored value or return "{}"
                return next(iter(payloads.values()), "{}")

        st = DummySubtensor()
        wallet = DummyWallet("hk")
        netuid = 23
        payload = {"hello": "world"}

        ok = await upsert_my_plain_json(
            st,
            wallet=wallet,
            netuid=netuid,
            payload=payload,
            period=None,
        )
        assert ok is True

        result = await read_my_plain_json(
            st,
            wallet=wallet,
            netuid=netuid,
            block=None,
        )
        assert result == payload
