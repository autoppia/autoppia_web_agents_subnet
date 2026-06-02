"""
Unit tests for gateway Anthropic provider support.
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


def _load_gateway(gateway_dir: str):
    with patch("logging.handlers.RotatingFileHandler", _NoOpFileHandler):
        if gateway_dir not in sys.path:
            sys.path.insert(0, gateway_dir)
        for mod_name in ("main", "config", "models", "util"):
            sys.modules.pop(mod_name, None)
        import main as gateway_main

        return gateway_main.gateway


@pytest.mark.unit
class TestGatewayAnthropicProvider:
    def test_detect_provider_anthropic(self):
        gateway_dir = _gateway_dir()
        env = {
            "GATEWAY_ALLOWED_PROVIDERS": "anthropic",
            "COST_LIMIT_PER_TASK": "10.0",
            "SANDBOX_GATEWAY_ADMIN_TOKEN": "test",
        }
        with patch.dict(os.environ, env, clear=False):
            gw = _load_gateway(gateway_dir)
        assert gw.detect_provider("anthropic/v1/chat/completions") == "anthropic"

    def test_anthropic_allowed_paths_and_models(self):
        gateway_dir = _gateway_dir()
        env = {
            "GATEWAY_ALLOWED_PROVIDERS": "anthropic",
            "COST_LIMIT_PER_TASK": "10.0",
            "SANDBOX_GATEWAY_ADMIN_TOKEN": "test",
        }
        with patch.dict(os.environ, env, clear=False):
            gw = _load_gateway(gateway_dir)
        assert gw._is_allowed_path("anthropic", "/v1/chat/completions") is True
        assert gw._is_allowed_path("anthropic", "/v1/other") is False
        assert gw._is_allowed_model("anthropic", "claude-sonnet-4.5") is True

    def test_anthropic_usage_and_cost_tracking(self):
        gateway_dir = _gateway_dir()
        env = {
            "GATEWAY_ALLOWED_PROVIDERS": "anthropic",
            "COST_LIMIT_PER_TASK": "10.0",
            "SANDBOX_GATEWAY_ADMIN_TOKEN": "test",
        }
        with patch.dict(os.environ, env, clear=False):
            gw = _load_gateway(gateway_dir)
        gw.set_allowed_task_ids(["task-anthropic-1"])
        response_data = {
            "model": "claude-sonnet-4.5",
            "usage": {"input_tokens": 1000, "output_tokens": 500},
        }
        tokens, cost, model = gw.update_usage_for_task("anthropic", "task-anthropic-1", response_data)
        assert tokens == 1500
        assert model == "claude-sonnet-4.5"
        assert cost > 0


@pytest.mark.unit
class TestSandboxManagerAnthropicKeys:
    def test_missing_anthropic_key_raises_when_anthropic_allowed(self):
        env = {
            "GATEWAY_ALLOWED_PROVIDERS": "anthropic",
            "VALIDATOR_NAME": "test",
            "VALIDATOR_IMAGE": "test",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("autoppia_web_agents_subnet.opensource.sandbox_manager.get_client"):
                with patch("autoppia_web_agents_subnet.opensource.sandbox_manager.ensure_network"):
                    from autoppia_web_agents_subnet.opensource.sandbox_manager import SandboxManager

                    manager = SandboxManager()
                    with pytest.raises(RuntimeError, match="Missing API keys"):
                        manager._validate_gateway_provider_keys()
