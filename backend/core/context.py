"""Text renderings of a GeoModel.

`describe_model` is what the model sees as CURRENT MODEL on an edit, and what
`GET …/context` returns. `describe_focus` turns a viewer selection — a part id — into
the sentence the edit prompt is about.
"""

from __future__ import annotations

from schemas.geo import GeoModel
from schemas.geosteps import expand_instances


def describe_model(geo: GeoModel) -> str:
    lines = [f'model "{geo.name}"' + (f" — {geo.description}" if geo.description else "")]
    elevations = geo.elevations()
    if geo.levels:
        lines.append("levels: " + ", ".join(
            f"{l.id} {l.display} h={l.height:g} z={elevations.get(l.id, 0):g}" for l in geo.ordered_levels()))
    for part in geo.parts:
        lines.append(part.describe())
    for opening in geo.openings:
        lines.append(opening.describe())
    for asm in geo.assemblies:
        lines.append(f"assembly id={asm.id} parts={','.join(asm.parts)}")
    for inst in geo.instances:
        lines.append(f"instance id={inst.id} of={inst.of} copies={inst.copies}")
    if geo.notes:
        lines.append("notes: " + " | ".join(geo.notes))
    return "\n".join(lines)


def describe_focus(geo: GeoModel, focus: str | None) -> str | None:
    """One sentence naming the selected part, including the id the next step must use."""
    if not focus or not str(focus).strip():
        return None
    fid = str(focus).strip()
    for part in expand_instances(geo):
        if part.id == fid:
            name = part.name or part.id
            return f"part id={part.id} name={name} {part.ifc} on {part.level}"
    opening = geo.opening(fid)
    if opening is not None:
        return f"opening id={opening.id} host={opening.host}"
    asm = geo.assembly(fid)
    if asm is not None:
        return f"assembly id={asm.id} name={asm.name or asm.id}"
    return f"element id={fid}"
