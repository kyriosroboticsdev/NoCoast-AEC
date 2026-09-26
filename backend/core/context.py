"""Render a BuildingSpec as compact text for the LLM.

One line per element, grouped by level, is roughly 15-25 tokens per element — a
40-element house is under 1k tokens, versus ~50k for the same building as IFC.
Beyond MAX_ELEMENTS the listing is truncated with a note; the production design
(README) replaces this with a summary plus a `query_model` tool.
"""

from __future__ import annotations

from schemas.bim import BuildingSpec

MAX_ELEMENTS = 400


def _pt(p) -> str:
    return f"({p[0]:g},{p[1]:g})"


def _outline(pts) -> str:
    return "[" + " ".join(_pt(p) for p in pts) + "]"


def describe_element(el) -> str:
    """`<type> id=<id> ...` — the explicit id= keeps small models from merging type and id into one token."""
    name = f' name="{el.name}"' if el.name and el.name != el.id else ""
    head = f"{el.type} id={el.id}{name}"
    if el.type == "wall":
        ext = " external" if el.external else ""
        h = f" h={el.height:g}" if el.height else ""
        return f"{head} {_pt(el.start)}->{_pt(el.end)} len={el.length:.2f} t={el.thickness:g}{h}{ext}"
    if el.type == "door":
        return f"{head} wall={el.wall} offset={el.offset:g} w={el.width:g} h={el.height:g}"
    if el.type == "window":
        return f"{head} wall={el.wall} offset={el.offset:g} w={el.width:g} h={el.height:g} sill={el.sill_height:g}"
    if el.type in ("slab", "roof"):
        return f"{head} outline={_outline(el.outline)} t={el.thickness:g}"
    if el.type == "space":
        return f"{head} outline={_outline(el.outline)}"
    if el.type == "column":
        return f"{head} at {_pt(el.position)} {el.width:g}x{el.depth:g}"
    return head


def describe_spec(spec: BuildingSpec) -> str:
    lines = [f'building "{spec.building.name}"' + (f": {spec.building.description}" if spec.building.description else "")]
    lines.append("levels:")
    for l in spec.levels:
        lines.append(f"  level id={l.id} name=\"{l.name}\" elevation={l.elevation:g} height={l.height:g}")
    by_level: dict[str, list] = {l.id: [] for l in spec.levels}
    walls = {el.id: el for el in spec.elements if el.type == "wall"}
    for el in spec.elements:
        level = el.level if hasattr(el, "level") else walls[el.wall].level
        by_level.setdefault(level, []).append(el)
    shown = 0
    for level_id, els in by_level.items():
        lines.append(f"elements on {level_id} ({len(els)}):")
        for el in els:
            if shown >= MAX_ELEMENTS:
                lines.append(f"  … {sum(len(v) for v in by_level.values()) - shown} more elements omitted")
                return "\n".join(lines)
            lines.append("  " + describe_element(el))
            shown += 1
    return "\n".join(lines)
