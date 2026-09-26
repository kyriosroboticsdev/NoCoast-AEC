"""Uploaded IFC components, per project.

    POST   /projects/{id}/components          multipart `files` (one or more .ifc): normalise, measure, store
    GET    /projects/{id}/components          list
    DELETE /projects/{id}/components/{cid}    forget one (versions that placed it keep compiling)

Uploads succeed or fail per file, like chat attachments: the response lists what was added and, for
each rejected file, the reason in plain words.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from api.routes import _project
from components.assets import MAX_BYTES, ComponentError
from components.store import ComponentRecord, component_store
from logsetup import log

router = APIRouter()
MAX_FILES = 12


class UploadError(BaseModel):
    filename: str
    error: str


class UploadResult(BaseModel):
    added: list[ComponentRecord]
    errors: list[UploadError]


@router.post("/projects/{project_id}/components")
async def upload_components(project_id: str, files: list[UploadFile] = File(...)) -> UploadResult:
    _project(project_id)
    if not files:
        raise HTTPException(422, "attach at least one .ifc file")
    if len(files) > MAX_FILES:
        raise HTTPException(422, f"at most {MAX_FILES} files at once")
    added: list[ComponentRecord] = []
    errors: list[UploadError] = []
    for upload in files:
        name = upload.filename or "component.ifc"
        data = await upload.read()
        if not name.lower().endswith(".ifc"):
            errors.append(UploadError(filename=name, error="only .ifc files can be attached as components"))
            continue
        if len(data) > MAX_BYTES:
            errors.append(UploadError(filename=name, error=f"larger than {MAX_BYTES // (1024 * 1024)} MB"))
            continue
        try:
            record = await run_in_threadpool(component_store().add, project_id, name, data)
            log.info("component: %s added %s as %s (%s, %s -> IFC4/m, %.2f x %.2f x %.2f m, %d elements)", project_id, name,
                     record.id, record.schema_in, record.unit_in, record.width, record.depth, record.height, record.elements)
            added.append(record)
        except ComponentError as exc:
            errors.append(UploadError(filename=name, error=str(exc)))
        except Exception as exc:  # noqa: BLE001 - a bad file must not take the others down
            log.exception("component upload failed for %s", name)
            errors.append(UploadError(filename=name, error=f"could not read this file: {exc}"))
    return UploadResult(added=added, errors=errors)


@router.get("/projects/{project_id}/components")
def list_components(project_id: str) -> list[ComponentRecord]:
    _project(project_id)
    return component_store().list(project_id)


@router.delete("/projects/{project_id}/components/{component_id}")
def delete_component(project_id: str, component_id: str) -> dict:
    _project(project_id)
    if not component_store().delete(project_id, component_id):
        raise HTTPException(404, f"component '{component_id}' not found")
    return {"deleted": component_id}
