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
printf '%s\n' "${round_lines[@]}" > "$tmpfile"

TARGET_ROUND="$target_round" \
SOURCE_DESC="$source_desc" \
ROUND_ACTIVE="$round_active" \
LATEST_COMPLETED="${latest_completed_round:-}" \
python3 - "$tmpfile" <<'PY'
import os
import re
import sys
from collections import OrderedDict

target_round = os.environ.get("TARGET_ROUND", "?")
source_desc = os.environ.get("SOURCE_DESC", "")
round_active = os.environ.get("ROUND_ACTIVE", "0") == "1"
latest_completed = os.environ.get("LATEST_COMPLETED", "") or ""

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
    timestamp = None
    level = None
    message = ""

    # Detect pm2-prefixed log lines (id|name|timestamp|level|module|message)
    if raw.lstrip().split("|", 1)[0].strip().isdigit() if "|" in raw else False:
        pm2_parts = raw.split("|", 5)
        if len(pm2_parts) >= 6:
            timestamp = pm2_parts[2].strip() or None
            level = pm2_parts[3].strip() or None
            message = pm2_parts[5].strip()
        else:
            message = pm2_parts[-1].strip()

    if not message:
        parts = raw.split(None, 2)
        if len(parts) >= 3 and ts_pattern.match(parts[0]):
            timestamp = timestamp or parts[0]
            level = level or parts[1]
            message = parts[2]
        else:
            message = raw

    entries.append({"raw": raw, "message": message.strip(), "timestamp": timestamp, "level": level})

def strip_pm2_prefix(text: str | None) -> str:
    if not text:
        return ""
    raw = text.rstrip()
    if "|" not in raw:
        return raw.strip()
    parts = raw.split("|", 5)
    if not parts or not parts[0].strip().isdigit():
        return raw.strip()
    # Drop id and name segments when present
    remainder = parts[1:]
    if remainder:
        remainder = remainder[1:]
    message = remainder[-1] if remainder else ""
    if not message and remainder:
        message = remainder[-1]
    if not message and parts:
        message = parts[-1]
    return message.strip()

COLOR_TITLE = "\033[95m"
COLOR_RESET = "\033[0m"
COLOR_OK = "\033[92m"
COLOR_WARN = "\033[93m"
COLOR_FAIL = "\033[91m"

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

def table_section() -> tuple[str | None, list[str]]:
    title = None
    block: list[str] = []
    capturing = False
    stop_tokens = ("[IPFS]", "[CONSENSUS]", "Round stats", "Scattered rewards", "Updated moving avg", "Tasks completed", "Winner", "Round completed")
    for entry in entries:
        msg = entry["message"]
        raw = strip_pm2_prefix(entry["raw"])
        display = msg.strip() or raw
        if "Round Summary — Miners" in msg:
            title = display
            block.append(title)
            capturing = True
            continue
        if not capturing:
            continue
        if not display.strip():
            block.append("")
            continue
        if any(token in display for token in stop_tokens):
            break
        block.append(display)
    return title, block

def format_section(title: str, lines: list[str]) -> None:
    if not lines:
        return
    print(f"{COLOR_TITLE}=== {title} ==={COLOR_RESET}")
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

table_title, table_block = table_section()

def count_table_rows(lines: list[str]) -> int:
    count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        stripped = stripped.lstrip("│┣┫┠┨┤┘└┴┬┼─━┄┅┆┇┈┉┊┋ ")
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if re.match(r"^\d+", stripped):
            count += 1
    return count

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

miner_rows_count = count_table_rows(table_block[1:] if table_block else [])
if miner_rows_count == 0:
    miner_rows_count = len(collect_messages(r"Score=\d"))

status_label = "completed" if not round_active else "active"
phase = "unknown"
phase_details: list[str] = []

def append_detail(line: str) -> None:
    if not line:
        return
    clean_line = strip_pm2_prefix(line)
    if clean_line and clean_line not in phase_details:
        phase_details.append(clean_line)

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

round_header_clean = strip_pm2_prefix(round_header)
validator_uid = None
hotkey_prefix = None
if round_header_clean:
    m_uid = re.search(r"validator_uid=([0-9]+)", round_header_clean)
    if m_uid:
        validator_uid = m_uid.group(1)
    m_hotkey = re.search(r"hotkey=([^\s|]+)", round_header_clean)
    if m_hotkey:
        hotkey_prefix = m_hotkey.group(1)
validator_round_id = round_info.get("Validator Round ID")
if not validator_round_id and round_header_clean:
    m_rid = re.search(r"validator_round_id=([^\s|]+)", round_header_clean)
    if m_rid:
        validator_round_id = m_rid.group(1)

if round_active:
    round_context_label = "CURRENT ROUND (in progress)"
elif latest_completed and target_round == latest_completed:
    round_context_label = "Latest completed round"
elif latest_completed:
    round_context_label = f"Historical round (latest completed: {latest_completed})"
else:
    round_context_label = "Historical round"

def parse_int(text: str | None, pattern: str) -> int | None:
    if not text:
        return None
    match = re.search(pattern, text)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None

def parse_int_pair(text: str | None, pattern: str) -> tuple[int | None, int | None]:
    if not text:
        return (None, None)
    match = re.search(pattern, text)
    if match:
        try:
            first = int(match.group(1))
        except Exception:
            first = None
        try:
            second = int(match.group(2))
        except Exception:
            second = None
        return (first, second)
    return (None, None)

task_ready_clean = strip_pm2_prefix(task_ready)
tasks_completed_clean = strip_pm2_prefix(tasks_completed_display)
handshake_line_clean = strip_pm2_prefix(handshake_line)
handshake_sent_clean = strip_pm2_prefix(handshake_sent_line) if handshake_sent_line else ""
clean_winner = strip_pm2_prefix(winner_line)
clean_aggregators = strip_pm2_prefix(aggregators_line)

planned_tasks = parse_int(round_info.get("Tasks to Execute"), r"(\d+)")
if planned_tasks is None:
    planned_tasks = parse_int(task_ready_clean, r"Task list ready:\s*([0-9]+)")

completed_tasks, completed_total = parse_int_pair(tasks_completed_clean, r"Tasks completed[:\s]*(\d+)\s*/\s*(\d+)")
handshake_responded, handshake_total = parse_int_pair(handshake_line_clean, r"(\d+)\s*/\s*(\d+)\s*Miners Responded")

consensus_published_clean = [strip_pm2_prefix(line) for line in consensus_published]
consensus_commits_clean = [strip_pm2_prefix(line) for line in consensus_commits]
consensus_fetch_clean = [strip_pm2_prefix(line) for line in consensus_fetch]
consensus_meta_clean = [strip_pm2_prefix(line) for line in consensus_meta]
score_updates_clean = [strip_pm2_prefix(line) for line in score_updates]

consensus_upload_ok = any("✅" in line and "[IPFS] [UPLOAD]" in line for line in consensus_published_clean)
consensus_commit_ok = any("✅" in line and "[IPFS] [BLOCKCHAIN]" in line for line in consensus_published_clean)
consensus_fetch_ok = any("✅" in line for line in consensus_fetch_clean)
final_weights_logged = any("Final weights" in line or "Updating scores" in line for line in score_updates_clean)
winner_logged = bool(strip_pm2_prefix(winner_line))
round_completion_logged = (not round_active) and any("Round completed" in strip_pm2_prefix(entry["message"]) for entry in entries[-10:])
tasks_match_plan = None
if planned_tasks is not None and completed_tasks is not None:
    tasks_match_plan = completed_tasks >= planned_tasks

handshake_ok = handshake_responded is not None and handshake_responded > 0
fetch_aggregated_ok = any("Aggregated scores" in line or "Using aggregated scores" in line for line in consensus_meta_clean + consensus_fetch_clean)
weights_set_ok = any("Updating scores for on-chain WTA winner" in line or "set_weights" in line.lower() for line in score_updates_clean + consensus_meta_clean)

consensus_publish_status = consensus_upload_ok if consensus_published_clean else None
if consensus_published_clean:
    consensus_publish_detail = "upload success log" if consensus_upload_ok else "upload success missing"
else:
    consensus_publish_detail = "no upload logs"

consensus_commit_status = consensus_commit_ok if consensus_published_clean else None
if consensus_published_clean:
    consensus_commit_detail = "commit success log" if consensus_commit_ok else "commit success missing"
else:
    consensus_commit_detail = "no commit logs"

consensus_fetch_status = consensus_fetch_ok if consensus_fetch_clean else None
if consensus_fetch_clean:
    consensus_fetch_detail = "fetch success log" if consensus_fetch_ok else "fetch success missing"
else:
    consensus_fetch_detail = "no fetch logs"

aggregated_status = fetch_aggregated_ok if consensus_meta_clean or consensus_fetch_clean else None
if consensus_meta_clean or consensus_fetch_clean:
    aggregated_detail = "aggregated scores success" if fetch_aggregated_ok else "aggregated scores missing"
else:
    aggregated_detail = "no aggregation logs"

final_weights_status = final_weights_logged if score_updates_clean else None
if score_updates_clean:
    final_weights_detail = "final weight log" if final_weights_logged else "final weight log missing"
else:
    final_weights_detail = "no final weight logs"

weights_set_status = weights_set_ok if score_updates_clean or consensus_meta_clean else None
if score_updates_clean or consensus_meta_clean:
    weights_set_detail = "weight update log" if weights_set_ok else "weight update missing"
else:
    weights_set_detail = "no weight update logs"

checks: list[tuple[str, bool | None, str]] = []
checks.append(("Tasks executed", tasks_match_plan, f"{completed_tasks or '?'} / {planned_tasks or '?'} tasks"))
checks.append(("Task completion log present", bool(tasks_completed_clean), tasks_completed_clean or "missing"))
if handshake_line_clean:
    checks.append(("Handshake responses", handshake_ok, f"{handshake_responded or 0}/{handshake_total or '?'} responded"))
else:
    checks.append(("Handshake responses", None, "no handshake info"))
checks.append(("Consensus publish (IPFS)", consensus_publish_status, consensus_publish_detail))
checks.append(("Consensus commit on-chain", consensus_commit_status, consensus_commit_detail))
checks.append(("Consensus fetch", consensus_fetch_status, consensus_fetch_detail))
checks.append(("Aggregated scores fetched", aggregated_status, aggregated_detail))
checks.append(("Winner recorded", winner_logged if not round_active else winner_logged or None, clean_winner or "Winner missing"))
checks.append(("Final weights logged", final_weights_status, final_weights_detail))
checks.append(("Weights set on-chain", weights_set_status, weights_set_detail))
checks.append(("Round completion marker", round_completion_logged if not round_active else None, "Round completed log"))

print(f"Validator round report (round {target_round})")
if source_desc:
    print(f"Source: {source_desc}")
print()

print("=== Round Overview ===")
headline = f"ROUND: {target_round}"
if validator_uid:
    headline += f" | Validator UID: {validator_uid}"
if hotkey_prefix:
    headline += f" | Hotkey: {hotkey_prefix}"
print(headline)
print(f"Round context: {round_context_label}")
if validator_round_id:
    print(f"Validator Round ID: {validator_round_id}")
if round_header_clean:
    print(round_header_clean)
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
    markers.append(strip_pm2_prefix(entries[0]["raw"]))
    markers.append(strip_pm2_prefix(entries[-1]["raw"]))
format_section("Round markers", markers)

def format_check_row(label: str, status: bool | None, detail: str) -> str:
    if status is None:
        return f"{COLOR_WARN}[--]{COLOR_RESET} {label}: {detail}"
    if status:
        return f"{COLOR_OK}[OK]{COLOR_RESET} {label}: {detail}"
    return f"{COLOR_FAIL}[FAIL]{COLOR_RESET} {label}: {detail}"

check_lines = [format_check_row(label, status, detail) for label, status, detail in checks]
format_section("Health checks", check_lines)

tasks_section: list[str] = []
if task_ready:
    tasks_section.append(task_ready_clean)
if "Tasks to Execute" in round_info:
    tasks_section.append(f"Planned tasks: {round_info['Tasks to Execute']}")
if tasks_completed_display:
    tasks_section.append(tasks_completed_clean)
format_section("Tasks", tasks_section)

miners_section: list[str] = []
if handshake_line:
    miners_section.append(handshake_line_clean)
if handshake_sent_clean and handshake_sent_clean not in miners_section:
    miners_section.append(handshake_sent_clean)
if miner_rows_count:
    miners_section.append(f"Miners evaluated (from summary table): {miner_rows_count}")
format_section("Miners", miners_section)

if table_title or table_block:
    table_lines = []
    if table_block:
        table_lines.extend(table_block)
    elif table_title:
        table_lines.append(table_title)
    if table_lines and f"Round {target_round}" not in table_lines[0]:
        table_lines.insert(0, f"Round Summary — Miners — Round {target_round}")
    format_section("Round Summary table", table_lines)

score_lines = []
if clean_winner:
    score_lines.append(clean_winner)
if clean_aggregators:
    score_lines.append(clean_aggregators)
for line in score_updates_clean:
    if line and line not in score_lines:
        score_lines.append(line)
format_section("Scores & winners", score_lines)

consensus_section: list[str] = []
for line in consensus_published_clean:
    if line:
        consensus_section.append(line)
for line in consensus_commits_clean:
    if line:
        consensus_section.append(line)
format_section("Consensus publish", consensus_section)

fetch_section: list[str] = []
for line in consensus_fetch_clean:
    if line:
        fetch_section.append(line)
for line in consensus_meta_clean:
    if line and line not in fetch_section:
        fetch_section.append(line)
for line in commitment_mentions:
    clean_line = strip_pm2_prefix(line)
    if clean_line and clean_line not in fetch_section:
        fetch_section.append(clean_line)
format_section("Consensus fetch & shared scores", fetch_section)
PY
rm -f "$tmpfile"
