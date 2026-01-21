import os
from dotenv import load_dotenv
load_dotenv()

COST_LIMIT_ENABLED = os.getenv("COST_LIMIT_ENABLED", "false").lower() == "true"
COST_LIMIT_VALUE = float(os.getenv("COST_LIMIT", "10.0"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CHUTES_API_KEY = os.getenv("CHUTES_API_KEY")