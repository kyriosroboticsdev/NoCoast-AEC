"""The deliverable zip: the stamped IFC plus everything a reviewer needs to trust it.

    <name>-vN/
      <name>-vN.ifc        stamped model
      README.md            what this is, element counts, validation summary, prompt history
      validation.json      the full validation report
      snapshots/*.png      3D views rendered by the app (optional)
      manifest.json        every file with its size and SHA-256
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass

from export.stamp import APP_NAME, ExportMeta, LineageEntry, history_text
from export.validate import ValidationReport

MAX_SNAPSHOTS = 8
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
_MARK = {"pass": "✓", "warn": "⚠", "fail": "✗"}
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@dataclass
class BundleFile:
    name: str
    data: bytes


def safe_stem(text: str) -> str:
    """A filename-safe slug: letters, digits and dashes."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug[:60] or "project"


def check_snapshot(name: str, data: bytes) -> str:
    """Validate one uploaded snapshot and return a safe filename for it."""
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise ValueError(f"snapshot {name!r} is larger than {MAX_SNAPSHOT_BYTES // (1024 * 1024)} MB")
    if not data.startswith(_PNG_MAGIC):
        raise ValueError(f"snapshot {name!r} is not a PNG")
    return safe_stem(name.rsplit(".", 1)[0]) + ".png"


def _readme(title: str, meta: ExportMeta, version: int, report: ValidationReport,
            lineage: list[LineageEntry], ifc_name: str, snapshots: list[str], exported_at: str) -> str:
    status = "passed" if report.ok else "FAILED"
    lines = [
        f"# {title}, version {version}",
        "",
        f"Exported {exported_at} from {APP_NAME}" + (f" by {meta.author}" if meta.author else "")
        + (f", {meta.organization}" if meta.organization else "") + ".",
        "",
        f"- Model: `{ifc_name}` ({report.schema_name})",
        f"- Validation: **{status}** ({len(report.errors)} errors, {len(report.warnings)} warnings"
        + (", schema rules included" if report.thorough else "") + "). Details in `validation.json`.",
        "",
        "## Contents of the model",
        "",
        "| Type | Count |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in report.counts.items()],
        "",
        "## Checks",
        "",
        *[f"- {_MARK[c.status]} {c.name}" for c in report.checks],
    ]
    if report.issues:
        lines += ["", "## Issues", "", *[f"- **{i.level}** ({i.code}): {i.message}" for i in report.issues]]
    lines += ["", "## How this version was made", "", "```", history_text(lineage), "```"]
    if snapshots:
        lines += ["", "## Snapshots", "", *[f"![{s}](snapshots/{s})" for s in snapshots]]
    return "\n".join(lines) + "\n"


def build_bundle(*, stem: str, ifc_bytes: bytes, report: ValidationReport, meta: ExportMeta,
                 version: int, lineage: list[LineageEntry], snapshots: list[BundleFile],
                 exported_at: str) -> bytes:
    ifc_name = f"{stem}.ifc"
    files = [
        BundleFile(ifc_name, ifc_bytes),
        BundleFile("validation.json", report.model_dump_json(indent=2).encode()),
        *[BundleFile(f"snapshots/{s.name}", s.data) for s in snapshots],
    ]
    title = meta.project_name or stem
    readme = _readme(title, meta, version, report, lineage, ifc_name, [s.name for s in snapshots], exported_at)
    files.insert(1, BundleFile("README.md", readme.encode()))
    manifest = {
        "application": APP_NAME,
        "format": 1,
        "exported_at": exported_at,
        "version": version,
        "validation_ok": report.ok,
        "files": [{"path": f.name, "bytes": len(f.data), "sha256": hashlib.sha256(f.data).hexdigest()} for f in files],
    }
    files.append(BundleFile("manifest.json", json.dumps(manifest, indent=2).encode()))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f"{stem}/{f.name}", f.data)
    return buf.getvalue()
