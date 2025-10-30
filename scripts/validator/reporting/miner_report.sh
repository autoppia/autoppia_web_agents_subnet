#!/usr/bin/env bash

set -euo pipefail

DEFAULT_LINES=${LINES:-4000}
DEFAULT_PM2_IDENTIFIER=${PM2_IDENTIFIER:-}

usage() {
    cat <<'USAGE'
Usage: miner_report.sh --uid UID [--round N] [--pm2 NAME|ID] [--path LOGFILE] [--lines N]

Generate a miner-focused report for a specific round from validator logs.

Options:
  --uid UID   Miner UID to inspect (required).
  --round N   Round number to inspect. When omitted, the latest completed round is used.
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
target_uid=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --uid)
            [[ $# -lt 2 ]] && { echo "Missing value for --uid" >&2; exit 1; }
            target_uid="$2"
            shift 2
            ;;
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

if [[ -z "$target_uid" ]]; then
    echo "Error: --uid is required" >&2
    usage >&2
    exit 1
fi

if ! [[ "$target_uid" =~ ^[0-9]+$ ]]; then
    echo "Error: --uid must be an integer" >&2
    exit 1
fi

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
latest_completed_round=$(extract_latest_round)
if [[ -z "$target_round" ]]; then
    target_round="$latest_completed_round"
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
trap 'rm -f "$tmpfile"' EXIT
printf '%s\n' "${round_lines[@]}" > "$tmpfile"

TARGET_ROUND="$target_round" \
TARGET_UID="$target_uid" \
SOURCE_DESC="$source_desc" \
ROUND_ACTIVE="$round_active" \
LATEST_COMPLETED="${latest_completed_round:-}" \
python3 - "$tmpfile" <<'PY'
import os
import re
import statistics
import sys
from collections import defaultdict


def strip_pm2_prefix(text: str | None) -> str:
    if not text:
        return ""
    raw = text.rstrip()
    if "|" not in raw:
        return raw.strip()
    parts = raw.split("|", 5)
    if not parts or not parts[0].strip().isdigit():
        return raw.strip()
    remainder = parts[1:]
    if remainder:
        remainder = remainder[1:]
    message = remainder[-1] if remainder else ""
    if not message and remainder:
        message = remainder[-1]
    if not message and parts:
        message = parts[-1]
    return message.strip()


def parse_entry(raw: str) -> dict[str, str | None]:
    entry: dict[str, str | None] = {"raw": raw, "timestamp": None, "level": None, "message": ""}
    stripped = raw.strip()
    if not stripped:
        entry["message"] = ""
        return entry

    if "|" in raw and raw.split("|", 1)[0].strip().isdigit():
        parts = raw.split("|", 5)
        if len(parts) >= 6:
            entry["timestamp"] = parts[2].strip() or None
            entry["level"] = parts[3].strip() or None
            entry["message"] = parts[5].strip()
        else:
            entry["message"] = parts[-1].strip()
    else:
        chunks = stripped.split(None, 2)
        if len(chunks) >= 3 and re.match(r"^\d{4}-\d{2}-\d{2}T", chunks[0]):
            entry["timestamp"] = chunks[0]
            entry["level"] = chunks[1]
            entry["message"] = chunks[2]
        else:
            entry["message"] = stripped
    pm2_clean = strip_pm2_prefix(raw)
    if not entry["message"]:
        entry["message"] = pm2_clean
    entry["clean"] = entry["message"] or pm2_clean or ""
    return entry


def table_section(entries: list[dict[str, str | None]]) -> tuple[str | None, list[str]]:
    title = None
    block: list[str] = []
    capturing = False
    stop_tokens = (
        "[IPFS]",
        "[CONSENSUS]",
        "Round stats",
        "Scattered rewards",
        "Updated moving avg",
        "Tasks completed",
        "Winner",
        "Round completed",
    )
    for entry in entries:
        msg = entry.get("message") or ""
        raw = strip_pm2_prefix(entry.get("raw"))
        display = (msg or raw or "").strip()
        if "Round Summary — Miners" in msg:
            title = display or msg
            block.append(display)
            capturing = True
            continue
        if not capturing:
            continue
        if not display:
            block.append("")
            continue
        if any(token in display for token in stop_tokens):
            break
        block.append(display)
    return title, block


def format_tags(tags: list[str]) -> str:
    if not tags:
        return ""
    return "[" + ",".join(tags) + "] "


def ensure_int(value: str | None, label: str) -> int:
    if value is None or value == "":
        raise RuntimeError(f"{label} not provided")
    return int(value)


target_round = os.environ.get("TARGET_ROUND")
target_uid = ensure_int(os.environ.get("TARGET_UID"), "TARGET_UID")
source_desc = os.environ.get("SOURCE_DESC") or ""
round_active = os.environ.get("ROUND_ACTIVE", "0") == "1"
latest_completed = os.environ.get("LATEST_COMPLETED", "") or ""

if len(sys.argv) < 2:
    raise SystemExit("miner_report: missing log path argument")

log_path = sys.argv[1]
with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
    lines = [line.rstrip("\n") for line in fh]

entries = [parse_entry(line) for line in lines]

round_header = None
for entry in entries:
    message = entry.get("message") or ""
    if "Round header" in message:
        round_header = strip_pm2_prefix(entry.get("raw")) or message
        break

table_title, table_block = table_section(entries)
miner_table_lines: list[str] = []
uid_exact = re.compile(rf"(?<!\d){target_uid}(?!\d)")
for line in table_block:
    if uid_exact.search(line):
        miner_table_lines.append(line)

relevant_entries: list[dict[str, str | None]] = []
warning_entries: list[dict[str, str | None]] = []
error_entries: list[dict[str, str | None]] = []

digit_exact = re.compile(rf"(?<!\d){target_uid}(?!\d)")
patterns = [
    re.compile(rf"\bminer_uid\s*[:=]\s*{target_uid}\b", re.IGNORECASE),
    re.compile(rf"\bminer\s+{target_uid}\b", re.IGNORECASE),
    re.compile(rf"(?<!validator_)\buid\s*=\s*{target_uid}\b", re.IGNORECASE),
    re.compile(rf"\"uid\"\s*:\s*{target_uid}"),
    re.compile(rf"'uid'\s*:\s*{target_uid}"),
]

metrics = {
    "start_agent_run": defaultdict(int),
    "add_evaluation": defaultdict(int),
    "gif_upload": defaultdict(int),
    "timeouts": 0,
    "responses": 0,
    "process_times": [],
    "none_responses": 0,
    "winner": False,
}
task_ids: set[str] = set()
agent_run_ids: set[str] = set()

for entry in entries:
    message = entry.get("message") or ""
    clean = entry.get("clean") or message
    lower = clean.lower()
    if "validator_uid" in lower:
        # Skip validator-specific lines to avoid false positives
        continue

    match_found = False
    for pattern in patterns:
        if pattern.search(clean):
            match_found = True
            break
    if not match_found and digit_exact.search(clean):
        # As a fallback, ensure the UID appears near miner references
        if "miner" in lower or "uid" in lower or "agent" in lower:
            match_found = True

    if not match_found:
        continue

    tags: list[str] = []
    if "iwap |" in lower:
        tags.append("IWAP")
    if "[time]" in lower:
        tags.append("TIME")
    if "start_agent_run" in lower:
        tags.append("START")
    if "add_evaluation" in lower:
        tags.append("EVAL")
    if "gif" in lower:
        tags.append("GIF")
    if "reward" in lower or "score" in lower:
        tags.append("SCORE")
    level = (entry.get("level") or "").upper()
    if level.startswith("WARN") or "⚠" in clean or "warning" in lower:
        tags.append("WARN")
        warning_entries.append(entry)
    if level.startswith("ERR") or "error" in lower or "❌" in clean or "failed" in lower:
        tags.append("ERROR")
        error_entries.append(entry)
    entry["tags"] = tags
    relevant_entries.append(entry)

    # Metrics extraction
    if "start_agent_run completed" in clean:
        metrics["start_agent_run"]["success"] += 1
    elif "start_agent_run failed" in clean:
        metrics["start_agent_run"]["failed"] += 1
    elif "start_agent_run returned" in clean:
        metrics["start_agent_run"]["warning"] += 1

    if "add_evaluation completed" in clean:
        metrics["add_evaluation"]["success"] += 1
    elif "add_evaluation failed" in clean:
        metrics["add_evaluation"]["failed"] += 1
    elif "add_evaluation returned" in clean:
        metrics["add_evaluation"]["warning"] += 1
    elif "skipping add_evaluation" in clean.lower():
        metrics["add_evaluation"]["skipped"] += 1

    if "uploaded successfully" in clean.lower():
        metrics["gif_upload"]["success"] += 1
    elif "failed to upload" in clean.lower():
        metrics["gif_upload"]["failed"] += 1

    if "[time]" in clean.lower():
        metrics["responses"] += 1
        match_time = re.search(r"process_time=([0-9.]+)", clean)
        if match_time:
            try:
                metrics["process_times"].append(float(match_time.group(1)))
            except ValueError:
                pass
        if "process_time=None" in clean or "response=None" in clean:
            metrics["timeouts"] += 1
    if "returned none response" in clean.lower():
        metrics["none_responses"] += 1

    if "winner uid" in clean.lower():
        metrics["winner"] = True

    match_task = re.search(r"task_id=([0-9A-Za-z_-]+)", clean)
    if match_task:
        task_ids.add(match_task.group(1))
    match_agent = re.search(r"agent_run_id=([0-9A-Za-z_-]+)", clean)
    if match_agent:
        agent_run_ids.add(match_agent.group(1))

if not relevant_entries:
    print(f"Miner report (round {target_round}, uid {target_uid})")
    if source_desc:
        print(f"Source: {source_desc}")
    print()
    print(f"No log entries found for miner uid {target_uid} in round {target_round}.")
    if latest_completed and latest_completed != target_round:
        print(f"Latest completed round found in logs: {latest_completed}")
    sys.exit(0)

def summarize_process_times(values: list[float]) -> str:
    if not values:
        return "n/a"
    if len(values) == 1:
        return f"{values[0]:.3f}s"
    avg = statistics.mean(values)
    sorted_vals = sorted(values)
    idx = max(0, int(round(0.95 * (len(sorted_vals) - 1))))
    p95 = sorted_vals[idx]
    return f"avg={avg:.3f}s, p95≈{p95:.3f}s, n={len(values)}"


print(f"Miner report (round {target_round}, uid {target_uid})")
if source_desc:
    print(f"Source: {source_desc}")
status_label = "active" if round_active else "completed"
print(f"Round status: {status_label}")
if latest_completed and latest_completed != target_round:
    print(f"Latest completed round in logs: {latest_completed}")
print()

print("=== Round Context ===")
if round_header:
    print(round_header)
else:
    print("Round header: not found in captured logs.")
print()

if table_title and miner_table_lines:
    print("=== Miner Summary Row ===")
    print(table_title)
    for line in miner_table_lines:
        print(line)
    print()
elif table_title:
    print("=== Miner Summary Row ===")
    print(table_title)
    print(f"UID {target_uid} not present in table output.")
    print()

print("=== Key Metrics ===")
start_metrics = metrics["start_agent_run"]
eval_metrics = metrics["add_evaluation"]
gif_metrics = metrics["gif_upload"]
print(
    f"start_agent_run: {start_metrics['success']} success, "
    f"{start_metrics['warning']} warnings, {start_metrics['failed']} failures"
)
print(
    f"add_evaluation: {eval_metrics['success']} success, "
    f"{eval_metrics['warning']} warnings, {eval_metrics['failed']} failures, "
    f"{eval_metrics['skipped']} skipped"
)
print(f"GIF uploads: {gif_metrics['success']} success, {gif_metrics['failed']} failures")
print(
    f"Task timings: {metrics['responses']} responses, "
    f"{metrics['timeouts']} fallbacks/timeouts, "
    f"avg time: {summarize_process_times(metrics['process_times'])}"
)
print(f"None responses logged: {metrics['none_responses']}")
if metrics["winner"]:
    print("Winner status: miner recorded as round winner ✅")
else:
    print("Winner status: not recorded as round winner")
if task_ids:
    print(f"Task IDs: {', '.join(sorted(task_ids, key=lambda x: (len(x), x)))}")
if agent_run_ids:
    print(f"Agent run IDs: {', '.join(sorted(agent_run_ids))}")
print()

if warning_entries:
    print("=== Warnings ===")
    for entry in warning_entries:
        tags = entry.get("tags") or []
        ts = entry.get("timestamp") or ""
        clean = entry.get("clean") or entry.get("message") or ""
        prefix = format_tags(tags)
        if ts:
            print(f"{prefix}{ts} {clean}")
        else:
            print(f"{prefix}{clean}")
    print()

if error_entries:
    print("=== Errors ===")
    for entry in error_entries:
        tags = entry.get("tags") or []
        ts = entry.get("timestamp") or ""
        clean = entry.get("clean") or entry.get("message") or ""
        prefix = format_tags(tags)
        if ts:
            print(f"{prefix}{ts} {clean}")
        else:
            print(f"{prefix}{clean}")
    print()

print("=== Timeline ===")
for entry in relevant_entries:
    tags = entry.get("tags") or []
    ts = entry.get("timestamp") or ""
    clean = entry.get("clean") or entry.get("message") or ""
    prefix = format_tags(tags)
    if ts:
        print(f"{prefix}{ts} {clean}")
    else:
        print(f"{prefix}{clean}")

print()
print("End of miner report.")
PY
