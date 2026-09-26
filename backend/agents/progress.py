"""Live progress reporting: planners and the IFC builder narrate what they're doing.

Each step is emitted twice — when it starts ("running") and when it ends ("done"/"error",
with its duration) — so a UI can show a live, nested trace. Without a sink it's a no-op.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Literal, Optional

Phase = Literal["plan", "validate", "build", "load"]


class Step:
    def __init__(self, progress: "Progress", title: str, phase: Phase, parent: Optional[str], layer: bool):
        self.id = uuid.uuid4().hex[:8]
        self.title = title
        self.detail: Optional[str] = None
        self._p = progress
        self._phase = phase
        self._parent = parent
        self._layer = layer
        self._t0 = time.perf_counter()

    def _emit(self, status: str, **extra: Any) -> None:
        self._p.emit({
            "type": "step", "id": self.id, "parent": self._parent, "phase": self._phase,
            "title": self.title, "detail": self.detail, "status": status, "layer": self._layer, **extra,
        })

    def update(self, detail: str) -> None:
        """Change the detail line while the step is still running."""
        self.detail = detail
        self._emit("running")


class Progress:
    def __init__(self, sink: Optional[Callable[[dict], None]] = None):
        self._sink = sink

    def emit(self, event: dict) -> None:
        if self._sink:
            self._sink(event)

    @contextmanager
    def step(self, title: str, *, phase: Phase, parent: Optional[Step] = None, detail: Optional[str] = None,
             layer: bool = False) -> Iterator[Step]:
        s = Step(self, title, phase, parent.id if parent else None, layer)
        s.detail = detail
        s._emit("running")
        try:
            yield s
        except Exception as exc:
            s._emit("error", ms=round((time.perf_counter() - s._t0) * 1000), error=str(exc))
            raise
        s._emit("done", ms=round((time.perf_counter() - s._t0) * 1000))

    def note(self, title: str, *, phase: Phase, parent: Optional[Step] = None, detail: Optional[str] = None) -> None:
        """A step that's already finished — a finding rather than work."""
        with self.step(title, phase=phase, parent=parent, detail=detail):
            pass


NO_PROGRESS = Progress()
