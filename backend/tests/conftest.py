"""Test settings: isolated output/db dir and the mock LLM, applied before `config` is imported."""

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="nocoast-test-"))
os.environ["BIM_OUTPUT_DIR"] = str(_tmp)
os.environ["BIM_DB_PATH"] = str(_tmp / "test.sqlite3")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["BIM_ENV_FILE"] = str(_tmp / "no.env")  # never let the developer's backend/.env leak into tests
os.environ["BIM_DEMO_DIR"] = str(_tmp / "demo")    # nor the shipped demo runs
