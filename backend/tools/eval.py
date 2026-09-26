"""Score the configured model on the evaluation prompts.

    python tools/eval.py                 # every case in tests/evals/prompts.json
    python tools/eval.py cabin villa     # selected cases
    python tools/eval.py --no-verify     # skip the fix round to measure the raw first pass

Each case runs the real pipeline (requirements → build steps → checks → fix round)
against a throw-away project, then scores the finished design against the case's
hand-written requirements. Prints a per-case table and the overall rate, and writes
eval-<timestamp>.json next to this file with the details.
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

from core import pipeline  # noqa: E402
from core.checks import check, score  # noqa: E402
from core.derive import analyze  # noqa: E402
from llm import get_llm  # noqa: E402
from schemas.requirements import Requirement  # noqa: E402
from store.db import Store  # noqa: E402


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
    for case in cases:
        pid = store.create_project(case["id"]).id
        t = time.perf_counter()
        events: list[tuple[str, str]] = []
        try:
            version = pipeline.run_prompt(store, llm, pid, case["prompt"], None, lambda s, m, d=None: events.append((s, m)))
            design = version.design
            results = check(design, analyze(design), [Requirement.model_validate(r) for r in case["requirements"]])
            met, n = score(results)
            detail = [r.line() for r in results]
            elements = version.summary["elements"]
            error = None
        except Exception as exc:  # noqa: BLE001
            met, n, detail, elements, error = 0, len([r for r in case["requirements"] if r.get("supported", True)]), [], 0, str(exc)
        seconds = time.perf_counter() - t
        steps = sum(1 for s, _ in events if s == "step")
        rejected = sum(1 for s, m in events if s == "step" and "rejected" in m)
        total_met += met
        total_all += n
        rows.append({"id": case["id"], "met": met, "checkable": n, "seconds": round(seconds, 1), "elements": elements,
                     "steps": steps, "rejected": rejected, "error": error, "detail": detail})
        print(f"{case['id']:18s} {met:2d}/{n:<2d} {seconds:5.1f}s  {elements:3d} elements  {steps:3d} steps ({rejected} rejected)"
              + (f"  ERROR {error}" if error else ""))
        for line in detail:
            if not line.startswith("[met]"):
                print("    " + line)
    rate = total_met / total_all if total_all else 0
    print(f"\noverall: {total_met}/{total_all} = {rate:.0%}")
    out = HERE / f"eval-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"model": f"{llm.name} {getattr(llm, 'model', '') or ''}", "overall": rate, "cases": rows}, indent=1), encoding="utf-8")
    print(f"details: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
