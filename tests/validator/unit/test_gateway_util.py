"""
Unit tests for gateway util.py — chutes validation helpers.
"""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

import sys
from pathlib import Path

_gw_dir = str(Path(__file__).resolve().parents[3] / "autoppia_web_agents_subnet" / "opensource" / "gateway")
if _gw_dir not in sys.path:
    sys.path.insert(0, _gw_dir)

from util import (
    is_valid_chutes_base_url,
    get_model_root,
    extract_model_pricing,
    _parse_usd,
    fetch_chutes_models,
    check_hf_model_public,
)


@pytest.mark.unit
class TestIsValidChutesBaseUrl:
    def test_valid_subdomain(self):
        assert is_valid_chutes_base_url("https://my-model.chutes.ai") is True

    def test_valid_llm_subdomain(self):
        assert is_valid_chutes_base_url("https://llm.chutes.ai") is True

    def test_valid_nested_subdomain(self):
        assert is_valid_chutes_base_url("https://a.b.chutes.ai") is True

    def test_rejects_http(self):
        assert is_valid_chutes_base_url("http://my-model.chutes.ai") is False

    def test_rejects_non_chutes_domain(self):
        assert is_valid_chutes_base_url("https://evil.com") is False

    def test_rejects_chutes_ai_suffix_trick(self):
        assert is_valid_chutes_base_url("https://notchutes.ai") is False

    def test_rejects_empty(self):
        assert is_valid_chutes_base_url("") is False

    def test_rejects_bare_chutes_ai(self):
        # "chutes.ai" without subdomain — still ends with ".chutes.ai"? No.
        assert is_valid_chutes_base_url("https://chutes.ai") is False

    def test_rejects_garbage(self):
        assert is_valid_chutes_base_url("not-a-url") is False


@pytest.mark.unit
class TestGetModelRoot:
    def test_root_present(self):
        assert get_model_root({"id": "my-model", "root": "org/real-model"}) == "org/real-model"

    def test_falls_back_to_id(self):
        assert get_model_root({"id": "org/model-name"}) == "org/model-name"

    def test_root_none_falls_back(self):
        assert get_model_root({"id": "org/m", "root": None}) == "org/m"

    def test_empty_dict(self):
        assert get_model_root({}) == ""


@pytest.mark.unit
class TestParseUsd:
    def test_structured_usd(self):
        assert _parse_usd({"input": {"usd": 0.5}}, "input") == 0.5

    def test_missing_key(self):
        assert _parse_usd({"input": {"usd": 0.5}}, "output") is None

    def test_no_usd_field(self):
        assert _parse_usd({"input": {"eur": 0.5}}, "input") is None

    def test_none_value(self):
        assert _parse_usd({"input": None}, "input") is None


@pytest.mark.unit
class TestExtractModelPricing:
    def test_structured_price_with_usd(self):
        m = {
            "price": {
                "input": {"usd": 0.1},
                "output": {"usd": 0.3},
                "input_cache_read": {"usd": 0.05},
            }
        }
        result = extract_model_pricing(m)
        assert result == {"input": 0.1, "output": 0.3, "input_cache_read": 0.05}

    def test_flat_pricing_input_output(self):
        m = {"pricing": {"input": 0.2, "output": 0.4}}
        result = extract_model_pricing(m)
        assert result == {"input": 0.2, "output": 0.4}

    def test_flat_pricing_prompt_completion(self):
        m = {"pricing": {"prompt": 0.15, "completion": 0.6}}
        result = extract_model_pricing(m)
        assert result == {"input": 0.15, "output": 0.6}

    def test_flat_pricing_with_cache(self):
        m = {"pricing": {"input": 1.0, "output": 2.0, "input_cache_read": 0.5}}
        result = extract_model_pricing(m)
        assert result == {"input": 1.0, "output": 2.0, "input_cache_read": 0.5}

    def test_structured_takes_priority_over_flat(self):
        m = {
            "price": {"input": {"usd": 0.1}, "output": {"usd": 0.3}},
            "pricing": {"input": 999, "output": 999},
        }
        result = extract_model_pricing(m)
        assert result["input"] == 0.1
        assert result["output"] == 0.3

    def test_empty_model(self):
        assert extract_model_pricing({}) == {}

    def test_partial_structured_price(self):
        # Only input, no output — should still return partial
        m = {"price": {"input": {"usd": 0.1}}}
        result = extract_model_pricing(m)
        assert result == {"input": 0.1}


@pytest.mark.unit
class TestFetchChutesModels:
    @pytest.mark.asyncio
    async def test_returns_models_from_data_field(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"id": "model-a", "root": "org/model-a"},
                {"id": "model-b", "root": "org/model-b"},
            ]
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = mock_resp

        result = await fetch_chutes_models(client, "https://my.chutes.ai", "key123")
        assert len(result) == 2
        assert result[0]["id"] == "model-a"
        client.get.assert_called_once()
        call_args = client.get.call_args
        assert "Bearer key123" in str(call_args)

    @pytest.mark.asyncio
    async def test_returns_models_from_list_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"id": "m1"}]
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = mock_resp

        result = await fetch_chutes_models(client, "https://x.chutes.ai", None)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_raises_on_401(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = mock_resp

        with pytest.raises(HTTPException) as exc_info:
            await fetch_chutes_models(client, "https://x.chutes.ai", None)
        assert "private or unauthorized" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_raises_on_connection_error(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = httpx.ConnectError("refused")

        with pytest.raises(HTTPException) as exc_info:
            await fetch_chutes_models(client, "https://x.chutes.ai", None)
        assert "unreachable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_filters_entries_without_id(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "good"}, {"name": "no-id"}, {"id": ""}]}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = mock_resp

        result = await fetch_chutes_models(client, "https://x.chutes.ai", None)
        assert len(result) == 1
        assert result[0]["id"] == "good"

    @pytest.mark.asyncio
    async def test_no_api_key_omits_auth_header(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = mock_resp

        await fetch_chutes_models(client, "https://x.chutes.ai", None)
        headers = client.get.call_args[1].get("headers", {})
        assert "Authorization" not in headers


@pytest.mark.unit
class TestCheckHfModelPublic:
    @pytest.mark.asyncio
    async def test_public_model_returns_true(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"private": False}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = mock_resp

        assert await check_hf_model_public(client, "org/model") is True

    @pytest.mark.asyncio
    async def test_private_model_returns_false(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"private": True}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = mock_resp

        assert await check_hf_model_public(client, "org/model") is False

    @pytest.mark.asyncio
    async def test_404_returns_false(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = mock_resp

        assert await check_hf_model_public(client, "org/model") is False

    @pytest.mark.asyncio
    async def test_no_slash_returns_false(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        assert await check_hf_model_public(client, "single-name") is False
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_error_returns_false(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = Exception("timeout")

        assert await check_hf_model_public(client, "org/model") is False
