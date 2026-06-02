"""
Unit tests for gateway util.py.
"""

from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException

_GW_DIR = str(Path(__file__).resolve().parents[3] / "autoppia_web_agents_subnet" / "opensource" / "gateway")
if _GW_DIR not in sys.path:
    sys.path.insert(0, _GW_DIR)

from util import _parse_usd, check_hf_model_public, extract_model_pricing, fetch_chutes_models, get_model_root, is_valid_chutes_base_url


@pytest.mark.unit
class TestIsValidChutesBaseUrl:
    def test_valid_subdomain(self):
        assert is_valid_chutes_base_url("https://my-model.chutes.ai") is True

    def test_rejects_http(self):
        assert is_valid_chutes_base_url("http://my-model.chutes.ai") is False

    def test_rejects_non_chutes_domain(self):
        assert is_valid_chutes_base_url("https://evil.com") is False

    def test_rejects_bare_chutes_ai(self):
        assert is_valid_chutes_base_url("https://chutes.ai") is False


@pytest.mark.unit
class TestModelHelpers:
    def test_get_model_root_prefers_root(self):
        assert get_model_root({"id": "my-model", "root": "org/real-model"}) == "org/real-model"

    def test_get_model_root_falls_back_to_id(self):
        assert get_model_root({"id": "org/model"}) == "org/model"

    def test_parse_usd(self):
        assert _parse_usd({"input": {"usd": 0.5}}, "input") == 0.5
        assert _parse_usd({"input": {"eur": 0.5}}, "input") is None

    def test_extract_model_pricing(self):
        model = {
            "price": {
                "input": {"usd": 0.1},
                "output": {"usd": 0.3},
                "input_cache_read": {"usd": 0.05},
            }
        }
        assert extract_model_pricing(model) == {"input": 0.1, "output": 0.3, "input_cache_read": 0.05}


@pytest.mark.unit
class TestFetchChutesModels:
    @pytest.mark.asyncio
    async def test_returns_models_from_data_field(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "model-a"}]}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = mock_resp

        result = await fetch_chutes_models(client, "https://my.chutes.ai", "key123")
        assert len(result) == 1
        assert result[0]["id"] == "model-a"

    @pytest.mark.asyncio
    async def test_raises_on_401(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = mock_resp

        with pytest.raises(HTTPException, match="private or unauthorized"):
            await fetch_chutes_models(client, "https://x.chutes.ai", None)

    @pytest.mark.asyncio
    async def test_raises_on_connection_error(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = httpx.ConnectError("refused")

        with pytest.raises(HTTPException, match="unreachable"):
            await fetch_chutes_models(client, "https://x.chutes.ai", None)


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

