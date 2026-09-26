# Generative BIM

Desktop app (Tauri 2 + Rust shell, ~5 MB): **natural-language prompt → structured BIM instructions → IfcOpenShell → valid IFC → interactive 3D viewer.**

```
Tauri + React (frontend/)               Python FastAPI (backend/)
 prompt ──POST /plan──────────────────▶  agents/  prompt → BuildingSpec (JSON)
        ◀──────────── spec + notes ─────
        ──POST /build (spec)──────────▶  ifc/     BuildingSpec → IfcOpenShell → .ifc
        ◀──────────── /models/<id>.ifc ─
 That Open Engine viewer loads the IFC
```

The AI decides *what* exists (`schemas/bim.py`); IfcOpenShell decides *how* it's represented in IFC; the viewer only ever sees an `.ifc`.

## Run

Prerequisites: Node 20+, Python 3.11+, Rust (`rustup`), and on Windows the MSVC build tools + WebView2 (preinstalled on Windows 11).

```bash
# backend (once)
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt     # Windows (use .venv/bin/pip elsewhere)

# frontend (once)
cd ../frontend
npm install

# develop: Vite + Tauri with hot reload; the app starts the backend if it isn't running
npm run dev

# release build -> src-tauri/target/release/generative-bim.exe (add the installer: drop --no-bundle)
npx tauri build --no-bundle
```

Backend on its own: `cd backend && .venv\Scripts\python main.py` → http://127.0.0.1:8765/docs
UI in a plain browser (no desktop shell): `npm run vite:dev` → http://localhost:5173

### Desktop shell (`frontend/src-tauri/src/lib.rs`)

Thin by design — it only does what a browser can't:
- launches `backend/.venv` Python and ties it to the app with a Windows Job Object, so the backend dies with the app (even on crash/force-quit)
- native open/save dialogs + `read_ifc` / `write_ifc` commands (raw bytes, no JSON round-trip)
- passes launch options (`BIM_PORT`, `BIM_BACKEND_URL`, `BIM_BACKEND_DIR`, smoke-test hooks) to the UI

`frontend/src/platform.ts` is the only frontend file that knows about Tauri; everything else is plain web code.

## API

| Endpoint | In | Out |
|---|---|---|
| `POST /plan` | `{prompt}` | `{spec, planner, notes}` |
| `POST /build` | `{spec}` | `{id, ifc_url, summary, seconds}` |
| `POST /generate` | `{prompt}` | both of the above in one call |
| `GET /models/<id>.ifc` | | the IFC file |

The frontend calls `/plan` then `/build` so the UI can show real progress stages (and so a spec can later be edited and rebuilt without re-prompting).

## Structured BIM instructions (`backend/schemas/bim.py`)

Metres. Levels stack automatically. Doors/windows reference a host wall by id and an `offset` along it.

```json
{
  "building": {"name": "Cabin"},
  "levels": [{"id": "L1", "name": "Ground", "height": 3}],
  "elements": [
    {"type": "wall", "id": "w1", "level": "L1", "start": [0, 0], "end": [6, 0], "thickness": 0.3, "external": true},
    {"type": "door", "wall": "w1", "offset": 2.5, "width": 0.9, "height": 2.1},
    {"type": "window", "wall": "w1", "offset": 4.2, "width": 1.2, "height": 1.2, "sill_height": 0.9},
    {"type": "slab", "level": "L1", "outline": [[0,0],[6,0],[6,4],[0,4]]},
    {"type": "roof", "level": "L1", "outline": [[0,0],[6,0],[6,4],[0,4]]},
    {"type": "column", "level": "L1", "position": [3, 3]},
    {"type": "space", "level": "L1", "name": "Living", "outline": [[0,0],[6,0],[6,4],[0,4]]}
  ]
}
```

Validation rejects unknown levels/walls, duplicate ids, openings that run off a wall or above it, zero-area outlines. Errors come back as readable text — useful for an LLM repair loop.

Supported IFC: `IfcProject/Site/Building/BuildingStorey`, `IfcWall`, `IfcSlab`, `IfcRoof` (flat), `IfcDoor`, `IfcWindow` (with `IfcOpeningElement` voids), `IfcColumn`, `IfcSpace`, plus colours, materials and common Psets. Every build is tessellated with IfcOpenShell before it's returned, and the output passes `ifcopenshell.validate` (including EXPRESS rules).

## Planners (`backend/agents/`)

- `template` (default) — deterministic, rule-based: reads storeys, room names/counts, per-floor assignments ("the second floor should have…"), garage, porch/columns, footprint ("40 by 30 feet"), "natural light". Always produces a valid spec; intended as the fallback.
- Add an LLM planner by implementing `plan(prompt) -> PlanResult` and registering it in `agents/__init__.py`; select with `BIM_PLANNER=<name>`.

## Tests

```powershell
cd backend; .venv\Scripts\python -m pytest       # prompt → IFC round-trips, validation

# Desktop smoke test (release exe): launch, wait for the UI to report, screenshot the window
cd frontend
.\scripts\smoke.ps1 -Autoload samples/sample-house.ifc -Out shot.png
.\scripts\smoke.ps1 -Prompt "two-story house with a garage" -Select IFCWINDOW -Out shot.png
$env:BIM_PORT = 8799   # run on a separate port so it doesn't reuse a backend you already have running
```

## Notes

- `web-ifc` is pinned to **0.0.77** (via `overrides`) — `@thatopen/fragments` 3.4.7 is built against it; 0.0.78 fails with `StreamMeshes called with 4 arguments`.
- The web-ifc WASM and the fragments worker are copied into `frontend/public/` on install (`scripts/copy-wasm.mjs`) so the viewer works offline.
- Migrated from Electron to Tauri: release exe is ~5 MB (vs ~367 MB Electron runtime) and the shell process uses ~30 MB RAM. The UI renders in the system WebView2.
- Release builds use LTO + `opt-level = "s"`; a clean release build takes ~7–10 min. Use `npm run dev` for iteration.
