"""
Unit tests for gateway custom chutes endpoint routing, pricing isolation,
and model allowlist bypass.

Tests the changes from:
- feat(gateway): custom chutes endpoint routing with HuggingFace model validation
- fix(gateway): isolate custom chute pricing from provider config and fix model allowlist bypass
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest


def _gateway_dir() -> str:
    root = Path(__file__).resolve().parents[3]
    return str(root / "autoppia_web_agents_subnet" / "opensource" / "gateway")


class _NoOpFileHandler(logging.Handler):
    def __init__(self, filename: str = "", **kwargs) -> None:
        super().__init__()

    def emit(self, record: logging.LogRecord) -> None:
        pass


def _make_gateway(extra_env: dict | None = None):
    """Import and create a fresh gateway instance with logging patched."""
    env = {
        "GATEWAY_ALLOWED_PROVIDERS": "chutes",
        "COST_LIMIT_PER_TASK": "10.0",
        "SANDBOX_GATEWAY_ADMIN_TOKEN": "test",
        "CHUTES_API_KEY": "test-key",
        "GATEWAY_STRICT_PRICING": "false",
    }
    if extra_env:
        env.update(extra_env)

    gateway_dir = _gateway_dir()
    with patch("logging.handlers.RotatingFileHandler", _NoOpFileHandler):
        with patch.dict(os.environ, env, clear=False):
            if gateway_dir not in sys.path:
                sys.path.insert(0, gateway_dir)
            # Force re-import to pick up env changes
            for mod_name in ("main", "config", "models", "util"):
                sys.modules.pop(mod_name, None)
            import main as gateway_main
            return gateway_main.gateway


@pytest.mark.unit
class TestCustomChutesPricingIsolation:
    """Custom chute pricing must not pollute provider_config.pricing."""

    def test_custom_chutes_pricing_cache_structure(self):
        gw = _make_gateway()
        assert gw._custom_chutes_pricing == {}

    def test_update_usage_with_custom_chutes_key(self):
        gw = _make_gateway()
        asyncio.get_event_loop().run_until_complete(gw.set_allowed_task_ids(["t1"]))

        # Populate custom chute cache
        cache_key = ("https://custom.chutes.ai", "my-model")
        gw._custom_chutes_pricing[cache_key] = {
            "root": "org/real-model",
            "pricing": {"input": 0.5, "output": 1.0},
        }

        response_data = {
            "model": "my-model",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }
        tokens, cost, model = gw.update_usage_for_task("chutes", "t1", response_data, custom_chutes_key=cache_key)

        assert tokens == 1500
        assert model == "my-model"
        # Cost should use custom pricing: (1000/1M * 0.5) + (500/1M * 1.0)
        expected = (1000 / 1_000_000) * 0.5 + (500 / 1_000_000) * 1.0
        assert abs(cost - expected) < 1e-10

    def test_update_usage_without_custom_key_uses_provider_pricing(self):
        gw = _make_gateway()
        asyncio.get_event_loop().run_until_complete(gw.set_allowed_task_ids(["t1"]))

        # Set provider pricing directly
        gw.providers["chutes"].pricing["standard-model"] = {"input": 2.0, "output": 4.0}

        response_data = {
            "model": "standard-model",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }
        tokens, cost, model = gw.update_usage_for_task("chutes", "t1", response_data)

        expected = (1000 / 1_000_000) * 2.0 + (500 / 1_000_000) * 4.0
        assert abs(cost - expected) < 1e-10

    def test_custom_pricing_does_not_pollute_provider_config(self):
        gw = _make_gateway()
        asyncio.get_event_loop().run_until_complete(gw.set_allowed_task_ids(["t1"]))

        original_pricing = dict(gw.providers["chutes"].pricing)

        cache_key = ("https://custom.chutes.ai", "custom-model")
        gw._custom_chutes_pricing[cache_key] = {
            "root": "org/model",
            "pricing": {"input": 0.1, "output": 0.2},
        }

        # Use it
        response_data = {
            "model": "custom-model",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
        gw.update_usage_for_task("chutes", "t1", response_data, custom_chutes_key=cache_key)

        # provider_config.pricing should be untouched
        assert "custom-model" not in gw.providers["chutes"].pricing
        assert gw.providers["chutes"].pricing == original_pricing

    def test_custom_key_uses_request_model_not_response_model(self):
        """Cache lookup should use the request model (in key), not response model."""
        gw = _make_gateway()
        asyncio.get_event_loop().run_until_complete(gw.set_allowed_task_ids(["t1"]))

        # Cache keyed by request model "req-model"
        cache_key = ("https://custom.chutes.ai", "req-model")
        gw._custom_chutes_pricing[cache_key] = {
            "root": "org/model",
            "pricing": {"input": 0.5, "output": 1.0},
        }

        # Response returns a different model name
        response_data = {
            "model": "response-model-v2",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }
        tokens, cost, model = gw.update_usage_for_task("chutes", "t1", response_data, custom_chutes_key=cache_key)

        # Should still use cached pricing from req-model key
        expected = (1000 / 1_000_000) * 0.5 + (500 / 1_000_000) * 1.0
        assert abs(cost - expected) < 1e-10


@pytest.mark.unit
class TestSetAllowedTaskIdsClearsCache:
    """set_allowed_task_ids should clear custom chute cache."""

    def test_clears_custom_chutes_pricing(self):
        gw = _make_gateway()
        gw._custom_chutes_pricing[("https://x.chutes.ai", "m")] = {
            "root": "org/m",
            "pricing": {"input": 1, "output": 2},
        }
        assert len(gw._custom_chutes_pricing) == 1

        asyncio.get_event_loop().run_until_complete(gw.set_allowed_task_ids(["t2"]))
        assert gw._custom_chutes_pricing == {}

    def test_resets_usage_per_task(self):
        gw = _make_gateway()
        asyncio.get_event_loop().run_until_complete(gw.set_allowed_task_ids(["a", "b"]))
        assert "a" in gw.usage_per_task
        assert "b" in gw.usage_per_task


@pytest.mark.unit
class TestCustomChutesModelAllowlistBypass:
    """Custom chute requests should skip CHUTES_ALLOWED_MODELS check."""

    def test_allowed_model_check_skipped_for_custom_chutes(self):
        gw = _make_gateway({"CHUTES_ALLOWED_MODELS": "only-this-model"})
        # Force re-import of config to pick up the env var
        sys.modules.pop("config", None)

        # Non-custom: model not in allowlist should be rejected
        assert gw._is_allowed_model("chutes", "some-other-model") is False
        assert gw._is_allowed_model("chutes", "only-this-model") is True

    def test_is_allowed_model_passes_when_no_allowlist(self):
        gw = _make_gateway({"CHUTES_ALLOWED_MODELS": ""})
        assert gw._is_allowed_model("chutes", "anything") is True


@pytest.mark.unit
class TestCustomChutesUsageWithCachedTokens:
    """Custom chute cost should account for cached input tokens."""

    def test_cached_tokens_reduce_cost(self):
        gw = _make_gateway()
        asyncio.get_event_loop().run_until_complete(gw.set_allowed_task_ids(["t1"]))

        cache_key = ("https://x.chutes.ai", "m")
        gw._custom_chutes_pricing[cache_key] = {
            "root": "org/m",
            "pricing": {"input": 2.0, "output": 4.0, "input_cache_read": 0.5},
        }

        response_data = {
            "model": "m",
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "prompt_tokens_details": {"cached_tokens": 400},
            },
        }
        tokens, cost, _ = gw.update_usage_for_task("chutes", "t1", response_data, custom_chutes_key=cache_key)

        assert tokens == 1500
        # non-cached input: 600, cached: 400, output: 500
        expected = (600 / 1_000_000) * 2.0 + (400 / 1_000_000) * 0.5 + (500 / 1_000_000) * 4.0
        assert abs(cost - expected) < 1e-10


@pytest.mark.unit
class TestCustomChuteFallbackPricing:
    """When custom chute cache miss for key, cost uses default prices."""

    def test_missing_cache_entry_uses_default_prices(self):
        gw = _make_gateway()
        asyncio.get_event_loop().run_until_complete(gw.set_allowed_task_ids(["t1"]))

        # No entry in _custom_chutes_pricing for this key
        cache_key = ("https://unknown.chutes.ai", "unknown-model")

        response_data = {
            "model": "unknown-model",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }
        tokens, cost, _ = gw.update_usage_for_task("chutes", "t1", response_data, custom_chutes_key=cache_key)

        # Should fall back to default_input_price=1.0, default_output_price=4.0
        expected = (1000 / 1_000_000) * 1.0 + (500 / 1_000_000) * 4.0
        assert abs(cost - expected) < 1e-10
