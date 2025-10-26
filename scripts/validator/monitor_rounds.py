#!/usr/bin/env python3
from __future__ import annotations

"""
Continuous monitor that watches pm2 logs for round completion and emails a
summary report every round (~4 epochs).

What it does:
- Polls pm2 logs for the validator process (by id or name)
- Detects the most recent completed round from logs ("✅ Round complete")
- Runs analyzer script to get GPT-5 insights and fetches commitments snapshot
- Extracts a score summary from logs (table when available; else WTA winner)
- Sends an email report to admins (env-configured SMTP)

Environment variables (override via CLI when provided by pm2 ecosystem):
- PM2_IDENTIFIER: pm2 id or process name (e.g., "11" or "Autoppi")
- NETUID: subnet netuid (default: 36)
- SUBTENSOR_NETWORK: e.g. "finney"
- OPENAI_API_KEY: for analyzer LLM
- EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD
- EMAIL_FROM, EMAIL_TO (comma-separated)
- MONITOR_LOG_LINES: number of log lines to read from pm2 (default 4000)
- MONITOR_POLL_SECONDS: poll interval (default 60)
- MONITOR_STATE_FILE: path to remember last notified round id

Usage under pm2:
  pm2 start autoppia_web_agents_subnet/scripts/validator/monitor_rounds.py --name monitor-rounds \
    --interpreter python3 -- \
    --pm2 11 --netuid 36 --network finney
"""

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]


def read_env(key: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(key)
    return val if val is not None else default


def collect_lines_from_pm2(identifier: str, lines: int) -> list[str]:
    cmd = ["pm2", "logs", identifier, "--lines", str(lines), "--nostream"]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"pm2 logs failed: {completed.stderr.strip() or 'unknown error'}")
    raw = completed.stdout.strip().splitlines()
    return raw[-lines:] if lines > 0 else raw


ROUND_COMPLETE_MARK = "✅ Round complete"
ROUND_ID_RE = re.compile(r"(validator_round_[A-Za-z0-9_\-]+)")


def extract_latest_round(lines: Sequence[str]) -> tuple[Optional[str], Optional[int]]:
    # Return (round_id, index_of_marker)
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if ROUND_COMPLETE_MARK in line:
            rid = None
            m = ROUND_ID_RE.search(line)
            if m:
                rid = m.group(1)
            else:
                # Look backwards a bit for a validator_round_id mention
                for j in range(max(0, idx - 200), idx + 1):
                    m2 = ROUND_ID_RE.search(lines[j])
                    if m2:
                        rid = m2.group(1)
                # If not found, keep None
            return rid, idx
    return None, None


def extract_score_snippet(lines: Sequence[str], marker_index: int) -> str:
    # Try to capture the "Round Summary — Miners" block near the end
    start_idx = None
    for i in range(max(0, marker_index - 400), marker_index + 1):
        if "Round Summary — Miners" in lines[i]:
            start_idx = i
    if start_idx is not None:
        # Grab up to the marker line
        snippet = "\n".join(lines[start_idx : marker_index + 1])
        return snippet
    # Fallback: capture WTA winner line
    for i in range(marker_index, max(marker_index - 400, -1), -1):
        if "🏆 Winner uid=" in lines[i]:
            return "\n".join(lines[i : marker_index + 1])
    return "[No score table or winner line detected in recent logs.]"


def run_analyzer(pm2_identifier: str, netuid: int, network: Optional[str], lines: int) -> str:
    # Reuse existing analyzer; capture output
    candidates = [
        REPO_ROOT / "autoppia_web_agents_subnet" / "scripts" / "validator" / "analyze_validator_logs.py",
        REPO_ROOT / "scripts" / "validator" / "analyze_validator_logs.py",
    ]
    analyzer = next((p for p in candidates if p.exists()), None)
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
    candidates = [
        REPO_ROOT / "autoppia_web_agents_subnet" / "scripts" / "validator" / "show_commitments.py",
        REPO_ROOT / "scripts" / "validator" / "show_commitments.py",
    ]
    script = next((p for p in candidates if p.exists()), None)
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
    BAD_TOKENS = ("ERROR", "Traceback", "❌", "exception", "TypeError", "CancelledError")
    hits: list[str] = []
    for ln in lines[-600:]:
        if any(tok.lower() in ln.lower() for tok in BAD_TOKENS):
            hits.append(ln)
    return hits[-40:]


def send_email(subject: str, html_body: str, text_body: Optional[str] = None) -> None:
    host = read_env("EMAIL_SMTP_HOST")
    port = int(read_env("EMAIL_SMTP_PORT", "587"))
    user = read_env("EMAIL_SMTP_USER")
    password = read_env("EMAIL_SMTP_PASSWORD")
    sender = read_env("EMAIL_FROM")
    recipients = read_env("EMAIL_TO")
    if not (host and sender and recipients):
        raise RuntimeError("Email settings incomplete: EMAIL_SMTP_HOST/EMAIL_FROM/EMAIL_TO required.")
    to_list = [addr.strip() for addr in recipients.split(",") if addr.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to_list)

    plain = (text_body or html_body).replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    msg.attach(MIMEText(plain, "plain", _charset="utf-8"))
    msg.attach(MIMEText(html_body, "html", _charset="utf-8"))

    import smtplib

    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls()
        if user and password:
            smtp.login(user, password)
        smtp.sendmail(sender, to_list, msg.as_string())


def load_last_state(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def save_last_state(path: Path, round_id: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(round_id, encoding="utf-8")
    except Exception:
        pass


def build_email(round_id: str, score_snippet: str, insights: str, commitments: str, error_lines: list[str]) -> tuple[str, str]:
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    subject = f"Autoppia Round Report: {round_id} — All good in last round"
    errors_html = "<br>".join(error_lines) if error_lines else "None"
    html = f"""
    <h3>Autoppia Validator — Round Report</h3>
    <p><b>Round:</b> {round_id}<br>
       <b>Time (UTC):</b> {ts}</p>
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Monitor validator rounds and email reports.")
    p.add_argument("--pm2", dest="pm2_identifier", default=read_env("PM2_IDENTIFIER"), help="pm2 id or name")
    p.add_argument("--netuid", type=int, default=int(read_env("NETUID", "36")))
    p.add_argument("--network", default=read_env("SUBTENSOR_NETWORK", None))
    p.add_argument("--lines", type=int, default=int(read_env("MONITOR_LOG_LINES", "4000")))
    p.add_argument("--poll", type=int, default=int(read_env("MONITOR_POLL_SECONDS", "60")))
    p.add_argument("--state-file", default=read_env("MONITOR_STATE_FILE", str(REPO_ROOT / "data" / "monitor" / "last_round_id.txt")))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.pm2_identifier:
        raise SystemExit("Provide --pm2 or set PM2_IDENTIFIER env var.")

    state_path = Path(args.state_file)
    last_rid = load_last_state(state_path)

    while True:
        try:
            lines = collect_lines_from_pm2(args.pm2_identifier, args.lines)
        except Exception as exc:  # noqa: BLE001
            print(f"[monitor] failed to read pm2 logs: {exc}", file=sys.stderr)
            time.sleep(args.poll)
            continue

        rid, idx = extract_latest_round(lines)
        if rid and rid != last_rid and idx is not None:
            # Build report
            score = extract_score_snippet(lines, idx)
            try:
                insights = run_analyzer(args.pm2_identifier, args.netuid, args.network, args.lines)
            except Exception as exc:  # noqa: BLE001
                insights = f"[Analyzer unavailable: {exc}]"
            try:
                commits = run_show_commitments(args.netuid, args.network, count=1)
            except Exception as exc:  # noqa: BLE001
                commits = f"[Commitments unavailable: {exc}]"
            errs = scan_errors(lines)

            subject, html = build_email(rid or "<unknown>", score, insights, commits, errs)
            try:
                send_email(subject, html)
                save_last_state(state_path, rid)
                last_rid = rid
                print(f"[monitor] emailed report for {rid}")
            except Exception as exc:  # noqa: BLE001
                print(f"[monitor] failed to send email: {exc}", file=sys.stderr)

        time.sleep(args.poll)


if __name__ == "__main__":
    main()

