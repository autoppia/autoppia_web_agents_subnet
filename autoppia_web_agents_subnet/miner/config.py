"""
Miner-specific configuration settings.

This module contains all configuration values that miners can customize,
including agent metadata, timeouts, and feature flags.
"""

import os
from distutils.util import strtobool


# ╭─────────────────────────── Agent Metadata ─────────────────────────────╮
# Metadata advertised to validators during StartRoundSynapse handshake.
# Override via environment variables.

AGENT_NAME = os.getenv("MINER_AGENT_NAME","miner_name")
"""Agent display name shown in leaderboard and logs. Empty string if unset."""

AGENT_IMAGE = os.getenv("MINER_AGENT_IMAGE", "")
"""Agent logo/avatar URL (or data URI). Empty string means no image."""

GITHUB_URL = os.getenv("MINER_GITHUB_URL", "https://github.com/autoppia/autoppia-subnet")
"""Repository URL where the miner/agent code lives."""

AGENT_VERSION = os.getenv("MINER_AGENT_VERSION", "1.0.0")
"""Semantic version of the agent (e.g., "1.2.3")."""

HAS_RL = bool(int(os.getenv("MINER_HAS_RL", "0")))
"""Whether this agent uses reinforcement learning. Set MINER_HAS_RL=1 to enable."""


# ╭─────────────────────────── Task Execution ─────────────────────────────╮

TASK_TIMEOUT = int(os.getenv("MINER_TASK_TIMEOUT", "120"))
"""Maximum time (seconds) to solve a single task. Default: 120s (2 minutes)."""

MAX_RETRIES = int(os.getenv("MINER_MAX_RETRIES", "3"))
"""Number of retries if task solving fails. Default: 3."""


# ╭─────────────────────────── Feedback & Logging ─────────────────────────────╮

SAVE_FEEDBACK_TO_JSON = bool(strtobool(os.getenv("MINER_SAVE_FEEDBACK", "false")))
"""Whether to save feedback from validators to a local JSON file."""

FEEDBACK_JSON_FILE = os.getenv("MINER_FEEDBACK_FILE", "feedback_tasks.json")
"""Path to JSON file where feedback is saved (if SAVE_FEEDBACK_TO_JSON is True)."""

VERBOSE_LOGGING = bool(strtobool(os.getenv("MINER_VERBOSE", "true")))
"""Enable verbose logging with colors and detailed output."""
