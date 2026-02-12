import os
from dotenv import load_dotenv
load_dotenv()

COST_LIMIT_ENABLED = os.getenv("COST_LIMIT_ENABLED", "false").lower() == "true"
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
