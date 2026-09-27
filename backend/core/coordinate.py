"""Coordination: every check on how the placed pieces work together, in one call.

    clashes      core/clash.py      bricks overlapping other pieces; things standing in keep-out volumes
    services     core/assembly.py   connector needs (hot water, air, data …) nothing in the design supplies
    structure    core/structure.py  unsupported spans and overhangs

Errors go back to the model as a fix round with their suggested steps; warnings are reported.
"""

from __future__ import annotations

import json

from core import assembly, structure
from core.clash import clashes
from core.derive import Derived
from core.issues import Issue
from schemas.design import Design


def coordinate(design: Design, derived: Derived) -> list[Issue]:
    if not design.rooms:
        return []
    return clashes(derived.spec) + assembly.services(design, derived) + structure.report(design, derived)


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]


def fix_lines(issues: list[Issue]) -> list[str]:
    """Issues as the fix round sees them: the message plus the steps that would resolve it."""
    out = []
    for i in errors(issues):
        line = i.line()
        if i.suggestions:
            line += " — e.g. " + " ".join(json.dumps(s, separators=(",", ":")) for s in i.suggestions[:4])
        out.append(line)
    return out
