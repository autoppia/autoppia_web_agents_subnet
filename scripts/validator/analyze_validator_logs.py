#!/usr/bin/env python3
"""
CLI helper that inspects recent validator logs and asks GPT-5 for a structured status report.

Examples:
    # Analyze the last 200 lines from a log file
    python autoppia_web_agents_subnet/scripts/validator/analyze_validator_logs.py \\
        ~/.cache/autoppia/validator.log --lines 200

    # Pull the last 400 lines directly from pm2 process index 11
    python autoppia_web_agents_subnet/scripts/validator/analyze_validator_logs.py \\
        --pm2 11 --lines 400
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import deque
from pathlib import Path
from textwrap import dedent
from typing import Iterable, Sequence

SCRIPT_PATH = Path(__file__).resolve()
IWA_ROOT: Path | None = None
for parent in SCRIPT_PATH.parents:
    candidate = parent / "autoppia_iwa_module"
    if candidate.is_dir():
        IWA_ROOT = candidate
        break
if IWA_ROOT is None:
    raise RuntimeError("Could not locate the 'autoppia_iwa_module' directory relative to this script.")
if str(IWA_ROOT) not in sys.path:
    sys.path.insert(0, str(IWA_ROOT))

from autoppia_iwa.src.llms.infrastructure.llm_service import LLMConfig, LLMFactory


DEFAULT_LINES = 250
DEFAULT_MODEL = "gpt-5.0"
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_TOKENS = 1200
DEFAULT_PATTERN = "*.log"
PROMPT_FILE = Path(__file__).with_name("analyzer_logs_prompt.txt")

GROUP_KEYWORDS: dict[str, Sequence[str]] = {
    "IWAP": ("iwa", "iwap", "phase", "add_evaluation", "gif"),
    "Commitments": ("commit", "weight", "consensus"),
    "IPFS": ("ipfs", "cid", "gateway", "publish"),
    "RoundManagement": ("round", "validator_round", "epoch", "resume"),
    "ErrorsWarnings": ("error", "warning", "traceback", "exception", "fail"),
}

SYSTEM_PROMPT = """\
You are an expert Autoppia validator SRE. You read validator logs and determine the health of validator flows.
You write concise but detailed incident-style notes with clear evidence and focused actions.
Classify each area as OK, WARN, or FAIL. If information is missing, state "Not observed".
"""

ROUND_ID_PATTERN = re.compile(r"(?:validator_round_id|round_id)=([A-Za-z0-9_\-]+)")
ROUND_FALLBACK_PATTERN = re.compile(r"(validator_round_[A-Za-z0-9_\-]+)")


def resolve_log_path(target: str, pattern: str) -> Path:
    path = Path(target).expanduser()
    if path.is_file():
        return path
    if path.is_dir():
        candidates = sorted(path.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
        if not candidates:
            raise FileNotFoundError(f"No files matching pattern '{pattern}' inside {path}")
        return candidates[0]
    raise FileNotFoundError(f"{path} is not a file or directory")


def read_tail(path: Path, lines: int) -> list[str]:
    buffer: deque[str] = deque(maxlen=lines)
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            buffer.append(line.rstrip("\n"))
    return list(buffer)


def clamp_text(lines: Iterable[str], limit: int) -> str:
    joined = "\n".join(lines)
    if len(joined) <= limit:
        return joined
    return joined[-limit:]


def keyword_windows(lines: Sequence[str], keywords: Sequence[str], limit: int = 60) -> list[str]:
    matches: list[str] = []
    lowered = [(line, line.lower()) for line in lines]
    for original, lowered_line in lowered:
        if any(keyword in lowered_line for keyword in keywords):
            matches.append(original)
    if not matches:
        return []
    return matches[-limit:]


def build_focus_blocks(lines: Sequence[str]) -> str:
    sections: list[str] = []
    for label, tokens in GROUP_KEYWORDS.items():
        found = keyword_windows(lines, tuple(token.lower() for token in tokens))
        if found:
            content = clamp_text(found, 6000)
            sections.append(f"## {label}\n{content}")
        else:
            sections.append(f"## {label}\n(No direct matches in recent logs.)")
    return "\n\n".join(sections)


def build_prompt(raw_excerpt: str, focus_blocks: str) -> str:
    guidance = load_prompt_template()
    return (
        f"{guidance}\n\n"
        f"Recent validator log excerpt (most recent last):\n```\n{raw_excerpt}\n```\n\n"
        f"Keyword-focused slices:\n```\n{focus_blocks}\n```"
    )


def load_prompt_template() -> str:
    default_guidance = dedent(
        """\
        Provide a structured analysis with the following sections:

        ### Overall Status
        - status: <OK | WARN | FAIL>
        - evidence:
        - next_steps:

        ### IWAP Pipeline
        - status:
        - evidence:
        - next_steps:

        ### Commitments & Weight Publishing
        - status:
        - evidence:
        - next_steps:

        ### Settlement & IPFS
        - status:
        - evidence:
        - next_steps:

        ### Round Management
        - status:
        - evidence:
        - next_steps:

        ### Summary
        - bullet list of key takeaways

        ### Recommended Actions
        1. Each action should be high-impact and clearly scoped.

        Use bullet points for evidence. Reference timestamps or identifiers when available.
        """
    ).strip()

    try:
        return PROMPT_FILE.read_text(encoding="utf-8").strip() or default_guidance
    except FileNotFoundError:
        return default_guidance


def run_analysis_from_lines(
    lines: Sequence[str],
    *,
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    if not lines:
        raise ValueError("No log lines available for analysis.")

    tail_excerpt = clamp_text(lines, 16000)
    focus = build_focus_blocks(lines)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY must be set to query GPT-5 via OpenAI.")

    config = LLMConfig(model=model, temperature=temperature, max_tokens=max_tokens)
    llm = LLMFactory.create_llm("openai", config=config, api_key=api_key)

    prompt = build_prompt(tail_excerpt, focus)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.strip()},
        {"role": "user", "content": prompt},
    ]

    return llm.predict(messages)


def collect_lines_from_path(target: str | None, pattern: str, lines: int) -> list[str]:
    if not target:
        raise ValueError("Path argument is required when --pm2 is not provided.")
    path = resolve_log_path(target, pattern)
    return read_tail(path, lines)


def collect_lines_from_pm2(identifier: str, lines: int) -> list[str]:
    cmd = ["pm2", "logs", identifier, "--lines", str(lines), "--nostream"]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise FileNotFoundError("pm2 command not found on PATH.") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "unknown error"
        raise RuntimeError(f"pm2 logs failed: {stderr}")

    output = completed.stdout.strip().splitlines()
    return output[-lines:] if lines > 0 else output


def extract_round_id(line: str) -> str | None:
    match = ROUND_ID_PATTERN.search(line)
    if match:
        return match.group(1)

    fallback = ROUND_FALLBACK_PATTERN.search(line)
    if fallback:
        return fallback.group(1)
    return None


def group_lines_by_round(lines: Sequence[str]) -> list[tuple[str, list[str]]]:
    groups: list[tuple[str, list[str]]] = []
    current_round: str | None = None
    current_bucket: list[str] = []

    for line in lines:
        round_id = extract_round_id(line)
        if round_id and round_id != current_round:
            if current_round and current_bucket:
                groups.append((current_round, current_bucket))
            current_round = round_id
            current_bucket = []

        if current_round is not None:
            current_bucket.append(line)

    if current_round and current_bucket:
        groups.append((current_round, current_bucket))

    return groups


def select_recent_rounds(lines: Sequence[str], rounds_to_keep: int) -> tuple[list[str], list[str]]:
    if rounds_to_keep <= 0:
        return list(lines), []

    grouped = group_lines_by_round(lines)
    if not grouped:
        return list(lines), []

    selected = grouped[-rounds_to_keep:]
    flattened: list[str] = []
    selected_ids: list[str] = []
    for round_id, chunk in selected:
        selected_ids.append(round_id)
        flattened.extend(chunk)

    return flattened, selected_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect recent validator logs and ask GPT-5 for a structured health assessment.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Path to a validator log file or directory. Directories select the newest file by pattern.",
    )
    parser.add_argument(
        "--pm2",
        help="PM2 process id or name. When provided, logs are pulled via `pm2 logs` and PATH is optional.",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=0,
        help="Limit analysis to the most recent N validator rounds (requires round markers in logs).",
    )
    parser.add_argument(
        "-n",
        "--lines",
        type=int,
        default=DEFAULT_LINES,
        help=f"Number of recent lines to inspect (default: {DEFAULT_LINES}).",
    )
    parser.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN,
        help=f"Filename glob when PATH is a directory (default: {DEFAULT_PATTERN}).",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI model to use (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help=f"Sampling temperature (default: {DEFAULT_TEMPERATURE}).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Maximum tokens in the LLM response (default: {DEFAULT_MAX_TOKENS}).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.path and not args.pm2:
        raise SystemExit("Provide a log path or use --pm2 to target a running process.")

    try:
        if args.pm2:
            log_lines = collect_lines_from_pm2(args.pm2, args.lines)
        else:
            log_lines = collect_lines_from_path(args.path, args.pattern, args.lines)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"[Analyzer] Failed to collect logs: {exc}")

    if args.rounds and args.rounds > 0:
        try:
            log_lines, selected_rounds = select_recent_rounds(log_lines, args.rounds)
            if selected_rounds:
                print(f"[Analyzer] Selected rounds: {', '.join(selected_rounds)}", file=sys.stderr)
            else:
                print("[Analyzer] No round markers detected; analyzing the full log window.", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"[Analyzer] Failed to slice by rounds: {exc}")

    try:
        result = run_analysis_from_lines(
            log_lines,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"[Analyzer] Failed to produce analysis: {exc}")

    print(result.strip())


if __name__ == "__main__":
    main()
