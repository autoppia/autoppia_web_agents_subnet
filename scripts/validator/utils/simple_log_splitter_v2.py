#!/usr/bin/env python3
"""
Simple log splitter for validator rounds - reads directly from PM2 log file.
"""

import re
import time
from pathlib import Path
from datetime import datetime

# Find repo root
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3]
LOGS_DIR = REPO_ROOT / "data" / "logs"
ROUNDS_DIR = LOGS_DIR / "rounds"

# PM2 log file
PM2_LOG = Path.home() / ".pm2" / "logs" / "validator-wta-out.log"

# Create directories
ROUNDS_DIR.mkdir(parents=True, exist_ok=True)

# Pattern to detect round start
ROUND_START_PATTERN = re.compile(r"🚦\s+Starting\s+Round:\s*(\d+)", re.IGNORECASE)

# Current round tracking
current_round = None
current_round_file = None


def detect_round_start(line: str):
    """Detect if line indicates a new round starting."""
    match = ROUND_START_PATTERN.search(line)
    if match:
        return int(match.group(1))
    return None


def process_line(line: str):
    """Process a single log line."""
    global current_round, current_round_file

    # Check if new round starts
    new_round = detect_round_start(line)
    if new_round and new_round != current_round:
        # Close previous round file
        if current_round_file:
            current_round_file.close()
            print(f"[{datetime.now()}] Closed round {current_round} log", flush=True)

        # Open new round file
        current_round = new_round
        round_log = ROUNDS_DIR / f"round_{current_round}.log"
        current_round_file = open(round_log, "a", encoding="utf-8")
        print(f"[{datetime.now()}] Started logging round {current_round} → {round_log}", flush=True)

    # Write to current round file
    if current_round_file:
        try:
            current_round_file.write(line)
            current_round_file.flush()
        except Exception as e:
            print(f"[{datetime.now()}] Write error: {e}", flush=True)


def tail_file(filepath: Path):
    """Tail a file continuously like tail -F."""
    print(f"[{datetime.now()}] Watching {filepath}", flush=True)

    # Open file and seek to end
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        # Remember original inode
        try:
            original_inode = filepath.stat().st_ino
        except:
            original_inode = None

        # Go to end of file
        f.seek(0, 2)

        while True:
            line = f.readline()
            if line:
                yield line
            else:
                # No new data, wait a bit
                time.sleep(0.5)

                # Check if file was rotated/recreated (compare inodes)
                if original_inode:
                    try:
                        current_inode = filepath.stat().st_ino
                        if current_inode != original_inode:
                            print(f"[{datetime.now()}] File rotated, reopening...", flush=True)
                            return  # Exit and let main loop reopen
                    except:
                        pass


def main():
    """Main loop - continuously tail PM2 log file."""
    print(f"[{datetime.now()}] Log splitter started", flush=True)
    print(f"[{datetime.now()}] Round logs directory: {ROUNDS_DIR}/", flush=True)
    print(f"[{datetime.now()}] PM2 log file: {PM2_LOG}", flush=True)

    while True:
        try:
            if not PM2_LOG.exists():
                print(f"[{datetime.now()}] Waiting for {PM2_LOG} to exist...", flush=True)
                time.sleep(5)
                continue

            for line in tail_file(PM2_LOG):
                try:
                    process_line(line)
                except Exception as e:
                    print(f"[{datetime.now()}] Error processing line: {e}", flush=True)

            # File was rotated, reopen
            time.sleep(1)

        except KeyboardInterrupt:
            print(f"\n[{datetime.now()}] Shutting down gracefully...", flush=True)
            break
        except Exception as e:
            print(f"[{datetime.now()}] Error: {e}", flush=True)
            time.sleep(5)

    # Cleanup
    if current_round_file:
        current_round_file.close()
        print(f"[{datetime.now()}] Closed round {current_round} log", flush=True)


if __name__ == "__main__":
    main()
