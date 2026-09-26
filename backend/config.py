"""Runtime configuration, read once from the environment (and backend/.env if present)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")

OUTPUT_DIR = Path(os.environ.get("BIM_OUTPUT_DIR", BACKEND_DIR / "output"))
DB_PATH = Path(os.environ.get("BIM_DB_PATH", OUTPUT_DIR / "projects.sqlite3"))
PORT = int(os.environ.get("BIM_PORT", 8765))

# LLM adapter selection. See llm/__init__.py.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "mock")  # mock | ollama | openai
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", 600))
MAX_REPAIRS = int(os.environ.get("BIM_MAX_REPAIRS", 2))
