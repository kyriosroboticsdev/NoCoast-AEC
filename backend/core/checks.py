"""Geometric checks. Each requirement kind is a question about the compiled model.

The selector (`ifc`, `name`, `level`, `id`) is the only place a word like "bedroom" or
"pier" is interpreted, and it is matched against the name the model itself chose.
"""

from __future__ import annotations

from dataclasses import dataclass

import ifcopenshell

from core.facts import ElementFact, Facts, collect, select, union_bbox, union_footprint
from schemas.requirements import Requirement


@dataclass
class CheckResult:
    requirement: Requirement
    status: str        # met | unmet | unsupported | skipped
    detail: str

    @property
    def ok(self) -> bool:
        return self.status in ("met", "skipped")

    def line(self) -> str:
        mark = {"met": "[met]", "unmet": "[UNMET]", "unsupported": "[unsupported]", "skipped": "[not checked]"}[self.status]
        return f"{mark} {self.requirement.text} — {self.detail}"


def _near(have: float, want: float, frac: float = 0.2, abs_tol: float = 0.35) -> bool:
    return abs(have - want) <= max(abs_tol, abs(want) * frac)


def _supports(element: ElementFact, others: list[ElementFact]) -> list[ElementFact]:
    """Elements whose top meets this one's base and whose footprint overlaps it."""
    if element.footprint is None or element.footprint.is_empty:
        return []
    zone = element.footprint.buffer(0.3)
    found = []
    for other in others:
        if other is element or other.zmax < element.zmin - 0.05 or other.zmax > element.zmin + 0.45:
            continue
        if other.footprint is not None and not other.footprint.is_empty and zone.intersects(other.footprint):
            found.append(other)
    return found


def _gap(selection: list[ElementFact], facts: Facts) -> float | None:
    """Largest horizontal gap between the supports under a selection, along its long axis."""
    if not selection:
        return None
    box = union_bbox(selection)
    if box is None:
        return None
    horizontal = (box[3] - box[0]) >= (box[4] - box[1])
    supports: list[ElementFact] = []
    for element in selection:
        supports += _supports(element, facts.elements)
    if len(supports) < 2:
        return None
    coords = sorted({round(s.centroid[0 if horizontal else 1], 3) for s in supports})
    if len(coords) < 2:
        return 0.0
    return max(b - a for a, b in zip(coords, coords[1:]))


def _clearance(selection: list[ElementFact], facts: Facts) -> float | None:
    """Smallest free height under the selection, ignoring solids that actually touch it."""
    if not selection:
        return None
    underside = min(e.zmin for e in selection)
    foot = union_footprint(selection).buffer(0.05)
    tops = [0.0]
    for other in facts.elements:
        if other in selection or other.zmax > underside - 0.05:
            continue
        if other.footprint is not None and not other.footprint.is_empty and foot.intersects(other.footprint):
            tops.append(other.zmax)
    return underside - max(tops)


def _enclosed(selection: list[ElementFact], facts: Facts) -> float | None:
    """Fraction of the footprint that is walled around and covered above. 0..1."""
    if not selection:
        return None
    foot = union_footprint(selection)
    if foot.is_empty or foot.length == 0:
        return None
    others = [e for e in facts.elements if e not in selection and e.footprint is not None and not e.footprint.is_empty]
    boundary = foot.boundary
    near = unary_buffer(others, 0.45)
    perimeter = boundary.length
    covered = boundary.intersection(near).length if perimeter else 0.0
    side = covered / perimeter if perimeter else 0.0
    ztop = max(e.zmax for e in selection)
    above = [e.footprint for e in others if e.zmin >= ztop - 0.35]
    overhead = unary_buffer((), 0)
    if above:
        from shapely.ops import unary_union
        overhead = unary_union(above)
    top = foot.intersection(overhead).area / foot.area if foot.area and not overhead.is_empty else 0.0
    return 0.5 * side + 0.5 * top


def unary_buffer(elements, dist: float):
    from shapely.ops import unary_union
    if not elements:
        from shapely.geometry import Polygon
        return Polygon()
    return unary_union([e.footprint for e in elements]).buffer(dist)


def check(model: ifcopenshell.file, requirements: list[Requirement], facts: Facts | None = None) -> list[CheckResult]:
    facts = facts or collect(model)
    out: list[CheckResult] = []
    for req in requirements:
        if not req.supported or req.kind in ("style", "other"):
            status = "unsupported" if not req.supported else "skipped"
            detail = "not supported by the builder" if not req.supported else "not automatically checkable"
            out.append(CheckResult(req, status, detail))
            continue
        try:
            out.append(_one(facts, req))
        except Exception as exc:  # noqa: BLE001 - a check must never break the pipeline
            out.append(CheckResult(req, "skipped", f"check failed: {exc}"))
    return out


def _one(facts: Facts, req: Requirement) -> CheckResult:
    sel = select(facts, ifc=req.ifc, name=req.name, level=req.level, id=req.id)
    k = req.kind
    n = req.value if req.value is not None else 1

    if k in ("count", "entity"):
        have = len(sel)
        word = req.ifc or req.name or "elements"
        return CheckResult(req, "met" if have >= n else "unmet", f"{have} {word}, wanted at least {n:g}")

    if k == "levels":
        have = facts.storeys()
        return CheckResult(req, "met" if have == int(n) else "unmet", f"{have} storey(s), wanted {int(n)}")

    if k == "extent":
        box = union_bbox(sel)
        if box is None:
            return CheckResult(req, "unmet", "nothing matches")
        dims = {"x": box[3] - box[0], "y": box[4] - box[1], "z": box[5] - box[2]}
        plan = sorted((dims["x"], dims["y"]))
        axis = req.axis or ("z" if req.value2 is None and req.which == "z" else None)
        if axis in dims:
            have = dims[axis]
            ok = _near(have, n)
            return CheckResult(req, "met" if ok else "unmet", f"{axis} {have:.2f} m, wanted {n:g}")
        if axis == "longest":
            have = plan[1]
            return CheckResult(req, "met" if _near(have, n) else "unmet", f"longest {have:.2f} m, wanted {n:g}")
        if axis == "shortest":
            have = plan[0]
            return CheckResult(req, "met" if _near(have, n) else "unmet", f"shortest {have:.2f} m, wanted {n:g}")
        want = sorted((n, req.value2 if req.value2 is not None else n))
        ok = _near(plan[0], want[0]) and _near(plan[1], want[1])
        return CheckResult(req, "met" if ok else "unmet",
                           f"footprint {plan[1]:.1f} x {plan[0]:.1f} m, wanted {want[1]:g} x {want[0]:g}")

    if k == "elevation":
        if not sel:
            return CheckResult(req, "unmet", "nothing matches")
        which = req.which or "base"
        have = min(e.zmin for e in sel) if which == "base" else max(e.zmax for e in sel)
        return CheckResult(req, "met" if _near(have, n, abs_tol=0.5) else "unmet", f"{which} at {have:.2f} m, wanted {n:g}")

    if k == "span":
        gap = _gap(sel, facts)
        if gap is None:
            return CheckResult(req, "unmet", "fewer than two supports under the selection")
        return CheckResult(req, "met" if _near(gap, n, frac=0.25, abs_tol=0.6) else "unmet", f"span {gap:.2f} m, wanted {n:g}")

    if k == "clearance":
        gap = _clearance(sel, facts)
        if gap is None:
            return CheckResult(req, "unmet", "nothing matches")
        return CheckResult(req, "met" if gap + 0.3 >= n else "unmet", f"clearance {gap:.2f} m, wanted at least {n:g}")

    if k == "enclosed":
        frac = _enclosed(sel, facts)
        if frac is None:
            return CheckResult(req, "unmet", "nothing matches")
        return CheckResult(req, "met" if frac + 1e-6 >= n else "unmet", f"closed fraction {frac:.2f}, wanted at least {n:g}")

    if k == "connects":
        other = select(facts, ifc=req.ifc2, name=req.name2, level=req.level)
        if not sel or not other:
            return CheckResult(req, "unmet", f"{len(sel)} and {len(other)} match the two selections")
        a, b = union_footprint(sel).buffer(0.35), union_footprint(other).buffer(0.35)
        touch = a.intersects(b)
        return CheckResult(req, "met" if touch else "unmet", "they touch" if touch else "they do not touch")

    if k == "supported":
        if not sel:
            return CheckResult(req, "unmet", "nothing matches")
        floating = []
        for element in sel:
            if element.zmin <= 0.4 or _supports(element, facts.elements):
                continue
            floating.append(element.name or element.id)
        if floating:
            return CheckResult(req, "unmet", "nothing beneath " + ", ".join(floating[:6]))
        return CheckResult(req, "met", f"{len(sel)} element(s) supported")

    if k == "opening":
        have = sum(e.openings for e in sel)
        return CheckResult(req, "met" if have >= n else "unmet", f"{have} opening(s), wanted at least {n:g}")

    if k == "volume":
        have = sum(e.volume for e in sel)
        return CheckResult(req, "met" if _near(have, n, frac=0.25, abs_tol=0.5) else "unmet", f"volume {have:.2f} m³, wanted {n:g}")

    if k == "area":
        have = sum(e.area for e in sel)
        return CheckResult(req, "met" if _near(have, n, frac=0.25, abs_tol=1.0) else "unmet", f"area {have:.1f} m², wanted {n:g}")

    if k == "curved":
        if not sel:
            return CheckResult(req, "unmet", "nothing matches")
        hit = [e for e in sel if e.curved]
        return CheckResult(req, "met" if hit else "unmet", f"{len(hit)} curved element(s) of {len(sel)}")

    if k == "material":
        want = (req.item or req.name or "").lower()
        have = sorted({(e.material or "").lower() for e in (sel or facts.elements) if e.material})
        ok = any(want and want in name for name in have)
        return CheckResult(req, "met" if ok else "unmet", f"materials {have or ['none']}, wanted {want}")

    return CheckResult(req, "skipped", "not automatically checkable")


def score(results: list[CheckResult]) -> tuple[int, int]:
    """(met, checkable). Unsupported and skipped requirements do not count."""
    checkable = [r for r in results if r.status in ("met", "unmet")]
    return sum(1 for r in checkable if r.status == "met"), len(checkable)


def unmet_lines(results: list[CheckResult]) -> list[str]:
    return [f"{r.requirement.text} — {r.detail}" for r in results if r.status == "unmet"]
