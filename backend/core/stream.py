"""Apply build steps while the model is still generating, and render previews as it goes.

The LLM adapter calls `feed(text)` with the accumulated reply after every chunk. On
the model's thread each newly completed step (the partial-JSON parser only returns
complete array elements) is applied to the design and the design is re-derived; a
step that cannot be applied is rejected on the spot with a message and the design
stays as it was. Every accepted step marks the design dirty; a worker thread takes
the latest dirty design, compiles it to IFC (geometry-checking only the elements that
changed), writes a preview file and emits a `partial` event. Steps therefore land in
the viewer at the model's pace — typically well under a second apart — while the
expensive compile is coalesced and never blocks the stream.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import Counter
from typing import Callable

import config
from core.clash import new_brick_clashes
from core.derive import DesignError, Derived, analyze
from core.partial_json import parse_partial
from ifc.builder import GeometryError, compile_ifc
from llm.base import clean_reply
from logsetup import log
from pydantic import ValidationError
from schemas.bim import BuildingSpec
from schemas.design import Design
from schemas.steps import Step, StepError, apply_step

Emit = Callable[[str, str, dict | None], None]

PARTIAL_DIR = config.OUTPUT_DIR / "partial"   # served by the /models static mount
PARTIAL_TTL = 1800                             # seconds before old preview files are pruned
STREAM_EVERY = 0.4                             # seconds between "stream" progress events
PREVIEW_DEBOUNCE = 0.5                         # seconds a preview waits for more steps, so a burst renders as one change
STREAM_TEXT_CAP = 30000                        # chars of live reply text sent with each stream event
HEARTBEAT_EVERY = 3.0                          # seconds between "waiting for the model" events before the first chunk


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


def _fmt_validation(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"] for e in exc.errors())


class StepStream:
    """Feeds the model's reply, applies steps as they complete, renders previews on a worker thread."""

    def __init__(self, emit: Emit, design: Design, guids: dict | None = None, first_index: int = 0):
        self.emit = emit
        self.design = design
        self.derived: Derived | None = None
        self.guids = dict(guids or {})
        self.first_index = first_index          # numbering continues across repair rounds
        self.applied = 0                        # steps consumed from the stream
        self.accepted: list[str] = []
        self.rejected: list[tuple[int, dict, str]] = []
        self.count = 0                          # previews rendered
        self.skipped = 0                        # previews that failed the geometry check
        self._dirty: Design | None = None
        self._cond = threading.Condition()
        self._closed = False
        self._last_desc: dict | None = None
        self._last_elements: dict[str, str] = {}
        self._last_stream = 0.0
        self._chars = 0
        self._started = time.time()
        prune_partials()
        self._thread = threading.Thread(target=self._run, name="preview", daemon=True)
        self._thread.start()
        self._beat = threading.Thread(target=self._heartbeat, name="heartbeat", daemon=True)
        self._beat.start()

    def _heartbeat(self) -> None:
        """Say something while the model is silent (grammar compilation, queueing, thinking)."""
        while True:
            with self._cond:
                self._cond.wait(HEARTBEAT_EVERY)
                if self._closed or self._chars:
                    return
            self.emit("stream", f"waiting for the model… {time.time() - self._started:.0f}s, nothing received yet", {"chars": 0, "text": ""})

    # --- producer side (LLM stream thread) ---------------------------------

    def feed(self, text: str) -> None:
        now = time.time()
        if not self._chars:
            with self._cond:
                self._chars = len(text)
                self._cond.notify_all()
        self._chars = len(text)
        if now - self._last_stream >= STREAM_EVERY:
            self._last_stream = now
            self.emit("stream", f"{len(text)} chars received", {"chars": len(text), "text": text[-STREAM_TEXT_CAP:]})
        self.consume(text)

    def consume(self, text: str) -> None:
        """Apply every complete step in `text` that has not been applied yet."""
        data = parse_partial(clean_reply(text))
        if not isinstance(data, dict):
            return
        steps = data.get("steps")
        if isinstance(steps, dict):
            steps = [steps]
        if not isinstance(steps, list) or len(steps) <= self.applied:
            return
        for raw in steps[self.applied:]:
            self.applied += 1
            self.apply(raw)

    def apply(self, raw) -> bool:
        index = self.first_index + self.applied
        if not isinstance(raw, dict):
            self._reject(index, {"raw": raw}, "each step must be a JSON object")
            return False
        try:
            step = Step.model_validate(raw)
        except ValidationError as exc:
            self._reject(index, raw, _fmt_validation(exc))
            return False
        try:
            candidate, message = apply_step(self.design, step)
            derived = analyze(candidate, prune=step.step in ("room", "layout", "level", "remove"))
            if derived.pruned:  # a structural change made some openings/fixtures impossible: drop them, say so
                candidate = derived.design
                message += "; " + "; ".join(derived.pruned)
            hits = new_brick_clashes(self.design, candidate, derived.spec)
            if hits:
                raise StepError(hits[0].message)
        except (StepError, DesignError, ValidationError, ValueError) as exc:
            msg = _fmt_validation(exc) if isinstance(exc, ValidationError) else str(exc)
            if isinstance(exc, DesignError):
                msg = f"applying this step makes the design unbuildable: {msg}"
            self._reject(index, raw, msg)
            return False
        self.design, self.derived = candidate, derived
        self.accepted.append(message)
        self.emit("step", f"step {index}: {message}", {"index": index, "ok": True, "message": message, "step": raw,
                                                        "elements": len(derived.spec.elements)})
        with self._cond:
            self._dirty = candidate
            self._cond.notify()
        return True

    def _reject(self, index: int, raw: dict, error: str) -> None:
        self.rejected.append((index, raw, error))
        log.info("step %d rejected: %s", index, error)
        self.emit("step", f"step {index} rejected: {error}", {"index": index, "ok": False, "step": raw, "error": error})

    def close(self) -> None:
        """Render the last pending design, then stop. Called before the final compile so IfcOpenShell is not used from two threads."""
        with self._cond:
            self._closed = True
            self._cond.notify()
        self._thread.join(timeout=120)

    # --- consumer side (worker thread) ------------------------------------

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._dirty is None and not self._closed:
                    self._cond.wait()
                if self._dirty is None:
                    return
                if not self._closed:
                    self._cond.wait(PREVIEW_DEBOUNCE)
                design, self._dirty = self._dirty, None
            try:
                self._render(design)
            except GeometryError as exc:
                self.skipped += 1
                log.warning("preview geometry failed: %s", exc)
                self.emit("partial", f"preview skipped: {exc}", {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - previews are best effort
                self.skipped += 1
                log.debug("preview skipped: %s", exc)

    def _render(self, design: Design) -> None:
        if not design.rooms and not design.elements:
            return  # nothing to look at yet (levels only); the first preview waits for a room
        derived = analyze(design)
        spec = derived.spec
        elements = {e.id: e.model_dump_json() for e in spec.elements}
        changed = {i for i, j in elements.items() if self._last_elements.get(i) != j}
        if not changed and set(elements) == set(self._last_elements):
            return
        t = time.perf_counter()
        model, self.guids = compile_ifc(spec, self.guids, design.model_dump_json(), check=changed)
        name = f"{uuid.uuid4().hex[:12]}.ifc"
        model.write(str(PARTIAL_DIR / name))
        desc = describe(spec)
        change = diff(self._last_desc, desc)
        self._last_desc, self._last_elements = desc, elements
        self.count += 1
        self.emit("partial", f"preview {self.count}: {desc['elements']} elements ({change})",
                  {"ifc_url": f"/models/partial/{name}", "preview": self.count, "change": change,
                   "compile_ms": round((time.perf_counter() - t) * 1000), "steps": self.first_index + self.applied,
                   "checked": len(changed), **desc})


def steps_json(steps: list[dict]) -> str:
    return json.dumps({"steps": steps})
