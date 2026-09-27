"""Which IFC4 element classes and predefined types the brick library covers, and which it does not.

    python tools/brick_coverage.py              # summary and the uncovered classes
    python tools/brick_coverage.py --json out   # the full list, for planning what to write next

The IFC4 schema has 130 concrete subclasses of IfcElement. A class counts as covered when at least one
brick uses it, and a predefined type when a brick uses that class with that type (USERDEFINED and
NOTDEFINED are not counted: they say nothing about what the thing is).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bricks.model import IFC_SCHEMA, predefined_types  # noqa: E402
from bricks.registry import library  # noqa: E402

GENERIC = ("USERDEFINED", "NOTDEFINED")


def _subtypes(entity):
    for sub in entity.subtypes():
        yield sub
        yield from _subtypes(sub)


def ifc4_elements() -> dict[str, list[str]]:
    """Concrete IfcElement class -> its specific predefined types."""
    out = {}
    for entity in _subtypes(IFC_SCHEMA.declaration_by_name("IfcElement")):
        if not entity.is_abstract():
            out[entity.name()] = [t for t in (predefined_types(entity.name()) or ()) if t not in GENERIC]
    return out


def coverage() -> dict:
    lib = library()
    used: dict[str, set] = defaultdict(set)
    for brick in lib.bricks.values():
        used[brick.ifc_class].add(brick.predefined_type)
    classes = ifc4_elements()
    return {
        "bricks": len(lib), "catalogue": len(lib.catalogue),
        "classes": len(classes), "classes_covered": sum(1 for c in classes if c in used),
        "types": sum(len(t) for t in classes.values()),
        "types_covered": sum(len(set(t) & used.get(c, set())) for c, t in classes.items()),
        "unused_classes": {c: t for c, t in sorted(classes.items()) if c not in used},
        "missing_types": {c: sorted(set(t) - used[c]) for c, t in sorted(classes.items()) if c in used and set(t) - used[c]},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path, help="write the full result to this file")
    args = parser.parse_args()
    c = coverage()
    print(f"{c['bricks']} bricks ({c['catalogue']} in the catalogue)")
    print(f"IFC4 element classes covered: {c['classes_covered']} of {c['classes']}")
    print(f"predefined types covered:     {c['types_covered']} of {c['types']}")
    print(f"\nclasses with no brick ({len(c['unused_classes'])}):\n  " + ", ".join(c["unused_classes"]))
    print(f"\nclasses with types still missing: {len(c['missing_types'])} (see --json)")
    if args.json:
        args.json.write_text(json.dumps(c, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
