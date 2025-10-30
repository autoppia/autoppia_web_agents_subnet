#!/usr/bin/env python3
from __future__ import annotations

import os
import socket
import sys
from datetime import datetime
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]

if __package__ in (None, ""):
    sys.path.append(str(PACKAGE_ROOT))
    from reporting.batch.forward import ForwardReportData, ForwardReportPaths, build_forward_report_data  # type: ignore
    from reporting.common import EmailConfig, parse_recipients, send_email  # type: ignore
else:  # pragma: no cover
    from ..common import EmailConfig, parse_recipients, send_email
    from .forward import ForwardReportData, ForwardReportPaths, build_forward_report_data

from html_report_template import render_html_report

# Optional .env support
try:  # pragma: no cover - optional dependency
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def load_email_config() -> EmailConfig:
    env = os.environ

    port = int(env.get("SMTP_PORT", "25"))
    starttls = env.get("SMTP_STARTTLS", "true").lower() in ("1", "true", "yes")

    return EmailConfig(
        host=env.get("SMTP_HOST", "localhost"),
        port=port,
        user=env.get("SMTP_USER") or None,
        password=env.get("SMTP_PASS") or None,
        sender=env.get("SMTP_FROM", "reports@localhost"),
        recipients=parse_recipients(env.get("SMTP_TO", "")),
        starttls=starttls,
        use_ssl=(port == 465) and (not starttls),
    )


def build_report_payload() -> ForwardReportData:
    paths = ForwardReportPaths.from_env()
    return build_forward_report_data(paths)


def main() -> None:
    email_config = load_email_config()
    if not email_config.recipients:
        print("⚠️  SMTP_TO vacío. No hay destinatarios.")
        return

    report_data = build_report_payload()
    host = socket.gethostname()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    body_html = render_html_report(
        report_data.forwards_table,
        report_data.coldkey_global_table,
        report_data.coldkey_cwu_table,
        report_data.last_forward_tasks,
        report_data.task_summary,
        host,
        timestamp,
    )
    body_text = f"Autoppia Web Agents Report – {timestamp}\nVer versión HTML."
    subject = f"[Autoppia] Reporte horario – {timestamp}"
    send_email(email_config, subject, body_html, body_text)
    print("✅ Email enviado.")


if __name__ == "__main__":
    main()
