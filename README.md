# NoCoast-AEC

Text prompt → building model → **IFC**, with the language model kept swappable and the building built
as a stream of small deltas so the user watches it grow and can iterate on it. Python/FastAPI backend
(IfcOpenShell + shapely), React frontend rendering with [That Open](https://github.com/ThatOpen)
(web-ifc + fragments + three.js), wrapped in Tauri for the desktop. Every prompt produces a new project
version, shown as a 3D turn card in the history (`packages/ifc-viewer`).

![prototype](docs/screenshot.png)

*"Two storey house with a kitchen, living room and three bedrooms, a garage and a front porch" — mock LLM.*

---

## 1. Design in one page

**The LLM never writes IFC, and never writes a wall.** It writes a checklist, then a stream of small
semantic *steps* (a room here, a door there); deterministic code derives every wall, slab, opening and
roof from those and compiles them to IFC after every step.

```
 prompt ──► LLM: REQUIREMENTS checklist  (atomic, typed, "supported" flag)
        ──► LLM: BUILD STEPS, streamed ──► each complete step ─► apply to DESIGN ─► derive ─► preview IFC ─► viewer
                                              (room, door, window, stair, furniture, roof …)      ▲     (≤ 1 s apart)
                 rejected steps ─────────────────────────────── fix round (≤ N) ──────────────────┘
        ──► deterministic CHECK of the design against the checklist ──► unmet → fix round
        ──► derive BuildingSpec (IR) ─► IfcOpenShell compiler (stable GlobalIds) ─► version store ─► viewer
 edit:  the same, starting from the head version's DESIGN; the model emits only the steps that change it
```

Why this shape:

| Problem with "LLM emits IFC" | What we do instead |
|---|---|
| STEP is a graph of `#123=` references; one wrong id breaks the file | The LLM emits JSON validated by Pydantic; the compiler owns every IFC reference |
| A small house is 50–200k tokens of IFC, ~600 tokens of design | Context for edits is the design rendered as text: rooms with rectangles, exterior sides, neighbours (`core/context.py`) |
| Geometry (placements, boolean openings, closed polygons) is where LLMs fail | LLMs place rectangles on a grid and name sides; `core/derive.py` turns that into walls, openings and roofs that always compile |
| One-shot answers hide what went wrong and show nothing until the end | Every step is applied and rendered as it streams; a bad step is rejected with a message the model gets back |
| Detailed prompts lose detail | The checklist is extracted first, carried through the build prompt, checked deterministically at the end, and unmet items trigger a fix round; unsupported wishes are reported, not dropped |
| Text-level diffs of IFC are meaningless (ids renumber) | Ids derive from room ids (`L1-wall-kitchen+hall`), so a room that moves keeps its walls' GlobalIds |
| Swapping the model later | The model only implements `LLM.complete(request, on_text) -> dict` (`llm/base.py`) |

## 2. Repository layout

```
backend/
  schemas/design.py     Design — what the LLM builds: levels, rooms as rectangles, doors, windows, stairs, fixtures, balconies, porch, roof
  schemas/steps.py      Step — the flat step vocabulary the LLM streams, and apply_step (with rejection messages)
  schemas/requirements.py  Requirement checklist (typed, checkable) extracted before building
  schemas/bim.py        BuildingSpec — the geometric IR: walls/slabs/roofs/doors/windows/columns/beams/spaces/stairs/fixtures/railings
  schemas/ops.py        Raw element ops (UI/scripts escape hatch; stored as design overrides)
  core/derive.py        Design → BuildingSpec: walls from room edges, opening placement, stairs, roofs, balconies, porch
  core/checks.py        deterministic verification of a design against its requirements
  core/stream.py        apply steps as they stream; worker thread compiles previews (geometry-checks only what changed)
  core/pipeline.py      the run: requirements → build stream → fix rounds → check → compile → version
  core/ops.py           apply raw ops to a spec (pure, cascading deletes, re-validates)
  core/construction.py  live-build job: writes a version's elements to disk one at a time in construction order
  slicer/               horizontal slices of a compiled IFC by construction phase + preview G-code
  core/guids.py         element id ↔ IFC GlobalId map, kept per project
  core/context.py       design / spec → compact text for the LLM
  core/partial_json.py  close the JSON a model has produced so far (only complete array elements survive)
  solver/layout.py      two-row packer for rooms that come without a rectangle (mock, fallback)
  llm/                  adapter protocol + mock / llamacpp / claude / ollama / openai-compatible implementations, prompts
  ifc/                  IfcOpenShell compiler: project, walls, slabs, roofs (flat/gable/hip), openings, stairs (+ slab wells),
                        fixtures/railings/beams, geometry helpers; lifter (IFC → spec + design)
  store/db.py           SQLite projects/versions (spec + design + checks); IFC files under backend/output/projects/<id>/vN.ifc
  api/routes.py         HTTP API; api/sse.py streams pipeline progress as Server-Sent Events
  agents/               stateless planners for /plan and /generate (template regex → steps, llm)
  tests/                pytest; runs entirely on the mock LLM; tests/evals/prompts.json = accuracy set
  tools/eval.py         score the configured model on the evaluation set
frontend/
  src/viewer/BimViewer.ts  That Open wrapper: model tree, properties, class visibility, hide/isolate
  src/api/client.ts        backend client incl. SSE-over-POST parser
  src/App.tsx, main.tsx    React entry point and top-level layout
  src/components/         Sidebar, TopBar, Workspace, Composer, LevelTree, DataViews, ViewerOverlays, …
  src/turns.ts            version history cards, wiring `packages/ifc-viewer`
  src/platform.ts         the only frontend file that knows about Tauri
  src-tauri/              Tauri 2 shell; starts `backend/.venv` python on start, kills it on exit
  scripts/copy-wasm.mjs   copies web-ifc's wasm + fragments worker into public/ (postinstall)
packages/ifc-viewer/     turn-card viewer: snapshot ⇄ live orbitable view, at most 3 live canvases
```

## 3. Running it

Requirements: Python ≥ 3.12 (3.14 tested), Node ≥ 20. For the desktop shell additionally Rust
(`rustup`), the MSVC C++ Build Tools on Windows, and WebView2 (present on Windows 11).

```bash
# backend
cd backend
pip install -r requirements.txt
cp .env.example .env            # optional; defaults to the mock LLM
python main.py                  # http://127.0.0.1:8765
python -m pytest                # 92 tests, ~15 s
python tools/eval.py            # accuracy of the configured model on tests/evals/prompts.json

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
venv there.

Environment (see `backend/.env.example`; `.env` is re-read before every LLM call and on `/health`, so
switching provider, model or key takes effect without a restart — only paths and the port need one):

| var | meaning |
|---|---|
| `LLM_PROVIDER` | `mock` (default, no model needed), `llamacpp`, `claude`, `ollama`, `openai` |
| `LLM_MODELS_DIR`, `LLAMA_SERVER`, `LLAMA_GPU_LAYERS`, `LLAMA_CTX` | `llamacpp`: folder of `.gguf` files, server binary, GPU offload (99 = all), context |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID` | `claude`: key (or an `ant auth login` profile); workspace id only for org-level keys |
| `BIM_LOG_LEVEL` | `INFO` (default) or `DEBUG` (full LLM prompts and replies in the backend console) |
| `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` | model id / endpoint / key for the chosen provider |
| `BIM_MAX_REPAIRS` | fix rounds for rejected steps per prompt (default 2) |
| `BIM_VERIFY_ROUNDS` | fix rounds for unmet requirements per prompt (default 1; 0 = report only) |
| `BIM_OUTPUT_DIR`, `BIM_DB_PATH`, `BIM_PORT` | storage and port |
| `BIM_BACKEND_URL` (Tauri) or `?backend=` (browser) | backend origin for the UI, default `http://127.0.0.1:8765` |
| `BIM_NO_BACKEND`, `BIM_BACKEND_DIR` (Tauri) | don't spawn the backend / where `backend/` is |
| `BIM_AUTOLOAD`, `BIM_PROMPT`, `BIM_SMOKE_SELECT` (Tauri) | smoke-test hooks: load a file, run a prompt, select an element class |

**Local `.gguf` models.** Fetch a prebuilt `llama-server` once, then point the backend at your model
folder; the server is started on first use and stopped with the backend:

```bash
cd backend
python tools/get_llama.py            # Vulkan build: any GPU, no CUDA toolkit (--backend cpu | cuda-13.4 also work)
# backend/.env
LLM_PROVIDER=llamacpp
LLM_MODELS_DIR=D:\Models
LLM_MODEL=llama-3.2-3b-instruct-q4_k_m.gguf
```

**Claude.** `LLM_PROVIDER=claude` and `ANTHROPIC_API_KEY=sk-ant-…` in `backend/.env` (optionally
`LLM_MODEL=claude-sonnet-5` for cheaper runs). A key created at organisation level rather than inside a
workspace is rejected with *"must include the anthropic-workspace-id header"* — add
`ANTHROPIC_WORKSPACE_ID=wrkspc_…` (Console → Settings → Workspaces) or create the key inside a workspace.

**Claude Opus 5.5 through the OpenAI API spec (current default).** Anthropic serves
`/v1/chat/completions`; the `openai` provider targets it directly (keys go in `.env`; `${VAR}` references
expand to variables defined above them):

```
CLAUDE_KEY=sk-ant-…
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.anthropic.com/v1
LLM_MODEL=claude-opus-5-5
LLM_API_KEY=${CLAUDE_KEY}
```

The adapter handles that host's quirks: `temperature` is omitted (Claude 5 rejects it), numeric bounds
are stripped from the schema (its validator rejects `minimum`/`maximum`), and if the endpoint ever answers
*"the compiled grammar is too large"* the request is retried once without constrained decoding (the step
log shows the note; Pydantic + the repair loop validate on our side). Measured on the family-house prompt
in §4.3: checklist 11 s, then ~22 s before the first step (server-side latency; a trivial request answers
in 1.6 s), then 77 steps at a median 0.8 s apart with 73 previews rendered; 15/16 requirements met.
Edits 2 min including a fix round. `LLM_PROVIDER=claude` uses the native SDK with structured outputs.

**Fireworks (or any other OpenAI-compatible API).** Same provider, streaming from `/chat/completions`
with a JSON-schema `response_format`: `LLM_BASE_URL=https://api.fireworks.ai/inference/v1`,
`LLM_MODEL=accounts/fireworks/models/qwen3p8-max`, `LLM_API_KEY=fw_…`. The same provider covers vLLM,
LM Studio, a hosted API or a fine-tuned model. **Ollama:** `LLM_PROVIDER=ollama LLM_MODEL=llama3.1`.

## 4. Specifications

### 4.1 Design — what the LLM builds

`backend/schemas/design.py`. Semantic, but with coarse geometry: rooms are axis-aligned rectangles
`[x, y, width, depth]` (metres, `(x, y)` = south-west corner, x east, y north) or, when the plan needs
it, polygons `poly: [[x,y], …]` listed counter-clockwise whose edges may be arcs
(`{"to":[x,y],"through":[x,y]}`, a three-point arc faceted at 0.25 m) or open (`{"to":[x,y],"open":true}`:
no wall, columns instead). The polygon is the inner face of the walls, so the area the model states is
the area the checks measure. Everything else refers to rooms and walls; a wall is named by `side`
(N/S/E/W, the compass direction its outside faces; enough for rectangles) or by `near: [x, y]`, a point
on or next to it (any shape; required when a room has two walls facing the same way). `roofed: false`
(courtyard, terrace) and `enclosed: false` (carport, pergola) are set by the room kind and can be
overridden. `elements` holds free-standing walls (polylines, arcs allowed), slabs, roofs, columns and
beams outside the room system; a door or window can sit in a free wall via `wall: <id>`.

```jsonc
{
  "name": "Family House", "description": "…",
  "levels":    [{"id": "L1", "name": "Ground Floor", "height": 3.0}, {"id": "L2", "height": 2.8}],
  "rooms":     [{"id": "kitchen", "name": "Kitchen", "level": "L1", "kind": "kitchen", "rect": [3, 5, 3, 5]}, …],
  "doors":     [{"id": "door-kitchen-hall", "room": "kitchen", "to": "hall", "at": 0.5, "kind": "single"},
                {"id": "door-hall-s", "room": "hall", "to": "outside", "side": "S"}],
  "windows":   [{"id": "win-kitchen-N", "room": "kitchen", "side": "N", "at": 0.5, "kind": "large"}],
  "stairs":    [{"id": "stair-hall", "room": "hall", "side": "W", "to_level": null}],
  "fixtures":  [{"id": "fridge-kitchen", "room": "kitchen", "kind": "fridge", "side": "E", "at": 0.8}],
  "balconies": [{"id": "balcony-master-bedroom-S", "room": "master-bedroom", "side": "S", "depth": 1.5}],
  "porch": {"side": "S", "depth": 2.4},
  "roof": {"kind": "gable", "pitch": 30, "overhang": 0.3},
  "wall_material": "timber",
  "columns": [], "overrides": [], "notes": []
}
```

Levels: `L1` is the ground floor, `L2`… above it, `B1`, `B2`… below ground (`below_ground` is set
automatically; storeys stack upward from 0, basements downward). Up to 40 levels, 2.2–12 m each.
`Design.storeys()` counts the levels above ground (what "two-storey house" means); `basements()` the rest.
Basement rooms get no windows (rejected with a message the model can act on) and no roof; a stair in a
basement room goes up to the ground floor, and the slab above gets its well.
Room kinds: living, kitchen, dining, office, bedroom, bathroom, hall, garage, utility, storage, other.
Door kinds: single, double, sliding, french, garage. Window kinds: standard, large, floor, small.
Fixture kinds (26): bed, double_bed, bunk_bed, sofa, armchair, coffee_table, tv_stand, dining_table,
chair, desk, bookshelf, wardrobe, dresser, kitchen_counter, island, fridge, oven, sink, dishwasher,
washing_machine, toilet, shower, bathtub, washbasin, fireplace, car. Roofs: flat, gable, hip.
Exterior wall materials: masonry, concrete, timber, plaster, stone, glass.

### 4.2 Steps — the deltas the LLM streams

`backend/schemas/steps.py`. The model answers `{"steps": [ … ]}`; one flat object per step, every field
optional except `step`, so the grammar is small and unconstrained models can be lenient (extra keys are
ignored, `"north"`→`"N"`, `2`→`"L2"`, `{"x","y","w","d"}`→rect).

| step | fields | effect |
|---|---|---|
| `building` | name, description | rename |
| `level` | id (`L1`… in order, or `B1`… for basements), name, height, below_ground | add or update a storey or basement |
| `room` | name, level, kind, rect *or* poly, roofed, enclosed, area | add, or update by id/name (rect null → auto-placed by `solver/layout.py`); kinds courtyard/terrace default to no roof, carport/pergola to no walls |
| `layout` | level, rooms:[{name, kind, rect *or* poly, roofed, enclosed}] | replace **all** rooms of a storey atomically (rooms keep id + items when the name is unchanged) |
| `door` | room, to (room id or `outside`), side *or* near, at, kind, width, height; or wall (a free wall id) | add / replace by id |
| `window` | room, side *or* near (an exterior wall), at, kind, width, height, sill; or wall | add / replace by id |
| `stair` | room, side *or* near, to_level, width | straight flight along that wall, well cut in the slab above |
| `furniture` | room, kind, side (`N/S/E/W/center`) *or* near, at, rotation, sizes | fixture against a wall or centred |
| `balcony` | room, side *or* near, depth | slab + railing outside that wall |
| `element` | kind (`wall/slab/roof/column/beam`), name, level, path / poly / position / start+end, height, thickness, width, depth | free-standing structure (garden wall, deck, pergola, pier); unchecked except by name |
| `porch` | side, depth | deck + columns + roof along that side of the ground floor |
| `roof` | kind, pitch, overhang | flat / gable / hip (pitched needs a rectangular footprint; else flat + note) |
| `material` | material | exterior wall material (colour + IfcMaterial) |
| `column` | level, x, y, width | free-standing column |
| `remove` | id | anything by id; rooms and levels cascade to their items |
| `note` | text | shown to the user |

`apply_step` is pure (returns a new design) and raises `StepError` with a message written for the
model: *"door: unknown room 'bedroom' (rooms: hall, kitchen, …)"*, *"levels must be added in order; the
next level id is L2"*. After applying, the design is re-derived; a step that makes the design unbuildable
(overlapping rooms, a window on an interior side, a stair that does not fit) is rejected with the derive
message. Structural steps (`room`, `layout`, `level`, `remove`) instead **prune** openings, stairs,
fixtures and balconies that no longer fit and say so in the step message.

### 4.3 Derivation — Design → BuildingSpec

`backend/core/derive.py`, deterministic. Per storey:

1. rooms without an outline are auto-placed; overlapping rooms are an error (they may share edges);
2. the boundaries of all rooms on the storey (arcs faceted) are **noded** against each other with shapely;
   walking each room's boundary, consecutive pieces with the same classification merge into one wall: a
   piece touched by one room is an **exterior wall** `L1-wall-<room>-<compass of its outward normal>`
   (0.3 m, `-2` suffix when two walls face the same way, extended by half its thickness at outline
   corners), a piece shared by two rooms a **partition** `L1-wall-<a>+<b>` (0.12 m). Rectangular rooms
   therefore keep the ids they always had. The chords of one arc become one faceted wall (`Wall.path`,
   true radius in the `NoCoast_Curve` pset). An **open** edge gets columns (both ends and every 4 m) and a
   beam instead of a wall; a wall between a room and an open or unroofed neighbour belongs to the
   enclosed room as its exterior wall (so it can take windows); an unroofed room's own free edges get a
   railing. The storey outline (union of the rooms) becomes the slab (ground-floor courtyards are left
   unpaved), spaces are the room polygons inset 0.06 m;
3. roofs cover what a storey's **roofed** rooms have that the storey above has not (a garage beside a
   two-storey block gets its own lower roof; a courtyard or terrace is a hole in it); gable/hip only for
   rectangular pieces; basements get none;
4. doors go on the partition between their two rooms or on an exterior wall of the room; windows and
   balconies need an exterior wall. The wall is picked by `near` (closest wall of the room within 1.5 m,
   position = the projection of the point), else by `side` (pieces of one straight edge count as one
   wall; two separate walls facing the same way are rejected with both `near` points to choose from),
   else the longest. `at ∈ [0,1]` chooses the position along the wall and openings are nudged to the
   nearest free slot; garages get a garage door automatically; free walls host openings via `wall`;
5. stairs run along the chosen straight wall (rise from the level height, 0.18 m risers, 0.25 m goings;
   the wall must be ~5 m long and the flight must fit inside the room polygon), with a well cut into the
   slab above; fixtures sit against the chosen wall with their back to it, rotated to the wall's angle
   (catalogue sizes in `ifc/fixtures.py`, footprint checked against the polygon); balconies are a slab
   plus a railing outside a straight exterior wall; the porch is a deck, columns and a roof along one
   side of the ground floor; free-standing elements are added as written;
6. stored raw ops (`overrides`) are replayed at the end; ones that no longer apply are dropped with a note.

`analyze()` also returns per-room information — exterior sides (compass of each exterior wall's outward
normal), open sides, neighbours, the polygon — and the compass side every opening ended up on, used by
the edit context and the checker. Everything raises `DesignError` with a model-readable message.

### 4.4 Requirements and checks — accuracy on detailed prompts

`schemas/requirements.py`, `core/checks.py`. Before building, the model turns the prompt into atomic
requirements with a `kind` the checker understands:

`storeys · room (room keyword, count, level) · room_level · area · adjacent · orientation (room has an exterior
wall on side) · window (count, side) · door (room ↔ room/outside) · stair · furniture (kind, room, count) ·
roof · feature (garage/porch/balcony/basement) · dimension · material · style · other`

plus `supported: false` for what the builder cannot do (curved walls, pools, elevators …) — those are
listed in the version notes instead of being silently dropped. After the build stream, `check()` runs each
requirement against the design deterministically (`[met]`, `[UNMET] living room facing south — Living
Room's exterior sides are N, W`, `[unsupported]`, `[not checked]` for style), the result goes to the step
log and the version record, and unmet items trigger one fix round with the same build prompt.

The same format is the evaluation set (`tests/evals/prompts.json`, 16 detailed prompts with hand-written
requirements). `python tools/eval.py` runs the real pipeline on each and prints met/checkable per case
and overall — the number to watch when changing prompts, schemas or models.

### 4.5 Streaming, previews and the step log

Every provider streams (`LLM.complete(request, on_text, on_note)` receives the accumulated reply after
each chunk). `core/stream.py::StepStream`:

```
LLM stream thread ──feed(text)──► parse_partial → new complete steps → apply_step + analyze (ms)
                                    ├─ ok:       SSE "step" {index, ok, message, elements}; design marked dirty
                                    └─ rejected: SSE "step" {index, ok:false, error}; design unchanged
preview worker thread ──────────► latest dirty design → derive → compile IFC, geometry-check ONLY changed
                                    elements → output/partial/<id>.ifc → SSE "partial" {ifc_url, change, …}
browser ────────────────────────► loads each preview (newest pending only); final version replaces it
```

- steps land at the model's token rate: the family house above emitted 77 steps at a median 0.8 s
  apart; a preview compile of a 100-element house is ~0.3 s, so the coalescing worker keeps up;
- `core/partial_json.py` closes the JSON produced so far and **drops any array element that is still
  open**, so a half-generated step never appears;
- nothing is emitted unless the derived spec validates *and* the changed products tessellate; previews use
  the project's GlobalId map so ids are stable even between previews;
- while the model is silent (queueing, thinking) a `stream` heartbeat says *"waiting for the model… 12 s"*
  every 3 s; SSE `stream` events (every 0.4 s once text flows) drive the live model-output pane;
- `close()` runs before the final compile, so IfcOpenShell is never used from two threads at once;
- preview files are served by the `/models` static mount and pruned after 30 minutes.

**Step log (transparency).** Every SSE event carries `seq` and `t`; stages: `requirements` (the checklist,
unsupported items flagged), `focus` (what the viewer selection resolved to, when one was sent), `build`
(which round and why: rejected steps / unmet requirements listed),
`llm` (what was sent to which model; then chars, seconds, steps applied/rejected, previews), `stream`,
`step` (one per step: applied with its effect, or rejected with the reason and the raw step), `partial`
(diff against the previous preview, rooms per level, counts, compile time, how many elements were
re-checked), `verify` (every requirement with met/unmet/unsupported and the detail), `compile`, `done`,
`error`. The UI renders these on the right in one of two modes: **friendly** (default) reads like an assistant
thinking aloud ("I understood 6 things to build", "Adding the Kitchen on the ground floor (4 × 5 m)",
"Skipped: window on the north wall of the Kitchen — that side is shared with the Hall", "Checked the result:
15 of 16 requirements met"); **verbose** shows every event with stage, timing, raw steps and preview rows
(clickable to re-show any intermediate render). A second checkbox reveals the raw model output, an overlay says
what the viewer is showing, and the notes under the prompt list unsupported / unmet requirements. The camera is
framed once per project and then kept, so previews and versions grow in place.

### 4.6 BuildingSpec — the geometric IR

`backend/schemas/bim.py`. Units are metres; plan coordinates `(x, y)`; `z` comes from levels. Element
types: `wall` (start/end/thickness/external/material, or `path` for a faceted curved wall; `frame_at(offset)`
gives the local frame an opening is cut in), `slab`, `roof` (outline + shape/pitch/ridge),
`door` (host wall + offset + kind), `window` (+ sill), `column`, `beam`, `space`, `stair` (position,
direction, width, risers/goings, `to_level`), `fixture` (kind, centre, rotation, w×d×h), `railing`
(path, height). Every element has a stable string `id`; walls are centred on `start→end`; openings are
parametric on their host wall. Validation (`BuildingSpec._check`) is semantic: unique ids, known levels
and host walls, openings inside their wall, outlines with area, pitched roofs on rectangles.

### 4.7 Raw element ops

`backend/schemas/ops.py` / `core/ops.py` remain for the UI and scripts (`POST /projects/{id}/ops`):
`add_element`, `modify_element`, `delete_element`, `add_level`, `modify_level`, `delete_level`,
`set_building`, in a typed and a flat form. On a project with a design they are stored as
`design.overrides` and replayed after every derivation, so a later design edit keeps them (or drops the
ones that no longer apply, with a note). Deleting a wall deletes its openings; level elevations re-stack.

### 4.8 LLM adapter and prompts

`backend/llm/`. The contract:

```python
@dataclass
class LLMRequest:
    system: str; user: str; schema: dict; schema_name: str  # "requirements" | "build"
    meta: dict                                              # side channel for the mock only

class LLM(Protocol):
    name: str
    def complete(self, request: LLMRequest, on_text=None, on_note=None) -> dict: ...
```

| provider | how JSON is enforced | notes |
|---|---|---|
| `mock` | regexes + the template layout (`llm/mock.py`, `agents/template_planner.py`) | no network; backs the tests |
| `llamacpp` | starts `llama-server` on a local `.gguf`, then `openai` below | grammar-constrained by llama.cpp |
| `claude` | Anthropic SDK, `output_config.format` json_schema | structured outputs |
| `ollama` | `/api/chat` with `format: <json schema>` | local models via Ollama |
| `openai` | `/chat/completions` with `response_format: json_schema` (strict) | Anthropic's compat endpoint, Fireworks, vLLM, LM Studio, fine-tuned models |

Every provider receives the schema through `llm/schema.py::strict_schema` (all properties required,
objects closed, tuples as arrays, `oneOf`→`anyOf`, optionally without numeric bounds). Two prompts exist
(`llm/prompts.py`): **requirements** and **build**; the build prompt carries the step vocabulary, the
coordinate conventions, typical room sizes, the construction order (levels → rooms → roof → doors →
windows → stairs → furniture, so the building grows visibly), completeness rules (every room a door and a
window, kitchens a counter/fridge/oven/sink …), and the edit rules (emit only changes; use one `layout`
step to rearrange a storey because rooms may never overlap between steps). The user message is
`CURRENT DESIGN` (empty or the rendered design) + `REQUEST` + `CHECKLIST` (+ rejected steps or unmet
requirements in fix rounds). `(context, prompt) → steps` pairs are stored with every version — the
fine-tuning target for a specialised model later.

### 4.9 GlobalId stability

`core/guids.py`. Per project a map `{"project", "site", "building", "level:<id>", "element:<id>",
"opening:<id>"} → GlobalId` is stored with each version. `compile_ifc(spec, guids)` assigns ids from the
map and mints new ones only for new keys; `prune_guids` drops keys that left the spec. Because derived
element ids are functions of room ids and sides, moving or resizing a room keeps its walls', windows' and
furniture's GlobalIds; adding a neighbour turns `L1-wall-a-E` into `L1-wall-a+b` (a new element, as it
should be). Tested in `tests/test_ifc_roundtrip.py` and `tests/test_projects_api.py`.

### 4.10 IFC compiler

`backend/ifc/`. IFC4, `ifcopenshell.api` for the standard pieces and hand-built solids
(`ifc/geometry.py`) for the rest. Walls: extruded rectangle on the wall axis, IfcMaterial and a colour per
material. Slabs/spaces: extruded outlines. Roofs: flat = extruded outline; gable = chevron profile with
gable-end infills; hip = faceted brep (pyramid when square). Doors/windows: an `IfcOpeningElement` cut
through the host wall and a parametric door/window filling (`OperationType` from the door kind). Stairs:
`IfcStair` (STRAIGHT_RUN_STAIR) as a sawtooth profile extruded across the width, plus an opening cut into
the slab of the level it reaches. Fixtures: `IfcFurniture` / `IfcSanitaryTerminal` /
`IfcElectricAppliance` (car and fireplace as `IfcBuildingElementProxy`) from a few boxes each; railings
as posts + handrail; beams as boxes. Every element, storey and the building carry a **`NoCoast_Spec`**
pset with their spec JSON and the building a **`NoCoast_Design`** pset with the design, which is what
makes the lifter lossless. `check_geometry` tessellates products (all of them for a version, only the
changed ones for a preview).

### 4.11 Lifter (IFC as context)

`backend/ifc/lifter.py`. Reads a NoCoast-generated IFC back into `(BuildingSpec, Design, GuidMap)` from
the psets and GlobalIds, so a downloaded file can be re-imported (`POST /projects/{id}/import`) and
edited with the same ids. A geometric lifter for *foreign* IFC files is the designed next step.

### 4.12 Version store and API

`backend/store/db.py`, SQLite: `versions(project_id, number, parent, prompt, mode, llm, spec, design,
checks, guids, ops, notes, summary, ifc_path)`. Modes: `design`, `edit`, `ops`, `revert`, `import`.
History is linear; `revert/{n}` appends a copy of *n*; `base_version` gives optimistic concurrency (409).

| method / path | body | result |
|---|---|---|
| `GET /health` | | `{ok, llm: {provider, model}}` |
| `POST /projects` | `{name}` | project |
| `GET /projects/{id}` | | `{project, head, versions}` |
| `POST /projects/{id}/prompt` | `{prompt, base_version?, focus?}` | **SSE** — design or edit; `focus` is the spec element id selected in the viewer (`L1-wall-hall-W`, `door-kitchen-hall`, `L1-space-hall`, …), described to the model in words by `core/context.py::describe_focus` ("SELECTED IN THE VIEWER: the west exterior wall of the Hall (L1) …") |
| `POST /projects/{id}/ops` | `{ops, base_version?}` | **SSE** — raw element ops (stored as overrides) |
| `POST /projects/{id}/revert/{n}` | | **SSE** |
| `POST /projects/{id}/import` | multipart `file` (.ifc) | **SSE** |
| `GET /projects/{id}/versions/{n}/ifc` | | the IFC file |
| `GET /projects/{id}/versions/{n}/spec` | | `{version, spec, design, guids}` |
| `GET /projects/{id}/versions/{n}/context` | | text — exactly what the LLM sees when editing |
| `GET /projects/{id}/versions/{n}/slices`, `…/gcode` | `?layer_height=` | horizontal slices of the compiled IFC in construction-phase order; slicer-style preview G-code (`slicer/`) |
| `POST /projects/{id}/versions/{n}/construction`, `GET …/construction/{job}` | | live-build job: one IFC per element in construction order, polled by the viewer (`core/construction.py`) |
| `POST /plan`, `/build`, `/generate` | | stateless one-shots (scripts, tests) |

SSE events: `event: <stage>` + `data: {"seq", "t", "stage", "message", "data"}`, stages as in §4.5.
`done.data` is the version record incl. `ifc_url` and `checks`.

### 4.13 Frontend

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

`Open IFC…` and `Sample` view a file in the main viewer without adding it to the project; the
backend's `/projects/{id}/import` endpoint has no button yet. The server-side slicer and live-build
endpoints (§4.11) exist in the backend but have no UI yet.

The Tauri shell (`src-tauri/`) starts `backend/.venv` python unless something already listens on the
port (skip with `BIM_NO_BACKEND=1`). A Windows Job Object ties the backend to the app, so it also dies
on a crash or force-quit. The shell also provides native open/save dialogs and raw-bytes
`read_ifc`/`write_ifc` commands. `src/platform.ts` is the only frontend file that knows about Tauri.

## 4.14 Troubleshooting

Both sides log verbosely so a failure can be diagnosed from two pastes:

- **Backend console** (`python main.py`): every request, LLM call with timing, each step applied or
  rejected with the validation errors that went back to the model, and full tracebacks.
  `BIM_LOG_LEVEL=DEBUG` adds the complete prompts and replies. `llama-server`'s own output is in
  `backend/.llama/server.log`.
- **Browser console** (F12 → Console, filter `[nocoast]`): page/backend URL, health, project open, every
  API call and SSE event, IFC size, web-ifc init and mesh counts, and uncaught errors. The status line
  under the prompt shows the last event or error too.

Common ones: *backend not reachable* / a browser CORS error with *status (null)* → nothing is listening on
8765; run `python main.py` in `backend/` in a second terminal (or pass `?backend=` / `BIM_BACKEND_URL`);
*viewer failed to start* or a 404 for `wasm/` or `fragments-worker.mjs` → `npm install` did not run
`scripts/copy-wasm.mjs` (run `node scripts/copy-wasm.mjs` in `frontend/`); *language model unavailable* →
the provider's own message follows (missing key, workspace id, model file, `llama-server` exit code with
the last log line). *the model produced no applicable steps* → every step was rejected; the step log
shows each reason (usually an edit request the model could not map onto existing ids).

## 5. Tests

`cd backend && python -m pytest` — 95 tests on the mock LLM, no network: derivation (walls from shared
and free edges, opening placement, stairs and wells, roofs over partial footprints, id stability when a
room moves, basements) · polygons (L-shaped rooms and their wall ids, ambiguous sides, curved walls as one
faceted wall with a window, open edges and carports, courtyards, `near` errors, free elements with a gate
in a garden wall, the template and mock vocabulary) · steps (application, rejection messages, cascades, the streaming runner rejecting an
overlapping room mid-stream) · checks against a template design and the eval fixtures · raw ops
semantics · partial-JSON parsing of every prefix · compile→lift round trip incl. the design · GlobalId
survival across edits, ops, revert · the SSE project API end to end (design with streamed steps and
previews, edits keeping GlobalIds, overrides replayed, conflict 409, import) · every element kind
compiling. `python tools/eval.py` measures accuracy on the real model.

## 6. Decisions and their reasons

| decision | reason |
|---|---|
| design layer + deterministic derivation, not direct IFC or wall-level JSON | the model reasons about rooms and sides; walls, offsets and polygons are where it fails |
| rooms as rectangles the model places itself, polygons only when the plan needs them | the only way detailed layouts ("kitchen next to dining, living facing south") can be honoured; overlaps are caught per step; rectangles keep the compass vocabulary the model knows |
| walls named by a nearby point, compass as sugar | compass sides do not survive L-shapes and curves; a point does, and the model already thinks in the coordinates it placed the rooms with |
| curved walls as one faceted IfcWall | every IFC toolchain copes with a polygon profile; openings in true curved profiles are where they break; the radius is kept in a pset |
| steps streamed and applied one at a time | small deltas, ≤ 1 s cadence, each rejection is local and explained; nothing invalid is ever rendered |
| requirements checklist + deterministic checker + fix round | accuracy becomes measurable and unmet detail is fed back instead of lost; unsupported wishes are surfaced |
| ids derived from room ids | GlobalIds survive moves and resizes without a diffing step |
| raw ops kept as overrides | element-level edits from the UI survive later design edits |
| mock adapter in the tree | the whole system is testable and demoable with no model installed |
| SSE over POST | the build is visible step by step; no WebSocket infrastructure |
| whole-model reload in the viewer | correct by construction; incremental mesh patching is deferred |
| Tauri over Electron | smaller, uses the system WebView2, Rust side is 40 lines |

## 7. Not in v0 (designed, not built)

- **Geometric lifter** for arbitrary IFC files (foreign elements as opaque, read-only context).
- **Pitched roofs over non-rectangular footprints** (decompose into rectangles, or a straight-skeleton hip).
- **L-shaped / two-flight stairs**; ramps; doors in `layout` steps.
- **Bridges and civil structures as first-class kinds** (deck, span, pier, abutment with their own checks);
  today they are free-standing elements.
- **Lightwells** for basement windows; split levels.
- **Incremental viewer updates** by GlobalId from the step list (today the whole model reloads and the
  change is animated).
- **Multi-user**: steps are already the right unit; only server-side ordering is missing.
- **Fine-tuned model**: train on the stored `(context, prompt) → steps` pairs; plug in via
  `LLM_PROVIDER=openai` pointing at its server.
