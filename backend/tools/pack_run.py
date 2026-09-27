"""Pack a recorded design run so another machine can replay it.

    python tools/pack_run.py <project id> [name]    # writes demo/<name>.zip (default: the project id)

The backend restores every zip in demo/ (BIM_DEMO_DIR) at startup, and the home screen lists it under
"Recorded runs": the model's full reasoning, the build previews and the deliverables, played back in about
a minute without an API key. Only a project's first version can be packed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from core import replay  # noqa: E402
from store.db import Store  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    project = argv[0]
    store = Store(config.DB_PATH, config.OUTPUT_DIR / "projects")
    data = replay.pack(store, project)
    out = config.DEMO_DIR / f"{argv[1] if len(argv) > 1 else project}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"{out} ({len(data) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
