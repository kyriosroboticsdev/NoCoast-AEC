"""Export a version as something you can hand to somebody else.

The IFC file is the deliverable, but on its own it loses everything around it: the brief the model
worked from, its reasoning, the checks, and the JSON the geometry was compiled from. `bundle()`
writes all of it into one zip, with a README that explains each file, so a version can be attached
to an email or dropped into a coordination folder and still make sense.

Individual artefacts are available on their own too (`artifact()`), which is what the UI's export
menu uses for "just the IFC" / "just the spec".
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from core.bcf import bcf
from core.context import describe_design, describe_spec
from core.derive import DesignError, analyze
from core.draw.canvas import pdf
from core.draw.sheets import Meta, Sheet, drawing_set
from core.estimate import estimate
from core.review import review
from schemas.bim import BuildingSpec, polygon_area
from store.db import VersionData

FORMATS = ("ifc", "zip", "drawings", "review", "bcf", "estimate", "spec", "design", "context", "checks", "schedule",
           "summary")
MEDIA = {
    "ifc": "application/x-step", "zip": "application/zip", "spec": "application/json",
    "design": "application/json", "context": "text/plain; charset=utf-8", "checks": "application/json",
    "schedule": "text/csv; charset=utf-8", "summary": "text/markdown; charset=utf-8",
    "drawings": "application/pdf", "review": "text/markdown; charset=utf-8", "bcf": "application/octet-stream",
    "estimate": "text/csv; charset=utf-8",
}
EXTENSIONS = {"ifc": "ifc", "zip": "zip", "spec": "spec.json", "design": "design.json",
              "context": "context.txt", "checks": "checks.json", "schedule": "schedule.csv",
              "summary": "summary.md", "drawings": "drawings.pdf", "review": "review.md", "bcf": "issues.bcfzip",
              "estimate": "estimate.csv"}
_CACHE: dict[tuple[str, int, float], dict] = {}


def stem(version: VersionData) -> str:
    return f"{version.project_id}-v{version.number}"


def filename(version: VersionData, fmt: str) -> str:
    return f"{stem(version)}.{EXTENSIONS[fmt]}"


def _when(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _key(version: VersionData) -> tuple[str, int, float]:
    return (version.project_id, version.number, version.created)


def analysis(version: VersionData) -> dict:
    """Review, estimate and drawing set of a version. Versions never change, so this is computed once."""
    key = _key(version)
    if key not in _CACHE:
        if len(_CACHE) > 64:
            _CACHE.clear()
        rev = review(version.spec, version.design)
        est = estimate(version.spec, rev)
        meta = Meta(project=version.spec.building.name, project_id=version.project_id, version=version.number,
                    description=version.spec.building.description or "", brief=version.prompt or "",
                    author=(version.llm or version.mode or "NoCoast agent").split(":")[0][:22], created=version.created)
        _CACHE[key] = {"review": rev, "estimate": est, "sheets": drawing_set(version.spec, rev, meta)}
    return _CACHE[key]


def sheets(version: VersionData) -> list[Sheet]:
    return analysis(version)["sheets"]


def drawings_pdf(version: VersionData) -> bytes:
    return pdf([s.canvas for s in sheets(version)], title=f"{version.spec.building.name} — drawings v{version.number}")


def review_markdown(version: VersionData) -> str:
    rev = analysis(version)["review"]
    est = analysis(version)["estimate"]
    occ, tot, cost, carbon = rev["occupancy"], rev["totals"], est["cost"], est["carbon"]
    icon = {"pass": "PASS", "warn": "REVIEW", "fail": "FAIL", "info": "INFO"}
    lines = [f"# Design review — {version.spec.building.name}, version {version.number}", "",
             f"Code basis: {rev['code']}. Occupancy **{occ['group']}** ({occ['name']}), design occupant load "
             f"**{occ['load']}**, {occ['construction']}.", "",
             f"GIA {tot['gia']:,.1f} m² ({tot['gia_sf']:,} sf), NIA {tot['nia']:,.1f} m², efficiency "
             f"{tot['efficiency']:.0%}, {tot['storeys']} storeys.", "",
             f"**{rev['score']['pass']} pass · {rev['score']['warn']} to review · {rev['score']['fail']} fail**", "",
             "| Status | Clause | Check | Measured | Required |", "| --- | --- | --- | --- | --- |"]
    for c in rev["checks"]:
        lines.append(f"| {icon[c['status']]} | {c['reference']} | {c['title']} | {c['value']} | {c['target']} |")
    actions = [c for c in rev["checks"] if c["advice"]]
    if actions:
        lines += ["", "## Actions", ""] + [f"- **{c['title']}** ({c['reference']}): {c['advice']}" for c in actions]
    lines += ["", "## Cost plan", "", f"{cost['class']}; {cost['basis']}.", "",
              f"**${cost['total']:,}** (${cost['low']:,} – ${cost['high']:,}), ${cost['per_m2']:,}/m² · "
              f"${cost['per_sf']:,}/sf.", "", "| Element | Qty | Unit | Rate | Total |", "| --- | ---: | --- | ---: | ---: |"]
    lines += [f"| {l['element']} | {l['quantity']:,} | {l['unit']} | ${l['rate']:,.0f} | ${l['total']:,.0f} |" for l in cost["lines"]]
    lines += [f"| General conditions, OH&P | | | | ${cost['general_conditions']:,} |",
              f"| Design contingency | | | | ${cost['contingency']:,} |", "",
              "## Upfront carbon", "", f"{carbon['basis']}.", "",
              f"**{carbon['per_m2']} kgCO2e/m²** ({carbon['total_kg'] / 1000:,.1f} tCO2e), LETI band **{carbon['band']}** "
              f"for {carbon['typology']} (2020 target {carbon['target_2020']}, 2030 target {carbon['target_2030']}).", ""]
    lines += [f"- {o['move']}: −{o['saving_kg'] / 1000:,.1f} tCO2e ({o['saving_pct']:.0%}), {o['per_m2']} kgCO2e/m²"
              for o in carbon["options"]]
    lines += ["", "## Assumptions", ""] + [f"- {a}" for a in rev["assumptions"]] + [""]
    return "\n".join(lines)


def estimate_csv(version: VersionData) -> str:
    est = analysis(version)["estimate"]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["uniformat", "element", "quantity", "unit", "rate_usd", "total_usd"])
    for l in est["cost"]["lines"]:
        w.writerow([l["group"], l["element"], l["quantity"], l["unit"], l["rate"], l["total"]])
    w.writerow(["", "General conditions, OH&P", "", "", "", est["cost"]["general_conditions"]])
    w.writerow(["", "Design contingency", "", "", "", est["cost"]["contingency"]])
    w.writerow(["", "TOTAL", "", "", "", est["cost"]["total"]])
    w.writerow([])
    w.writerow(["carbon", "element", "kgCO2e"])
    for r in est["carbon"]["rows"]:
        w.writerow(["", r["element"], r["kg"]])
    w.writerow(["", "TOTAL A1-A5", est["carbon"]["total_kg"]])
    return out.getvalue()


def context_text(version: VersionData) -> str:
    if version.design is None:
        return describe_spec(version.spec)
    try:
        return describe_design(version.design, analyze(version.design))
    except DesignError:
        return describe_design(version.design)


def schedule_csv(spec: BuildingSpec) -> str:
    """A room/element schedule: the table a quantity surveyor would ask for first."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["category", "level", "id", "name", "type", "quantity", "unit"])
    levels = {l.id: l.name for l in spec.levels}
    for el in spec.elements:
        if el.type != "space":
            continue
        writer.writerow(["room", levels.get(el.level, el.level), el.id, el.name or el.id, "space",
                         f"{polygon_area(el.outline):.2f}", "m2"])
    for el in spec.elements:
        if el.type == "wall":
            writer.writerow(["wall", levels.get(el.level, el.level), el.id, el.name or el.id,
                             "external" if el.external else "internal", f"{el.length:.2f}", "m"])
    for el in spec.elements:
        if el.type in ("door", "window"):
            writer.writerow([el.type, "", el.id, el.name or el.id, getattr(el, "kind", el.type),
                             f"{el.width:.2f}x{el.height:.2f}", "m"])
    for el in spec.elements:
        if el.type in ("fixture", "custom"):
            writer.writerow(["equipment", levels.get(el.level, el.level), el.id, el.name or el.id,
                             getattr(el, "kind", "custom"), "1", "no"])
    return out.getvalue()


def summary_markdown(version: VersionData) -> str:
    v = version
    counts = Counter(e.type for e in v.spec.elements)
    lines = [f"# {v.spec.building.name} — version {v.number}", ""]
    if v.spec.building.description:
        lines += [v.spec.building.description, ""]
    lines += [f"- Project: `{v.project_id}`", f"- Version: {v.number}" + (f" (from v{v.parent})" if v.parent else ""),
              f"- Created: {_when(v.created)}", f"- Produced by: {v.llm or v.mode}", ""]
    if v.prompt:
        lines += ["## Brief", "", f"> {v.prompt.strip()}", ""]
    if v.approach:
        lines += ["## Design approach", "", v.approach.strip(), ""]
    lines += ["## Model", "", "| Element | Count |", "| --- | ---: |"]
    lines += [f"| {k} | {n} |" for k, n in sorted(counts.items())]
    lines += ["", f"{len(v.spec.levels)} level(s): " + ", ".join(f"{l.name} at {l.elevation:+.2f} m" for l in v.spec.levels), ""]
    if v.checks:
        met = sum(1 for c in v.checks if c.get("status") == "met")
        checkable = sum(1 for c in v.checks if c.get("status") in ("met", "unmet"))
        lines += ["## Requirements", "", f"{met} of {checkable} checkable requirements met.", ""]
        for c in v.checks:
            mark = {"met": "x", "unmet": " ", "unsupported": "-", "skipped": "?"}.get(c.get("status", ""), "?")
            detail = f" — {c['detail']}" if c.get("detail") and c.get("status") != "met" else ""
            lines.append(f"- [{mark}] {c.get('text', '')}{detail}")
        lines.append("")
    if v.notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in v.notes] + [""]
    return "\n".join(lines)


README = """# NoCoast export — {name}, version {number}

Generated {when} by {by}.

| File | What it is |
| --- | --- |
| `{stem}.ifc` | The model. IFC4 (`IfcProject` → storeys → elements), openable in any BIM tool. |
| `{stem}.drawings.pdf` | The drawing set: cover, code analysis, plans, elevations, section, schedules (A3). |
| `drawings/*.svg` | The same sheets as vector SVG, one per sheet, for CAD/Illustrator/InDesign. |
| `{stem}.review.md` | Indicative code review (IBC/IRC 2021, ADA), cost plan and upfront carbon. |
| `{stem}.issues.bcfzip` | The review's open issues as BCF 2.1 topics, linked to IFC GlobalIds (Revit, Solibri, BIMcollab). |
| `{stem}.estimate.csv` | UniFormat II cost plan and A1–A5 carbon by element. |
| `{stem}.summary.md` | Brief, design approach, element counts and the requirement checklist. |
| `{stem}.spec.json` | The geometric IR the IFC was compiled from: every wall, slab, opening and fixture. |
| `{stem}.design.json` | The semantic design the model actually authored: rooms as rectangles, doors, windows. |
| `{stem}.context.txt` | The same design rendered as the text an LLM is given when editing this version. |
| `{stem}.checks.json` | Each requirement from the brief and whether the model satisfies it. |
| `{stem}.schedule.csv` | Room, wall, opening and equipment schedule for take-off. |
| `guids.json` | Element id → IFC GlobalId. Stable across versions, so diffs between exports line up. |

Re-importing `{stem}.ifc` into NoCoast recovers the design layer, so an export can be round-tripped.
"""


def artifact(version: VersionData, fmt: str) -> bytes:
    """One export artefact as bytes. `fmt` is one of FORMATS (zip goes through `bundle`)."""
    if fmt == "ifc":
        return Path(version.ifc_path).read_bytes()
    if fmt == "zip":
        return bundle(version)
    if fmt == "spec":
        return version.spec.model_dump_json(indent=1).encode()
    if fmt == "design":
        data = version.design.model_dump_json(indent=1) if version.design else "null"
        return data.encode()
    if fmt == "context":
        return context_text(version).encode()
    if fmt == "checks":
        return json.dumps(version.checks, indent=1).encode()
    if fmt == "schedule":
        return schedule_csv(version.spec).encode()
    if fmt == "summary":
        return summary_markdown(version).encode()
    if fmt == "drawings":
        return drawings_pdf(version)
    if fmt == "review":
        return review_markdown(version).encode()
    if fmt == "bcf":
        return bcf(version.spec, version.guids, analysis(version)["review"]["checks"], filename(version, "ifc"),
                   version.spec.building.name)
    if fmt == "estimate":
        return estimate_csv(version).encode()
    raise ValueError(f"unknown export format '{fmt}' (known: {', '.join(FORMATS)})")


def bundle(version: VersionData) -> bytes:
    """Everything about a version in one zip."""
    base = stem(version)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", README.format(name=version.spec.building.name, number=version.number,
                                               when=_when(version.created), by=version.llm or version.mode, stem=base))
        for fmt in ("ifc", "drawings", "review", "bcf", "estimate", "summary", "spec", "design", "context", "checks",
                    "schedule"):
            zf.writestr(filename(version, fmt), artifact(version, fmt))
        for sheet in sheets(version):
            zf.writestr(f"drawings/{sheet.number}.svg", sheet.svg())
        zf.writestr("guids.json", json.dumps(version.guids, indent=1))
    return buf.getvalue()
