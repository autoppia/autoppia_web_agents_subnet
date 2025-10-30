#!/usr/bin/env python3
"""
Send an email alert to subnet administrators using SMTP settings from environment variables.
Usage:
    python scripts/validator/utils/alert_admins.py "Subject" "Body text"

If SMTP configuration is missing, the message is printed to stdout instead.
"""

from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path


def load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or key in os.environ:
                continue
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            os.environ[key] = value
    except Exception:
        pass


def to_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    load_env(repo_root / ".env")

    args = sys.argv[1:]
    subject = args[0] if args else os.environ.get("ALERT_SUBJECT") or "Autoppia alert"
    body = args[1] if len(args) > 1 else os.environ.get("ALERT_BODY") or "No message provided."

    recipients = [addr.strip() for addr in (os.environ.get("REPORT_MONITOR_EMAIL_TO") or os.environ.get("SMTP_TO") or "").split(",") if addr.strip()]
    sender = os.environ.get("REPORT_MONITOR_EMAIL_FROM") or os.environ.get("SMTP_FROM")
    host = os.environ.get("REPORT_MONITOR_SMTP_HOST") or os.environ.get("SMTP_HOST")
    port_raw = os.environ.get("REPORT_MONITOR_SMTP_PORT") or os.environ.get("SMTP_PORT") or "587"
    username = os.environ.get("REPORT_MONITOR_SMTP_USERNAME") or os.environ.get("SMTP_USER")
    password = os.environ.get("REPORT_MONITOR_SMTP_PASSWORD") or os.environ.get("SMTP_PASS")
    use_tls = to_bool(os.environ.get("REPORT_MONITOR_SMTP_TLS") or os.environ.get("SMTP_STARTTLS"), default=True)
    use_ssl = to_bool(os.environ.get("REPORT_MONITOR_SMTP_SSL") or os.environ.get("SMTP_SSL"), default=False)

    try:
        port = int(port_raw)
    except ValueError:
        port = 587

    if not use_ssl and port == 465 and not use_tls:
        use_ssl = True

    if not (recipients and sender and host):
        print("[alert_admins] Missing SMTP configuration; message:")
        print(f"Subject: {subject}")
        print(body)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    msg.add_alternative(
        f"<div style='font-family:Segoe UI, sans-serif; padding:16px; background:#0b1120; color:#e2e8f0;'>"
        f"<h3 style='margin-top:0;'>Autoppia validator alert</h3>"
        f"<pre style='background:#111827; padding:16px; border-radius:8px; font-family:\"Fira Code\", monospace; white-space:pre-wrap;'>{body}</pre>"
        f"</div>",
        subtype="html",
    )

    if use_ssl:
        with smtplib.SMTP_SSL(host, port) as server:
            if username and password:
                server.login(username, password)
            server.send_message(msg)
    elif use_tls:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            if username and password:
                server.login(username, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as server:
            if username and password:
                server.login(username, password)
            server.send_message(msg)

    print("[alert_admins] Notification sent.")


if __name__ == "__main__":
    main()
