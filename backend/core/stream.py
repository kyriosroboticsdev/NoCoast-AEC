"""Apply GeoSteps while the model is still generating, and render previews as it goes.

The LLM adapter calls `feed(text)` with the accumulated reply after every chunk. Each newly
completed step is applied to the GeoModel; a step that cannot be applied is rejected on the
spot and the model stays as it was. Every accepted step marks the model dirty; a worker thread
compiles the latest one (geometry-checking only the parts that changed), writes a preview and
emits `partial`.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import Counter
from typing import Callable

from pydantic import ValidationError

import config
from core.guids import GuidMap
from core.partial_json import parse_partial
from ifc.compile import GeometryError, compile_ifc
from llm.base import clean_reply
from logsetup import log
from schemas.geo import GeoModel
from schemas.geosteps import GeoStep, StepError, apply_step, expand_instances

Emit = Callable[[str, str, dict | None], None]

PARTIAL_DIR = config.OUTPUT_DIR / "partial"
PARTIAL_TTL = 1800
STREAM_EVERY = 0.4
PREVIEW_DEBOUNCE = 0.5
STREAM_TEXT_CAP = 30000
HEARTBEAT_EVERY = 3.0


def prune_partials() -> None:
    PARTIAL_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - PARTIAL_TTL
    for f in PARTIAL_DIR.glob("*.ifc"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def describe(geo: GeoModel) -> dict:
    """What a model contains, for the step log: spaces per level and counts by entity."""
    parts = expand_instances(geo)
    rooms = {}
    for part in parts:
        if part.ifc == "IfcSpace":
            rooms.setdefault(part.level, []).append(part.name or part.id)
    return {"elements": len(parts), "levels": len(geo.levels), "rooms": rooms,
            "counts": dict(sorted(Counter(p.ifc for p in parts).items()))}


def diff(before: dict | None, after: dict) -> str:
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

    def __init__(self, emit: Emit, geo: GeoModel, guids: GuidMap | None = None, first_index: int = 0):
        self.emit = emit
        self.geo = geo
        self.guids = dict(guids or {})
        self.first_index = first_index
        self.applied = 0
        self.accepted: list[str] = []
        self.rejected: list[tuple[int, dict, str]] = []
        self.count = 0
        self.skipped = 0
        self._dirty: GeoModel | None = None
        self._cond = threading.Condition()
        self._closed = False
        self._last_desc: dict | None = None
        self._last_parts: dict[str, str] = {}
        self._last_stream = 0.0
        self._chars = 0
        self._started = time.time()
        prune_partials()
        self._thread = threading.Thread(target=self._run, name="preview", daemon=True)
        self._thread.start()
        self._beat = threading.Thread(target=self._heartbeat, name="heartbeat", daemon=True)
        self._beat.start()

    def _heartbeat(self) -> None:
        while True:
            with self._cond:
                self._cond.wait(HEARTBEAT_EVERY)
                if self._closed or self._chars:
                    return
            self.emit("stream", f"waiting for the model… {time.time() - self._started:.0f}s, nothing received yet", {"chars": 0, "text": ""})

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
            step = GeoStep.model_validate(raw)
        except ValidationError as exc:
            self._reject(index, raw, _fmt_validation(exc))
            return False
        try:
            candidate, message = apply_step(self.geo, step)
        except (StepError, ValidationError, ValueError) as exc:
            msg = _fmt_validation(exc) if isinstance(exc, ValidationError) else str(exc)
            self._reject(index, raw, msg)
            return False
        self.geo = candidate
        self.accepted.append(message)
        self.emit("step", f"step {index}: {message}", {"index": index, "ok": True, "message": message, "step": raw,
                                                        "elements": len(expand_instances(candidate))})
        with self._cond:
            self._dirty = candidate
            self._cond.notify()
        return True

    def _reject(self, index: int, raw: dict, error: str) -> None:
        self.rejected.append((index, raw, error))
        log.info("step %d rejected: %s", index, error)
        self.emit("step", f"step {index} rejected: {error}", {"index": index, "ok": False, "step": raw, "error": error})

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify()
        self._thread.join(timeout=120)

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._dirty is None and not self._closed:
                    self._cond.wait()
                if self._dirty is None:
                    return
                if not self._closed:
                    self._cond.wait(PREVIEW_DEBOUNCE)
                geo, self._dirty = self._dirty, None
            try:
                self._render(geo)
            except GeometryError as exc:
                self.skipped += 1
                log.warning("preview geometry failed: %s", exc)
                self.emit("partial", f"preview skipped: {exc}", {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - previews are best effort
                self.skipped += 1
                log.debug("preview skipped: %s", exc)

    def _render(self, geo: GeoModel) -> None:
        if geo.is_empty():
            return
        parts = {p.id: p.model_dump_json() for p in expand_instances(geo)}
        openings = {o.id: o.model_dump_json() for o in geo.openings}
        changed = {i for i, blob in parts.items() if self._last_parts.get(i) != blob}
        for opening in geo.openings:
            if self._last_parts.get(f"opening:{opening.id}") != openings[opening.id]:
                changed.add(opening.host)
        if not changed and set(parts) == {k for k in self._last_parts if not k.startswith("opening:")}:
            return
        t = time.perf_counter()
        model, self.guids = compile_ifc(geo, self.guids, check=changed or None)
        name = f"{uuid.uuid4().hex[:12]}.ifc"
        model.write(str(PARTIAL_DIR / name))
        desc = describe(geo)
        change = diff(self._last_desc, desc)
        self._last_desc = desc
        self._last_parts = parts | {f"opening:{i}": blob for i, blob in openings.items()}
        self.count += 1
        self.emit("partial", f"preview {self.count}: {desc['elements']} elements ({change})",
                  {"ifc_url": f"/models/partial/{name}", "preview": self.count, "change": change,
                   "compile_ms": round((time.perf_counter() - t) * 1000), "steps": self.first_index + self.applied,
                   "checked": len(changed), **desc})


def steps_json(steps: list[dict]) -> str:
    return json.dumps({"steps": steps})
