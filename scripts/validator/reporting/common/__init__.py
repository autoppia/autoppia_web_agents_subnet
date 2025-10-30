"""Shared primitives for reporting pipelines."""

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
