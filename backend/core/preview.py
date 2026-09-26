"""Live previews while the model is still generating.

The LLM stream reader calls `feed(text)` with the accumulated reply after every
chunk. A worker thread takes only the *latest* snapshot (tokens arrive faster than
a compile), parses the partial JSON, builds a spec from it, compiles it to IFC and,
only if the geometry check passes, writes a preview file and emits a `partial`
event with its URL. Snapshots that don't validate yet are simply skipped; the
final answer goes through the normal validate/repair path afterwards.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import config
from core.partial_json import parse_partial
from ifc.builder import compile_ifc
from llm.base import clean_reply
from logsetup import log
from schemas.bim import BuildingSpec

Emit = Callable[[str, str, dict | None], None]
Build = Callable[[dict], BuildingSpec | None]

PARTIAL_DIR = config.OUTPUT_DIR / "partial"   # served by the /models static mount
PARTIAL_TTL = 1800                             # seconds before old preview files are pruned
STREAM_EVERY = 0.5                             # seconds between "stream" progress events


def prune_partials() -> None:
    PARTIAL_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - PARTIAL_TTL
    for f in PARTIAL_DIR.glob("*.ifc"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


class Preview:
    def __init__(self, emit: Emit, build: Build):
        self.emit, self.build = emit, build
        self._latest: str | None = None
        self._cond = threading.Condition()
        self._closed = False
        self._last_key: str | None = None
        self._last_stream = 0.0
        self.count = 0
        prune_partials()
        self._thread = threading.Thread(target=self._run, name="preview", daemon=True)
        self._thread.start()

    # --- producer side (LLM stream thread) ---------------------------------

    def feed(self, text: str) -> None:
        now = time.time()
        if now - self._last_stream >= STREAM_EVERY:
            self._last_stream = now
            self.emit("stream", f"receiving model output ({len(text)} chars)", {"chars": len(text), "tail": text[-60:]})
        with self._cond:
            self._latest = text
            self._cond.notify()

    def close(self) -> None:
        """Stop after the current compile. Called before the final compile so IfcOpenShell is not used from two threads."""
        with self._cond:
            self._closed = True  # the worker still renders a pending snapshot before it exits
            self._cond.notify()
        self._thread.join(timeout=60)

    # --- consumer side (worker thread) ------------------------------------

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._latest is None and not self._closed:
                    self._cond.wait()
                if self._latest is None:
                    return
                text, self._latest = self._latest, None
            try:
                self._render(text)
            except Exception as exc:  # noqa: BLE001 - previews are best effort
                log.debug("preview skipped: %s", exc)

    def _render(self, text: str) -> None:
        data = parse_partial(clean_reply(text))
        if not isinstance(data, dict):
            return
        spec = self.build(data)
        if spec is None:
            return
        key = spec.model_dump_json()
        if key == self._last_key:
            return
        model, _ = compile_ifc(spec, {})
        name = f"{uuid.uuid4().hex[:12]}.ifc"
        model.write(str(PARTIAL_DIR / name))
        self._last_key = key
        self.count += 1
        self.emit("partial", f"preview {self.count}: {len(spec.elements)} elements",
                  {"ifc_url": f"/models/partial/{name}", "elements": len(spec.elements)})
