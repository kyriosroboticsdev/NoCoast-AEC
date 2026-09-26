"""Console logging for the backend. Everything the pipeline does is logged under the `nocoast` logger;
set BIM_LOG_LEVEL=DEBUG to also see LLM prompts and raw replies."""

from __future__ import annotations

import logging
import sys

import config


def setup() -> logging.Logger:
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
        root.addHandler(handler)
    root.setLevel(config.LOG_LEVEL.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return logging.getLogger("nocoast")


log = setup()
