#!/usr/bin/env python3
"""Round monitor that validates each round with the report script and notifies admins."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Deque, Optional
import html
from datetime import datetime, UTC
from textwrap import dedent


ROUND_START_RE = re.compile(r"Starting Round: (\d+)")
ROUND_FINISH_RE = re.compile(r"Round completed:\s*(\d+)")
TASKS_COMPLETED_RE = re.compile(r"Tasks completed:\s*(\d+)")
ROUND_STATUS_RE = re.compile(r"Round status\s*\|\s*round=(\d+)\s*\|\s*epoch\s*([0-9.]+)/([0-9.]+)")


def expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path))).resolve()


def _load_env_file() -> None:
    """
    Load key=value pairs from a .env located in the current working directory (preferred)
    or alongside this script if not already exported.
    Existing environment variables take precedence.
    """
    candidate_paths = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]

    for env_path in candidate_paths:
        if not env_path.exists():
            continue
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
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
            # Non-fatal: proceed without .env contents if parsing fails
            pass
        # Only load first existing .env to avoid conflicting overrides
        break


_load_env_file()


def parse_codex_checkpoints() -> list[float]:
    raw = os.environ.get("CODEX_CHECK_FRACTIONS", "0.25,0.5,0.75,1.0")
    checkpoints: set[float] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = float(chunk)
        except ValueError:
            continue
        if 0.0 <= value <= 1.0:
            checkpoints.add(round(value, 4))
    result = sorted(checkpoints)
    if 1.0 not in result:
        result.append(1.0)
    return result


def _extract_first(pattern: str, text: str) -> Optional[str]:
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()
    return None


def _format_plain_tasks(completed: Optional[int], planned: Optional[int]) -> str:
    if completed is None and planned is None:
        return "unknown"
    if planned is None:
        return str(completed)
    if completed is None:
        return f"?/{planned}"
    return f"{completed}/{planned}"


def build_email_payload(
    *,
    round_id: int,
    status_label: str,
    status_badge: str,
    report_text: str,
    report_source: str,
    tasks_completed: Optional[int],
    planned_tasks: Optional[int],
    llm_summary: Optional[str],
    codex_success: bool,
    codex_stdout: str,
    codex_stderr: str,
    log_tail: Optional[str],
    checkpoint_label: Optional[str] = None,
) -> tuple[str, str, str]:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")

    def _extract_codex_final(stdout: str) -> Optional[str]:
        if not stdout:
            return None
        text = stdout.strip()
        if not text:
            return None
        marker = "\ncodex\n"
        if marker in text:
            text = text.split(marker)[-1]
        tokens_marker = "\ntokens used"
        if tokens_marker in text:
            text = text.split(tokens_marker, 1)[0]
        return text.strip() or None

    winner_line = _extract_first(r"Winner uid=([^\n]+)", report_text)
    miners_line = _extract_first(r"Miners evaluated \(from summary table\): ([^\n]+)", report_text)
    validators_line = _extract_first(r"Validators included \([^)]+\): ([^\n]+)", report_text)
    validator_uid = _extract_first(r"Validator UID: ([^\n]+)", report_text)
    hotkey_line = _extract_first(r"Hotkey: ([^\n]+)", report_text)
    round_context = _extract_first(r"Round context: ([^\n]+)", report_text)

    tasks_display = _format_plain_tasks(tasks_completed, planned_tasks)
    codex_status_text = "success" if codex_success else "failed"
    codex_transcript = codex_stdout.strip() if codex_stdout else ""
    codex_final = _extract_codex_final(codex_stdout)
    codex_final_summary = ""
    if codex_final:
        first_line = codex_final.splitlines()[0]
        codex_final_summary = first_line[:140] + ("…" if len(first_line) > 140 else "")
    subject_suffix = status_label
    if checkpoint_label and checkpoint_label != status_label:
        subject_suffix = f"{status_label} ({checkpoint_label})"

    subject = f"[validator] Round {round_id} {subject_suffix}"

    plain_lines = [
        f"Codex validator review at {timestamp}",
        f"Round: {round_id}",
        f"Status: {status_label}",
        f"Codex invocation: {codex_status_text}",
        f"Tasks completed (monitor): {tasks_display}",
        f"Report source: {report_source}",
    ]
    if codex_final:
        plain_lines.extend(["", "Codex verdict:", codex_final])
    if winner_line:
        plain_lines.append(f"Winner: {winner_line}")
    if miners_line:
        plain_lines.append(f"Miners evaluated: {miners_line}")
    if validators_line:
        plain_lines.append(f"Validators included: {validators_line}")
    if llm_summary:
        plain_lines.extend(["", "LLM summary:", llm_summary])
    plain_lines.extend(["", "Report excerpt:", report_text])
    if codex_transcript and codex_final and codex_transcript != codex_final:
        plain_lines.extend([
            "",
            f"Full Codex transcript: {len(codex_transcript.splitlines())} lines (see monitor logs).",
        ])
    if codex_stderr:
        stderr_line_count = len([line for line in codex_stderr.splitlines() if line.strip()])
        plain_lines.extend(["", f"Codex stderr: {stderr_line_count} lines (see monitor logs)."])
    body_text = "\n".join(plain_lines)

    def _badge(color: str, text: str) -> str:
        return (
            f"<span style=\"display:inline-block;padding:4px 10px;border-radius:999px;"
            f"background:{color};color:#0f172a;font-weight:600;font-size:12px;\">{html.escape(text)}</span>"
        )

    info_rows = [
        ("Round", str(round_id)),
        ("Status", status_label),
        ("Codex invocation", codex_status_text.title()),
        ("Tasks completed", tasks_display),
        ("Report source", report_source),
        ("Timestamp (UTC)", timestamp),
    ]
    if validator_uid:
        info_rows.insert(1, ("Validator UID", validator_uid))
    if hotkey_line:
        info_rows.insert(2, ("Hotkey", hotkey_line))
    if round_context:
        info_rows.append(("Round context", round_context))
    if checkpoint_label:
        info_rows.insert(2, ("Checkpoint", checkpoint_label))
    if codex_final:
        info_rows.insert(
            3,
            ("Codex final opinion", codex_final_summary or codex_final),
        )

    info_html = "".join(
        f"<tr><td style=\"padding:6px 12px;border-bottom:1px solid #1f2937;color:#a5b4fc;white-space:nowrap;\">{html.escape(label)}</td>"
        f"<td style=\"padding:6px 12px;border-bottom:1px solid #1f2937;color:#f8fafc;\">{html.escape(value)}</td></tr>"
        for (label, value) in info_rows
    )

    codex_output_html = ""
    if codex_transcript and codex_final and codex_transcript != codex_final:
        codex_output_html = (
            "<details style=\"margin-bottom:24px;\">"
            "<summary style=\"cursor:pointer;color:#60a5fa;font-weight:600;\">Full Codex transcript "
            f"({len(codex_transcript.splitlines())} lines)</summary>"
            f"<pre style=\"margin-top:12px;background:#0f172a;color:#e2e8f0;padding:16px;border-radius:10px;"
            f"font-family:'Fira Code',Monaco,monospace;font-size:13px;line-height:1.5;white-space:pre-wrap;\">"
            f"{html.escape(codex_transcript)}</pre>"
            "</details>"
        )

    codex_stderr_html = ""
    if codex_stderr:
        stderr_line_count = len([line for line in codex_stderr.splitlines() if line.strip()])
        codex_stderr_html = (
            "<details style=\"margin-bottom:24px;\">"
            "<summary style=\"cursor:pointer;color:#f97316;font-weight:600;\">Codex stderr "
            f"({stderr_line_count} lines)</summary>"
            f"<pre style=\"margin-top:12px;background:#7c2d12;color:#fff7ed;padding:16px;border-radius:10px;font-family:'Fira Code',Monaco,monospace;"
            f"font-size:13px;line-height:1.5;white-space:pre-wrap;\">{html.escape(codex_stderr)}</pre>"
            "</details>"
        )

    codex_final_html = (
        "<div style=\"background:rgba(37,99,235,0.12);border:1px solid rgba(129,140,248,0.35);"
        "padding:18px 20px;border-radius:14px;\">"
        "<p style=\"margin:0;color:#e2e8f0;font-size:15px;line-height:1.7;\">Codex verdict unavailable.</p>"
        "</div>"
    )
    if codex_final:
        safe_codex_final = html.escape(codex_final).replace("\n", "<br>")
        codex_final_html = (
            "<div style=\"background:rgba(37,99,235,0.12);border:1px solid rgba(129,140,248,0.35);"
            "padding:18px 20px;border-radius:14px;\">"
            "<p style=\"margin:0;color:#e2e8f0;font-size:15px;line-height:1.7;\">"
            f"{safe_codex_final}"
            "</p>"
            "</div>"
        )

    llm_html = ""
    if llm_summary:
        llm_html = (
            "<details style=\"margin-bottom:28px;\">"
            "<summary style=\"cursor:pointer;color:#38bdf8;font-weight:600;letter-spacing:0.01em;\">LLM summary</summary>"
            f"<pre style=\"margin-top:12px;background:#0f172a;color:#cbd5f5;padding:16px;border-radius:14px;font-family:'Fira Code',Monaco,monospace;"
            f"font-size:13px;line-height:1.6;white-space:pre-wrap;\">{html.escape(llm_summary)}</pre>"
            "</details>"
        )

    log_tail_html = ""
    if log_tail:
        lines = log_tail.splitlines()
        log_tail_html = (
            "<details style=\"margin-bottom:0;\">"
            "<summary style=\"cursor:pointer;color:#38bdf8;font-weight:600;letter-spacing:0.01em;\">Recent log tail "
            f"({len(lines)} lines)</summary>"
            f"<pre style=\"margin-top:12px;background:#0f172a;color:#cbd5f5;padding:16px;border-radius:14px;"
            f"font-family:'Fira Code',Monaco,monospace;font-size:13px;line-height:1.6;white-space:pre-wrap;\">"
            f"{html.escape(log_tail)}</pre>"
            "</details>"
        )

    insights = []
    if winner_line:
        insights.append(f"<strong>Winner:</strong> {html.escape(winner_line)}")
    if miners_line:
        insights.append(f"<strong>Miners evaluated:</strong> {html.escape(miners_line)}")
    if validators_line:
        insights.append(f"<strong>Validators sharing scores:</strong> {html.escape(validators_line)}")
    if not insights:
        insights.append("No additional highlights extracted from the report.")

    report_html = (
        "<details style=\"margin-bottom:28px;\">"
        "<summary style=\"cursor:pointer;color:#38bdf8;font-weight:600;letter-spacing:0.01em;\">Full round report</summary>"
        f"<pre style=\"margin-top:12px;background:#0f172a;color:#e2e8f0;padding:16px;border-radius:14px;font-family:'Fira Code',Monaco,monospace;"
        f"font-size:13px;line-height:1.6;white-space:pre-wrap;\">{html.escape(report_text)}</pre>"
        "</details>"
    )

    header_tag = ""
    if codex_final_summary:
        header_tag = (
            "<div style=\"margin-top:12px;display:inline-flex;align-items:center;padding:6px 14px;"
            "border-radius:999px;background:#0ea5e9;color:#0b1120;font-weight:600;font-size:13px;\">"
            f"{html.escape(codex_final_summary)}"
            "</div>"
        )

    status_colors = {
        "OK": "linear-gradient(135deg,#22c55e,#16a34a)",
        "ERROR": "linear-gradient(135deg,#ef4444,#b91c1c)",
        "FAIL": "linear-gradient(135deg,#ef4444,#b91c1c)",
        "WARN": "linear-gradient(135deg,#f59e0b,#d97706)",
    }
    badge_background = status_colors.get(status_label.upper(), "linear-gradient(135deg,#6366f1,#4338ca)")
    status_badge_html = dedent(
        f"""
        <div style="display:flex;align-items:center;gap:12px;">
            <span style="display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;border-radius:50%;background:{badge_background};color:#0b1120;font-weight:700;font-size:14px;letter-spacing:0.08em;">
                {html.escape(status_label.upper()[:4])}
            </span>
            <span style="font-weight:600;font-size:15px;color:#e2e8f0;letter-spacing:0.04em;">{html.escape(status_label.title())}</span>
        </div>
        """
    ).strip()

    body_html = dedent(
        f"""
        <div style="font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#050b18;color:#e2e8f0;padding:40px;">
            <div style="max-width:920px;margin:0 auto;background:linear-gradient(145deg,#0f172a,#111b30);border:1px solid rgba(56,189,248,0.16);box-shadow:0 24px 60px rgba(8,16,35,0.45);border-radius:24px;padding:44px;">
                <header style="display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:32px;">
                    <div style="flex:1 1 auto;">
                        <p style="margin:0;color:#64748b;font-size:13px;text-transform:uppercase;letter-spacing:0.14em;">Codex Monitor</p>
                        <h1 style="margin:6px 0 0;color:#38bdf8;font-size:32px;letter-spacing:-0.015em;">Validator Review</h1>
                        <p style="margin:14px 0 0;color:#94a3b8;font-size:15px;max-width:540px;">Automated analysis generated by Codex for the latest validator round.</p>
                    </div>
                    <div style="flex:0 0 auto;display:flex;flex-direction:column;align-items:flex-end;gap:12px;">
                        {status_badge_html}
                        {header_tag}
                    </div>
                </header>
                <section style="margin-bottom:28px;">
                    <table style="width:100%;border-collapse:separate;border-spacing:0;background:rgba(15,23,42,0.92);border-radius:20px;overflow:hidden;border:1px solid rgba(148,163,184,0.18);">
                        {info_html}
                    </table>
                </section>
                <section style="margin-bottom:28px;">
                    <h3 style="margin:0 0 12px;color:#38bdf8;font-size:18px;">Highlights</h3>
                    <p style="margin:0;color:#e2e8f0;font-size:15px;line-height:1.7;">{'<br>'.join(insights)}</p>
                </section>
                <section style="margin-bottom:28px;">
                    <h3 style="margin:0 0 12px;color:#38bdf8;font-size:18px;">Codex assessment</h3>
                    {codex_final_html}
                    {codex_output_html}
                    {codex_stderr_html}
                </section>
                {llm_html}
                {report_html}
                {log_tail_html}
            </div>
        </div>
        """
    ).strip()

    return subject, body_text, body_html


def resolve_log_path(pm2_identifier: Optional[str], explicit_path: Optional[str]) -> Path:
    if explicit_path:
        return expand(explicit_path)
    if not pm2_identifier:
        return expand("~/.pm2/logs/validator-out.log")

    try:
        result = subprocess.run(
            ["pm2", "jlist"],
            check=True,
            capture_output=True,
            text=True,
        )
        processes = json.loads(result.stdout or "[]")
    except Exception as exc:  # pragma: no cover - runtime behaviour
        raise RuntimeError("Failed to fetch pm2 process list. Provide --log-path instead.") from exc

    match = None
    for proc in processes:
        name = proc.get("name")
        pm_id = proc.get("pm_id")
        if str(pm2_identifier).isdigit():
            if int(pm_id) == int(pm2_identifier):
                match = proc
                break
        elif name == pm2_identifier:
            match = proc
            break

    if not match:
        raise ValueError(f"pm2 process {pm2_identifier!r} not found. Provide --log-path explicitly.")

    out_log = match.get("pm2_env", {}).get("pm_out_log_path")
    if not out_log:
        raise ValueError(f"pm2 process {pm2_identifier!r} does not have an out log path.")
    return expand(out_log)


def capture_report(report_script: Path, round_id: int, *, pm2_identifier: Optional[str], log_path: Optional[Path]) -> str:
    cmd: list[str] = [str(report_script), "--round", str(round_id)]
    if log_path:
        cmd.extend(["--path", str(log_path)])
    elif pm2_identifier:
        cmd.extend(["--pm2", pm2_identifier])
    else:
        cmd.extend(["--pm2", "validator"])

    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"report.sh exited with {completed.returncode}:\n{completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout.strip()


def run_llm_evaluation(report_text: str, *, llm_command: Optional[str]) -> Optional[str]:
    command = llm_command or os.environ.get("REPORT_MONITOR_LLM_COMMAND")
    if not command:
        return None

    try:
        proc = subprocess.run(
            shlex.split(command),
            input=report_text,
            text=True,
            capture_output=True,
            check=True,
        )
    except Exception as exc:  # pragma: no cover - runtime behaviour
        raise RuntimeError(f"Failed to execute LLM command: {command}") from exc

    return proc.stdout.strip()


def invoke_codex(
    report_script: Path,
    round_id: int,
    *,
    status_label: str,
    report_content: str,
    llm_summary: Optional[str] = None,
) -> tuple[bool, str, str]:
    codex_runner = (report_script.parent / "run_codex.sh").resolve()
    if not codex_runner.exists() or not os.access(codex_runner, os.X_OK):
        print(f"[monitor] Codex runner not found at {codex_runner}")
        return False, "", f"Codex runner not found at {codex_runner}"

    cmd = [str(codex_runner), "--round", str(round_id), "--status", status_label]
    if llm_summary:
        cmd.extend(["--llm-summary", llm_summary])

    try:
        completed = subprocess.run(
            cmd,
            input=report_content,
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception as exc:
        print(f"[monitor] Codex run failed: {exc}")
        return False, "", str(exc)

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if stdout:
        print(f"[monitor] Codex stdout ({len(stdout.splitlines())} lines)")
    if stderr:
        print(f"[monitor] Codex stderr ({len(stderr.splitlines())} lines)")
    return completed.returncode == 0, stdout, stderr


def _bool_from_env(value: Optional[str], default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


@dataclass
class EmailConfig:
    host: Optional[str]
    port: int
    use_tls: bool
    use_ssl: bool
    username: Optional[str]
    password: Optional[str]
    sender: Optional[str]
    recipients: list[str]

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "EmailConfig":
        def pick(arg_name: str, env_keys: list[str], default: Optional[str] = None) -> Optional[str]:
            value = getattr(args, arg_name, None)
            if value:
                return value
            for key in env_keys:
                env_val = os.environ.get(key)
                if env_val:
                    return env_val
            return default

        raw_recipients = pick(
            "email_to",
            ["REPORT_MONITOR_EMAIL_TO", "SMTP_TO"],
            default=None,
        )
        recipients = [addr.strip() for addr in (raw_recipients or "").split(",") if addr.strip()]

        port_str = pick("smtp_port", ["REPORT_MONITOR_SMTP_PORT", "SMTP_PORT"], default="587")
        use_tls_raw = pick("smtp_tls", ["REPORT_MONITOR_SMTP_TLS", "SMTP_STARTTLS"], default=None)
        use_ssl_raw = pick("smtp_ssl", ["REPORT_MONITOR_SMTP_SSL", "SMTP_SSL"], default=None)

        host = pick("smtp_host", ["REPORT_MONITOR_SMTP_HOST", "SMTP_HOST"])
        sender = pick("email_from", ["REPORT_MONITOR_EMAIL_FROM", "SMTP_FROM"])
        username = pick("smtp_username", ["REPORT_MONITOR_SMTP_USERNAME", "SMTP_USER"])
        password = pick("smtp_password", ["REPORT_MONITOR_SMTP_PASSWORD", "SMTP_PASS"])

        try:
            port = int(port_str or 587)
        except ValueError:
            port = 587

        use_tls = _bool_from_env(use_tls_raw, default=True)
        use_ssl = _bool_from_env(use_ssl_raw, default=False)

        if not use_ssl and port == 465 and not use_tls:
            use_ssl = True

        return cls(
            host=host,
            port=port,
            use_tls=use_tls,
            use_ssl=use_ssl,
            username=username,
            password=password,
            sender=sender,
            recipients=recipients,
        )

    def is_configured(self) -> bool:
        return bool(self.host and self.sender and self.recipients)


def send_email(config: EmailConfig, subject: str, body_text: str, body_html: Optional[str] = None) -> None:
    if not config.is_configured():
        print("[email] configuration missing; printing notification instead:")
        print(f"Subject: {subject}")
        print(body_text)
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)
    message.set_content(body_text)
    if body_html:
        message.add_alternative(body_html, subtype="html")

    try:
        import smtplib

        if config.use_ssl:
            with smtplib.SMTP_SSL(config.host, config.port) as server:
                if config.username and config.password:
                    server.login(config.username, config.password)
                server.send_message(message)
        elif config.use_tls:
            with smtplib.SMTP(config.host, config.port) as server:
                server.starttls()
                if config.username and config.password:
                    server.login(config.username, config.password)
                server.send_message(message)
        else:
            with smtplib.SMTP(config.host, config.port) as server:
                if config.username and config.password:
                    server.login(config.username, config.password)
                server.send_message(message)
    except Exception as exc:  # pragma: no cover - runtime behaviour
        raise RuntimeError("Failed to send notification email.") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pm2", metavar="ID_OR_NAME", help="pm2 identifier for the validator process.")
    parser.add_argument("--log-path", help="Path to the validator stdout log (overrides --pm2).")
    parser.add_argument("--report-script", default=None, help="Path to report.sh (defaults to sibling script).")
    parser.add_argument("--block-delay", type=int, default=3, help="Number of blocks to wait before running the report.")
    parser.add_argument("--seconds-per-block", type=float, default=12.0, help="Seconds per block estimate.")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Polling interval in seconds when tailing logs.")
    parser.add_argument("--llm-command", help="Command to run for LLM analysis. Falls back to REPORT_MONITOR_LLM_COMMAND env.")

    parser.add_argument("--smtp-host", help="SMTP host.")
    parser.add_argument("--smtp-port", help="SMTP port.")
    parser.add_argument("--smtp-tls", help="Use TLS (true/false).")
    parser.add_argument("--smtp-username", help="SMTP username.")
    parser.add_argument("--smtp-password", help="SMTP password.")
    parser.add_argument("--email-from", help="Notification sender email.")
    parser.add_argument("--email-to", help="Comma separated recipients.")

    return parser


def evaluate_report(report_text: str) -> bool:
    return "[FAIL]" not in report_text and "Error:" not in report_text


def main() -> None:  # pragma: no cover - CLI entry
    parser = build_parser()
    args = parser.parse_args()

    report_script = Path(args.report_script).resolve() if args.report_script else Path(__file__).resolve().with_name("report.sh")
    if not report_script.exists():
        raise FileNotFoundError(f"report script not found at {report_script}")

    log_path = resolve_log_path(args.pm2, args.log_path)
    if not log_path.exists():
        raise FileNotFoundError(f"log file not found at {log_path}")

    email_config = EmailConfig.from_args(args)
    seconds_to_wait = args.block_delay * args.seconds_per_block
    report_source = str(log_path) if args.log_path else f"pm2:{args.pm2 or 'validator'}"

    print(f"[monitor] Watching {log_path} (pm2={args.pm2 or 'N/A'})")
    print(f"[monitor] Reports will run ~{seconds_to_wait:.1f}s after round completion.")

    # We keep recent lines so we can include context in notifications
    context_buffer: Deque[str] = deque(maxlen=200)

    pending_rounds: dict[int, float] = {}
    pending_tasks: dict[int, Optional[int]] = {}
    codex_checkpoints = parse_codex_checkpoints()
    codex_progress: dict[int, set[float]] = {}

    with log_path.open("r", encoding="utf-8", errors="replace") as stream:
        stream.seek(0, os.SEEK_END)

        while True:
            position = stream.tell()
            line = stream.readline()
            if not line:
                time.sleep(args.poll_interval)
                stream.seek(position)
            else:
                context_buffer.append(line.rstrip())

                start_match = ROUND_START_RE.search(line)
                if start_match:
                    round_id = int(start_match.group(1))
                    print(f"[monitor] Observed start of round {round_id}")
                    codex_progress[round_id] = set()
                    continue

                finish_match = ROUND_FINISH_RE.search(line)
                if finish_match:
                    round_id = int(finish_match.group(1))
                    pending_rounds[round_id] = time.time() + seconds_to_wait
                    pending_tasks.setdefault(round_id, None)
                    print(f"[monitor] Round {round_id} completed; scheduling verification.")
                    codex_progress.setdefault(round_id, set()).add(1.0)
                    continue

                tasks_match = TASKS_COMPLETED_RE.search(line)
                if tasks_match:
                    # Associate with most recent pending round
                    if pending_rounds:
                        latest_round = max(pending_rounds.keys(), key=pending_rounds.get)
                        pending_tasks[latest_round] = int(tasks_match.group(1))

                status_match = ROUND_STATUS_RE.search(line)
                if status_match:
                    round_id = int(status_match.group(1))
                    current_epoch = float(status_match.group(2))
                    target_epoch = float(status_match.group(3))
                    if target_epoch > 0:
                        fraction = max(min(current_epoch / target_epoch, 1.0), 0.0)
                        triggered = codex_progress.setdefault(round_id, set())
                        for checkpoint in codex_checkpoints:
                            if checkpoint >= 1.0:
                                continue  # final handled on completion
                            if checkpoint in triggered:
                                continue
                            if fraction + 1e-6 >= checkpoint:
                                triggered.add(checkpoint)
                                continue
            now = time.time()
            ready = [rid for rid, due in pending_rounds.items() if due <= now]
            for round_id in ready:
                try:
                    report_output = capture_report(
                        report_script,
                        round_id,
                        pm2_identifier=args.pm2,
                        log_path=log_path if args.log_path else None,
                    )
                except Exception as exc:
                    log_tail = "\n".join(context_buffer)
                    error_message = f"Report generation failed: {exc}"
                    subject, body_text, body_html = build_email_payload(
                        round_id=round_id,
                        status_label="REPORT FAILURE",
                        status_badge="REPORT FAILURE",
                        report_text=error_message,
                        report_source=report_source,
                        tasks_completed=pending_tasks.get(round_id),
                        planned_tasks=None,
                        llm_summary=None,
                        codex_success=False,
                        codex_stdout="",
                        codex_stderr="Codex not invoked due to report generation failure.",
                        log_tail=log_tail,
                    )
                    send_email(email_config, subject, body_text, body_html)
                    pending_rounds.pop(round_id, None)
                    pending_tasks.pop(round_id, None)
                    continue

                is_healthy = evaluate_report(report_output)
                llm_summary = None
                try:
                    llm_summary = run_llm_evaluation(report_output, llm_command=args.llm_command)
                except Exception as exc:
                    print(f"[monitor] LLM evaluation failed: {exc}")

                tasks_completed = pending_tasks.get(round_id)
                status_word = "OK" if is_healthy else "ERROR"

                planned_tasks_value = None
                for pattern in (r"Planned tasks:\s*([0-9]+)", r"Tasks to Execute:\s*([0-9]+)"):
                    extracted = _extract_first(pattern, report_output)
                    if extracted and extracted.isdigit():
                        planned_tasks_value = int(extracted)
                        break

                log_tail = "\n".join(context_buffer)
                report_for_codex = report_output
                if log_tail:
                    report_for_codex = (
                        f"{report_output}\n\nRecent log tail (last {len(context_buffer)} lines):\n{log_tail}"
                    )

                codex_success, codex_stdout, codex_stderr = invoke_codex(
                    report_script,
                    round_id,
                    status_label=status_word,
                    report_content=report_for_codex,
                    llm_summary=llm_summary,
                )

                subject, body_text, body_html = build_email_payload(
                    round_id=round_id,
                    status_label=status_word,
                    status_badge=status_word,
                    report_text=report_output,
                    report_source=report_source,
                    tasks_completed=tasks_completed,
                    planned_tasks=planned_tasks_value,
                    llm_summary=llm_summary,
                    codex_success=codex_success,
                    codex_stdout=codex_stdout,
                    codex_stderr=codex_stderr,
                    log_tail=log_tail,
                )

                send_email(email_config, subject, body_text, body_html)

                winner_uid: Optional[str] = None
                if winner_line:
                    uid_match = re.search(r"uid=(\d+)", winner_line)
                    if uid_match:
                        winner_uid = uid_match.group(1)

                if winner_uid:
                    miner_cmd = [
                        str(report_script.parent / "miner_report.sh"),
                        "--uid",
                        winner_uid,
                        "--round",
                        str(round_id),
                        "--lines",
                        "20000",
                        "--codex",
                    ]
                    if args.log_path:
                        miner_cmd.extend(["--path", str(log_path)])
                    else:
                        miner_cmd.extend(["--pm2", args.pm2 or "validator"])
                    try:
                        subprocess.run(miner_cmd, check=False)
                    except Exception as exc:
                        print(f"[monitor] Miner audit report failed: {exc}")

                pending_rounds.pop(round_id, None)
                pending_tasks.pop(round_id, None)
                codex_progress.pop(round_id, None)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    try:
        main()
    except KeyboardInterrupt:
        print("\n[monitor] Stopping round monitor.")
