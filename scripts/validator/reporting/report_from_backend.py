#!/usr/bin/env python3
"""
Generate validator round reports from the backend (source of truth).
Supports historical rounds and automatic email delivery.

Usage:
    # View report in terminal
    python3 report_from_backend.py --round 70

    # Send report via email
    python3 report_from_backend.py --round 70 --send-email

    # Specify custom backend
    python3 report_from_backend.py --round 70 --backend https://api-leaderboard.autoppia.com
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    print("Error: requests module not found. Install with: pip install requests")
    sys.exit(1)

# Try to import email functionality from monitor_rounds.py
try:
    from monitor_rounds import send_email, EmailConfig, build_email_payload

    HAS_EMAIL = True
except ImportError:
    HAS_EMAIL = False
    print("Warning: Could not import email functions from monitor_rounds.py")


def fetch_round_data(round_number: int, backend_url: str) -> Dict[str, Any]:
    """Fetch round data from backend API."""
    url = f"{backend_url}/api/v1/rounds/{round_number}"

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Failed to fetch round {round_number} from backend: {exc}") from exc


def fetch_round_miners(round_number: int, backend_url: str) -> List[Dict[str, Any]]:
    """Fetch miners data for a specific round."""
    url = f"{backend_url}/api/v1/rounds/{round_number}/miners"

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("miners", [])
    except requests.exceptions.RequestException as exc:
        print(f"Warning: Could not fetch miners data: {exc}")
        return []


def fetch_validators_for_round(round_number: int, backend_url: str) -> List[Dict[str, Any]]:
    """Fetch validators that participated in consensus for this round."""
    # This would need a specific endpoint in the backend
    # For now, return empty list
    return []


def format_report(round_data: Dict[str, Any], miners: List[Dict[str, Any]], validators: List[Dict[str, Any]]) -> str:
    """Format the round data into a human-readable report."""

    lines = []

    # Header
    round_number = round_data.get("roundNumber") or round_data.get("round_number", "?")
    lines.append(f"{'='*80}")
    lines.append(f"VALIDATOR ROUND REPORT - Round {round_number}")
    lines.append(f"Generated from backend at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"{'='*80}")
    lines.append("")

    # Round Overview
    lines.append("=== Round Overview ===")
    lines.append(f"Round Number: {round_number}")

    validator_hotkey = round_data.get("validatorHotkey") or round_data.get("validator_hotkey", "N/A")
    if validator_hotkey and validator_hotkey != "N/A":
        lines.append(f"Validator Hotkey: {validator_hotkey[:12]}...{validator_hotkey[-8:]}")

    validator_uid = round_data.get("validatorUid") or round_data.get("validator_uid")
    if validator_uid is not None:
        lines.append(f"Validator UID: {validator_uid}")

    start_block = round_data.get("startBlock") or round_data.get("start_block")
    if start_block:
        lines.append(f"Start Block: {start_block:,}")

    end_block = round_data.get("endBlock") or round_data.get("end_block")
    if end_block:
        lines.append(f"End Block: {end_block:,}")

    tasks_completed = round_data.get("tasksCompleted") or round_data.get("tasks_completed")
    if tasks_completed is not None:
        lines.append(f"Tasks Completed: {tasks_completed}")

    status = round_data.get("status", "unknown")
    lines.append(f"Status: {status}")

    created_at = round_data.get("createdAt") or round_data.get("created_at")
    if created_at:
        lines.append(f"Created At: {created_at}")

    lines.append("")

    # Handshake Results
    lines.append("=== Handshake Results ===")
    total_miners = len(miners) if miners else 0
    lines.append(f"Miners Responded: {total_miners}")
    if miners:
        responding_uids = [str(m.get("minerUid") or m.get("miner_uid", "?")) for m in miners[:10]]
        if len(miners) > 10:
            lines.append(f"Sample UIDs: {', '.join(responding_uids)} ... and {len(miners) - 10} more")
        else:
            lines.append(f"UIDs: {', '.join(responding_uids)}")
    lines.append("")

    # Miners Table
    if miners:
        lines.append("=== Miners Evaluated ===")
        lines.append(f"{'#':<4} {'UID':<6} {'Hotkey':<14} {'Tasks':<7} {'Success':<8} {'Failed':<7} {'AvgTime':<9} {'AvgReward':<10}")
        lines.append("-" * 80)

        for idx, miner in enumerate(sorted(miners, key=lambda m: m.get("avgScore", 0) or m.get("avg_score", 0), reverse=True), start=1):
            uid = miner.get("minerUid") or miner.get("miner_uid", "?")
            hotkey = miner.get("minerHotkey") or miner.get("miner_hotkey", "unknown")
            hotkey_short = f"{hotkey[:12]}..." if len(str(hotkey)) > 12 else hotkey

            tasks_attempted = miner.get("tasksAttempted") or miner.get("tasks_attempted", 0)
            tasks_success = miner.get("tasksSuccess") or miner.get("tasks_success", 0)
            tasks_failed = miner.get("tasksFailed") or miner.get("tasks_failed", 0)

            avg_time = miner.get("avgTime") or miner.get("avg_time", 0.0)
            avg_score = miner.get("avgScore") or miner.get("avg_score", 0.0)

            lines.append(f"{idx:<4} {uid:<6} {hotkey_short:<14} {tasks_attempted:<7} " f"{tasks_success:<8} {tasks_failed:<7} {avg_time:<9.2f} {avg_score:<10.4f}")

        lines.append("")

    # Winner
    lines.append("=== Winner ===")
    winner_found = False

    # Try to find winner from round data
    winner_uid = round_data.get("winnerUid") or round_data.get("winner_uid")
    winner_hotkey = round_data.get("winnerHotkey") or round_data.get("winner_hotkey")

    if winner_uid is not None:
        winner_found = True
        lines.append(f"🏆 Winner UID: {winner_uid}")
        if winner_hotkey:
            lines.append(f"   Hotkey: {winner_hotkey[:12]}...{winner_hotkey[-8:]}")

    # If not in round data, find top scorer from miners
    if not winner_found and miners:
        top_miner = max(miners, key=lambda m: m.get("avgScore", 0) or m.get("avg_score", 0))
        top_uid = top_miner.get("minerUid") or top_miner.get("miner_uid")
        top_score = top_miner.get("avgScore") or top_miner.get("avg_score", 0)
        lines.append(f"🏆 Top Scorer: UID {top_uid} (score: {top_score:.4f})")

    if not winner_found and not miners:
        lines.append("No winner information available")

    lines.append("")

    # Validators (Consensus)
    if validators:
        lines.append("=== Validators (Consensus Participants) ===")
        lines.append(f"{'Hotkey':<14} {'UID':<6} {'Stake (τ)':<12}")
        lines.append("-" * 40)

        for val in validators:
            hotkey = val.get("hotkey", "unknown")
            hotkey_short = f"{hotkey[:12]}..." if len(hotkey) > 12 else hotkey
            uid = val.get("uid", "?")
            stake = val.get("stake", 0.0)
            lines.append(f"{hotkey_short:<14} {uid:<6} {stake:<12.0f}")

        lines.append("")
    else:
        lines.append("=== Validators (Consensus) ===")
        lines.append("No consensus validator data available from backend")
        lines.append("(This information may be in the validator logs)")
        lines.append("")

    # Top 5 Summary
    if miners and len(miners) >= 5:
        lines.append("=== Top 5 Miners (After Consensus) ===")
        top_5 = sorted(miners, key=lambda m: m.get("avgScore", 0) or m.get("avg_score", 0), reverse=True)[:5]
        for idx, miner in enumerate(top_5, start=1):
            uid = miner.get("minerUid") or miner.get("miner_uid", "?")
            score = miner.get("avgScore") or miner.get("avg_score", 0)
            lines.append(f"{idx}. UID {uid}: {score:.4f}")
        lines.append("")

    # Footer
    lines.append(f"{'='*80}")
    lines.append("Report generated from backend database (source of truth)")
    lines.append(f"{'='*80}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument("--round", type=int, required=True, help="Round number to generate report for")

    parser.add_argument(
        "--backend", default=os.getenv("IWAP_API_BASE_URL", "https://api-dev-leaderboard.autoppia.com"), help="Backend API base URL (default: from IWAP_API_BASE_URL env or dev backend)"
    )

    parser.add_argument("--send-email", action="store_true", help="Send report via email (requires email configuration)")

    # Email configuration (same as monitor_rounds.py)
    parser.add_argument("--smtp-host", help="SMTP host")
    parser.add_argument("--smtp-port", help="SMTP port")
    parser.add_argument("--smtp-tls", help="Use TLS (true/false)")
    parser.add_argument("--smtp-ssl", help="Use SSL (true/false)")
    parser.add_argument("--smtp-username", help="SMTP username")
    parser.add_argument("--smtp-password", help="SMTP password")
    parser.add_argument("--email-from", help="Sender email address")
    parser.add_argument("--email-to", help="Recipient email address(es), comma-separated")

    args = parser.parse_args()

    # Fetch data from backend
    print(f"Fetching round {args.round} data from {args.backend}...")

    try:
        round_data = fetch_round_data(args.round, args.backend)
        miners = fetch_round_miners(args.round, args.backend)
        validators = fetch_validators_for_round(args.round, args.backend)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Generate report
    report_text = format_report(round_data, miners, validators)

    # Output or send email
    if args.send_email:
        if not HAS_EMAIL:
            print("Error: Email functionality not available. Check monitor_rounds.py import.", file=sys.stderr)
            sys.exit(1)

        try:
            email_config = EmailConfig.from_args(args)

            if not email_config.is_configured():
                print("Error: Email not configured. Provide SMTP settings or set environment variables.", file=sys.stderr)
                print("\nRequired environment variables:")
                print("  REPORT_MONITOR_SMTP_HOST")
                print("  REPORT_MONITOR_SMTP_PORT")
                print("  REPORT_MONITOR_SMTP_USERNAME")
                print("  REPORT_MONITOR_SMTP_PASSWORD")
                print("  REPORT_MONITOR_EMAIL_FROM")
                print("  REPORT_MONITOR_EMAIL_TO")
                sys.exit(1)

            # Build email payload
            subject, body_text, body_html = build_email_payload(
                round_id=args.round,
                status_label="OK",
                status_badge="OK",
                report_text=report_text,
                report_source=f"backend:{args.backend}",
                tasks_completed=round_data.get("tasksCompleted") or round_data.get("tasks_completed"),
                planned_tasks=None,
                llm_summary=None,
                codex_success=False,
                codex_stdout="",
                codex_stderr="",
                log_tail=None,
            )

            # Send email
            send_email(email_config, subject, body_text, body_html)
            print(f"✅ Email sent successfully for round {args.round}")

        except Exception as exc:
            print(f"Error sending email: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        # Print to terminal
        print(report_text)


if __name__ == "__main__":
    main()
