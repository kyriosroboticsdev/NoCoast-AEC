# Generic building blocks: replacing the room-centric design layer

*Design record for branch `cursor/generic-building-blocks-870e`, cut from `main` at `f9722ab`.*

This document is the plan as approved, with the user's decisions folded in. It is written
before the code so the reasoning survives independently of the diff. Numbers marked
**(measured)** were filled in after the work landed; nothing in this document is an estimate.

---

## 1. The problem

The backend has two layers stacked on one another:

* a **semantic layer** (`schemas/design.py`) whose vocabulary is *rooms, doors, windows,
  stairs, fixtures, balconies, a porch, a roof kind*, and
* a **geometric layer** (`schemas/bim.py`, `BuildingSpec`) whose vocabulary is *walls, slabs,
  roofs, columns, beams, spaces*.

`core/derive.py` (1020 lines) is the bridge: it nodes room outlines against each other,
classifies every boundary piece as exterior wall / partition / railing / open edge, places
openings along the resulting walls, drops in stairs and furniture, unions storey footprints
into slabs and roofs, and adds an MEP rough-in.

That bridge is the whole product's ceiling. Because the only way to make geometry is to
declare a *room*, the system can only build things that are made of rooms:

* **A dome, a vault, an arch, a shell.** There is no revolve and no sweep anywhere in the
  codebase. `ifc/geometry.py` offers exactly three operations: extrude a polygon, box, and
  faceted brep.
* **A tunnel, a culvert, a retaining structure.** `LevelDef` forces `B1`/`B2` basements that
  stack downward *by storey height*; there is no way to say "a 6 m bore whose crown is 20 m
  below datum".
* **A helical stair, a spiral ramp, a colonnade, a repeated bay.** `StairDef` is a single
  straight flight along a wall of a room. There is no instancing and no array transform.
* **A bridge with a curved deck.** The branch added bridges as "free elements" (`FreeDef`),
  but a `FreeDef` slab is a flat polygon: a deck on a horizontal curve with a vertical
  profile is not expressible, and the piers are unrelated to the deck except by coordinate
  coincidence.
* **Anything the fixed catalogues do not name.** `FixtureKind` is 26 literals.
  `RoofShape` is `flat | gable | hip`. `RoomKind` is 15 literals. `FreeKind` is 5.

The room layer also *hard-codes behaviour*. `agents/template_planner.py` expands a prompt
into a house: it guesses storeys, assigns rooms to floors by whether they are "public" or
"private", gives every storey a hall so the stair has somewhere to stand, and adds a garage
door if the model forgot one. `core/derive.py` adds an electrical panel to a
utility/garage/storage room and a plumbing riser to every kitchen and bathroom. None of that
is a capability; it is a house-shaped prior baked into the engine.

**The requirement is that any prompt must be able to produce any output, with no hard-coded
behaviours.** That is not reachable by extending the room vocabulary, because every extension
is another literal in another enum. It is reachable by replacing the semantic layer with a
*generic geometric* one and moving all the domain knowledge out of the code and into
retrieved data.

---

## 2. Decisions (hard constraints)

These are the user's, not negotiable, and they shape everything below.

1. **Full replacement, no flag.** `Design`, the room/door/window/stair/fixture/balcony/porch/
   roof step vocabulary, `core/derive.py` and the room-centric `core/checks.py` are deleted
   outright. The generic layer is the only path. There is no `mode` flag, no legacy path and
   no coexistence period. The internal build order below keeps phases 0–7 as a useful
   sequence, but phases 4/6/7 collapse: there is nothing to flip and nothing to run in
   parallel with. **The branch's end state contains no room vocabulary.**
2. **Keep the streamed-JSON-step mechanism.** No provider-native tool calling. The per-step
   apply/reject/preview streaming loop, the SSE stages and llama.cpp / Ollama / mock support
   all keep working. The flat `GeoStep` design below is chosen precisely because it keeps the
   grammar small enough for constrained decoders.
3. **Backend-only scope.** `LevelTree`, `DataViews`, the design-facts inspector and the
   friendly step-log renderer are not reworked. This does **not** license leaving the app
   crashing — see §9.
4. **IFC4, not IFC4X3.** The viewer pins web-ifc 0.0.77 and That Open's 4X3 support cannot be
   assumed. But entity-name validation is driven by IfcOpenShell schema introspection and is
   **strictly version-parameterised**: the schema identifier is a single named constant
   (`ifc/schema.py::IFC_SCHEMA`, overridable by `BIM_IFC_SCHEMA`) and there is no hard-coded
   IFC4 entity list anywhere in the tree. Flipping to 4X3 is a one-line change plus a viewer
   decision. Where a civil concept is only expressible in 4X3, the closest IFC4 typing
   (`IfcCivilElement`, `IfcBuildingElementProxy`) is used and the recipe card says so,
   naming the 4X3 entity it would prefer.
5. **One-way migration.** `BuildingSpec` → `GeoModel`, so stored projects and `ifc/lifter.py`
   keep working and existing projects stay openable and editable *through the generic
   vocabulary*. One-way only: no round trip back to the room model, no legacy editing path.
   The migration doubles as a test-fixture source.
6. **No house template expander, anywhere — including `/plan`.** A modest capability
   regression on houses is acceptable. It is compensated with coverage in the blocks
   repository, not with special-casing: residential exemplars (multi-storey party-wall
   construction, openings in walls, a straight stair, a pitched roof over a rectangle) exist
   as recipe cards so a house is still well supported, purely as retrieved knowledge.
7. **The quality metric lands in this branch.** `core/checks.py` plus the eval set is the only
   objective number in the repo, and full replacement kills 11 of the 16 requirement kinds. A
   geometric taxonomy computed from cached tessellation is implemented and a replacement eval
   set written, in the same branch, with a residential subset so a house regression is visible
   as a number.

---

## 3. The new semantic layer: `GeoModel`

`schemas/geo.py`. A `GeoModel` is a flat list of **parts** in a small number of **levels**,
plus **openings** that void parts, **assemblies** that group them, and **instances** that
place transformed copies. Nothing in it names a building function.

```
GeoModel
  name, description
  levels:     [ GeoLevel ]      id (L1/L2…/B1…), name, height, elevation?
  parts:      [ GeoPart ]
  openings:   [ GeoOpening ]
  assemblies: [ GeoAssembly ]
  instances:  [ GeoInstance ]
  notes:      [ str ]
```

### 3.1 `GeoPart` — one IFC element

```
GeoPart
  id          stable handle; survives edits, maps 1:1 to an IFC GlobalId
  name        display name; the only place a *word* like "pier" or "bedroom" appears
  ifc         IFC entity name, e.g. IfcWall, IfcSlab, IfcCivilElement
  ifc_type    PredefinedType, e.g. SOLIDWALL, FLOOR
  level       spatial container
  place       Placement — the part's own frame, relative to the level
  solids      [ Solid ] — one or more solids, unioned as one Body representation
  repeat      Repeat? — array the solids by a transform
  material    free-text material name
  style       free-text colour key
```

`ifc` is **validated by schema introspection**, not against a list: the name must exist in
the configured schema, be a non-abstract entity, and be a subtype of `IfcProduct`. That is
the whole of the entity vocabulary — 776 entities in IFC4, every one of them reachable.

### 3.2 `Solid` — the four geometric operations

The entire geometric vocabulary, chosen to be the smallest set that spans the target cases:

| op        | meaning                                                            | unlocks                                              |
|-----------|--------------------------------------------------------------------|------------------------------------------------------|
| `extrude` | a profile swept linearly by `depth` along the placement's +Z       | walls, slabs, columns, beams, decks, prisms, gables  |
| `revolve` | a profile revolved `angle`° about an axis                          | domes, vaults, apses, cones, tori, rings             |
| `sweep`   | a cross-section transported along a 3D `path`                      | tunnels, curved decks, curved walls, mouldings       |
| `mesh`    | explicit faces (outward vertex loops)                              | hip roofs, faceted shells, anything else             |

Each solid carries its own `Placement` in part-local coordinates, so one part can hold
several differently-oriented solids (a chair, a gable roof with its end infills, a pier with
a cap). Surfaces are never used: everything is a closed solid, because the geometry check
tessellates everything and a shell that does not close is a bug we want to see.

`extrude` and `revolve` become `IfcExtrudedAreaSolid` / `IfcRevolvedAreaSolid` — the two
best-supported solid types in every IFC consumer. `sweep` and `mesh` become
`IfcFacetedBrep`: we facet the sweep ourselves rather than emit
`IfcFixedReferenceSweptAreaSolid` or `IfcSweptDiskSolid`, because portability to web-ifc
0.0.77 matters more than representation elegance, and a faceted brep is universally read.

### 3.3 `Profile` — the 2D shapes

```
Profile
  points  [Edge]        polygon; an edge may be an arc through a point
  rect    [w, d]        centred on the origin
  circle  diameter
  band    [Edge]        a polyline …
  width   …thickened by this much (a wall footprint, a ring, an annulus)
  holes   [[Edge]]      inner rings (IfcArbitraryProfileDefWithVoids)
```

`Edge` (`to`, `through`, i.e. vertex or arc-through-point) is lifted unchanged out of
`schemas/design.py` into `schemas/geom2d.py`, together with `arc_points`,
`edges_to_segments`, `signed_area` and the polygon helpers. That machinery is good and is
not room-specific; only its `RoomDef`/`FreeDef` callers were.

### 3.4 `Placement`, `Repeat`, `GeoOpening`, `GeoAssembly`, `GeoInstance`

```
Placement   at [x,y,z]  rotation °(about axis)  axis [x,y,z]=+Z  ref [x,y,z]=+X
Repeat      count  translate [dx,dy,dz]  rotate °  about [x,y]
GeoOpening  id  host  (solid | along/up/width/height/depth)  fill?
GeoAssembly id  name  parts [ids]  ifc_type
GeoInstance id  of (assembly)  place  repeat?
```

`Placement` maps exactly onto `IfcAxis2Placement3D`, which is why out-of-plane extrusion is
free: a gable roof is a chevron profile extruded along `axis=[0,-1,0]`.

`Repeat` is the array transform. A helical stair is **one** part: a tread profile extruded
0.04 m, repeated 24 times with `translate=[0,0,0.18]`, `rotate=15`, `about=[cx,cy]`. A
colonnade, a pier row and a repeated structural bay are the same step with different numbers.

`GeoOpening` has two positioning modes. The general one gives the void as a full `Solid` in
the host's local frame. The sugar (`along`/`up`/`width`/`height`) resolves to a box in the
host's local frame at `(along, -depth/2, up)` — generic, because "along the host's local +X"
is a geometric statement, not a wall-shaped one. `depth` defaults to the host's own local-Y
extent plus clearance, so "through the host" needs no number. `fill` names the part that
fills the void, which is how `IfcDoor`/`IfcWindow` get their `IfcRelFillsElement`.

`GeoInstance` places transformed copies of an assembly's parts, with derived ids
`<instance>-<part>`, so a repeated storey or a repeated bridge bay keeps stable GlobalIds.

### 3.5 What is deliberately *not* in it

No room. No door, window, stair, fixture, balcony, porch. No roof *kind*. No compass `side`.
No `near` point. No adjacency. No auto-placement solver. No MEP rough-in. No material enum.
No wall thickness constant. Every one of those was a decision the engine made on the model's
behalf; they are now the model's to make, informed by recipe cards.

---

## 4. The new step layer: `GeoStep`

`schemas/geosteps.py`. One flat schema, every field optional except `step`, exactly as
`schemas/steps.py` does today — that is what keeps the grammar small for constrained
decoders and tolerant of unconstrained ones, and it is why this design keeps the
streamed-JSON mechanism instead of moving to provider-native tool calls.

```
{"step":"model",    "name","description"}
{"step":"level",    "id","name","height","elevation"}
{"step":"part",     "id","name","ifc","ifc_type","level","material","style",
                    "at","rotation","axis","ref","solids":[…],"repeat":{…}}
{"step":"opening",  "id","host","along","up","width","height","depth","solid","fill"}
{"step":"assembly", "id","name","parts":[…],"ifc_type"}
{"step":"instance", "id","of","at","rotation","repeat":{…}}
{"step":"remove",   "id"}
{"step":"note",     "text"}
```

Eight step kinds against the old seventeen, and the whole of the expressiveness moved into
`solids`. A step is applied the moment it completes in the stream, the model is re-validated,
and a preview is compiled — the existing `core/stream.py` machinery is retargeted, not
rewritten: it already takes "apply one JSON object, re-derive, compile changed elements
only, emit `step` and `partial`".

Sugar the step layer resolves so the model can write the short thing:
`solids:[{"box":[w,d,h]}]`, `{"cylinder":[d,h]}`, `{"extrude":{…}}`, and a bare
`"solid":{…}` for the single-solid case. Sugar is *step-layer only*; `GeoModel` stores the
resolved form, so there is exactly one representation to compile, check and migrate.

---

## 5. The compiler

`ifc/compile.py` replaces `ifc/builder.py` and absorbs `walls.py`, `slabs.py`, `roofs.py`,
`stairs.py`, `openings.py`, `fixtures.py` and `mep.py` — seven type-specific builders become
one generic one, because there is no longer a type to specialise on. `ifc/solids.py`
replaces `ifc/geometry.py` and grows revolve, sweep and profile-with-voids.

`ifc/project.py` keeps the `IfcProject → IfcSite → IfcBuilding → IfcBuildingStorey`
skeleton, with the schema version taken from `ifc/schema.py::IFC_SCHEMA`. Storeys keep
`Description = level.id`, because that is how the viewer maps step events and the section
slider's storey snaps to levels.

`ifc/schema.py` is the only module that knows an entity name at all, and it knows them by
asking the schema:

```python
schema_by_name(IFC_SCHEMA).declaration_by_name(name)   # exists?
… .is_abstract()                                       # instantiable?
supertype chain contains "IfcProduct"                   # a product?
PredefinedType attribute's enumeration                  # valid ifc_type values
```

Styles and materials are keyed by the IFC entity name with a supertype-walk fallback, so a
brand-new entity gets a sensible colour without anyone editing a table.

The `NoCoast_Spec` pset that made our own files losslessly liftable stays, alongside a new
`NoCoast_Geo` pset carrying the `GeoPart` JSON, and `NoCoast_Model` on `IfcBuilding`
carrying the whole `GeoModel`. `ifc/lifter.py` reads either: a new file lifts to a
`GeoModel` directly; an old file lifts to a `BuildingSpec` and is migrated (§7).

---

## 6. The knowledge: `blocks/`

This is where the deleted house prior goes, and it is the answer to "no template expander".

`blocks/cards/*.json`, ~25 **recipe cards**. Each card is data, not code:

```
id, title, keywords[], tags[],
ifc:      the IFC4 typing to use
ifc4x3:   the 4X3 entity it would prefer, when IFC4 has none  (decision 4)
summary:  one line
notes[]:  the geometric reasoning — what to compute, what breaks
steps[]:  a worked, applying GeoStep example
```

Retrieval is deterministic keyword/token scoring against the prompt
(`blocks/__init__.py::retrieve`), not an LLM call and not an embedding index: it has to be
testable and it has to work offline with the mock. The top *k* cards are injected into the
build prompt. Because a card's `steps` are real steps, **every card is tested by applying it
and compiling the result** — the repository cannot rot into prose.

Coverage spans the target cases *and* the residential exemplars decision 6 requires:

* structure: straight wall, wall with openings, party wall / multi-storey stack, floor slab,
  column grid, beam, footing, pitched roof over a rectangle, flat roof/parapet
* spans & civil: bridge deck on piers, curved deck, retaining wall, tunnel bore, culvert
* curved & revolved: dome, barrel vault, arch, apse, cylindrical tower, cone/spire
* circulation: straight stair, helical stair, ramp, landing, void/stair well
* rooms-as-geometry: `IfcSpace` volumes, enclosing a space with walls, openings between spaces
* composition: assemblies, instancing a bay, arraying a colonnade

The residential regression is therefore "a house is a retrieval result", not "a house is a
code path".

---

## 7. Migration

`core/migrate.py`, one way only.

Stored versions carry **both** the `Design` and the `BuildingSpec` it derived to, and the
`BuildingSpec` is the geometric truth. So the migration is purely geometric —
`BuildingSpec → GeoModel` — and `core/derive.py` is not needed to perform it. The `Design`
record is dropped on read; there is no path back.

Each legacy element type maps to a `GeoPart` with the same id (so GlobalIds survive) and the
IFC entity it always compiled to: `wall → IfcWall` from a `band` profile of the axis
polyline, `slab → IfcSlab`, `roof → IfcRoof` (flat = extrude, gable = chevron extrude,
hip = mesh), `door/window → IfcDoor`/`IfcWindow` plus a `GeoOpening` in the host wall,
`fixture`/`custom → IfcFurniture` etc. from their box/round parts, `pipe`/`wire`/`outlet`/
`panel`/`light` → their existing MEP entities as plain boxes.

Three things fall out of this for free, which is why it is worth doing properly:

* Stored projects reopen and are **editable through the generic vocabulary**.
* `/build`, which takes a hand-written `BuildingSpec`, becomes "migrate then compile" — so
  the existing hand-written-spec tests exercise the migration on every run.
* The migration output of the old template planner's houses is a rich **test-fixture source**
  for the compiler and the checker, as proposed.

`schemas/bim.py` survives as a *read-only legacy format*. `schemas/design.py` does not
survive; its geometry helpers move to `schemas/geom2d.py`.

---

## 8. The metric: geometric checks and the eval set

Deleting the room layer kills 11 of the 16 `RequirementKind`s (`room`, `room_level`, `area`,
`adjacent`, `orientation`, `window`, `door`, `stair`, `furniture`, `roof`, `feature`). The
replacement is a **geometric taxonomy computed from cached tessellation**, which is strictly
more general: it checks the *thing that was built*, not the *instruction that was recorded*.

`core/facts.py` tessellates the compiled model **once** per check round with
`ifcopenshell.geom.iterator`, and caches per element: IFC class and supertype chain,
`PredefinedType`, name, id, level, world-space triangle mesh, bounding box, z-extent,
volume, plan footprint (shapely), centroid, facet count and normal spread.

A **selector** picks the elements a requirement is about: `ifc` (entity, subtypes included),
`name` (substring), `level`, `id`. Selectors are the only place words appear, and they match
the `name` the model itself chose — so "three bedrooms" is
`count · ifc=IfcSpace · name=bedroom · ≥3`, which is retrieved knowledge (a card says model a
habitable room as a named `IfcSpace`), not a room type in the engine.

| kind        | question it answers                                                        |
|-------------|----------------------------------------------------------------------------|
| `count`     | how many elements match the selector                                       |
| `entity`    | does the model contain ≥ n of an IFC entity (subtypes included)            |
| `extent`    | is a selection's bounding box ≈ value along x / y / z / longest / shortest  |
| `elevation` | is a selection's base/top at ≈ value                                       |
| `span`      | largest horizontal gap between the supports under a selection              |
| `clearance` | smallest free vertical height under a selection                            |
| `enclosed`  | what fraction of a footprint's perimeter and top is closed by solids       |
| `connects`  | do two selections touch within tolerance                                   |
| `supported` | does every element of a selection have something beneath it                |
| `opening`   | how many voids/fillings a selection has                                    |
| `volume`    | total solid volume of a selection ≈ value                                  |
| `area`      | total plan footprint of a selection ≈ value                                |
| `curved`    | does a selection contain non-prismatic (revolved/swept/faceted) geometry   |
| `levels`    | number of storeys                                                          |
| `material`  | a selection's material name                                               |
| `style`     | not checkable (aesthetics) — reported, not scored                          |
| `other`     | not checkable                                                              |

`tests/evals/prompts.json` is rewritten against this taxonomy, with a **residential subset**
kept so a house regression shows up as a number, and non-residential cases (dome, vault,
tunnel, helical stair, bridge, tower, colonnade) that the old eval set could not express at
all.

**Measured result (measured):** see §11.

---

## 9. Deferred frontend work

Backend-only does not mean a broken app. The HTTP surface is kept source-compatible where
that is possible:

* `GET /projects/{id}` and the `done` SSE event still return a `Version` with
  `summary.{schema,storeys,spaces,elements,counts}` and `checks[]` of
  `{text,status,detail}` — `Assistant.tsx` and the checklist keep working unchanged.
* `summary.storeys` is still the storey-name list and `summary.spaces` still lists
  `IfcSpace` long names, so "N storeys, rooms: …" still reads correctly for anything modelled
  with `IfcSpace` parts.
* SSE stage names are unchanged: `requirements · focus · build · llm · stream · step ·
  partial · verify · compile · done · error`. `state/trace.ts` keeps rendering the run.
* `GET …/versions/{n}/context` still returns plain text.
* `focus` is still a spec element id and still resolves to a part, so click-to-select and
  selection-as-prompt-focus keep working end to end.
* `GET …/versions/{n}/slices` and `/gcode` keep working: they read the compiled IFC by entity
  name, which is generic already.

Where source compatibility is genuinely impossible, the backend returns something **inert
and safe** rather than a shape the frontend will crash on. The exact deferred work:

1. **`GET …/versions/{n}/spec` returns `design: null`** and carries the new model under a new
   `model` key. Returning a `GeoModel` as `design` would crash
   `state/design.ts::describeElement` on `design.rooms.find`. With `null`, `App.tsx`'s
   existing fallback applies ("imports and old versions have no design record; the inspector
   then shows IFC data only"). **Deferred:** rewrite `state/design.ts` against `GeoModel` so
   the design-facts inspector shows part facts (entity, solids, placement, openings) instead
   of falling back to raw IFC properties.
2. **`state/trace.ts` renders the new steps by its `default` branch.** `part`, `opening`,
   `assembly` and `instance` fall through to the raw stage message, which is accurate but not
   friendly; `layout`-based storey grouping no longer fires, so steps nest under one build
   step instead of one per storey. **Deferred:** add `GeoStep` cases to `describe()` and group
   by `part.level` instead of by `layout`.
3. **`viewer/section.ts` storey-snap labels** come from `layout` steps for live previews; with
   no `layout` step the slider still snaps to storeys from the IFC, but the pre-compile
   labels are missing. **Deferred:** learn storeys from `level` steps.
4. **`LegacyViewer`'s rooms toggle** hides `IfcSpace`, which still works, but "rooms" is now
   just "space parts". **Deferred:** rename the control.
5. **`Composer`'s focus chip** shows `f?.title ?? id`, i.e. the raw part id until (1) lands.

None of these throw. None are started in this branch.

---

## 10. Build order

| phase | work | collapses? |
|---|---|---|
| 0 | survey, this document | — |
| 1 | `schemas/geom2d.py`, `schemas/geo.py`, `schemas/geosteps.py`, `ifc/schema.py` — **schema frozen here** | — |
| 2 | `ifc/solids.py`, `ifc/compile.py`, guids, project skeleton | — |
| 3 | `blocks/` cards + retrieval, `llm/prompts.py` | — |
| 4 | `core/stream.py`, `core/pipeline.py`, `core/context.py`, `core/ops.py`, `api/routes.py` | no flag to flip |
| 5 | `core/facts.py`, `core/checks.py`, new eval set | — |
| 6 | `core/migrate.py`, `llm/mock.py` v2, `agents/` | no coexistence period |
| 7 | delete `core/derive.py`, `schemas/design.py`, `solver/`, the old `ifc/*` builders, old tests | plain deletion |

The schema is frozen at the end of phase 1 before any parallel work starts, because
parallelising across an unstable interface is how you get four incompatible halves.

---

## 11. Measured results

*Not yet measured at the time of this first commit. Every figure in this section is filled in
by a later commit on this branch from an actual run; nothing here is an estimate, and the
baseline numbers below were taken on `f9722ab` before any code changed.*

**Baselines on `f9722ab` (the room model), measured:**

* test suite: **110 passed, 33.8 s** (`.venv/bin/python -m pytest`)
* eval set: **93/136 = 68 %** (`tools/eval.py`, mock provider, 21 cases, 16 requirement kinds)

**To be filled in:** this branch's test count and runtime, this branch's eval score on the new
geometric eval set with its residential subset broken out, the per-case element counts and file
sizes from the end-to-end demo, and the deleted/added line counts.

## 12. Risks accepted

* **Capability regression on houses.** Accepted by decision 6. Mitigated by recipe cards and
  measured by the residential eval subset.
* **The model must now do arithmetic.** Wall coordinates, opening offsets and profile
  vertices were previously derived; now they are the model's. This is the cost of "any prompt
  can produce any output" and is mitigated by the recipe cards carrying worked numbers, by
  the step-level rejection messages being specific, and by the geometry check rejecting
  nonsense before the viewer sees it.
* **`sweep` and `mesh` are faceted by us.** Slightly larger files, no analytic curve in the
  IFC. Deliberate: portability to the pinned web-ifc beats representational purity, and the
  arc radius is recorded in a pset the way the old curved-wall code did.
* **IFC4 typing for civil concepts.** `IfcCivilElement` / `IfcBuildingElementProxy` stand in
  for 4X3 entities. Recorded per card so the 4X3 flip is mechanical.
