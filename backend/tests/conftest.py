"""Test settings: isolated output/db dir and the mock LLM, applied before `config` is imported."""

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="nocoast-test-"))
os.environ["BIM_OUTPUT_DIR"] = str(_tmp)
os.environ["BIM_DB_PATH"] = str(_tmp / "test.sqlite3")
os.environ["LLM_PROVIDER"] = "mock"
