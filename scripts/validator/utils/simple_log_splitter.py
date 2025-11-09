#!/usr/bin/env python3
"""
Simple log splitter for validator rounds.
Reads from stdin (PM2 logs) and splits by round number.
"""

import re
import sys
from pathlib import Path
from datetime import datetime

# Find repo root
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3]
LOGS_DIR = REPO_ROOT / "data" / "logs"
ROUNDS_DIR = LOGS_DIR / "rounds"

# Create directories
ROUNDS_DIR.mkdir(parents=True, exist_ok=True)

# Pattern to detect round start
# Matches: "🚦 Starting Round: 169" or "[ROUND] Starting round 169"
ROUND_START_PATTERNS = [
    re.compile(r'🚦\s+Starting\s+Round:\s*(\d+)', re.IGNORECASE),
    re.compile(r'\[ROUND\]\s+Starting\s+round\s*(\d+)', re.IGNORECASE),
    re.compile(r'Starting\s+validator\s+round\s*(\d+)', re.IGNORECASE),
]

# Current round tracking
current_round = None
current_round_file = None

def detect_round_start(line: str):
    """Detect if line indicates a new round starting."""
    for pattern in ROUND_START_PATTERNS:
        match = pattern.search(line)
        if match:
            return int(match.group(1))
    return None

def process_line(line: str):
    """Process a single log line."""
    global current_round, current_round_file
    
    # Check if new round starts
    new_round = detect_round_start(line)
    if new_round:
        # Close previous round file
        if current_round_file:
            current_round_file.close()
            print(f"[{datetime.now()}] Closed round {current_round} log", file=sys.stderr, flush=True)
        
        # Open new round file
        current_round = new_round
        round_log = ROUNDS_DIR / f"round_{current_round}.log"
        current_round_file = open(round_log, 'a', encoding='utf-8')
        print(f"[{datetime.now()}] Started logging round {current_round} → {round_log}", file=sys.stderr, flush=True)
    
    # Write to current round file
    if current_round_file:
        try:
            current_round_file.write(line)
            current_round_file.flush()
        except Exception as e:
            print(f"[{datetime.now()}] Write error: {e}", file=sys.stderr, flush=True)

def main():
    """Main loop - read from stdin and process lines."""
    print(f"[{datetime.now()}] Log splitter started", file=sys.stderr, flush=True)
    print(f"[{datetime.now()}] Round logs directory: {ROUNDS_DIR}/", file=sys.stderr, flush=True)
    print(f"[{datetime.now()}] Waiting for log input...", file=sys.stderr, flush=True)
    
    try:
        for line in sys.stdin:
            try:
                process_line(line)
            except Exception as e:
                print(f"[{datetime.now()}] Error processing line: {e}", file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] Shutting down gracefully...", file=sys.stderr, flush=True)
    finally:
        if current_round_file:
            current_round_file.close()
            print(f"[{datetime.now()}] Closed round {current_round} log", file=sys.stderr, flush=True)

if __name__ == "__main__":
    main()

