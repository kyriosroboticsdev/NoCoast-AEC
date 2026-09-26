"""Run a blocking pipeline function in a thread and stream its `emit` calls as Server-Sent Events."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Callable

from fastapi.responses import StreamingResponse

from core.pipeline import ConflictError, PipelineError

_END = object()


def sse_response(work: Callable[[Callable[[str, str, dict | None], None]], object]) -> StreamingResponse:
    """`work(emit)` runs in a worker thread; every emit becomes an SSE event.
    Events: {stage, message, data} for progress; stage "done" carries the version; stage "error" a message."""
    q: queue.Queue = queue.Queue()

    def emit(stage: str, message: str, data: dict | None = None) -> None:
        q.put({"stage": stage, "message": message, "data": data})

    def run() -> None:
        try:
            work(emit)
        except ConflictError as exc:
            q.put({"stage": "error", "message": str(exc), "data": {"code": 409}})
        except PipelineError as exc:
            q.put({"stage": "error", "message": str(exc), "data": {"code": 422}})
        except Exception as exc:  # noqa: BLE001 - report, don't hang the stream
            q.put({"stage": "error", "message": f"{type(exc).__name__}: {exc}", "data": {"code": 500}})
        finally:
            q.put(_END)

    threading.Thread(target=run, daemon=True).start()

    async def stream():
        while True:
            item = await asyncio.to_thread(q.get)
            if item is _END:
                break
            yield f"event: {item['stage']}\ndata: {json.dumps(item)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
