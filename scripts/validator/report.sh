#!/usr/bin/env bash

set -euo pipefail

DEFAULT_LINES=${LINES:-4000}
DEFAULT_PM2_IDENTIFIER=${PM2_IDENTIFIER:-}

usage() {
    cat <<'USAGE'
Usage: report.sh [--round N] [--pm2 NAME|ID] [--path LOGFILE] [--lines N]

Generate a rich validator round report from pm2 logs or a log file.

Options:
  --round N   Round number to summarize. When omitted, the latest completed round is used.
  --pm2 ID    pm2 process id or name to pull logs from (default: $PM2_IDENTIFIER or required when --path omitted).
  --path FILE Path to a log file instead of pm2 logs.
  --lines N   Number of log lines to read (default: 4000 or $LINES env).
  -h, --help  Show this help message.

Either --pm2 or --path must be provided. When both are supplied, --path takes precedence.
USAGE
}

round_arg=""
pm2_identifier="$DEFAULT_PM2_IDENTIFIER"
log_path=""
lines="$DEFAULT_LINES"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --round)
            [[ $# -lt 2 ]] && { echo "Missing value for --round" >&2; exit 1; }
            round_arg="$2"
            shift 2
            ;;
        --pm2)
            [[ $# -lt 2 ]] && { echo "Missing value for --pm2" >&2; exit 1; }
            pm2_identifier="$2"
            shift 2
            ;;
        --path)
            [[ $# -lt 2 ]] && { echo "Missing value for --path" >&2; exit 1; }
            log_path="$2"
            shift 2
            ;;
        --lines)
            [[ $# -lt 2 ]] && { echo "Missing value for --lines" >&2; exit 1; }
            lines="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$log_path" && -z "$pm2_identifier" ]]; then
    echo "Error: provide either --pm2 or --path" >&2
    usage >&2
    exit 1
fi

if ! [[ "$lines" =~ ^[0-9]+$ ]]; then
    echo "Error: --lines must be an integer" >&2
    exit 1
fi

collect_logs() {
    if [[ -n "$log_path" ]]; then
        if [[ ! -f "$log_path" ]]; then
            echo "Error: log file not found: $log_path" >&2
            exit 1
        fi
        tail -n "$lines" "$log_path"
    else
        if ! command -v pm2 >/dev/null 2>&1; then
            echo "Error: pm2 command not found. Install pm2 or provide --path" >&2
            exit 1
        fi
        pm2 logs "$pm2_identifier" --lines "$lines" --nostream
    fi
}

mapfile -t LOG_LINES < <(collect_logs | sed -e 's/\x1B\[[0-9;]*[A-Za-z]//g')

if [[ ${#LOG_LINES[@]} -eq 0 ]]; then
    echo "No log lines collected." >&2
    exit 1
fi

log_text=$(printf '%s\n' "${LOG_LINES[@]}")

extract_latest_round() {
    local latest_round=""
    while IFS= read -r line; do
        if [[ "$line" =~ Round[[:space:]]+completed:\ ([0-9]+) ]]; then
            latest_round="${BASH_REMATCH[1]}"
        fi
    done <<< "$log_text"
    echo "$latest_round"
}

target_round="$round_arg"
if [[ -z "$target_round" ]]; then
    target_round=$(extract_latest_round)
    if [[ -z "$target_round" ]]; then
        echo "Unable to locate a completed round in logs." >&2
        exit 1
    fi
fi

if ! [[ "$target_round" =~ ^[0-9]+$ ]]; then
    echo "Invalid round number: $target_round" >&2
    exit 1
fi

start_index=-1
end_index=-1
round_active=0

for idx in "${!LOG_LINES[@]}"; do
    line=${LOG_LINES[$idx]}
    if [[ "$line" =~ Round[[:space:]]+completed:\ ([0-9]+) ]]; then
        if [[ "${BASH_REMATCH[1]}" == "$target_round" ]]; then
            end_index=$idx
        fi
    fi
done

if (( end_index < 0 )); then
    round_active=1
    end_index=$(( ${#LOG_LINES[@]} - 1 ))
    if (( end_index < 0 )); then
        echo "No log lines available after scanning for round $target_round" >&2
        exit 1
    fi
fi

for (( idx=end_index; idx>=0; idx-- )); do
    line=${LOG_LINES[$idx]}
    if [[ "$line" =~ Starting[[:space:]]+Round:\ ([0-9]+) ]]; then
        if [[ "${BASH_REMATCH[1]}" == "$target_round" ]]; then
            start_index=$idx
            break
        fi
    elif [[ "$line" =~ Starting[[:space:]]+round-based[[:space:]]+forward[[:space:]]*\(round[[:space:]]*([0-9]+)\) ]]; then
        if [[ "${BASH_REMATCH[1]}" == "$target_round" ]]; then
            start_index=$idx
            break
        fi
    elif [[ "$line" =~ Round\ status\ \|\ round\=([0-9]+) ]]; then
        if [[ "${BASH_REMATCH[1]}" == "$target_round" ]]; then
            start_index=$idx
            break
        fi
    elif [[ "$line" =~ Round\ header\ \|\ round\=([0-9]+) ]]; then
        if [[ "${BASH_REMATCH[1]}" == "$target_round" ]]; then
            start_index=$idx
            break
        fi
    fi
done

if (( start_index < 0 )); then
    echo "Could not find start marker for round $target_round" >&2
    exit 1
fi

round_lines=("${LOG_LINES[@]:$start_index:$((end_index - start_index + 1))}")
source_desc=""
if [[ -n "$log_path" ]]; then
    source_desc="$log_path"
else
    source_desc="pm2:$pm2_identifier (last $lines lines)"
fi

tmpfile=$(mktemp)
printf '%s\n' "${round_lines[@]}" > "$tmpfile"

TARGET_ROUND="$target_round" \
SOURCE_DESC="$source_desc" \
ROUND_ACTIVE="$round_active" \
python3 - "$tmpfile" <<'PY'
import os
import re
import sys
from collections import OrderedDict

target_round = os.environ.get("TARGET_ROUND", "?")
source_desc = os.environ.get("SOURCE_DESC", "")
round_active = os.environ.get("ROUND_ACTIVE", "0") == "1"

if len(sys.argv) < 2:
    lines: list[str] = []
else:
    log_path = sys.argv[1]
    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        lines = [line.rstrip("\n") for line in fh]

ts_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T")

entries = []
for raw in lines:
    if not raw:
        entries.append({"raw": raw, "message": "", "timestamp": None, "level": None})
        continue
    parts = raw.split(None, 2)
    if len(parts) >= 3 and ts_pattern.match(parts[0]):
        timestamp, level, message = parts[0], parts[1], parts[2]
    else:
        timestamp, level, message = None, None, raw
    entries.append({"raw": raw, "message": message, "timestamp": timestamp, "level": level})

def first_message(pattern: str) -> str | None:
    regex = re.compile(pattern)
    for entry in entries:
        if regex.search(entry["message"]):
            return entry["message"]
    return None

def last_message(pattern: str) -> str | None:
    regex = re.compile(pattern)
    for entry in reversed(entries):
        if regex.search(entry["message"]):
            return entry["message"]
    return None

def collect_messages(pattern: str) -> list[str]:
    regex = re.compile(pattern)
    results = []
    seen = set()
    for entry in entries:
        msg = entry["message"]
        if regex.search(msg):
            if msg not in seen:
                seen.add(msg)
                results.append(msg)
    return results

def table_section() -> tuple[str | None, str | None, list[str]]:
    title = None
    header = None
    rows: list[str] = []
    capturing = False
    for entry in entries:
        msg = entry["message"]
        if "Round Summary — Miners" in msg:
            title = msg
            capturing = True
            continue
        if not capturing:
            continue
        stripped = msg.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            header = stripped
            continue
        if re.match(r"^\d+\s+", stripped):
            rows.append(stripped)
            continue
        # Stop capturing once we have rows and encounter unrelated text
        if rows or header:
            break
    return title, header, rows

def format_section(title: str, lines: list[str]) -> None:
    if not lines:
        return
    print(f"=== {title} ===")
    for line in lines:
        print(line)
    print()

round_header = first_message(r"Round header \|")
resume_hint = first_message(r"♻️ Resume")
winner_line = first_message(r"Winner uid=")
aggregators_line = first_message(r"Aggregators:")
task_ready = first_message(r"Task list ready")
tasks_completed = first_message(r"Tasks completed")
last_task_progress = last_message(r"📍 Task\s+(\d+)/(\d+)")
tasks_completed_last = last_message(r"Tasks completed[:\s]*(\d+)/(\d+)")
tasks_completed_display = tasks_completed_last or tasks_completed
consensus_published = collect_messages(r"\[IPFS] \[(?:UPLOAD|BLOCKCHAIN)]")
consensus_commits = collect_messages(r"CONSENSUS COMMIT")
consensus_fetch = collect_messages(r"\[IPFS] \[DOWNLOAD]")
consensus_meta = collect_messages(r"\[CONSENSUS]")
commitment_mentions: list[str] = []
for entry in entries:
    msg = entry["message"]
    lower_msg = msg.lower()
    if "commitments fetched" in lower_msg or ("commitment" in lower_msg and "consensus commit" not in msg and "[UPLOAD]" not in msg and "[BLOCKCHAIN]" not in msg):
        if msg not in commitment_mentions:
            commitment_mentions.append(msg)
score_updates = collect_messages(r"Updated moving avg scores|Final weights|Scattered rewards|Updating scores|Round Summary — Miners")
score_updates = [line for line in score_updates if "Round Summary — Miners" not in line]
round_details_lines = []
round_detail_regex = re.compile(r"\[ROUND DETAILS]\s*(.+)")
for entry in entries:
    match = round_detail_regex.search(entry["message"])
    if match:
        round_details_lines.append(match.group(1))

table_title, table_header, table_rows = table_section()

resume_status = None
if round_header:
    resumed_match = re.search(r"resumed=(True|False)", round_header)
    if resumed_match:
        resume_status = "resume" if resumed_match.group(1) == "True" else "fresh"
if resume_status is None and resume_hint:
    resume_status = "resume"
if resume_status is None:
    resume_status = "unknown"

round_info = OrderedDict()
for entry in round_details_lines:
    if ": " in entry:
        key, value = entry.split(": ", 1)
        round_info[key.strip()] = value.strip()

handshake_line = first_message(r"Handshake Results")
handshake_sent_line = first_message(r"Handshake sent")

miner_rows_count = len(table_rows)
if miner_rows_count == 0:
    miner_rows_count = len(collect_messages(r"Score=\d"))

status_label = "completed" if not round_active else "active"
phase = "unknown"
phase_details: list[str] = []

def append_detail(line: str) -> None:
    if line and line not in phase_details:
        phase_details.append(line)

if not round_active:
    phase = "completed"
else:
    if winner_line:
        phase = "finalizing"
        append_detail(winner_line)
    elif consensus_published or consensus_commits:
        phase = "consensus"
        if consensus_commits:
            append_detail(consensus_commits[-1])
        elif consensus_published:
            append_detail(consensus_published[-1])
    elif last_task_progress:
        m = re.search(r"📍 Task\s+(\d+)/(\d+)", last_task_progress)
        if m:
            current = int(m.group(1))
            total = int(m.group(2))
            if total and current >= total:
                phase = "post-tasks"
                append_detail(f"All tasks dispatched ({current}/{total}); awaiting consensus")
            else:
                phase = "tasks"
                denom = total if total else (current if current else 1)
                append_detail(f"Current task progress: {current}/{denom}")
        else:
            phase = "tasks"
    elif task_ready:
        phase = "queued"
        append_detail(task_ready)
    elif handshake_line or handshake_sent_line:
        phase = "handshake"
        if handshake_line:
            append_detail(handshake_line)
        elif handshake_sent_line:
            append_detail(handshake_sent_line)

if tasks_completed_last and round_active:
    m = re.search(r"(\d+)/(\d+)", tasks_completed_last)
    if m:
        append_detail(f"Tasks completed so far: {m.group(1)}/{m.group(2)}")

print(f"Validator round report (round {target_round})")
if source_desc:
    print(f"Source: {source_desc}")
print()

print("=== Round Overview ===")
if round_header:
    print(round_header)
print(f"Start mode: {resume_status}")
print(f"Current round: {target_round}")
status_line = f"Status: {status_label}"
if phase not in {"unknown", "completed"}:
    status_line += f" (phase: {phase})"
elif phase == "completed" and round_active:
    status_line += f" (phase: {phase})"
print(status_line)
for detail in phase_details:
    print(detail)
if round_info:
    for key in [
        "Round Number",
        "Validator Round ID",
        "Start Block",
        "Start Epoch",
        "Target Epoch",
        "Duration",
        "Total Blocks",
        "Tasks to Execute",
        "Stop Evaluation at",
        "Fetch Commits at",
    ]:
        if key in round_info:
            print(f"{key}: {round_info[key]}")
print()

markers: list[str] = []
if entries:
    markers.append(entries[0]["raw"])
    markers.append(entries[-1]["raw"])
format_section("Round markers", markers)

tasks_section: list[str] = []
if task_ready:
    tasks_section.append(task_ready)
if "Tasks to Execute" in round_info:
    tasks_section.append(f"Planned tasks: {round_info['Tasks to Execute']}")
if tasks_completed_display:
    tasks_section.append(tasks_completed_display)
format_section("Tasks", tasks_section)

miners_section: list[str] = []
if handshake_line:
    miners_section.append(handshake_line)
if handshake_sent_line and handshake_sent_line not in miners_section:
    miners_section.append(handshake_sent_line)
if miner_rows_count:
    miners_section.append(f"Miners evaluated (from summary table): {miner_rows_count}")
format_section("Miners", miners_section)

if table_title or table_header or table_rows:
    table_lines = []
    if table_title:
        table_lines.append(table_title)
        if f"Round {target_round}" not in table_title:
            table_lines.append(f"(Current round: {target_round})")
    else:
        table_lines.append(f"Round Summary — Miners — Round {target_round}")
    if table_header:
        table_lines.append(table_header)
    table_lines.extend(table_rows)
    format_section("Round Summary table", table_lines)

score_lines = []
if winner_line:
    score_lines.append(winner_line)
if aggregators_line:
    score_lines.append(aggregators_line)
for line in score_updates:
    if line not in score_lines:
        score_lines.append(line)
format_section("Scores & winners", score_lines)

consensus_section: list[str] = []
consensus_section.extend(consensus_published)
consensus_section.extend(consensus_commits)
format_section("Consensus publish", consensus_section)

fetch_section: list[str] = []
fetch_section.extend(consensus_fetch)
for line in consensus_meta:
    if line not in fetch_section and "[UPLOAD]" not in line:
        fetch_section.append(line)
for line in commitment_mentions:
    if line not in fetch_section:
        fetch_section.append(line)
format_section("Consensus fetch & shared scores", fetch_section)
PY
rm -f "$tmpfile"
