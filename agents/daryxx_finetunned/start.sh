#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi

if [[ -z "${OPENAI_API_KEY:-}" || -z "${OPENAI_MODEL:-}" ]]; then
  echo "OPENAI_API_KEY or OPENAI_MODEL not set. Copy .env.example to .env and fill values." >&2
  exit 1
fi

exec uvicorn autoppia_web_agents_subnet.agents.daryxx_finetunned.app:app --host "${AGENT_HOST:-0.0.0.0}" --port "${AGENT_PORT:-8080}"
