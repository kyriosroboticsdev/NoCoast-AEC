"""Export a project version as a final deliverable.

    GET  /projects/{id}/versions/{n}/validate   check the version's IFC (fast; ?thorough=true adds schema rules)
    POST /projects/{id}/versions/{n}/export     validated, stamped IFC, or a .zip bundle (multipart)

The export form has an `options` field (JSON, see ExportOptions) and zero or more `snapshots`
(PNG files rendered by the app). With `strict` on, a version that fails validation is refused
with 422 and the report, so a broken file never leaves the tool by accident.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Literal

import ifcopenshell
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from api.routes import _project, _version, store
from export.bundle import MAX_SNAPSHOTS, BundleFile, build_bundle, check_snapshot, safe_stem
from export.stamp import ExportMeta, LineageEntry, stamp
from export.validate import ValidationReport, validate_ifc
from logsetup import log

router = APIRouter()

# Headers the browser may read on a cross-origin response (the UI runs on another port).
EXPOSED_HEADERS = ["Content-Disposition", "X-Export-Filename", "X-Validation-Status"]


class ExportOptions(ExportMeta):
    format: Literal["ifc", "zip"] = "ifc"
    strict: bool = True  # refuse to export a version that fails validation
    thorough: bool = True  # include the schema's WHERE rules (a few seconds per model)


def _lineage(project_id: str, number: int) -> list[LineageEntry]:
    """This version and its ancestors, oldest first: the prompts that produced it."""
    out: list[LineageEntry] = []
    seen: set[int] = set()
    current: int | None = number
    while current is not None and current not in seen:
        seen.add(current)
        v = store.get_version(project_id, current)
        if v is None:
            break
        out.append(LineageEntry(number=v.number, mode=v.mode, prompt=v.prompt, llm=v.llm))
        current = v.parent
    return out[::-1]


def _open(path: str) -> ifcopenshell.file:
    try:
        return ifcopenshell.open(path)
    except Exception as exc:  # noqa: BLE001 - IfcOpenShell raises its own error types
        raise HTTPException(500, f"stored IFC cannot be read: {exc}") from exc


@router.get("/projects/{project_id}/versions/{number}/validate")
def validate_version(project_id: str, number: int, thorough: bool = False) -> ValidationReport:  # sync: runs in a worker thread
    return validate_ifc(_open(_version(project_id, number).ifc_path), thorough=thorough)


@router.post("/projects/{project_id}/versions/{number}/export")
async def export_version(
    project_id: str,
    number: int,
    options: str = Form("{}"),
    snapshots: list[UploadFile] = File(default_factory=list),
) -> Response:
    project = _project(project_id)
    version = _version(project_id, number)
    try:
        opts = ExportOptions.model_validate(json.loads(options or "{}"))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(422, f"invalid export options: {exc}") from exc

    # Read snapshots before the slow work, so bad uploads fail fast.
    images: list[BundleFile] = []
    if opts.format == "zip":
        if len(snapshots) > MAX_SNAPSHOTS:
            raise HTTPException(422, f"at most {MAX_SNAPSHOTS} snapshots")
        names: set[str] = set()
        for upload in snapshots:
            data = await upload.read()
            try:
                name = check_snapshot(upload.filename or "snapshot.png", data)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            while name in names:
                name = name.removesuffix(".png") + "-1.png"
            names.add(name)
            images.append(BundleFile(name, data))

    # Validation, stamping and zipping take seconds of CPU; run them off the event loop so the server
    # keeps answering (health checks, other requests) meanwhile.
    return await run_in_threadpool(_export, project, version, number, opts, images)


def _export(project, version, number: int, opts: ExportOptions, images: list[BundleFile]) -> Response:
    project_id = project.id
    t0 = time.perf_counter()
    model = _open(version.ifc_path)  # a fresh copy; the stored file is never modified
    report = validate_ifc(model, thorough=opts.thorough)
    if opts.strict and not report.ok:
        raise HTTPException(422, {"message": "version failed validation; fix it or export with strict off",
                                  "report": report.model_dump()})

    stem = f"{safe_stem(opts.project_name or project.name)}-v{number}"
    now = time.time()
    exported_at = datetime.fromtimestamp(now, tz=timezone.utc).isoformat(timespec="seconds")
    lineage = _lineage(project_id, number)
    stamp(model, opts, project_id=project_id, version=number, lineage=lineage,
          validation_status=("passed" if report.ok else "failed") + (" (with schema rules)" if report.thorough else ""),
          filename=f"{stem}.ifc", exported_at=now)

    # Stamping only adds metadata, but check the result anyway before handing it over.
    after = validate_ifc(model, thorough=False)
    if report.ok and not after.ok:
        log.error("export: stamping broke %s v%d: %s", project_id, number, after.errors)
        raise HTTPException(500, "stamping produced an invalid IFC; export aborted")
    ifc_bytes = model.to_string().encode()

    if opts.format == "zip":
        body = build_bundle(stem=stem, ifc_bytes=ifc_bytes, report=report, meta=opts, version=number,
                            lineage=lineage, snapshots=images, exported_at=exported_at)
        filename, media_type = f"{stem}.zip", "application/zip"
    else:
        body, filename, media_type = ifc_bytes, f"{stem}.ifc", "application/x-step"

    log.info("export: %s v%d as %s, %d bytes, validation %s, %.2fs", project_id, number, opts.format,
             len(body), "ok" if report.ok else "FAILED", time.perf_counter() - t0)
    return Response(body, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Export-Filename": filename,
        "X-Validation-Status": "passed" if report.ok else "failed",
    })
