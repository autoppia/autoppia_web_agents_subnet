#!/usr/bin/env bash

set -euo pipefail

DEFAULT_LINES=${LINES:-4000}
DEFAULT_PM2_IDENTIFIER=${PM2_IDENTIFIER:-}

usage() {
    cat <<'USAGE'
Usage: summary.sh [--round N] [--pm2 NAME|ID] [--path LOGFILE] [--lines N]

Summarize validator round information from pm2 logs.

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

for idx in "${!LOG_LINES[@]}"; do
    line=${LOG_LINES[$idx]}
    if [[ "$line" =~ Round[[:space:]]+completed:\ ([0-9]+) ]]; then
        if [[ "${BASH_REMATCH[1]}" == "$target_round" ]]; then
            end_index=$idx
        fi
    fi
done

if (( end_index < 0 )); then
    echo "Could not find completion marker for round $target_round" >&2
    exit 1
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
    fi

done

if (( start_index < 0 )); then
    echo "Could not find start marker for round $target_round" >&2
    exit 1
fi

round_lines=("${LOG_LINES[@]:$start_index:$((end_index - start_index + 1))}")
round_text=$(printf '%s\n' "${round_lines[@]}")

print_section() {
    local title="$1"
    local content="$2"
    if [[ -n "${content// }" ]]; then
        printf '\n=== %s ===\n' "$title"
        printf '%s\n' "$content"
    fi
}

first_marker=$(printf '%s\n' "${round_lines[0]}")
last_index=$(( ${#round_lines[@]} - 1 ))
completion_marker=$(printf '%s\n' "${round_lines[$last_index]}")

task_ready=$(printf '%s\n' "${round_lines[@]}" | grep -F "Task list ready" | head -n1 || true)
tasks_completed=$(printf '%s\n' "${round_lines[@]}" | grep -F "Tasks completed" | tail -n1 || true)
round_id=$(printf '%s\n' "${round_lines[@]}" | grep -F "validator_round_id" | head -n1 || true)
wta_winner=$(printf '%s\n' "${round_lines[@]}" | grep -F "🏆 Winner" | tail -n1 || true)
consensus_lines=$(printf '%s\n' "${round_lines[@]}" | grep -Ei "commit|consensus|aggregated" || true)
score_lines=$(printf '%s\n' "${round_lines[@]}" | grep -E "(Scattered rewards|Updated moving avg scores|Final weights|Updating scores)" || true)

tables=$(printf '%s\n' "${round_lines[@]}" | awk '
    /Round Summary — Miners/ {
        if (in_block) {
            print "";
        }
        in_block=1;
    }
    in_block {
        print $0;
        if ($0 ~ /^\s*$/) {
            in_block=0;
        }
    }
')

commitments=$(printf '%s\n' "${round_lines[@]}" | grep -Ei "commitment" || true)
aggregators=$(printf '%s\n' "${round_lines[@]}" | grep -F "Aggregators:" | tail -n1 || true)

printf 'Validator round summary (round %s)\n' "$target_round"
if [[ -n "$log_path" ]]; then
    source_desc="$log_path"
else
    source_desc="pm2:$pm2_identifier (last $lines lines)"
fi
printf 'Source: %s\n' "$source_desc"

round_markers=$(printf '%s\n%s' "$first_marker" "$completion_marker")
task_summary=$(printf '%s\n%s' "$task_ready" "$tasks_completed")
consensus_summary=$(printf '%s\n%s\n' "$consensus_lines" "$commitments" | awk 'NF { if (!seen[$0]++) print }')

print_section "Round markers" "$round_markers"
print_section "Identifiers" "$round_id"
print_section "Tasks" "$task_summary"
print_section "Consensus & commitments" "$consensus_summary"
print_section "Score updates" "$score_lines"
print_section "Winner" "$wta_winner"
print_section "Aggregators" "$aggregators"
print_section "Round Summary tables" "$tables"

if [[ -z "${tables// }" ]]; then
    print_section "Raw log excerpt" "$round_text"
fi
