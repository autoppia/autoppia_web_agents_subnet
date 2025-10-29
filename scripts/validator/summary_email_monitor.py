#!/usr/bin/env python3
"""
Poll pm2 validator logs, capture the bash summary output for the latest
completed round, and email it to the configured admin recipients.

The script reuses the SMTP settings expected by `monitor_rounds.py`:
  EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD,
  EMAIL_FROM, EMAIL_TO
"""

from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.append(str(Path(__file__).resolve().parent))
from monitor_rounds import read_env, send_email  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_FILE = REPO_ROOT / "data" / "monitor" / "last_summary_round.txt"
SUMMARY_SCRIPT = Path(__file__).resolve().with_name("summary.sh")
ROUND_RE = re.compile(r"Validator round summary \(round (\d+)\)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Email the validator summary.sh output each time a round finishes."
    )
    parser.add_argument("--pm2", dest="pm2_identifier", default=read_env("PM2_IDENTIFIER"), help="pm2 id or name")
    parser.add_argument("--path", dest="log_path", help="Explicit log file path instead of pm2 logs")
    parser.add_argument("--lines", type=int, default=int(read_env("SUMMARY_LINES", "4000")), help="Log lines to fetch")
    parser.add_argument("--poll", type=int, default=int(read_env("SUMMARY_POLL_SECONDS", "60")), help="Polling interval")
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=int(read_env("SUMMARY_WAIT_SECONDS", "90")),
        help="Delay after detecting a new round before emailing",
    )
    parser.add_argument(
        "--state-file",
        default=read_env("SUMMARY_STATE_FILE", str(DEFAULT_STATE_FILE)),
        help="File to store the last emailed round number",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=int(read_env("SUMMARY_ROUND_OFFSET", "1")),
        help="Rounds to subtract from the latest completed round (default 1). Set to 0 to email the latest.",
    )
    parser.add_argument(
        "--summary-script",
        default=str(read_env("SUMMARY_SCRIPT_PATH", str(SUMMARY_SCRIPT))),
        help="Path to the summary.sh script",
    )
    parser.add_argument(
        "--round",
        dest="round_forced",
        type=int,
        help="Send a single email for the specified round and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not send email; just print the summary when a new round is detected",
    )
    return parser.parse_args()


def load_state(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"[summary-monitor] failed to read state file: {exc}", file=sys.stderr)
        return None


def save_state(path: Path, round_number: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(round_number, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[summary-monitor] failed to persist state: {exc}", file=sys.stderr)


def run_summary(
    summary_script: Path, pm2_identifier: Optional[str], log_path: Optional[str], lines: int, round_arg: Optional[str] = None
) -> str:
    cmd = [str(summary_script)]
    if log_path:
        cmd.extend(["--path", log_path])
    elif pm2_identifier:
        cmd.extend(["--pm2", pm2_identifier])
    else:
        raise RuntimeError("Provide --pm2 or --path to locate validator logs.")
    cmd.extend(["--lines", str(lines)])
    if round_arg is not None:
        cmd.extend(["--round", str(round_arg)])
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise RuntimeError(stderr or "summary.sh failed")
    return completed.stdout.strip()


def extract_round(summary_output: str) -> Optional[str]:
    match = ROUND_RE.search(summary_output)
    return match.group(1) if match else None


def build_email(round_number: str, summary_output: str) -> tuple[str, str, str]:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    subject = f"Autoppia Round Summary — Round {round_number}"
    escaped_body = html.escape(summary_output)
    html_body = (
        f"<h3>Autoppia Validator — Round {round_number}</h3>"
        f"<p><b>Generated:</b> {ts}</p>"
        f"<pre style=\"white-space: pre-wrap; font-family: monospace;\">{escaped_body}</pre>"
    )
    text_body = f"Autoppia Validator — Round {round_number}\nGenerated: {ts}\n\n{summary_output}"
    return subject, html_body, text_body


def main() -> None:
    args = parse_args()
    if args.offset < 0:
        args.offset = 0

    summary_path = Path(args.summary_script).expanduser().resolve()
    if not summary_path.exists():
        raise SystemExit(f"summary script not found at {summary_path}")

    if not args.log_path and not args.pm2_identifier:
        raise SystemExit("Provide --pm2 or --path to locate validator logs.")

    state_path = Path(args.state_file).expanduser()

    if args.round_forced is not None:
        target_round = str(args.round_forced)
        try:
            summary_out = run_summary(summary_path, args.pm2_identifier, args.log_path, args.lines, target_round)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"Failed to run summary for round {target_round}: {exc}") from exc
        subject, html_body, text_body = build_email(target_round, summary_out)
        if args.dry_run:
            print(f"[summary-monitor] dry-run email subject: {subject}")
            print(summary_out)
            return
        try:
            send_email(subject, html_body, text_body)
            print(f"[summary-monitor] emailed summary for round {target_round}")
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"Failed to send email: {exc}") from exc
        save_state(state_path, target_round)
        return

    last_round = load_state(state_path)

    print(
        f"[summary-monitor] starting with last_round={last_round or 'None'}, "
        f"poll={args.poll}s, wait={args.wait_seconds}s, offset={args.offset}"
    )

    while True:
        try:
            latest_out = run_summary(summary_path, args.pm2_identifier, args.log_path, args.lines)
        except Exception as exc:  # noqa: BLE001
            print(f"[summary-monitor] summary.sh failed: {exc}", file=sys.stderr)
            time.sleep(args.poll)
            continue

        latest_round = extract_round(latest_out)
        if not latest_round:
            print("[summary-monitor] unable to detect round number from summary output", file=sys.stderr)
            time.sleep(args.poll)
            continue

        target_round = latest_round
        if args.offset:
            try:
                latest_int = int(latest_round)
                target_round = str(max(latest_int - args.offset, 0))
            except ValueError:
                print(
                    f"[summary-monitor] latest round '{latest_round}' not numeric; using without offset.",
                    file=sys.stderr,
                )

        if last_round == target_round:
            time.sleep(args.poll)
            continue

        print(
            f"[summary-monitor] detected candidate round {target_round} "
            f"(latest {latest_round}), waiting {args.wait_seconds}s before emailing"
        )
        if args.wait_seconds > 0:
            time.sleep(args.wait_seconds)
            try:
                summary_out = run_summary(summary_path, args.pm2_identifier, args.log_path, args.lines, target_round)
            except Exception as exc:  # noqa: BLE001
                print(f"[summary-monitor] summary.sh failed for target round {target_round}: {exc}", file=sys.stderr)
                time.sleep(args.poll)
                continue
        else:
            try:
                summary_out = run_summary(summary_path, args.pm2_identifier, args.log_path, args.lines, target_round)
            except Exception as exc:  # noqa: BLE001
                print(f"[summary-monitor] summary.sh failed for target round {target_round}: {exc}", file=sys.stderr)
                time.sleep(args.poll)
                continue

        subject, html_body, text_body = build_email(target_round, summary_out)
        if args.dry_run:
            print(f"[summary-monitor] dry-run email subject: {subject}")
            print(summary_out)
            last_round = target_round
            save_state(state_path, target_round)
            time.sleep(args.poll)
            continue

        try:
            send_email(subject, html_body, text_body)
            print(f"[summary-monitor] emailed summary for round {target_round}")
            save_state(state_path, target_round)
            last_round = target_round
        except Exception as exc:  # noqa: BLE001
            print(f"[summary-monitor] failed to send email: {exc}", file=sys.stderr)

        time.sleep(args.poll)


if __name__ == "__main__":
    main()
