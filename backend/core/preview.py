"""Live previews while the model is still generating.

The LLM stream reader calls `feed(text)` with the accumulated reply after every
chunk. A worker thread takes only the *latest* snapshot (tokens arrive faster than
a compile), parses the partial JSON, builds a spec from it, compiles it to IFC and,
only if the geometry check passes, writes a preview file and emits a `partial`
event with its URL and a description of what it contains and what changed.
Snapshots that don't validate yet are simply skipped; the final answer goes through
the normal validate/repair path afterwards.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import Counter
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
STREAM_EVERY = 0.4                             # seconds between "stream" progress events
STREAM_TEXT_CAP = 30000                        # chars of live reply text sent with each stream event
RENDER_EVERY = 0.3                             # floor between "partial" IFC renders, so the viewer's
                                                # 300ms poll/update loop always has something new-ish
                                                # to pick up without a fast local model spamming it


def prune_partials() -> None:
    PARTIAL_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - PARTIAL_TTL
    for f in PARTIAL_DIR.glob("*.ifc"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def describe(spec: BuildingSpec) -> dict:
    """What a spec contains, for the step log: rooms per level and element counts by type."""
    rooms = {l.id: [e.name or e.id for e in spec.elements if e.type == "space" and e.level == l.id] for l in spec.levels}
    return {"elements": len(spec.elements), "levels": len(spec.levels), "rooms": rooms,
            "counts": dict(sorted(Counter(e.type for e in spec.elements).items()))}


def diff(before: dict | None, after: dict) -> str:
    """One line saying what changed between two `describe()` results."""
    if before is None:
        return "first preview"
    parts = []
    d = after["elements"] - before["elements"]
    if d:
        parts.append(f"{d:+d} elements")
    for level, names in after["rooms"].items():
        new = [n for n in names if n not in before["rooms"].get(level, [])]
        if new:
            parts.append(f"{level}: +{', '.join(new)}")
    gone = [n for level, names in before["rooms"].items() for n in names if n not in after["rooms"].get(level, [])]
    if gone:
        parts.append(f"removed {', '.join(gone)}")
    if after["levels"] != before["levels"]:
        parts.append(f"{after['levels']} levels")
    return "; ".join(parts) or "geometry changed"


class Preview:
    def __init__(self, emit: Emit, build: Build):
        self.emit, self.build = emit, build
        self._latest: str | None = None
        self._cond = threading.Condition()
        self._closed = False
        self._last_key: str | None = None
        self._last_desc: dict | None = None
        self._last_stream = 0.0
        self._started = time.time()
        self._last_render = 0.0
        self.count = 0
        self.skipped = 0
        prune_partials()
        self._thread = threading.Thread(target=self._run, name="preview", daemon=True)
        self._thread.start()

    # --- producer side (LLM stream thread) ---------------------------------

    def feed(self, text: str) -> None:
        now = time.time()
        if now - self._last_stream >= STREAM_EVERY:
            self._last_stream = now
            self.emit("stream", f"{len(text)} chars received", {"chars": len(text), "text": text[-STREAM_TEXT_CAP:]})
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
            wait = self._last_render + RENDER_EVERY - time.time()
            if wait > 0:
                time.sleep(wait)  # steady cadence, not "as fast as a compile allows"
            self._last_render = time.time()
            try:
                self._render(text)
            except Exception as exc:  # noqa: BLE001 - previews are best effort
                self.skipped += 1
                log.debug("preview skipped: %s", exc)

    def _render(self, text: str) -> None:
        data = parse_partial(clean_reply(text))
        if not isinstance(data, dict):
            return
        spec = self.build(data)
        if spec is None:
            self.skipped += 1
            return
        key = spec.model_dump_json()
        if key == self._last_key:
            return
        t = time.perf_counter()
        model, _ = compile_ifc(spec, {})
        name = f"{uuid.uuid4().hex[:12]}.ifc"
        model.write(str(PARTIAL_DIR / name))
        desc = describe(spec)
        change = diff(self._last_desc, desc)
        self._last_key, self._last_desc = key, desc
        self.count += 1
        self.emit("partial", f"preview {self.count}: {desc['elements']} elements ({change})",
                  {"ifc_url": f"/models/partial/{name}", "preview": self.count, "change": change,
                   "compile_ms": round((time.perf_counter() - t) * 1000), "chars": len(text), **desc})
