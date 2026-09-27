"""Check brick definitions before they join the library.

    python tools/check_bricks.py path/to/file.json [more.json …]     # files anywhere, e.g. a staging folder
    python tools/check_bricks.py                                      # every file in bricks/library/catalogue/

Loading a brick only proves its JSON has the right shape. This runs what the test suite demands of every
library brick, one brick at a time, so a failure names the brick and the reason:

  load      the definition validates, numbers are finite, the id is new and short
  range     geometry evaluates at every corner of the parameter ranges, with a real and plausible size
  ifc       the IFC class and predefined type agree
  place     it places with its defaults in the test scene (a 12 x 12 m hall, 4 m storey) and compiles to
            IFC geometry that tessellates
  words     its name and tags do not make a plain house prompt place it (agents/brick_words.py)
  search    searching for its name finds it

Exit code 1 when any brick fails. Warnings do not fail.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bricks.geometry import bounds  # noqa: E402
from bricks.model import Brick, predefined_types  # noqa: E402
from bricks.registry import CATALOGUE_DIR, Library, library  # noqa: E402

CONTEXT = {"ref_w": 12.0, "ref_d": 12.0, "ref_h": 4.0, "path_length": 4.0}   # as tests/test_bricks.py
MAX_ID = 40
MAX_EXTENT = 120.0        # metres; nothing in a building library is larger
MIN_EXTENT = 0.002
PLAIN_EXTRA = [
    "a small house with 2 bedrooms", "Two storey house with a kitchen, living room and three bedrooms, plus a garage",
    "a one storey cabin", "an office with a meeting room and a kitchen", "add a bedroom", "add a front porch",
    "add a window to the kitchen on the west", "gable roof please", "remove the garage", "a flat with an open plan living room",
]


@dataclass
class Result:
    id: str
    file: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _finite(value, where: str, out: list[str]) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        out.append(f"{where} is {value}")


def _raw_bricks(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    defaults = {k: v for k, v in data.items() if k != "bricks"} if isinstance(data, dict) else {}
    return [{**defaults, **raw} for raw in (data["bricks"] if isinstance(data, dict) else data)]


def check_load(raw: dict, res: Result, taken: set[str], core: bool = False) -> Brick | None:
    try:
        brick = Brick.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - some bad definitions raise IndexError or TypeError, not ValueError
        res.errors.append(f"load: {type(exc).__name__}: {str(exc)[:300]}")
        return None
    if brick.id in taken:
        res.errors.append(f"load: id '{brick.id}' is already used")
    if len(brick.id) > MAX_ID:
        res.errors.append(f"load: id is {len(brick.id)} characters, at most {MAX_ID}")
    if not brick.tags:
        res.errors.append("load: needs at least one tag")
    if any(t != t.lower() for t in brick.tags):
        res.errors.append("load: tags must be lower-case (the tag filter cannot match capitals)")
    if "fixture" in brick.properties and not core:
        res.errors.append("load: `fixture` is reserved for the bricks that stand in for catalogue fixtures")
    if not brick.description:
        res.warnings.append("load: no description; search and the model's card depend on it")
    for p in brick.params:
        for name in ("default", "min", "max"):
            _finite(getattr(p, name), f"param {p.name}.{name}", res.errors)
        if not p.name.isidentifier():
            res.errors.append(f"load: param name {p.name!r} cannot be used in an expression")
        if (p.min is None or p.max is None) and not p.fit:
            res.warnings.append(f"load: param {p.name} has no range, so nothing stops a value of any size")
    return brick


def check_ifc(brick: Brick, res: Result) -> None:
    enum = predefined_types(brick.ifc_class)
    if brick.predefined_type is None and enum and "NOTDEFINED" not in enum:
        res.errors.append(f"ifc: {brick.ifc_class} needs a predefined type, one of {', '.join(enum)}")
    if brick.ifc_class == "IfcBuildingElementProxy":
        res.warnings.append("ifc: IfcBuildingElementProxy says nothing about what this is; use a real class if one fits")


def check_range(brick: Brick, res: Result) -> None:
    sized = [p for p in brick.params if p.min is not None and p.max is not None and not p.fit]
    for corner in itertools.product(*[(p.min, p.default, p.max) for p in sized[:4]]):
        given = {p.name: v for p, v in zip(sized, corner)}
        try:
            values = brick.resolve(given, CONTEXT)
            box = bounds(brick.solids(values))
            brick.elevation_of(values)
            brick.keepout_boxes(values)
        except Exception as exc:  # noqa: BLE001 - expressions can raise more than ValueError
            res.errors.append(f"range: at {given}: {type(exc).__name__}: {str(exc)[:200]}")
            return
        extent = [box[3] - box[0], box[4] - box[1], box[5] - box[2]]
        if any(not math.isfinite(e) for e in extent):
            res.errors.append(f"range: at {given}: size is not finite: {extent}")
            return
        if min(extent) < MIN_EXTENT:
            res.errors.append(f"range: at {given}: size {[round(e, 4) for e in extent]} has no extent on one axis")
            return
        if max(extent) > MAX_EXTENT:
            res.errors.append(f"range: at {given}: size {[round(e, 1) for e in extent]} m is larger than {MAX_EXTENT:g} m")
            return


def _placement(brick: Brick) -> dict:
    """As tests/test_brick_steps.py::_placement."""
    outdoor = "outdoor" in brick.tags
    if "foundations" in brick.tags:
        return {"start": [1, 6], "end": [7, 6]} if brick.mount == "path" else {"position": [6, 6]}
    if brick.mount == "path":
        return {"ref": "site", "start": [-12, 2], "end": [-12, 8]} if outdoor else {"ref": "hall", "start": [1, 6], "end": [7, 6]}
    if "roof" in brick.tags:
        return {"ref": "roof"}
    if outdoor:
        return {"ref": "site", "position": [-12, 6]}
    return {"ref": "hall"}


def check_place(brick: Brick, raw: dict, res: Result, in_library: bool) -> None:
    from core.derive import DesignError, derive
    from ifc.builder import check_geometry, compile_ifc
    from schemas.bim import Asset, BuildingSpec
    from schemas.design import Design
    from schemas.steps import Step, StepError, apply_step

    design = Design(name="check")
    try:
        for step in (dict(step="level", id="L1", height=4.0), dict(step="room", name="Hall", rect=[0, 0, 12, 12])):
            design, _ = apply_step(design, Step(**step))
        if not in_library:   # a brick outside the library goes in as the design's own asset, then places the same way
            design, _ = apply_step(design, Step(step="asset", definition=json.dumps(raw)))
        design, _ = apply_step(design, Step(step="brick", brick=brick.id, id=f"b-{brick.id}", **_placement(brick)))
        spec, _ = derive(design)
    except (StepError, DesignError) as exc:
        hint = ""
        if "outdoor" not in brick.tags and "roof" not in brick.tags and "foundations" not in brick.tags:
            hint = " (a brick that does not fit a 3.8 m high room needs the tag outdoor, roof or foundations, or a ref_h fit)"
        res.errors.append(f"place: {str(exc)[:300]}{hint}")
        return
    assets = [e for e in spec.elements if isinstance(e, Asset) and e.brick == brick.id]
    if not assets:
        res.errors.append("place: no asset was derived")
        return
    try:
        one = BuildingSpec(building={"name": "check"}, levels=[{"id": "L1", "name": "Ground", "height": 4.0, "elevation": 0}], elements=assets)
        model, _ = compile_ifc(one)
        problems = check_geometry(model)
    except Exception as exc:  # noqa: BLE001
        res.errors.append(f"place: compile failed: {type(exc).__name__}: {str(exc)[:300]}")
        return
    if problems:
        res.errors.append(f"place: IFC geometry: {'; '.join(str(p) for p in problems)[:300]}")
        return
    product = next((p for p in model.by_type("IfcProduct") if p.is_a(brick.ifc_class)), None)
    if product is None:
        res.errors.append(f"place: the compiled file has no {brick.ifc_class}")


def plain_prompts() -> list[str]:
    prompts = list(PLAIN_EXTRA)
    evals = Path(__file__).resolve().parents[1] / "tests" / "evals" / "prompts.json"
    if evals.is_file():
        prompts += [p["prompt"] for p in json.loads(evals.read_text(encoding="utf-8"))]
    return prompts


def check_words(bricks: list[Brick], results: dict[str, Result]) -> None:
    """A prompt that names no bricks today must still name none with the new ones in the library."""
    import agents.brick_words as words
    import bricks.registry as registry

    base = library()
    new_ids = {b.id for b in bricks}
    before_lib = Library([b for b in base.bricks.values() if b.id not in new_ids], {})
    after_lib = Library(list(before_lib.bricks.values()) + bricks, {})

    def mentions(lib: Library, prompt: str) -> set[str]:
        words._phrases.cache_clear()
        words.library = lambda: lib
        try:
            return {(m.brick, m.phrase) for m in words.mentioned_bricks(prompt)}
        finally:
            words._phrases.cache_clear()
            words.library = registry.library

    for prompt in plain_prompts():
        was = {b for b, _ in mentions(before_lib, prompt)}
        for brick, phrase in mentions(after_lib, prompt):
            if brick not in new_ids or brick in was:
                continue
            if was:   # the prompt already names bricks; one more changes what the mock builds for it
                results[brick].warnings.append(f"words: '{phrase}' adds this brick to a prompt that names {sorted(was)}: \"{prompt[:60]}…\"")
            else:
                results[brick].errors.append(f"words: the phrase '{phrase}' makes a plain prompt place this brick: \"{prompt[:70]}…\"")


def check_search(bricks: list[Brick], results: dict[str, Result]) -> None:
    base = library()
    new_ids = {b.id for b in bricks}
    lib = Library([b for b in base.bricks.values() if b.id not in new_ids] + bricks, {})
    for brick in bricks:
        top = [b.id for b, _ in lib.search(brick.name, limit=5)]
        if brick.id not in top:
            results[brick.id].warnings.append(f"search: '{brick.name}' finds {top[:3]} first; make the name and tags more specific")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path, help="brick files (default: the catalogue)")
    parser.add_argument("--json", type=Path, help="also write the results to this file")
    parser.add_argument("--quiet", action="store_true", help="print failures and the summary only")
    args = parser.parse_args()
    files = args.files or sorted(CATALOGUE_DIR.glob("*.json"))
    if not files:
        print("no brick files to check")
        return 0

    lib = library()
    results: dict[str, Result] = {}
    loaded: list[Brick] = []
    worded: list[Brick] = []
    taken: set[str] = set()
    for path in files:
        in_library = path.resolve().is_relative_to(CATALOGUE_DIR.parent)
        try:
            raws = _raw_bricks(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            results[str(path)] = Result(str(path), path.name, [f"load: cannot read the file: {exc}"])
            continue
        for raw in raws:
            rid = str(raw.get("id"))
            res = results.setdefault(rid, Result(rid, path.name))
            others = taken | (set() if in_library else set(lib.bricks))
            core = path.resolve().parent == CATALOGUE_DIR.parent   # a core file: its words and fixtures are deliberate
            brick = check_load(raw, res, others, core)
            taken.add(rid)
            if brick is None:
                continue
            check_ifc(brick, res)
            check_range(brick, res)
            if not res.errors:
                check_place(brick, raw, res, in_library)
            if not res.errors:
                loaded.append(brick)
                if not core:
                    worded.append(brick)
    check_words(worded, results)
    check_search(loaded, results)

    failed = [r for r in results.values() if r.errors]
    for r in results.values():
        if r.errors or (r.warnings and not args.quiet):
            print(f"{'FAIL' if r.errors else 'warn'}  {r.id}  ({r.file})")
            for line in r.errors:
                print(f"      error    {line}")
            for line in r.warnings:
                print(f"      warning  {line}")
    print(f"\n{len(results)} bricks checked, {len(results) - len(failed)} pass, {len(failed)} fail, "
          f"{sum(1 for r in results.values() if r.warnings)} with warnings")
    if args.json:
        args.json.write_text(json.dumps([r.__dict__ for r in results.values()], indent=1), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
