"""Runtime configuration from the environment and backend/.env.

`reload()` re-reads .env, so changing the provider or model does not need a backend
restart: the API calls it before each LLM request and on /health. Storage paths and
the port are read once at import (they cannot change while the server runs).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = Path(os.environ.get("BIM_ENV_FILE", BACKEND_DIR / ".env"))  # tests point this at an empty file
load_dotenv(ENV_FILE)

OUTPUT_DIR = Path(os.environ.get("BIM_OUTPUT_DIR", BACKEND_DIR / "output"))
DB_PATH = Path(os.environ.get("BIM_DB_PATH", OUTPUT_DIR / "projects.sqlite3"))
PORT = int(os.environ.get("BIM_PORT", 8765))
DEMO_DIR = Path(os.environ.get("BIM_DEMO_DIR", BACKEND_DIR / "demo"))  # packed runs restored at startup (core/replay.py)

# Set by reload(); listed here so the names exist for imports.
LLM_PROVIDER = LLM_MODEL = LLM_BASE_URL = LLM_API_KEY = ""
LLM_TIMEOUT = 600.0
MAX_REPAIRS = 2
NET_RETRIES = 3
ANTHROPIC_WORKSPACE_ID = LLAMA_SERVER = LLM_MODELS_DIR = ""
LOG_LEVEL = "INFO"
LLM_VISION: bool | None = None


def reload() -> None:
    """Re-read .env (values there override the process environment) and refresh the LLM settings."""
    global LLM_PROVIDER, LLM_MODEL, LLM_BASE_URL, LLM_API_KEY, LLM_TIMEOUT, MAX_REPAIRS, NET_RETRIES
    global ANTHROPIC_WORKSPACE_ID, LLAMA_SERVER, LLM_MODELS_DIR, LOG_LEVEL, LLM_VISION
    load_dotenv(ENV_FILE, override=True)
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "mock")           # mock | llamacpp | claude | ollama | openai
    LLM_MODEL = os.environ.get("LLM_MODEL", "")
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
    LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", 600))
    MAX_REPAIRS = int(os.environ.get("BIM_MAX_REPAIRS", 2))
    NET_RETRIES = int(os.environ.get("BIM_NET_RETRIES", 3))   # extra attempts after a dropped connection or a 429/5xx
    ANTHROPIC_WORKSPACE_ID = os.environ.get("ANTHROPIC_WORKSPACE_ID", "")  # claude provider, org-level keys only
    LLAMA_SERVER = os.environ.get("LLAMA_SERVER", "")        # llamacpp provider: path to llama-server(.exe)
    LLM_MODELS_DIR = os.environ.get("LLM_MODELS_DIR", "")    # llamacpp provider: folder with .gguf files
    LOG_LEVEL = os.environ.get("BIM_LOG_LEVEL", "INFO")
    vision = os.environ.get("LLM_VISION", "").strip().lower()   # 1/0 overrides whether the model is sent screenshots
    LLM_VISION = None if not vision else vision in ("1", "true", "yes", "on")


reload()
