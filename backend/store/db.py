"""Projects and their version history in SQLite; IFC files on disk next to it.

A version stores the GeoModel, the guid map and the ops that produced it. Rows written by the
room-centric pipeline (a BuildingSpec in the spec column) are migrated on read.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.guids import GuidMap
from schemas.geo import GeoModel

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id),
    number INTEGER NOT NULL,
    parent INTEGER,
    prompt TEXT,
    mode TEXT NOT NULL,
    llm TEXT,
    spec TEXT NOT NULL,
    program TEXT,
    design TEXT,
    checks TEXT,
    guids TEXT NOT NULL,
    ops TEXT NOT NULL,
    notes TEXT NOT NULL,
    summary TEXT NOT NULL,
    ifc_path TEXT NOT NULL,
    created REAL NOT NULL,
    UNIQUE(project_id, number)
);
"""
MIGRATIONS = ["ALTER TABLE versions ADD COLUMN design TEXT", "ALTER TABLE versions ADD COLUMN checks TEXT"]


class Project(BaseModel):
    id: str
    name: str
    created: float


class Version(BaseModel):
    project_id: str
    number: int
    parent: int | None
    prompt: str | None
    mode: str  # design | edit | ops | revert | import
    llm: str | None
    notes: list[str]
    summary: dict
    ops: list[dict]
    checks: list[dict] = []
    ifc_path: str
    created: float

    @property
    def ifc_url(self) -> str:
        return f"/projects/{self.project_id}/versions/{self.number}/ifc"


class VersionData(Version):
    """A version plus the model and guid map the pipeline needs."""

    geo: GeoModel
    guids: GuidMap

    def as_version(self) -> Version:
        return Version(**{k: getattr(self, k) for k in Version.model_fields})


def _geo_from_spec_column(raw: dict) -> GeoModel:
    """A GeoModel stored directly, or a legacy BuildingSpec migrated on read."""
    if "elements" in raw and "parts" not in raw:
        from core.migrate import from_spec
        from schemas.bim import BuildingSpec
        return from_spec(BuildingSpec.model_validate(raw))
    return GeoModel.model_validate(raw)


class Store:
    def __init__(self, db_path: Path, ifc_dir: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        ifc_dir.mkdir(parents=True, exist_ok=True)
        self.ifc_dir = ifc_dir
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        for stmt in MIGRATIONS:
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        self._conn.commit()
        self._lock = threading.Lock()

    def create_project(self, name: str) -> Project:
        project = Project(id=uuid.uuid4().hex[:12], name=name, created=time.time())
        with self._lock:
            self._conn.execute("INSERT INTO projects VALUES (?, ?, ?)", (project.id, project.name, project.created))
            self._conn.commit()
        return project

    def list_projects(self) -> list[Project]:
        rows = self._conn.execute("SELECT * FROM projects ORDER BY created DESC").fetchall()
        return [Project(**dict(r)) for r in rows]

    def get_project(self, project_id: str) -> Project | None:
        row = self._conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return Project(**dict(row)) if row else None

    def ifc_path(self, project_id: str, number: int) -> Path:
        return self.ifc_dir / project_id / f"v{number}.ifc"

    def add_version(self, project_id: str, *, geo: GeoModel, guids: GuidMap, mode: str, summary: dict,
                    ifc_path: Path, prompt: str | None = None, llm: str | None = None, ops: list[dict] | None = None,
                    notes: list[str] | None = None, checks: list[dict] | None = None) -> VersionData:
        with self._lock:
            head = self._conn.execute("SELECT MAX(number) FROM versions WHERE project_id = ?", (project_id,)).fetchone()[0]
            number = (head or 0) + 1
            row: dict[str, Any] = dict(
                project_id=project_id, number=number, parent=head, prompt=prompt, mode=mode, llm=llm,
                spec=geo.model_dump_json(), design=None, checks=json.dumps(checks or []), guids=json.dumps(guids),
                ops=json.dumps(ops or []), notes=json.dumps(notes or []), summary=json.dumps(summary),
                ifc_path=str(ifc_path), created=time.time(),
            )
            self._conn.execute(
                "INSERT INTO versions (project_id, number, parent, prompt, mode, llm, spec, design, checks, guids, ops, notes, summary, ifc_path, created)"
                " VALUES (:project_id, :number, :parent, :prompt, :mode, :llm, :spec, :design, :checks, :guids, :ops, :notes, :summary, :ifc_path, :created)",
                row,
            )
            self._conn.commit()
        return self._to_data(row)

    def head(self, project_id: str) -> VersionData | None:
        row = self._conn.execute(
            "SELECT * FROM versions WHERE project_id = ? ORDER BY number DESC LIMIT 1", (project_id,)
        ).fetchone()
        return self._to_data(dict(row)) if row else None

    def get_version(self, project_id: str, number: int) -> VersionData | None:
        row = self._conn.execute("SELECT * FROM versions WHERE project_id = ? AND number = ?", (project_id, number)).fetchone()
        return self._to_data(dict(row)) if row else None

    def list_versions(self, project_id: str) -> list[Version]:
        rows = self._conn.execute("SELECT * FROM versions WHERE project_id = ? ORDER BY number", (project_id,)).fetchall()
        return [self._to_data(dict(r)).as_version() for r in rows]

    @staticmethod
    def _to_data(row: dict) -> VersionData:
        geo = _geo_from_spec_column(json.loads(row["spec"]))
        return VersionData(
            project_id=row["project_id"], number=row["number"], parent=row["parent"], prompt=row["prompt"],
            mode=row["mode"], llm=row["llm"], notes=json.loads(row["notes"]), summary=json.loads(row["summary"]),
            ops=json.loads(row["ops"]), checks=json.loads(row["checks"]) if row.get("checks") else [],
            ifc_path=row["ifc_path"], created=row["created"], geo=geo, guids=json.loads(row["guids"]),
        )
