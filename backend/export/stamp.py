"""Stamp an in-memory copy of a model with who made it, from what, and when.

Written in two places a receiving tool will show:
- the STEP header (FILE_NAME author, organization, originating system), and
- a `NoCoast_Export` property set on the IfcProject, including the prompt history that
  produced this version, so the file explains its own provenance.
Element GlobalIds are untouched, so a stamped file still lines up with the project history.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import ifcopenshell
import ifcopenshell.api.pset
from pydantic import BaseModel, Field

APP_NAME = "NoCoast-AEC"
PSET_NAME = "NoCoast_Export"
_LABEL_MAX = 255  # IfcLabel is STRING(255); longer values are written as IfcText


class ExportMeta(BaseModel):
    """What the person exporting tells us. Everything is optional."""

    project_name: str | None = Field(default=None, max_length=200)
    author: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=200)


class LineageEntry(BaseModel):
    number: int
    mode: str
    prompt: str | None
    llm: str | None


def _text(model: ifcopenshell.file, value: str):
    """Short strings become IfcLabel (via the API default); long ones need IfcText."""
    return value if len(value) <= _LABEL_MAX else model.createIfcText(value)


def history_text(lineage: list[LineageEntry]) -> str:
    lines = []
    for v in lineage:
        what = v.prompt or {"revert": "reverted", "import": "imported"}.get(v.mode, v.mode)
        lines.append(f"v{v.number} [{v.mode}{', ' + v.llm if v.llm else ''}]: {what}")
    return "\n".join(lines)


def stamp(
    model: ifcopenshell.file,
    meta: ExportMeta,
    *,
    project_id: str,
    version: int,
    lineage: list[LineageEntry],
    validation_status: str,
    filename: str,
    exported_at: float | None = None,
) -> None:
    """Mutates `model` in place. Pass a copy, never the stored version."""
    when = datetime.fromtimestamp(exported_at or time.time(), tz=timezone.utc)

    header = model.header.file_name
    header.name = filename
    header.time_stamp = when.strftime("%Y-%m-%dT%H:%M:%S")
    header.author = (meta.author or "",)
    header.organization = (meta.organization or "",)
    header.originating_system = f"{APP_NAME} (IfcOpenShell {ifcopenshell.version})"
    header.authorization = meta.author or ""

    project = model.by_type("IfcProject")[0]
    if meta.project_name:
        project.Name = meta.project_name
    project.Description = f"{APP_NAME} project {project_id}, version {version}"

    existing = [
        rel.RelatingPropertyDefinition
        for rel in getattr(project, "IsDefinedBy", None) or []
        if rel.is_a("IfcRelDefinesByProperties") and rel.RelatingPropertyDefinition.Name == PSET_NAME
    ]
    pset = existing[0] if existing else ifcopenshell.api.pset.add_pset(model, product=project, name=PSET_NAME)
    props: dict[str, object] = {
        "ExportedAt": when.isoformat(timespec="seconds"),
        "SourceProject": project_id,
        "SourceVersion": version,
        "Application": APP_NAME,
        "ValidationStatus": validation_status,
        "PromptHistory": _text(model, history_text(lineage)),
    }
    if meta.author:
        props["ExportedBy"] = meta.author
    if meta.organization:
        props["Organization"] = meta.organization
    ifcopenshell.api.pset.edit_pset(model, pset=pset, properties=props)
