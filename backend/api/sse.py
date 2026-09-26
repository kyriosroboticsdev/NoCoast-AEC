"""Run a blocking pipeline function in a thread and stream its `emit` calls as Server-Sent Events.

Every event carries `seq` (ordinal) and `t` (seconds since the request started) so the UI can show
the run as a timeline."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import Callable

from fastapi.responses import StreamingResponse

from core.pipeline import ConflictError, PipelineError
from logsetup import log

_END = object()


def sse_response(work: Callable[[Callable[[str, str, dict | None], None]], object]) -> StreamingResponse:
    """`work(emit)` runs in a worker thread; every emit becomes an SSE event.
    Events: {seq, t, stage, message, data} for progress; stage "done" carries the version; stage "error" a message."""
    q: queue.Queue = queue.Queue()
    t0 = time.time()
    seq = 0

    def emit(stage: str, message: str, data: dict | None = None) -> None:
        nonlocal seq
        seq += 1
        log.info("stage %s (%.1fs): %s", stage, time.time() - t0, message)
        q.put({"seq": seq, "t": round(time.time() - t0, 2), "stage": stage, "message": message, "data": data})

    def run() -> None:
        try:
            work(emit)
        except ConflictError as exc:
            log.warning("conflict: %s", exc)
            emit("error", str(exc), {"code": 409})
        except PipelineError as exc:
            log.error("pipeline error: %s", exc)
            emit("error", str(exc), {"code": 422})
        except Exception as exc:  # noqa: BLE001 - report, don't hang the stream
            log.exception("unexpected error in pipeline")
            emit("error", f"{type(exc).__name__}: {exc}", {"code": 500})
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
