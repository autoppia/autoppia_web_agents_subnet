from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Mapping, Optional, Sequence


def _coerce_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _normalise_recipients(recipients: Sequence[str]) -> list[str]:
    return [recipient.strip() for recipient in recipients if recipient and recipient.strip()]


@dataclass
class EmailConfig:
    """SMTP configuration for sending validator notifications."""

    host: str
    port: int
    sender: str
    recipients: list[str]
    user: Optional[str] = None
    password: Optional[str] = None
    starttls: bool = True
    use_ssl: bool = False

    def __post_init__(self) -> None:
        self.host = self.host or ""
        self.sender = self.sender or ""
        self.recipients = _normalise_recipients(self.recipients)
        if not self.host:
            raise ValueError("SMTP host is required.")
        if not self.sender:
            raise ValueError("Sender email is required.")


def parse_recipients(raw: str, separator: str = ",") -> list[str]:
    """Split a raw comma-separated recipients string into a clean list."""
    if not raw:
        return []
    return _normalise_recipients(raw.split(separator))


def as_plaintext(html_body: str) -> str:
    """Fallback plain-text conversion for HTML bodies."""
    return (
        html_body.replace("<br />", "\n")
        .replace("<br/>", "\n")
        .replace("<br>", "\n")
        .replace("</p>", "\n\n")
        .replace("<p>", "")
    )


def send_email(config: EmailConfig, subject: str, html_body: str, text_body: Optional[str] = None) -> None:
    """Send an email using the provided SMTP configuration."""
    if not config.recipients:
        raise ValueError("At least one recipient email is required.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.sender
    msg["To"] = ", ".join(config.recipients)

    plain = text_body or as_plaintext(html_body)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    smtp_cls = smtplib.SMTP_SSL if config.use_ssl else smtplib.SMTP
    with smtp_cls(config.host, config.port) as smtp:
        if not config.use_ssl and config.starttls:
            smtp.starttls()
        if config.user and config.password:
            smtp.login(config.user, config.password)
        smtp.sendmail(config.sender, config.recipients, msg.as_string())


def load_email_config_from_env(
    *,
    host_key: str,
    sender_key: str,
    recipients_key: str,
    port_key: Optional[str] = None,
    user_key: Optional[str] = None,
    password_key: Optional[str] = None,
    starttls_key: Optional[str] = None,
    use_ssl_key: Optional[str] = None,
    default_port: int = 587,
    default_starttls: bool = True,
    require_recipients: bool = True,
    env: Optional[Mapping[str, str]] = None,
) -> EmailConfig:
    """
    Build an EmailConfig from environment variables.

    Callers can control which env variable names are used per field to support
    both the monitor and batch report scripts.
    """

    env = dict(env or os.environ)

    host = env.get(host_key, "")
    sender = env.get(sender_key, "")
    recipients = parse_recipients(env.get(recipients_key, ""))

    if port_key:
        port_str = env.get(port_key)
        port = int(port_str) if port_str else default_port
    else:
        port = default_port

    user = env.get(user_key) if user_key else None
    password = env.get(password_key) if password_key else None

    if starttls_key:
        starttls = _coerce_bool(env.get(starttls_key), default_starttls)
    else:
        starttls = default_starttls

    use_ssl = _coerce_bool(env.get(use_ssl_key), False) if use_ssl_key else False

    config = EmailConfig(
        host=host,
        port=port,
        sender=sender,
        recipients=recipients,
        user=user,
        password=password,
        starttls=starttls,
        use_ssl=use_ssl,
    )

    if require_recipients and not config.recipients:
        raise ValueError("Recipient list cannot be empty.")

    return config
