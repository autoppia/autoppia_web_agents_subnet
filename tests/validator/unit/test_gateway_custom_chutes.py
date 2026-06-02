"""
Unit tests for gateway custom chutes endpoint routing and pricing isolation.
"""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch

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
            for mod_name in ("main", "config", "models", "util"):
                sys.modules.pop(mod_name, None)
            import main as gateway_main

            return gateway_main.gateway


@pytest.mark.unit
class TestCustomChutesPricingIsolation:
    def test_update_usage_with_custom_chutes_key(self):
        gw = _make_gateway()
        gw.set_allowed_task_ids(["t1"])
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
        expected = (1000 / 1_000_000) * 0.5 + (500 / 1_000_000) * 1.0
        assert tokens == 1500
        assert model == "my-model"
        assert abs(cost - expected) < 1e-10

    def test_custom_pricing_does_not_pollute_provider_config(self):
        gw = _make_gateway()
        gw.set_allowed_task_ids(["t1"])
        original_pricing = dict(gw.providers["chutes"].pricing)
        cache_key = ("https://custom.chutes.ai", "custom-model")
        gw._custom_chutes_pricing[cache_key] = {
            "root": "org/model",
            "pricing": {"input": 0.1, "output": 0.2},
        }
        gw.update_usage_for_task(
            "chutes",
            "t1",
            {"model": "custom-model", "usage": {"prompt_tokens": 100, "completion_tokens": 50}},
            custom_chutes_key=cache_key,
        )
        assert "custom-model" not in gw.providers["chutes"].pricing
        assert gw.providers["chutes"].pricing == original_pricing

    def test_set_allowed_task_ids_clears_custom_cache(self):
        gw = _make_gateway()
        gw._custom_chutes_pricing[("https://x.chutes.ai", "m")] = {"root": "org/m", "pricing": {"input": 1, "output": 2}}
        gw.set_allowed_task_ids(["t2"])
        assert gw._custom_chutes_pricing == {}


@pytest.mark.unit
class TestCustomChutesModelAllowlist:
    def test_allowed_model_check_skipped_for_custom_chutes(self):
        gw = _make_gateway({"CHUTES_ALLOWED_MODELS": "only-this-model"})
        assert gw._is_allowed_model("chutes", "some-other-model") is False
        assert gw._is_allowed_model("chutes", "only-this-model") is True

