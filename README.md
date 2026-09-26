# NoCoast-AEC

Text prompt → building model → **IFC**, with the language model kept swappable and edits applied as
deltas so a design can be iterated on. Python/FastAPI backend (IfcOpenShell), React frontend
rendering with [That Open](https://github.com/ThatOpen) (web-ifc + fragments + three.js), wrapped in
Tauri for the desktop. Every prompt produces a new project version, shown as a 3D turn card in the
history (`packages/ifc-viewer`).

![prototype](docs/screenshot.png)

*Mock LLM. v1 "Two storey house with a kitchen, living room and three bedrooms and a garage", v2 "add a
front porch", v3 Undo back to v1. Left: prompt, interpretation and version history as 3D cards. Centre:
the head version. Right: model tree and properties.*

---

## 1. Design in one page

**The LLM never writes IFC.** It writes a small semantic JSON, deterministic code compiles that to IFC.

```
 prompt ──► LLM adapter ──► PROGRAM (rooms, storeys, features)  ──► layout solver ─┐
                                  (new design)                                     ├─► BuildingSpec (IR)
 prompt + current IR ──► LLM adapter ──► EDIT ops / new PROGRAM ──► apply / solve ─┘        │
                                  (iteration)                                                ▼
                                                                 validate ─► IfcOpenShell compiler ─► IFC
                                                                    ▲              (stable GlobalIds)   │
                                                                    └── errors fed back (≤ N repairs)   ▼
                                                                                              version store ─► viewer
```

Why this shape:

| Problem with "LLM emits IFC" | What we do instead |
|---|---|
| STEP is a graph of `#123=` references; one wrong id breaks the file | LLM emits JSON validated by Pydantic; the compiler owns every IFC reference |
| A small house is 50–200k tokens of IFC, ~1k tokens of IR | Context for edits is the IR rendered as one line per element (`core/context.py`) |
| Geometry (placements, boolean openings, closed polygons) is where LLMs fail | LLMs decide *what* (program); a deterministic solver decides *where* |
| Text-level diffs of IFC are meaningless (ids renumber) | Edits are **ops on stable element ids**; the IFC is recompiled with the **same GlobalIds** |
| Swapping the model later | The model only implements `LLM.complete(request) -> dict` (`llm/base.py`) |

## 2. Repository layout

```
backend/
  schemas/bim.py        BuildingSpec — the IR: levels + walls/slabs/roofs/doors/windows/columns/spaces
  schemas/program.py    Program — what the LLM decides for a new design (rooms, storeys, features)
  schemas/ops.py        Edit ops + EditResponse — what the LLM returns when iterating
  solver/layout.py      Program → BuildingSpec (deterministic two-row grid layout)
  core/ops.py           apply ops to a spec (pure, cascading deletes, re-validates)
  core/guids.py         element id ↔ IFC GlobalId map, kept per project
  core/context.py       spec → compact text for the LLM
  core/pipeline.py      the run: LLM call → validate/repair loop → compile → new version
  llm/                  adapter protocol + mock / ollama / openai-compatible implementations, prompts
  ifc/                  IfcOpenShell compiler (project, walls, slabs, roofs, openings) + lifter (IFC → IR)
  store/db.py           SQLite projects/versions; IFC files under backend/output/projects/<id>/vN.ifc
  api/routes.py         HTTP API; api/sse.py streams pipeline progress as Server-Sent Events
  export/               final deliverable: validate, stamp provenance, zip bundle (route: api/export.py)
  agents/               stateless planners for /plan and /generate (template regex, llm)
  tests/                pytest; runs entirely on the mock LLM
frontend/
  src/App.tsx           the app: project + version state, prompt → SSE stages → new version, undo
  src/api/client.ts     backend client: /projects API incl. SSE-over-POST parser, plus /plan + /build
  src/turns.ts          maps backend versions to @nocoast/ifc-viewer turns (history cards + snapshots)
  src/viewer/BimViewer.ts  That Open main viewer: model tree, properties, hide/isolate, categories
  src/components/       PromptPanel (prompt, stages, interpretation, history), InspectorPanel, ModelTree
  src/platform.ts       the only Tauri-aware file: native open/save dialogs, launch options
  src-tauri/            Tauri 2 shell: starts backend/.venv python (Job Object ties it to the app), IFC file I/O
  scripts/copy-wasm.mjs copies web-ifc's wasm + the fragments worker into public/ (postinstall)
  scripts/smoke.ps1     desktop smoke test driven by BIM_AUTOLOAD / BIM_PROMPT / BIM_SMOKE_SELECT
packages/ifc-viewer/    turn cards (snapshot → live 3D on hover, pooled WebGL), PNG snapshots, inspector;
                        consumed by the frontend from source; own tests, playground and README
```

## 3. Running it

Requirements: Python ≥ 3.12 (3.14 tested), Node ≥ 20. For the desktop shell additionally Rust
(`rustup`), the MSVC C++ Build Tools on Windows, and WebView2 (present on Windows 11).

```bash
# backend (once)
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows; .venv/bin/pip elsewhere
cp .env.example .env            # optional; defaults to the mock LLM
.venv\Scripts\python main.py    # http://127.0.0.1:8765 (API docs at /docs)
.venv\Scripts\python -m pytest  # 41 tests

# frontend (once)
cd frontend
npm install                     # also copies web-ifc.wasm + the fragments worker into public/

# desktop: Vite + Tauri with hot reload; the app starts backend/.venv python if nothing is on 8765
npm run dev
npx tauri build --no-bundle     # release exe under src-tauri/target/release (drop --no-bundle for an installer)

# browser only (no desktop shell); start the backend yourself first
npm run vite:dev                # http://localhost:5173
```

The desktop shell looks for `backend/.venv` and falls back to `python` on the PATH, so create the
venv where shown.

Environment (see `backend/.env.example`; `.env` is re-read before every LLM call and on `/health`, so
switching provider, model or key takes effect without a restart — only paths and the port need one):

| var | meaning |
|---|---|
| `LLM_PROVIDER` | `mock` (default, no model needed), `llamacpp`, `claude`, `ollama`, `openai` |
| `LLM_MODELS_DIR`, `LLAMA_SERVER`, `LLAMA_GPU_LAYERS`, `LLAMA_CTX` | `llamacpp`: folder of `.gguf` files, server binary, GPU offload (99 = all), context |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID` | `claude`: key (or an `ant auth login` profile); workspace id only for org-level keys |
| `BIM_LOG_LEVEL` | `INFO` (default) or `DEBUG` (full LLM prompts and replies in the backend console) |
| `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` | model id / endpoint / key for the chosen provider |
| `BIM_MAX_REPAIRS` | validate→repair round trips per LLM call (default 2) |
| `BIM_OUTPUT_DIR`, `BIM_DB_PATH`, `BIM_PORT` | storage and port |
| `BIM_BACKEND_URL` (Tauri) or `?backend=` (browser) | backend origin for the UI, default `http://127.0.0.1:8765` |
| `BIM_NO_BACKEND`, `BIM_BACKEND_DIR` (Tauri) | don't spawn the backend / where `backend/` is |
| `BIM_AUTOLOAD`, `BIM_PROMPT`, `BIM_SMOKE_SELECT` (Tauri) | smoke-test hooks: load a file, run a prompt, select an element class |

**Local `.gguf` models (recommended for development).** Fetch a prebuilt `llama-server` once, then point
the backend at your model folder; the server is started on first use and stopped with the backend:

```bash
cd backend
python tools/get_llama.py            # Vulkan build: any GPU, no CUDA toolkit (--backend cpu | cuda-13.4 also work)
# backend/.env
LLM_PROVIDER=llamacpp
LLM_MODELS_DIR=D:\Models
LLM_MODEL=llama-3.2-3b-instruct-q4_k_m.gguf
```

Measured on an RTX 5060 laptop (Vulkan): model load 4–50 s (first run compiles shaders, ~80 s), a new
design 10–15 s, an edit 3–10 s. Llama-3.2-3B and Qwen3-4B both complete design + edits without repair
rounds after the schema hardening described in §4.5.

**Claude.** `LLM_PROVIDER=claude` and `ANTHROPIC_API_KEY=sk-ant-…` in `backend/.env` (optionally
`LLM_MODEL=claude-sonnet-5` for cheaper runs). A key created at organisation level rather than inside a
workspace is rejected with *"must include the anthropic-workspace-id header"* — add
`ANTHROPIC_WORKSPACE_ID=wrkspc_…` (Console → Settings → Workspaces) or create the key inside a workspace.

**Ollama / anything OpenAI-compatible.** `LLM_PROVIDER=ollama LLM_MODEL=llama3.1`, or
`LLM_PROVIDER=openai LLM_BASE_URL=http://host:port/v1` for vLLM, LM Studio, a hosted API or a fine-tuned model.

## 4. Specifications

### 4.1 BuildingSpec — the intermediate representation

`backend/schemas/bim.py`. Units are metres; plan coordinates `(x, y)`; `z` comes from levels.

```jsonc
{
  "building": {"name": "Generated House", "description": "…"},
  "levels": [{"id": "L1", "name": "Ground Floor", "height": 3.0, "elevation": 0.0}],   // elevation stacks when omitted
  "elements": [
    {"type": "wall",   "id": "L1-wall-S", "level": "L1", "start": [-0.15, 0], "end": [12.15, 0], "thickness": 0.3, "external": true, "height": null},
    {"type": "door",   "id": "L1-door-entrance", "wall": "L1-wall-S", "offset": 0.75, "width": 1.0, "height": 2.1},
    {"type": "window", "id": "L1-win-S1", "wall": "L1-wall-S", "offset": 4.5, "width": 1.2, "height": 1.2, "sill_height": 0.9},
    {"type": "slab",   "id": "L1-floor", "level": "L1", "outline": [[0,0],[12,0],[12,9],[0,9]], "thickness": 0.2},
    {"type": "roof",   "id": "roof", "level": "L2", "outline": [[…]], "thickness": 0.3, "shape": "flat"},
    {"type": "space",  "id": "L1-space-kitchen", "name": "Kitchen", "level": "L1", "outline": [[…]]},
    {"type": "column", "id": "porch-col-1", "level": "L1", "position": [0.3, -2.4], "width": 0.3, "depth": 0.3}
  ]
}
```

Conventions the whole system relies on:

- **Every element has a stable string `id`** (auto-assigned as `<type>-<n>` if missing). Ids are immutable;
  they are what ops, the UI, and the GlobalId map refer to.
- Walls are centred on `start→end`. Openings are **parametric on their host wall**: `offset` from the wall
  start to the opening's near edge. The LLM never computes opening coordinates.
- Validation (`BuildingSpec._check`) is semantic, not just structural: unique ids, known levels and host
  walls, openings inside their wall's length and height, outlines with area, walls with length.
  Error strings are written to be fed back to a model.

Supported element vocabulary (v0): storeys, walls, slabs, flat roofs, doors, windows, columns, spaces.
Adding a type means: a Pydantic class in `bim.py`, a builder in `ifc/`, one line in `core/context.py`.

### 4.2 Program — what the LLM decides for a new design

`backend/schemas/program.py`. No coordinates at all.

```jsonc
{
  "name": "Lakeside House", "description": "…",
  "storeys": 2, "storey_height": 3.0,
  "rooms": [
    {"name": "Kitchen", "level": 0, "kind": "kitchen", "area": 18},
    {"name": "Bedroom 1", "level": 1, "kind": "bedroom", "area": null}
  ],
  "footprint": [12, 9],          // optional [width, depth]; sized from rooms when null
  "garage": true, "porch": false, "bright": false, "roof": "flat",
  "notes": ["2 storeys", "bedrooms upstairs", "…"]     // shown to the user
}
```

### 4.3 Layout solver

`backend/solver/layout.py`. Deterministic: same Program → byte-identical spec. Rooms go on a two-row
grid per storey (public rooms in the south/front row, private in the back), spine wall between rows,
cross walls between bays, doors on every partition, windows on every exterior bay, entrance in the
first ground-floor bay, roof on the top storey, optional east garage and south porch. Footprint is
taken from the program or sized from mean room area. **Element ids are derived from position**
(`L2-wall-x1`, `L1-space-kitchen`), so a redesign that keeps a room keeps its ids and GlobalIds.

The solver is intentionally simple. It is the piece to replace with constraint solving / optimisation
when layouts need to honour adjacencies and target areas properly; nothing else changes.

### 4.4 Edit ops — the delta format

`backend/schemas/ops.py`, applied by `core/ops.py`.

```jsonc
{"mode": "ops",
 "ops": [
   {"op": "add_element",    "element": {"type": "window", "id": "L1-win-W3", "wall": "L1-wall-W", "offset": 5.0}},
   {"op": "modify_element", "id": "L1-wall-S", "set": {"thickness": 0.4}},
   {"op": "delete_element", "id": "garage-door"},
   {"op": "add_level",      "level": {"id": "L3", "name": "Level 3", "height": 3}},
   {"op": "modify_level",   "id": "L1", "set": {"height": 3.5}},
   {"op": "delete_level",   "id": "L3"},
   {"op": "set_building",   "set": {"name": "Casa"}}
 ],
 "notes": ["…"]}
```

or `{"mode": "redesign", "program": {…}, "notes": […]}` when the change is at program level
(rooms, storeys, footprint). Rules enforced by `apply_ops`:

- pure: returns a new spec, input untouched; the result is re-validated as a whole
- `modify_*` merges fields; `type` and `id` cannot change
- deleting a wall deletes its openings; deleting a level deletes its elements (both reported as notes)
- an explicit delete of something already cascade-deleted is not an error (models do this)
- level elevations are re-stacked after height changes unless an op set an elevation on purpose
- every failure raises `OpError` with a message naming known ids — it goes straight back to the model

**Delta vs whole file.** The op batch is the delta; it is what the model emits, what is logged, what
undo replays. The IFC file itself is regenerated in full from the IR each version (cheap: ~0.5 s for a
house) **but with the GlobalIds of the previous version** (§4.6), so to any consumer the result is
indistinguishable from an in-place patch. In-place patching of the IFC entities with
`ifcopenshell.api` is a pure optimisation for very large models and can be added behind the same
`compile_ifc(spec, guids)` call.

### 4.5 LLM adapter and prompts

`backend/llm/`. The contract:

```python
@dataclass
class LLMRequest:
    system: str; user: str; schema: dict; schema_name: str  # "program" | "edit"
    meta: dict                                              # side channel for the mock only

class LLM(Protocol):
    name: str
    def complete(self, request: LLMRequest) -> dict: ...
```

| provider | how JSON is enforced | notes |
|---|---|---|
| `mock` | regexes over the prompt (`llm/mock.py`) | no network; backs the tests; fallback when a model is down |
| `llamacpp` | starts `llama-server` on a local `.gguf`, then `openai` below (`llm/llamacpp.py`) | grammar-constrained by llama.cpp; server log in `backend/.llama/server.log` |
| `claude` | Anthropic SDK, `output_config.format` json_schema (`llm/claude.py`) | `claude-opus-5` by default |
| `ollama` | `/api/chat` with `format: <json schema>` (grammar-constrained) | local models via Ollama |
| `openai` | `/chat/completions` with `response_format: json_schema` | vLLM, LM Studio, hosted, fine-tuned |

Every provider receives the schema through `llm/schema.py::strict_schema`: all properties required,
objects closed, tuples as fixed-length arrays. This came out of testing 3–4B local models, which skip
optional keys (rooms lost their `level`) and, once keys are required, fill unused ones with junk — so the
Program coerces junk (`footprint: [0, 0]`, `storey_height: 0`) to "unspecified", rooms name storeys by id
(`"L2"`, the same ids the model sees in the context) instead of a 0-based index, `program` is ignored in
`mode="ops"`, and unknown-id errors suggest the closest real ids. The context lists elements as
`wall id=L1-wall-S …` because small models otherwise merge type and id into `wall-L1-wall-S`.

Two calls exist (`llm/prompts.py`): **program** (`PROGRAM_SYSTEM`, user = request) and **edit**
(`EDIT_SYSTEM`, user = current model as text + request). Both are single-shot and schema-constrained,
which is deliberate — `(context, prompt) → JSON` pairs are the easiest possible fine-tuning target for
the specialised model that replaces the general one later. `store` keeps prompt, ops/program, notes and
llm name for every version, so the training log accumulates by itself.

### 4.6 Validate / repair loop

`core/pipeline.py`. For each LLM call, up to `BIM_MAX_REPAIRS` (2) extra rounds:

1. schema validation of the JSON (Pydantic) → field-level messages
2. semantic validation (`BuildingSpec._check`, `apply_ops`) → e.g. `door 'd1': runs past the end of wall 'w1' (3.50 > 2.00 m)`
3. geometry check: every product is tessellated with IfcOpenShell (`ifc/builder.py::check_geometry`);
   failures are also fed back

Errors are appended to the user message as *"YOUR PREVIOUS ANSWER WAS REJECTED. Fix these problems"*.
After the last attempt a `PipelineError` reaches the client as an SSE `error` event (HTTP-style code
422; 409 for a stale `base_version`).

### 4.7 GlobalId stability

`core/guids.py`. Per project a map `{"project", "site", "building", "level:<id>", "element:<id>",
"opening:<id>"} → GlobalId` is stored with each version. `compile_ifc(spec, guids)` assigns ids from
the map and mints new ones only for new keys; `prune_guids` drops keys that left the spec (a deleted
and re-added id gets a *new* GlobalId, on purpose). Tested in `tests/test_ifc_roundtrip.py` and
`tests/test_projects_api.py`: modify-in-place, delete, redesign and revert all keep GlobalIds for
surviving elements.

### 4.8 IFC compiler

`backend/ifc/`. IFC4, `ifcopenshell.api` throughout. Project → Site → Building → Storeys (elevations
from levels). Walls: `add_wall_representation` (extruded rectangle centred on the axis, local frame at
`start` rotated along the wall). Slabs/roofs/spaces: `add_slab_representation` from the outline
(slab top at storey elevation; roof on top of its storey; spaces aggregated into storeys). Doors and
windows: an `IfcOpeningElement` box cut through the host wall (`feature.add_feature`) and filled with
a parametric door/window representation (`feature.add_filling`). Styles (colour, glass transparency),
materials, `Pset_*Common`, and a **`NoCoast_Spec` pset with the element's spec JSON** on every element,
storey and the building (that is what makes the lifter lossless).

### 4.9 Lifter (IFC as context)

`backend/ifc/lifter.py`. Reads a NoCoast-generated IFC back into `(BuildingSpec, GuidMap)` from the
`NoCoast_Spec` psets and GlobalIds — lossless, so a downloaded file can be re-imported into a fresh
project (`POST /projects/{id}/import`) and edited with the same ids. A geometric lifter for *foreign*
IFC files (reading placements/extrusions back into walls, slabs, openings; unknown classes as read-only
opaque elements with a bounding box) is the designed next step and plugs into the same function.

### 4.10 Version store

`backend/store/db.py`, SQLite. `versions(project_id, number, parent, prompt, mode, llm, spec, program,
guids, ops, notes, summary, ifc_path)`. Every accepted prompt, raw op batch, revert or import appends
a version; the IFC for version *n* is `output/projects/<project>/v<n>.ifc`. History is linear;
`revert/{n}` appends a new version equal to *n* (undo that is itself undoable). Optimistic concurrency:
requests carry `base_version`; a mismatch is rejected (409) rather than merged. Postgres + object
storage replace this module with the same interface.

### 4.11 HTTP API

| method / path | body | result |
|---|---|---|
| `GET /health` | | `{ok, llm: {provider, model}}` |
| `POST /projects` | `{name}` | project |
| `GET /projects/{id}` | | `{project, head, versions}` |
| `POST /projects/{id}/prompt` | `{prompt, base_version?, planner?}` | **SSE** |
| `POST /projects/{id}/ops` | `{ops, base_version?}` | **SSE** — apply ops without an LLM |
| `POST /projects/{id}/revert/{n}` | | **SSE** |
| `POST /projects/{id}/import` | multipart `file` (.ifc) | **SSE** |
| `GET /projects/{id}/versions/{n}/ifc` | | the IFC file |
| `GET /projects/{id}/versions/{n}/spec` | | `{version, spec, program, guids}` |
| `GET /projects/{id}/versions/{n}/context` | | text — exactly what the LLM sees when editing |
| `GET /projects/{id}/versions/{n}/validate` | `?thorough=true` adds schema rules | validation report |
| `POST /projects/{id}/versions/{n}/export` | multipart `options` (JSON) + `snapshots` (PNG) | stamped `.ifc` or `.zip` bundle |
| `POST /plan`, `/build`, `/generate` | | stateless one-shots (scripts, tests) |

SSE events: `event: <stage>` + `data: {"stage", "message", "data"}` where stage ∈
`program, edit, apply, solve, compile, done, error`. `done.data` is the version record incl. `ifc_url`;
repair rounds carry `data.errors`.

**Export** (`backend/export/`, route in `api/export.py`) turns a version into a deliverable. The stored
version is never modified; every export works on a fresh copy.

1. **Validate.** IfcOpenShell schema validation, plus the schema's WHERE rules when `thorough` (a few
   seconds). Structural checks: one project with units, building storeys, unique GlobalIds, and
   elements with geometry placed in a storey. Errors block export when `strict` (the default) and the
   route returns 422 with the report. Warnings never block.
2. **Stamp.** The STEP header gets author, organization, originating system and file name.
   `IfcProject` gets the project name and a `NoCoast_Export` property set: export time, source project
   and version, validation status, and the prompt history that produced this version (walked through
   the version parents). GlobalIds are unchanged. The stamped file is validated again before it is sent.
3. **Bundle** (`format: "zip"`): `<name>-vN/` containing the IFC, a `README.md` (counts, checks, issues,
   prompt history, snapshots), `validation.json`, `snapshots/*.png` rendered by the app, and a
   `manifest.json` with every file's SHA-256.

`options`: `{format: "ifc"|"zip", project_name?, author?, organization?, strict = true, thorough = true}`.
The file name comes back in `X-Export-Filename`, and `X-Validation-Status` is `passed` or `failed`.

### 4.12 Frontend

React + Vite. The app keeps one project id in `localStorage` and reopens it on start. The first prompt
creates a design (`POST /projects/{id}/prompt`); later prompts send the head as `base_version`, so
they are edits. Pipeline stages stream into the step list. **Undo** reverts to the head's parent,
recorded as a new version, and **New** starts a fresh project.

Two viewers share the page, both on That Open with the same pinned versions:

- **Main viewer** (`src/viewer/BimViewer.ts`): the selected version at full size, with the model tree,
  properties, class visibility, and hide/isolate. After every accepted version the **whole IFC is
  reloaded**; incremental patching by GlobalId is deferred.
- **History cards** (`packages/ifc-viewer`, wired in `src/turns.ts`): one card per version, showing a
  snapshot that turns into a live orbitable view on hover. At most 3 live WebGL canvases exist at
  once. **Inspect** on a card loads that version into the main viewer. Each version also gets a
  1024×768 PNG snapshot, held in memory for now (see §7).

**Keep `web-ifc` at 0.0.77.** In 0.0.78 the browser wasm does not match its own JavaScript, and That
Open fails every conversion. `frontend/package.json` enforces this with an `overrides` entry.

**Export…** in the toolbar opens a dialog for the version in the main viewer. It shows a quick
validation first, remembers author and organization, and offers the zip bundle or a stamped IFC.
For the bundle it renders iso, top, front and side views with the viewer package's snapshot API.

`Open IFC…` and `Sample` view a file in the main viewer without adding it to the project; the
backend's `/projects/{id}/import` endpoint has no button yet.

The Tauri shell (`src-tauri/`) starts `backend/.venv` python unless something already listens on the
port (skip with `BIM_NO_BACKEND=1`). A Windows Job Object ties the backend to the app, so it also dies
on a crash or force-quit. The shell also provides native open/save dialogs and raw-bytes
`read_ifc`/`write_ifc` commands. `src/platform.ts` is the only frontend file that knows about Tauri.

## 4.13 Troubleshooting

Both sides log verbosely so a failure can be diagnosed from two pastes:

- **Backend console** (`python main.py`): every request, LLM call with timing, rejected answer with the
  validation errors that went back to the model, and full tracebacks. `BIM_LOG_LEVEL=DEBUG` adds the
  complete prompts and replies. `llama-server`'s own output is in `backend/.llama/server.log`.
- **Browser console** (F12 → Console, filter `[nocoast]`): page/backend URL, health, project open, every
  API call and SSE event, IFC size, web-ifc init and mesh counts, and uncaught errors. The status line
  under the prompt shows the last event or error too.

Common ones: *backend not reachable* / a browser CORS error with *status (null)* → nothing is listening on
8765; run `python main.py` in `backend/` in a second terminal (or pass `?backend=` / `BIM_BACKEND_URL`);
*viewer failed to start* or a 404 for `wasm/` or `fragments-worker.mjs` → `npm install` did not run
`scripts/copy-wasm.mjs` (run `node scripts/copy-wasm.mjs` in `frontend/`);
*language model unavailable* → the provider's own message follows (missing key, workspace id, model file,
`llama-server` exit code with the last log line).

## 5. Tests

`cd backend && python -m pytest` — 41 tests on the mock LLM, no network:
ops semantics and error messages · solver determinism and id stability · compile→lift round trip ·
GlobalId survival across modify/delete/redesign/revert · the SSE project API end to end (design, edit,
conflict 409, ops, revert, import, bad import) · export (validation, stamping, bundle, strict refusal) ·
the legacy stateless endpoints.

`packages/ifc-viewer`: `npm test` (unit + real IFC conversion), `npm run e2e` (headless Chrome), and
`npm run validate -- <file.ifc>`, which checks a generated file the same way the viewer will.
`frontend/scripts/smoke.ps1` runs the desktop app end to end.

## 6. Decisions and their reasons

| decision | reason |
|---|---|
| IR + compiler, not direct IFC generation | validation, token cost, deltas, and a clean fine-tuning target |
| program → solver for new designs, ops for edits | LLMs are good at intent, bad at coordinates; the solver never emits invalid geometry |
| ops as the delta unit, full IFC recompile with stable GlobalIds | simple and provably correct; in-place patching is an optimisation with the same interface |
| single-shot schema-constrained LLM calls, no agent loop in v0 | keeps the swappable surface tiny; an agent loop (query/propose/apply/check tools) wraps these calls without changing them |
| mock adapter in the tree | the whole system is testable and demoable with no model installed |
| SSE over POST | the repair loop is visible; no WebSocket infrastructure |
| SQLite + files | same shape as Postgres + object storage, zero infrastructure |
| whole-model reload in the viewer | correct by construction; incremental patching is frontend work that proves nothing about the pipeline |
| Tauri over Electron | smaller, uses the system WebView2, and the Rust side stays thin |
| That Open for both viewers | fragments reload fast per version; one pinned stack for the main viewer and the history cards |

## 7. Not in v0 (designed, not built)

- **Geometric lifter** for arbitrary IFC files (foreign elements as opaque, read-only context).
- **Agent loop**: `query_model`, `propose_ops` (dry run), `apply_ops`, `check(rules)`, `run_layout` as
  tools around the same two LLM calls, for multi-step requests; bounded to ~10 steps.
- **Selection as context**: pass clicked ids with the prompt; the context builder then includes those
  elements in full and summarises the rest (`core/context.py` already truncates past 400 elements).
- **Smarter solver**: adjacency and target-area aware layout; pitched roofs; stairs.
- **Incremental viewer updates** by GlobalId from the op list.
- **Snapshots to the model**: each version's PNG is rendered already; a backend endpoint to store it
  next to `vN.ifc` would let a vision model check its own output (`TurnSource.writeSnapshot` in
  `frontend/src/turns.ts`).
- **Import button** for `/projects/{id}/import`, and `?project=<id>` deep links (in the old frontend).
- **Multi-user**: ops are already the right unit; only server-side ordering is missing.
- **Fine-tuned model**: train on the stored `(context, prompt) → ops/program` pairs; plug in via
  `LLM_PROVIDER=openai` pointing at its server.
