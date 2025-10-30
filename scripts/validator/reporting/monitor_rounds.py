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
) -> None:
    codex_runner = (report_script.parent / "run_codex.sh").resolve()
    if not codex_runner.exists() or not os.access(codex_runner, os.X_OK):
        print(f"[monitor] Codex runner not found at {codex_runner}")
        return

    cmd = [str(codex_runner), "--round", str(round_id), "--status", status_label]
    if llm_summary:
        cmd.extend(["--llm-summary", llm_summary])

    try:
        subprocess.run(
            cmd,
            input=report_content,
            text=True,
            check=False,
        )
    except Exception as exc:
        print(f"[monitor] Codex run failed: {exc}")


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
                                try:
                                    intermediate_report = capture_report(
                                        report_script,
                                        round_id,
                                        pm2_identifier=args.pm2,
                                        log_path=log_path if args.log_path else None,
                                    )
                                except Exception as exc:
                                    intermediate_report = (
                                        f"[monitor] Failed to capture report at {checkpoint:.0%}: {exc}\n"
                                    )
                                log_tail = "\n".join(context_buffer)
                                report_for_codex = intermediate_report
                                if log_tail:
                                    report_for_codex = (
                                        f"{intermediate_report}\n\n"
                                        f"Recent log tail (last {len(context_buffer)} lines):\n{log_tail}"
                                    )
                                status_label = f"CHECKPOINT@{int(checkpoint * 100)}pct"
                                invoke_codex(
                                    report_script,
                                    round_id,
                                    status_label=status_label,
                                    report_content=report_for_codex,
                                )

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
                    subject = f"[validator] Round {round_id} report FAILED"
                    body = f"Report generation failed: {exc}\n\nRecent log tail:\n" + "\n".join(context_buffer)
                    send_email(email_config, subject, body)
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
                status_color = "#1b5e20" if is_healthy else "#b71c1c"
                subject = f"[validator] Round {round_id} {status_word}"

                body_lines = [
                    f"Round {round_id} verification status: {status_word}",
                    f"Tasks completed (reported): {tasks_completed if tasks_completed is not None else 'unknown'}",
                    "",
                    "Report output:",
                    report_output,
                ]
                if llm_summary:
                    body_lines.extend(["", "LLM analysis:", llm_summary])

                body_text = "\n".join(body_lines)

                report_html = (
                    "<pre style=\"background:#111827;color:#E5E7EB;padding:16px;border-radius:8px;"
                    "font-family:'Fira Code',Monaco,monospace;font-size:13px;line-height:1.45;"
                    "white-space:pre-wrap;\">"
                    f"{html.escape(report_output)}</pre>"
                )

                llm_html = ""
                if llm_summary:
                    llm_html = (
                        "<h3 style=\"margin:16px 0 8px;font-family:'Segoe UI',sans-serif;"
                        "color:#0d47a1;\">LLM analysis</h3>"
                        "<pre style=\"background:#0f172a;color:#E5E7EB;padding:16px;border-radius:8px;"
                        "font-family:'Fira Code',Monaco,monospace;font-size:13px;line-height:1.45;"
                        "white-space:pre-wrap;\">"
                        f"{html.escape(llm_summary)}</pre>"
                    )

                def _extract(pattern: str, text: str) -> Optional[str]:
                    match = re.search(pattern, text)
                    if match:
                        return match.group(1).strip()
                    return None

                winner_line = _extract(r"Winner uid=([^\n]+)", report_output)
                miners_line = _extract(r"Miners evaluated \(from summary table\): ([0-9]+)", report_output)
                validators_line = _extract(r"Validators included \([^)]+\): ([^\n]+)", report_output)

                body_html = [
                    "<div style=\"font-family:'Segoe UI',sans-serif;background:#0b1120;color:#e2e8f0;padding:24px;\">",
                    "  <h2 style=\"margin-top:0;color:#38bdf8;\">Validator round report</h2>",
                    "  <p style=\"margin:8px 0;font-size:15px;\">",
                    f"    <strong>Round:</strong> {round_id}<br>",
                    f"    <strong>Status:</strong> <span style=\\\"color:{status_color};font-weight:600;\\\">{status_word}</span><br>",
                    f"    <strong>Tasks completed:</strong> {html.escape(str(tasks_completed) if tasks_completed is not None else 'unknown')}"
                ]

                if winner_line:
                    body_html.append(f"<br>    <strong>Winner:</strong> {html.escape(winner_line)}")
                if miners_line:
                    body_html.append(f"<br>    <strong>Miners evaluated:</strong> {html.escape(miners_line)}")
                if validators_line:
                    body_html.append(f"<br>    <strong>Validators sharing scores:</strong> {html.escape(validators_line)}")

                body_html.extend([
                    "  </p>",
                    "  <h3 style=\"margin:24px 0 12px;color:#38bdf8;\">Report output</h3>",
                    f"  {report_html}",
                    f"  {llm_html}",
                    "</div>",
                ])

                body_html = "\n".join(body_html)

                send_email(email_config, subject, body_text, body_html)

                log_tail = "\n".join(context_buffer)
                report_for_codex = report_output
                if log_tail:
                    report_for_codex = (
                        f"{report_output}\n\nRecent log tail (last {len(context_buffer)} lines):\n{log_tail}"
                    )
                invoke_codex(
                    report_script,
                    round_id,
                    status_label=status_word,
                    report_content=report_for_codex,
                    llm_summary=llm_summary,
                )
                pending_rounds.pop(round_id, None)
                pending_tasks.pop(round_id, None)
                codex_progress.pop(round_id, None)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    try:
        main()
    except KeyboardInterrupt:
        print("\n[monitor] Stopping round monitor.")
