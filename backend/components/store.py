"""Per-project component files and their metadata.

Files: output/projects/<project>/components/<id>.ifc (the normalised IFC4/metre copy) plus the
original upload next to it as <id>.orig.ifc, so nothing the user gave us is lost.
Rows: a `components` table in the same SQLite database as projects/versions (own connection).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import ifcopenshell
from pydantic import BaseModel

import config
from components.assets import ComponentError, ComponentInfo, analyse
from schemas.design import AssetRef, slug

SCHEMA = """
CREATE TABLE IF NOT EXISTS components (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    filename TEXT NOT NULL,
    info TEXT NOT NULL,
    source TEXT NOT NULL,
    created REAL NOT NULL,
    PRIMARY KEY (project_id, id)
);
"""


class ComponentRecord(BaseModel):
    id: str
    project_id: str
    name: str
    filename: str
    schema_in: str
    unit_in: str
    width: float
    depth: float
    height: float
    counts: dict[str, int]
    elements: int
    source: str
    created: float

    def asset(self, origin: tuple[float, float, float], products: list[str]) -> AssetRef:
        return AssetRef(id=self.id, name=self.name, source=self.source, width=self.width, depth=self.depth,
                        height=self.height, origin=origin, products=products, counts=self.counts)


class ComponentStore:
    def __init__(self, db_path: Path, output_dir: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_dir = output_dir
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()

    def _dir(self, project_id: str) -> Path:
        d = self.output_dir / "projects" / project_id / "components"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def add(self, project_id: str, filename: str, data: bytes) -> ComponentRecord:
        """Normalise, measure and store one upload. Raises ComponentError with a user-facing reason."""
        try:
            model = ifcopenshell.file.from_string(data.decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001 - IfcOpenShell raises its own error types
            raise ComponentError(f"not a readable IFC file: {exc}") from exc
        model, info = analyse(model, filename)
        with self._lock:
            taken = {r["id"] for r in self._conn.execute("SELECT id FROM components WHERE project_id=?", (project_id,))}
        base = slug(info.name)[:40] or "component"
        cid, n = base, 2
        while cid in taken:
            cid, n = f"{base}-{n}", n + 1
        folder = self._dir(project_id)
        (folder / f"{cid}.orig.ifc").write_bytes(data)
        model.write(str(folder / f"{cid}.ifc"))
        source = (folder / f"{cid}.ifc").relative_to(self.output_dir).as_posix()
        record = _record(project_id, cid, filename, info, source, time.time())
        payload = {**info.__dict__}
        with self._lock:
            self._conn.execute(
                "INSERT INTO components (id, project_id, name, filename, info, source, created) VALUES (?,?,?,?,?,?,?)",
                (cid, project_id, info.name, filename, json.dumps(payload), source, record.created))
            self._conn.commit()
        return record

    def _rows(self, project_id: str):
        with self._lock:
            return list(self._conn.execute(
                "SELECT * FROM components WHERE project_id=? ORDER BY created", (project_id,)))

    def list(self, project_id: str) -> list[ComponentRecord]:
        return [_row_record(r) for r in self._rows(project_id)]

    def assets(self, project_id: str) -> dict[str, AssetRef]:
        """What the design layer needs: every available component with size, origin and products."""
        out = {}
        for r in self._rows(project_id):
            info = json.loads(r["info"])
            out[r["id"]] = _row_record(r).asset(tuple(info["origin"]), list(info["products"]))
        return out

    def get(self, project_id: str, component_id: str) -> ComponentRecord | None:
        return next((c for c in self.list(project_id) if c.id == component_id), None)

    def delete(self, project_id: str, component_id: str) -> bool:
        """Forget a component. Its files stay on disk: earlier versions that placed it still compile."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM components WHERE project_id=? AND id=?", (project_id, component_id))
            self._conn.commit()
        return cur.rowcount > 0


def _record(project_id: str, cid: str, filename: str, info: ComponentInfo, source: str, created: float) -> ComponentRecord:
    return ComponentRecord(id=cid, project_id=project_id, name=info.name, filename=filename, schema_in=info.schema_in,
                           unit_in=info.unit_in, width=info.size[0], depth=info.size[1], height=info.size[2],
                           counts=info.counts, elements=len(info.products), source=source, created=created)


def _row_record(r) -> ComponentRecord:
    info = json.loads(r["info"])
    ci = ComponentInfo(name=info["name"], schema_in=info["schema_in"], unit_in=info["unit_in"], size=tuple(info["size"]),
                       origin=tuple(info["origin"]), products=info["products"], counts=info.get("counts", {}))
    return _record(r["project_id"], r["id"], r["filename"], ci, r["source"], r["created"])


_store: ComponentStore | None = None
_store_lock = threading.Lock()


def component_store() -> ComponentStore:
    """Process-wide store on the configured database and output directory."""
    global _store
    with _store_lock:
        if _store is None:
            _store = ComponentStore(config.DB_PATH, config.OUTPUT_DIR)
        return _store

