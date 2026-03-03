"""
Unit tests for round log capture (ColoredLogger set_round_log_file / clear_round_log_file).

Verifies that:
- The subnet does NOT depend on IWA (only optionally uses loguru if present).
- set_round_log_file creates the correct path (data/season_X/round_Y/logs/<round_id>.log).
- Python logging and (if available) loguru write to the same file without collision.
- get_round_log_file returns the path; clear_round_log_file cleans up.
"""

import logging
import os
from pathlib import Path

import pytest


@pytest.mark.unit
class TestRoundLogCapture:
    """Test round log file creation, capture, and cleanup."""

    def test_set_round_log_file_creates_path_and_file(self, tmp_path):
        """set_round_log_file creates data/season_X/round_Y/logs/<round_id>.log."""
        from autoppia_web_agents_subnet.utils.logging import ColoredLogger

        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            ColoredLogger.clear_round_log_file()
            round_id = "validator_round_1_1_abc123"
            ColoredLogger.set_round_log_file(round_id)
            path = ColoredLogger.get_round_log_file()
            assert path is not None
            assert "validator_round_1_1_abc123.log" in path
            assert "season_1" in path and "round_1" in path and "logs" in path
            assert Path(path).exists()
        finally:
            os.chdir(orig_cwd)
            ColoredLogger.clear_round_log_file()

    def test_python_logging_writes_to_round_log_file(self, tmp_path):
        """Messages via root logger are written to the round log file."""
        from autoppia_web_agents_subnet.utils.logging import ColoredLogger

        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            ColoredLogger.clear_round_log_file()
            round_id = "validator_round_2_3_test"
            ColoredLogger.set_round_log_file(round_id)
            path = ColoredLogger.get_round_log_file()
            assert path is not None
            logging.getLogger().info("python_logging_test_message")
            content = Path(path).read_text(encoding="utf-8")
            assert "python_logging_test_message" in content
        finally:
            os.chdir(orig_cwd)
            ColoredLogger.clear_round_log_file()

    def test_loguru_writes_to_round_log_file_if_available(self, tmp_path):
        """If loguru is available, it also writes to the same file (no collision)."""
        from autoppia_web_agents_subnet.utils.logging import ColoredLogger

        try:
            from loguru import logger as loguru_logger
        except ImportError:
            pytest.skip("loguru not installed")
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            ColoredLogger.clear_round_log_file()
            round_id = "validator_round_1_1_loguru"
            ColoredLogger.set_round_log_file(round_id)
            path = ColoredLogger.get_round_log_file()
            assert path is not None
            loguru_logger.info("loguru_test_message")
            content = Path(path).read_text(encoding="utf-8")
            assert "loguru_test_message" in content
        finally:
            os.chdir(orig_cwd)
            ColoredLogger.clear_round_log_file()

    def test_clear_round_log_file_cleans_up_and_returns_none(self, tmp_path):
        """After clear_round_log_file, get_round_log_file returns None."""
        from autoppia_web_agents_subnet.utils.logging import ColoredLogger

        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            ColoredLogger.clear_round_log_file()
            ColoredLogger.set_round_log_file("validator_round_1_1_xyz")
            assert ColoredLogger.get_round_log_file() is not None
            ColoredLogger.clear_round_log_file()
            assert ColoredLogger.get_round_log_file() is None
        finally:
            os.chdir(orig_cwd)
            ColoredLogger.clear_round_log_file()

    def test_subnet_logging_does_not_import_iwa(self):
        """Subnet utils.logging must not import autoppia_iwa (no hard dependency)."""
        import sys

        # Ensure IWA is not loaded by the logging module
        modules_before = set(sys.modules.keys())
        from autoppia_web_agents_subnet.utils import logging as subnet_logging  # noqa: F401

        modules_after = set(sys.modules.keys())
        new_modules = modules_after - modules_before
        iwa_loaded = any("autoppia_iwa" in m for m in new_modules)
        assert not iwa_loaded, "Subnet logging must not import IWA"
