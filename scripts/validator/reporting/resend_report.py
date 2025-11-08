#!/usr/bin/env python3
"""
Resend report for a past round from pickle file.

Usage:
    python3 resend_report.py 77
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo_root))

# Load .env file
env_file = repo_root / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and not key.startswith("#"):
                    os.environ.setdefault(key, value)

from autoppia_web_agents_subnet.validator.reporting.mixin import ReportingMixin


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 resend_report.py <round_number>")
        print("\nExample: python3 resend_report.py 77")
        sys.exit(1)

    try:
        round_number = int(sys.argv[1])
    except ValueError:
        print(f"Error: '{sys.argv[1]}' is not a valid round number")
        sys.exit(1)

    print(f"📊 Loading round {round_number} report from pickle...")

    success = ReportingMixin.resend_round_report(round_number)

    if success:
        print(f"✅ Email sent successfully for round {round_number}")
        sys.exit(0)
    else:
        print(f"❌ Failed to send email for round {round_number}")
        sys.exit(1)


if __name__ == "__main__":
    main()
