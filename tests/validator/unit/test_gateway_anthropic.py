"""
Unit tests for LLM gateway Anthropic provider.

Tests provider detection, path/model allowlists, pricing resolution,
and usage/cost tracking for the Anthropic provider without starting the full app.
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
    """Handler that does not open a file; used when testing gateway outside Docker."""

    def __init__(self, filename: str = "", **kwargs) -> None:
        super().__init__()

    def emit(self, record: logging.LogRecord) -> None:
        pass


def _load_gateway(gateway_dir: str):
    """Import gateway main with logging patched so /app/logs is not required."""
    with patch("logging.handlers.RotatingFileHandler", _NoOpFileHandler):
        sys.path.insert(0, gateway_dir)
        try:
            import main as gateway_main
            return gateway_main.gateway
        finally:
            sys.path.remove(gateway_dir)


@pytest.mark.unit
class TestGatewayAnthropicProvider:
    """Test Anthropic provider integration in the LLM gateway."""

    def test_detect_provider_anthropic(self) -> None:
        gateway_dir = _gateway_dir()
        env = {
            "GATEWAY_ALLOWED_PROVIDERS": "anthropic",
            "COST_LIMIT_PER_TASK": "10.0",
            "SANDBOX_GATEWAY_ADMIN_TOKEN": "test",
        }
        with patch.dict(os.environ, env, clear=False):
            gw = _load_gateway(gateway_dir)
        assert gw.detect_provider("anthropic") == "anthropic"
        assert gw.detect_provider("anthropic/") == "anthropic"
        assert gw.detect_provider("anthropic/v1/chat/completions") == "anthropic"
        assert gw.detect_provider("anthropic/v1/responses") == "anthropic"

    def test_anthropic_allowed_paths_and_models(self) -> None:
        gateway_dir = _gateway_dir()
        env = {
            "GATEWAY_ALLOWED_PROVIDERS": "anthropic",
            "COST_LIMIT_PER_TASK": "10.0",
            "SANDBOX_GATEWAY_ADMIN_TOKEN": "test",
        }
        with patch.dict(os.environ, env, clear=False):
            gw = _load_gateway(gateway_dir)
        assert gw._is_allowed_path("anthropic", "/v1/chat/completions") is True
        assert gw._is_allowed_path("anthropic", "/v1/responses") is True
        assert gw._is_allowed_path("anthropic", "/v1/other") is False
        assert gw._is_allowed_model("anthropic", "claude-sonnet-4.5") is True
        assert gw._is_allowed_model("anthropic", "claude-opus-4.6") is True

    def test_anthropic_pricing_resolution(self) -> None:
        gateway_dir = _gateway_dir()
        env = {
            "GATEWAY_ALLOWED_PROVIDERS": "anthropic",
            "COST_LIMIT_PER_TASK": "10.0",
            "SANDBOX_GATEWAY_ADMIN_TOKEN": "test",
        }
        with patch.dict(os.environ, env, clear=False):
            gw = _load_gateway(gateway_dir)
        assert gw._resolve_pricing_model("anthropic", "claude-sonnet-4.5") == "claude-sonnet-4.5"
        assert gw._resolve_pricing_model("anthropic", "claude-sonnet-4.5-20241022") == "claude-sonnet-4.5"
        assert gw._resolve_pricing_model("anthropic", "claude-opus-4.6") == "claude-opus-4.6"
        assert gw._resolve_pricing_model("anthropic", "claude-haiku-4.5") == "claude-haiku-4.5"

    def test_anthropic_usage_and_cost_tracking(self) -> None:
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
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 500,
            },
        }
        tokens, cost, model = gw.update_usage_for_task("anthropic", "task-anthropic-1", response_data)
        assert tokens == 1500
        assert model == "claude-sonnet-4.5"
        assert cost > 0
        usage = gw.get_usage_for_task("task-anthropic-1")
        assert usage.total_tokens == 1500
        assert usage.total_cost == cost

    def test_anthropic_usage_with_cached_tokens(self) -> None:
        gateway_dir = _gateway_dir()
        env = {
            "GATEWAY_ALLOWED_PROVIDERS": "anthropic",
            "COST_LIMIT_PER_TASK": "10.0",
            "SANDBOX_GATEWAY_ADMIN_TOKEN": "test",
        }
        with patch.dict(os.environ, env, clear=False):
            gw = _load_gateway(gateway_dir)
        gw.set_allowed_task_ids(["task-cached"])
        response_data = {
            "model": "claude-sonnet-4.6",
            "usage": {
                "input_tokens": 200,
                "output_tokens": 100,
                "input_tokens_details": {"cached_tokens": 100},
            },
        }
        tokens, cost, _ = gw.update_usage_for_task("anthropic", "task-cached", response_data)
        assert tokens == 300
        assert cost > 0

    def test_is_cost_exceeded_missing_task_id(self) -> None:
        gateway_dir = _gateway_dir()
        env = {
            "GATEWAY_ALLOWED_PROVIDERS": "anthropic",
            "COST_LIMIT_PER_TASK": "10.0",
            "SANDBOX_GATEWAY_ADMIN_TOKEN": "test",
        }
        with patch.dict(os.environ, env, clear=False):
            gw = _load_gateway(gateway_dir)
        gw.set_allowed_task_ids(["task-1"])
        assert gw.is_cost_exceeded("task-1") is False
        assert gw.is_cost_exceeded("task-nonexistent") is False


@pytest.mark.unit
class TestSandboxManagerAnthropicKeys:
    """Test sandbox manager requires ANTHROPIC_API_KEY when anthropic is allowed."""

    def test_missing_anthropic_key_raises_when_anthropic_allowed(self) -> None:
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

    def test_anthropic_key_present_passes_validation(self) -> None:
        env = {
            "GATEWAY_ALLOWED_PROVIDERS": "anthropic",
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "VALIDATOR_NAME": "test",
            "VALIDATOR_IMAGE": "test",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("autoppia_web_agents_subnet.opensource.sandbox_manager.get_client"):
                with patch("autoppia_web_agents_subnet.opensource.sandbox_manager.ensure_network"):
                    from autoppia_web_agents_subnet.opensource.sandbox_manager import SandboxManager
                    manager = SandboxManager()
                    manager._validate_gateway_provider_keys()
