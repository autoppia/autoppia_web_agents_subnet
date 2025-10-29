"""
Utilities shared by validator reporting and monitoring scripts.

This package centralizes helpers that were previously duplicated across
stand-alone scripts so they can share configuration, IO helpers, and
email delivery plumbing.
"""

from .emailing import EmailConfig, load_email_config_from_env, parse_recipients, send_email
from .state import load_last_state, save_last_state

__all__ = [
    "EmailConfig",
    "load_email_config_from_env",
    "parse_recipients",
    "send_email",
    "load_last_state",
    "save_last_state",
]
