"""Checks a file must pass before it leaves the tool as a deliverable.

Two layers:
- IFC schema validation by IfcOpenShell (attribute types, cardinalities, inverses; with
  `thorough=True` also the schema's WHERE rules and functions, which takes seconds).
- Structural checks a receiving tool relies on: one project, units, a storey hierarchy,
  unique GlobalIds, and elements that have geometry and sit in the spatial structure.

Errors make a file unfit to hand over; warnings are worth reading but do not block export.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Literal

import ifcopenshell
import ifcopenshell.util.element as element_util
import ifcopenshell.validate
from pydantic import BaseModel

Level = Literal["error", "warning"]

# Elements that legitimately have no container of their own: openings are voids in a wall,
# and doors/windows are usually placed through the opening they fill.
_HOSTED = ("IfcOpeningElement", "IfcFeatureElement")
_MAX_LISTED = 5  # entity names quoted per issue, so a report stays readable


class Issue(BaseModel):
    level: Level
    code: str
    message: str
    count: int = 1


class Check(BaseModel):
    name: str
    status: Literal["pass", "warn", "fail"]


class ValidationReport(BaseModel):
    ok: bool
    schema_name: str
    thorough: bool
    seconds: float
    checks: list[Check]
    issues: list[Issue]
    counts: dict[str, int]

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]


def _names(entities: list) -> str:
    listed = [f"{e.is_a()} '{getattr(e, 'Name', None) or e.GlobalId}'" for e in entities[:_MAX_LISTED]]
    more = len(entities) - len(listed)
    return ", ".join(listed) + (f" and {more} more" if more > 0 else "")


def validate_ifc(model: ifcopenshell.file, thorough: bool = False) -> ValidationReport:
    t0 = time.perf_counter()
    issues: list[Issue] = []
    checks: list[Check] = []

    def check(name: str, problems: list[Issue]) -> None:
        status = "fail" if any(p.level == "error" for p in problems) else "warn" if problems else "pass"
        checks.append(Check(name=name, status=status))
        issues.extend(problems)

    # 1. Schema conformance.
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=thorough)
    schema_problems = [
        Issue(level="error", code="schema", message=str(s.get("message", s)).strip()[:500])
        for s in logger.statements
    ]
    check("IFC schema" + (" and rules" if thorough else ""), schema_problems)

    # 2. Exactly one project, with units.
    projects = model.by_type("IfcProject")
    project_problems = []
    if len(projects) != 1:
        project_problems.append(Issue(level="error", code="project", message=f"expected 1 IfcProject, found {len(projects)}"))
    elif not projects[0].UnitsInContext:
        project_problems.append(Issue(level="error", code="units", message="IfcProject has no unit assignment"))
    check("One project with units", project_problems)

    # 3. A storey hierarchy to hang elements on.
    storeys = model.by_type("IfcBuildingStorey")
    check("Building storeys", [] if storeys else [
        Issue(level="error", code="storeys", message="no IfcBuildingStorey: receiving tools cannot place elements on levels")
    ])

    # 4. GlobalIds are unique (tools key everything on them).
    dupes = [g for g, n in Counter(e.GlobalId for e in model.by_type("IfcRoot")).items() if n > 1]
    check("Unique GlobalIds", [
        Issue(level="error", code="guid", message=f"duplicate GlobalIds: {', '.join(dupes[:_MAX_LISTED])}", count=len(dupes))
    ] if dupes else [])

    # 5. Elements: geometry and containment.
    elements = [e for e in model.by_type("IfcElement") if not e.is_a(_HOSTED[0]) and not e.is_a(_HOSTED[1])]
    element_problems = []
    if not elements:
        element_problems.append(Issue(level="error", code="empty", message="the model has no building elements"))
    no_geometry = [e for e in elements if not e.Representation]
    if no_geometry:
        element_problems.append(Issue(level="warning", code="no-geometry", count=len(no_geometry),
                                      message=f"{len(no_geometry)} element(s) without geometry: {_names(no_geometry)}"))
    loose = [e for e in elements if element_util.get_container(e) is None and not getattr(e, "FillsVoids", None)]
    if loose:
        element_problems.append(Issue(level="warning", code="uncontained", count=len(loose),
                                      message=f"{len(loose)} element(s) not placed in a storey: {_names(loose)}"))
    check("Elements have geometry and a storey", element_problems)

    counts = dict(sorted(Counter(e.is_a() for e in elements).items()))
    counts["IfcBuildingStorey"] = len(storeys)
    counts["IfcSpace"] = len(model.by_type("IfcSpace"))
    return ValidationReport(
        ok=not any(i.level == "error" for i in issues),
        schema_name=model.schema,
        thorough=thorough,
        seconds=round(time.perf_counter() - t0, 2),
        checks=checks,
        issues=issues,
        counts=counts,
    )
