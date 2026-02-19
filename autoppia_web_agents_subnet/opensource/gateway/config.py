import os
from dotenv import load_dotenv

load_dotenv()

COST_LIMIT_PER_TASK = float(os.getenv("COST_LIMIT_PER_TASK", "10.0"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CHUTES_API_KEY = os.getenv("CHUTES_API_KEY")

# Protect privileged endpoints (/set-allowed-task-ids, /usage/*) from untrusted
# containers on the same Docker network.
SANDBOX_GATEWAY_ADMIN_TOKEN = os.getenv("SANDBOX_GATEWAY_ADMIN_TOKEN")


def _csv_env(name: str) -> set[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


# Optional restrictions to keep cost-accounting reliable.
# If empty, all models/paths are allowed.
DEFAULT_GATEWAY_ALLOWED_PROVIDERS = {"openai", "chutes"}
GATEWAY_ALLOWED_PROVIDERS = _csv_env("GATEWAY_ALLOWED_PROVIDERS") or set(DEFAULT_GATEWAY_ALLOWED_PROVIDERS)
OPENAI_ALLOWED_MODELS = _csv_env("OPENAI_ALLOWED_MODELS")
CHUTES_ALLOWED_MODELS = _csv_env("CHUTES_ALLOWED_MODELS")

# Only allow OpenAI-compatible JSON endpoints that return a usage object.
# If empty, all paths are allowed (not recommended).
OPENAI_ALLOWED_PATHS = _csv_env("OPENAI_ALLOWED_PATHS") or {
    "/v1/chat/completions",
    "/v1/responses",
}
CHUTES_ALLOWED_PATHS = _csv_env("CHUTES_ALLOWED_PATHS") or {
    "/v1/chat/completions",
    "/v1/responses",
}

# If true: reject models that are missing explicit pricing (instead of using a
# fallback price), to prevent under-priced spend.
GATEWAY_STRICT_PRICING = os.getenv("GATEWAY_STRICT_PRICING", "true").lower() == "true"

# Chutes pricing refresh (seconds). Used to populate per-model pricing from the
# public OpenAI-compatible /v1/models endpoint.
CHUTES_PRICING_TTL_SECONDS = float(os.getenv("CHUTES_PRICING_TTL_SECONDS", "3600"))
CHUTES_PRICING_TIMEOUT_SECONDS = float(os.getenv("CHUTES_PRICING_TIMEOUT_SECONDS", "10"))

# Gateway behavior knobs (safe defaults for this subnet use-case).
# Force OpenAI-compatible endpoints to return JSON objects when possible so
# miners can reliably parse decisions. Retries fall back when providers reject it.
GATEWAY_FORCE_JSON_RESPONSE_FORMAT = os.getenv("GATEWAY_FORCE_JSON_RESPONSE_FORMAT", "true").lower() == "true"

# Limit concurrent upstream requests per provider to reduce 429s (especially OpenAI).
GATEWAY_OPENAI_MAX_CONCURRENCY = int(os.getenv("GATEWAY_OPENAI_MAX_CONCURRENCY", "2"))
GATEWAY_CHUTES_MAX_CONCURRENCY = int(os.getenv("GATEWAY_CHUTES_MAX_CONCURRENCY", "8"))

# Upstream retry policy (best-effort) for transient errors.
GATEWAY_UPSTREAM_MAX_RETRIES = int(os.getenv("GATEWAY_UPSTREAM_MAX_RETRIES", "2"))
GATEWAY_UPSTREAM_RETRY_BASE_DELAY_S = float(os.getenv("GATEWAY_UPSTREAM_RETRY_BASE_DELAY_S", "0.5"))
