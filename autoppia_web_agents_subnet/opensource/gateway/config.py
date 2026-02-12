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
