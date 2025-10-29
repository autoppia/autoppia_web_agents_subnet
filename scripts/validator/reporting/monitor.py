from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from .emailing import EmailConfig, load_email_config_from_env, send_email
from .state import load_last_state, save_last_state

REPO_ROOT = Path(__file__).resolve().parents[3]
ROUND_COMPLETE_MARK = "✅ Round complete"
ROUND_ID_RE = re.compile(r"(validator_round_[A-Za-z0-9_\-]+)")


def read_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Wrapper around os.getenv that keeps typing explicit."""
    value = os.getenv(key)
    return value if value is not None else default


def collect_lines_from_pm2(identifier: str, lines: int) -> list[str]:
    """Fetch recent pm2 logs for the validator process."""
    cmd = ["pm2", "logs", identifier, "--lines", str(lines), "--nostream"]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"pm2 logs failed: {completed.stderr.strip() or 'unknown error'}")
    raw = completed.stdout.strip().splitlines()
    return raw[-lines:] if lines > 0 else raw


def extract_latest_round(lines: Sequence[str]) -> tuple[Optional[str], Optional[int]]:
    """Return the latest completed round identifier and its index in the log."""
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if ROUND_COMPLETE_MARK in line:
            rid = None
            match = ROUND_ID_RE.search(line)
            if match:
                rid = match.group(1)
            else:
                for inner_idx in range(max(0, idx - 200), idx + 1):
                    inner_match = ROUND_ID_RE.search(lines[inner_idx])
                    if inner_match:
                        rid = inner_match.group(1)
                        break
            return rid, idx
    return None, None


def extract_score_snippet(lines: Sequence[str], marker_index: int) -> str:
    """Slice the score table / winner snippet that accompanies a round completion."""
    start_idx = None
    for i in range(max(0, marker_index - 400), marker_index + 1):
        if "Round Summary — Miners" in lines[i]:
            start_idx = i
    if start_idx is not None:
        return "\n".join(lines[start_idx : marker_index + 1])
    for i in range(marker_index, max(marker_index - 400, -1), -1):
        if "🏆 Winner uid=" in lines[i]:
            return "\n".join(lines[i : marker_index + 1])
    return "[No score table or winner line detected in recent logs.]"


def run_analyzer(pm2_identifier: str, netuid: int, network: Optional[str], lines: int) -> str:
    """Invoke the analyzer helper script to gather GPT-5 insights."""
    candidates = [
        REPO_ROOT / "autoppia_web_agents_subnet" / "scripts" / "validator" / "analyze_validator_logs.py",
        REPO_ROOT / "scripts" / "validator" / "analyze_validator_logs.py",
    ]
    analyzer = next((path for path in candidates if path.exists()), None)
    if analyzer is None:
        return "[Analyzer script not found]"

    cmd = [
        sys.executable,
        str(analyzer),
        "--pm2",
        pm2_identifier,
        "--rounds",
        "1",
        "--lines",
        str(lines),
        "--commitments-count",
        "3",
        "--commitments-netuid",
        str(netuid),
    ]
    if network:
        cmd.extend(["--commitments-network", network])

    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        return f"[Analyzer failed: {completed.stderr.strip()}]"
    return completed.stdout.strip()


def run_show_commitments(netuid: int, network: Optional[str], count: int = 1) -> str:
    """Invoke show_commitments helper to capture latest stakes snapshot."""
    candidates = [
        REPO_ROOT / "autoppia_web_agents_subnet" / "scripts" / "validator" / "show_commitments.py",
        REPO_ROOT / "scripts" / "validator" / "show_commitments.py",
    ]
    script = next((path for path in candidates if path.exists()), None)
    if script is None:
        return "[show_commitments.py not found]"

    cmd = [
        sys.executable,
        str(script),
        "-N",
        str(count),
    ]
    if network:
        cmd.extend(["--network", network])
    if netuid is not None:
        cmd.extend(["--netuid", str(netuid)])

    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        return f"[show_commitments.py failed: {completed.stderr.strip()}]"
    return completed.stdout.strip()


def scan_errors(lines: Sequence[str]) -> list[str]:
    """Return a trimmed list of recent error lines to include in alert emails."""
    bad_tokens = ("ERROR", "Traceback", "❌", "exception", "TypeError", "CancelledError")
    hits: list[str] = []
    for line in lines[-600:]:
        if any(token.lower() in line.lower() for token in bad_tokens):
            hits.append(line)
    return hits[-40:]


def build_email(round_id: str, score_snippet: str, insights: str, commitments: str, error_lines: list[str]) -> tuple[str, str]:
    """Compose the monitor round email subject and HTML body."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    subject = f"Autoppia Round Report: {round_id} — All good in last round"
    errors_html = "<br>".join(error_lines) if error_lines else "None"
    html = f"""
    <h3>Autoppia Validator — Round Report</h3>
    <p><b>Round:</b> {round_id}<br>
       <b>Time (UTC):</b> {timestamp}</p>
    <h4>Summary</h4>
    <p>All good in last round. Below are the highlights:</p>
    <h4>Score Table / Winner</h4>
    <pre style="white-space: pre-wrap;">{score_snippet}</pre>
    <h4>LLM Insights (GPT-5)</h4>
    <pre style="white-space: pre-wrap;">{insights}</pre>
    <h4>Commitments Snapshot (show_commitments)</h4>
    <pre style="white-space: pre-wrap;">{commitments}</pre>
    <h4>Recent Errors (tail)</h4>
    <pre style="white-space: pre-wrap;">{errors_html}</pre>
    """.strip()
    return subject, html


def load_monitor_email_config(env: Optional[dict[str, str]] = None) -> EmailConfig:
    """Load the email settings for the monitor script."""
    try:
        return load_email_config_from_env(
            host_key="EMAIL_SMTP_HOST",
            port_key="EMAIL_SMTP_PORT",
            user_key="EMAIL_SMTP_USER",
            password_key="EMAIL_SMTP_PASSWORD",
            sender_key="EMAIL_FROM",
            recipients_key="EMAIL_TO",
            default_port=587,
            env=env,
            require_recipients=True,
        )
    except ValueError as exc:
        raise RuntimeError("Email settings incomplete: EMAIL_SMTP_HOST/EMAIL_FROM/EMAIL_TO required.") from exc


@dataclass
class MonitorSettings:
    pm2_identifier: str
    netuid: int
    network: Optional[str]
    lines: int
    poll_seconds: int
    state_file: Path


def monitor_loop(settings: MonitorSettings) -> None:
    """Main blocking loop that watches pm2 logs and dispatches per-round emails."""
    last_round_id = load_last_state(settings.state_file)

    while True:
        try:
            lines = collect_lines_from_pm2(settings.pm2_identifier, settings.lines)
        except Exception as exc:  # noqa: BLE001
            print(f"[monitor] failed to read pm2 logs: {exc}", file=sys.stderr)
            time.sleep(settings.poll_seconds)
            continue

        round_id, marker_index = extract_latest_round(lines)
        if round_id and marker_index is not None and round_id != last_round_id:
            score = extract_score_snippet(lines, marker_index)
            try:
                insights = run_analyzer(settings.pm2_identifier, settings.netuid, settings.network, settings.lines)
            except Exception as exc:  # noqa: BLE001
                insights = f"[Analyzer unavailable: {exc}]"
            try:
                commitments = run_show_commitments(settings.netuid, settings.network, count=1)
            except Exception as exc:  # noqa: BLE001
                commitments = f"[Commitments unavailable: {exc}]"
            errors = scan_errors(lines)

            subject, html = build_email(round_id, score, insights, commitments, errors)
            try:
                config = load_monitor_email_config()
                send_email(config, subject, html)
                save_last_state(settings.state_file, round_id)
                last_round_id = round_id
                print(f"[monitor] emailed report for {round_id}")
            except Exception as exc:  # noqa: BLE001
                print(f"[monitor] failed to send email: {exc}", file=sys.stderr)

        time.sleep(settings.poll_seconds)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor validator rounds and email reports.")
    parser.add_argument("--pm2", dest="pm2_identifier", default=read_env("PM2_IDENTIFIER"), help="pm2 id or name")
    parser.add_argument("--netuid", type=int, default=int(read_env("NETUID", "36")))
    parser.add_argument("--network", default=read_env("SUBTENSOR_NETWORK", None))
    parser.add_argument("--lines", type=int, default=int(read_env("MONITOR_LOG_LINES", "4000")))
    parser.add_argument("--poll", type=int, default=int(read_env("MONITOR_POLL_SECONDS", "60")))
    parser.add_argument(
        "--state-file",
        default=read_env("MONITOR_STATE_FILE", str(REPO_ROOT / "data" / "monitor" / "last_round_id.txt")),
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    if not args.pm2_identifier:
        raise SystemExit("Provide --pm2 or set PM2_IDENTIFIER env var.")

    settings = MonitorSettings(
        pm2_identifier=args.pm2_identifier,
        netuid=args.netuid,
        network=args.network,
        lines=args.lines,
        poll_seconds=args.poll,
        state_file=Path(args.state_file),
    )
    monitor_loop(settings)


def cli_main() -> None:
    main()
