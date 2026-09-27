"""Projects and their version history in SQLite; IFC files, screenshots and prompt attachments on disk next to it.

Every accepted prompt (or raw op batch, or revert) appends a version. A version
stores the full spec, the semantic design it was derived from, the guid map, the
ops that produced it and the images attached to its prompt, so history is both a snapshot log and an op log — undo is
"add a version equal to an older one". Postgres + object storage would replace this
module unchanged in interface.
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
from schemas.attachments import ImageAttachment
from schemas.bim import BuildingSpec
from schemas.design import Design

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
    images TEXT,
    approach TEXT,
    guids TEXT NOT NULL,
    ops TEXT NOT NULL,
    notes TEXT NOT NULL,
    summary TEXT NOT NULL,
    ifc_path TEXT NOT NULL,
    created REAL NOT NULL,
    UNIQUE(project_id, number)
);
"""
MIGRATIONS = ["ALTER TABLE versions ADD COLUMN design TEXT", "ALTER TABLE versions ADD COLUMN checks TEXT",
              "ALTER TABLE versions ADD COLUMN images TEXT",
              "ALTER TABLE versions ADD COLUMN approach TEXT"]


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
    images: list[dict] = []  # attachments of the prompt: {name, media_type, bytes, url}
    approach: str | None = None  # the design strategy the model wrote before it started building
    ifc_path: str
    created: float

    @property
    def ifc_url(self) -> str:
        return f"/projects/{self.project_id}/versions/{self.number}/ifc"

    @property
    def export_url(self) -> str:
        """The everything-bundle: IFC + spec + design + checks + reasoning, as one zip."""
        return f"/projects/{self.project_id}/versions/{self.number}/export"


class VersionData(Version):
    """A version plus the heavy payloads the pipeline needs."""

    spec: BuildingSpec
    design: Design | None
    guids: GuidMap

    def as_version(self) -> Version:
        return Version(**{k: getattr(self, k) for k in Version.model_fields})


class Store:
    def __init__(self, db_path: Path, ifc_dir: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        ifc_dir.mkdir(parents=True, exist_ok=True)
        self.ifc_dir = ifc_dir
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        for stmt in MIGRATIONS:  # databases created by the previous pipeline
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        self._conn.commit()
        self._lock = threading.Lock()

    # --- projects --------------------------------------------------------

    def create_project(self, name: str, *, project_id: str | None = None, created: float | None = None) -> Project:
        project = Project(id=project_id or uuid.uuid4().hex[:12], name=name, created=created or time.time())
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

    # --- versions --------------------------------------------------------

    def ifc_path(self, project_id: str, number: int) -> Path:
        return self.ifc_dir / project_id / f"v{number}.ifc"

    def shot_path(self, project_id: str, name: str) -> Path:
        return self.ifc_dir / project_id / "shots" / name

    def save_shot(self, project_id: str, png: bytes) -> str:
        """Store a screenshot the model was shown; returns its file name."""
        name = f"{uuid.uuid4().hex[:12]}.png"
        path = self.shot_path(project_id, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        return name

    def attachment_path(self, project_id: str, name: str) -> Path:
        return self.ifc_dir / project_id / "attachments" / name

    def save_attachment(self, project_id: str, image: ImageAttachment) -> dict:
        """Keep an image the user attached to a prompt and return what its version records about it.
        The file name is the hash of the bytes, so re-sending the same sketch does not store it twice."""
        path = self.attachment_path(project_id, image.filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(image.raw)
        return {"name": image.name, "media_type": image.media_type, "bytes": len(image.raw),
                "url": f"/projects/{project_id}/attachments/{image.filename}"}

    def add_version(self, project_id: str, *, spec: BuildingSpec, guids: GuidMap, mode: str, summary: dict,
                    ifc_path: Path, prompt: str | None = None, llm: str | None = None, ops: list[dict] | None = None,
                    notes: list[str] | None = None, design: Design | None = None, checks: list[dict] | None = None,
                    images: list[dict] | None = None, approach: str | None = None) -> VersionData:
        with self._lock:
            head = self._conn.execute("SELECT MAX(number) FROM versions WHERE project_id = ?", (project_id,)).fetchone()[0]
            number = (head or 0) + 1
            row: dict[str, Any] = dict(
                project_id=project_id, number=number, parent=head, prompt=prompt, mode=mode, llm=llm,
                spec=spec.model_dump_json(), design=design.model_dump_json() if design else None,
                checks=json.dumps(checks or []), images=json.dumps(images or []), guids=json.dumps(guids),
                ops=json.dumps(ops or []),
                notes=json.dumps(notes or []), summary=json.dumps(summary), ifc_path=str(ifc_path), created=time.time(),
                approach=approach,
            )
            self._conn.execute(
                "INSERT INTO versions (project_id, number, parent, prompt, mode, llm, spec, design, checks, images, approach, guids, ops, notes, summary, ifc_path, created)"
                " VALUES (:project_id, :number, :parent, :prompt, :mode, :llm, :spec, :design, :checks, :images, :approach, :guids, :ops, :notes, :summary, :ifc_path, :created)",
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
        design = None
        if row.get("design"):
            try:
                design = Design.model_validate_json(row["design"])
            except ValueError:
                design = None
        return VersionData(
            project_id=row["project_id"], number=row["number"], parent=row["parent"], prompt=row["prompt"],
            mode=row["mode"], llm=row["llm"], notes=json.loads(row["notes"]), summary=json.loads(row["summary"]),
            ops=json.loads(row["ops"]), checks=json.loads(row["checks"]) if row.get("checks") else [],
            images=json.loads(row["images"]) if row.get("images") else [], approach=row.get("approach"),
            ifc_path=row["ifc_path"], created=row["created"],
            spec=BuildingSpec.model_validate_json(row["spec"]), design=design, guids=json.loads(row["guids"]),
        )
