"""Score the configured model on the evaluation prompts.

    python tools/eval.py                 # every case in tests/evals/prompts.json
    python tools/eval.py cabin vault     # selected cases
    python tools/eval.py --no-verify     # skip the fix round

Each case runs the real pipeline (requirements → GeoSteps → geometric checks) against a
throw-away project, then scores the compiled model against the case's hand-written
requirements. Prints a per-case table, the residential subset, and the overall rate.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

tmp = Path(tempfile.mkdtemp(prefix="nocoast-eval-"))
os.environ.setdefault("BIM_OUTPUT_DIR", str(tmp))
os.environ.setdefault("BIM_DB_PATH", str(tmp / "eval.sqlite3"))

import ifcopenshell  # noqa: E402

from core import pipeline  # noqa: E402
from core.checks import check, score  # noqa: E402
from llm import get_llm  # noqa: E402
from schemas.requirements import Requirement  # noqa: E402
from store.db import Store  # noqa: E402


def _rate(met: int, total: int) -> str:
    return f"{met}/{total} = {met / total:.0%}" if total else "0/0"


def main(argv: list[str]) -> int:
    if "--no-verify" in argv:
        os.environ["BIM_VERIFY_ROUNDS"] = "0"
        argv = [a for a in argv if a != "--no-verify"]
    cases = json.loads((HERE.parent / "tests" / "evals" / "prompts.json").read_text(encoding="utf-8"))
    if argv:
        cases = [c for c in cases if c["id"] in argv]
    store = Store(Path(os.environ["BIM_DB_PATH"]), tmp / "projects")
    llm = get_llm()
    print(f"model: {llm.name} {getattr(llm, 'model', '') or ''}\n")
    rows, total_met, total_all = [], 0, 0
    res_met = res_all = 0
    for case in cases:
        pid = store.create_project(case["id"]).id
        t = time.perf_counter()
        events: list[tuple[str, str]] = []
        try:
            version = pipeline.run_prompt(store, llm, pid, case["prompt"], None, lambda s, m, d=None: events.append((s, m)))
            results = check(ifcopenshell.open(version.ifc_path), [Requirement.model_validate(r) for r in case["requirements"]])
            met, n = score(results)
            detail = [r.line() for r in results]
            elements = version.summary["elements"]
            error = None
        except Exception as exc:  # noqa: BLE001
            met, n, detail, elements, error = 0, len([r for r in case["requirements"] if r.get("supported", True) and r.get("kind") not in ("style", "other")]), [], 0, str(exc)
        seconds = time.perf_counter() - t
        steps = sum(1 for s, _ in events if s == "step")
        rejected = sum(1 for s, m in events if s == "step" and "rejected" in m)
        total_met += met
        total_all += n
        if case.get("residential"):
            res_met += met
            res_all += n
        rows.append({"id": case["id"], "residential": bool(case.get("residential")), "met": met, "checkable": n,
                     "seconds": round(seconds, 1), "elements": elements, "steps": steps, "rejected": rejected,
                     "error": error, "detail": detail})
        print(f"{case['id']:18s} {met:2d}/{n:<2d} {seconds:5.1f}s  {elements:3d} elements  {steps:3d} steps ({rejected} rejected)"
              + ("  residential" if case.get("residential") else "")
              + (f"  ERROR {error}" if error else ""))
        for line in detail:
            if not line.startswith("[met]"):
                print("    " + line)
    print(f"\nresidential: {_rate(res_met, res_all)}")
    print(f"overall:     {_rate(total_met, total_all)}")
    out = HERE / f"eval-{time.strftime('%Y%m%d-%H%M%S')}.json"
    payload = {"model": f"{llm.name} {getattr(llm, 'model', '') or ''}".strip(),
               "overall": (total_met / total_all) if total_all else 0,
               "overall_met": total_met, "overall_checkable": total_all,
               "residential": (res_met / res_all) if res_all else 0,
               "residential_met": res_met, "residential_checkable": res_all,
               "cases": rows}
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"details: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
