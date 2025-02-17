import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# ============================
# LLM CONFIGURATION
# ============================
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local")  # Can be "serverless", "local", or "openai"
LLM_THRESHOLD = 100
LLM_ENPOINT = os.getenv("LLM_ENPOINT", "http://127.0.0.1:6000/generate")

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-32k-0613")
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", 2000))
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", 0.7))

# Validate critical environment variables
if LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER is set to 'openai'.")

# ==================================
# Database and File Configuration
# ==================================
MONGODB_URL = "mongodb://localhost:27017"
MONGODB_NAME = "workflow"
ANALYSIS_COLLECTION = "web_analysis"
TASKS_COLLECTION = "tasks"
DOCUMENTS_DIR = "data/web_analysis_files"

# ============================
# Browser and Chrome Paths
# ============================
CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH", "/opt/chromedriver/chromedriver-linux64/chromedriver")
CHROME_PATH = os.getenv("CHROME_PATH", "/opt/chrome/chrome-linux64/chrome")
PROFILE_DIR = os.getenv("PROFILE_DIR", "~/.config/google-chrome/Profile 6")
PROFILE = os.getenv("PROFILE", "Profile 6")

# ============================
# Application Configuration
# ============================
GENERATE_MILESTONES = os.getenv("GENERATE_MILESTONES", "false").lower() == "true"

# ============================
# Project Base Directory Path
# ============================
PROJECT_BASE_DIR = Path(__file__).resolve().parents[1]


# ============================
# DEMO WEBS
# ============================
DEMO_WEBS_ENDPOINT = os.getenv("DEMO_WEBS_ENDPOINT", "http://localhost")
DEMO_WEBS_STARTING_PORT = int(os.getenv("DEMO_WEBS_STARTING_PORT", '8000'))

# ============================
# Agent Configurations
# ============================
AGENT_NAME = os.getenv("AGENT_NAME")
AGENT_HOST = os.getenv("AGENT_HOST", 'localhost')
AGENT_PORT = int(os.getenv("AGENT_PORT", '8080'))
