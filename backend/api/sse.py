"""Run a blocking pipeline function in a thread and stream its `emit` calls as Server-Sent Events.

Every event carries `seq` (ordinal) and `t` (seconds since the request started) so the UI can show
the run as a timeline. A comment line goes out every KEEPALIVE seconds while the pipeline is quiet,
which keeps proxies (and the browser's own buffering) from sitting on the connection."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import Callable, Iterable

from fastapi.responses import StreamingResponse

from core.pipeline import ConflictError, PipelineError
from logsetup import log

_END = object()
KEEPALIVE = 1.0  # seconds of silence after which a `: ping` comment is sent
CHATTY = {"stream", "draft"}  # several a second: logged at DEBUG so the INFO log stays a readable timeline
HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def sse_response(work: Callable[[Callable[[str, str, dict | None], None]], object],
                 record: Callable[[list[dict]], object] | None = None) -> StreamingResponse:
    """`work(emit)` runs in a worker thread; every emit becomes an SSE event.
    Events: {seq, t, stage, message, data} for progress; stage "done" carries the version; stage "error" a message.
    `record`, if given, gets every event of the run once it has finished."""
    q: queue.Queue = queue.Queue()
    t0 = time.time()
    seq = 0
    sent: list[dict] = []

    def emit(stage: str, message: str, data: dict | None = None) -> None:
        nonlocal seq
        seq += 1
        live = stage in CHATTY or (stage == "think" and data is not None and "live" in data)
        log.log(10 if live else 20, "stage %s (%.1fs): %s", stage, time.time() - t0, message)
        event = {"seq": seq, "t": round(time.time() - t0, 2), "stage": stage, "message": message, "data": data}
        if record is not None:
            sent.append(event)
        q.put(event)

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
            if record is not None:
                try:
                    record(sent)
                except Exception:  # noqa: BLE001 - a recording must never fail the run
                    log.exception("could not record the run")
            q.put(_END)

    threading.Thread(target=run, daemon=True).start()

    async def stream():
        yield ": open\n\n"  # flush the response head immediately so the client starts reading
        while True:
            try:
                item = await asyncio.to_thread(q.get, True, KEEPALIVE)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            if item is _END:
                break
            yield f"event: {item['stage']}\ndata: {json.dumps(item)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers=HEADERS)


def replay_response(paced: Iterable[tuple[float, dict]]) -> StreamingResponse:
    """Play recorded events back as SSE, each after its pause."""
    async def stream():
        yield ": open\n\n"
        for pause, item in paced:
            if pause:
                await asyncio.sleep(pause)
            yield f"event: {item['stage']}\ndata: {json.dumps(item)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers=HEADERS)
