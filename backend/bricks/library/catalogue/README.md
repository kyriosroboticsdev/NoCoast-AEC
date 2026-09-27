# The brick catalogue

Files in this folder are bricks that are **found by search and not listed in the system prompts**.
The prompts carry one line for the whole catalogue: each file name as a topic, with its brick count.
The files one level up are the core library, whose ids are all listed in the prompts. Keep the core
small and put anything specialised here.

A brick is data. See `bricks/model.py` for the fields, `bricks/geometry.py` for the shapes and
`bricks/expr.py` for the expression language. The file name becomes the topic the model reads
(`hvac_plant.json` is shown as "hvac plant"), so name files by what an engineer would look for.

## Before a brick goes in

```
cd backend
python tools/check_bricks.py path/to/new_bricks.json      # any folder
python tools/check_bricks.py                              # the whole catalogue
```

The checker runs what the test suite demands of every brick, one brick at a time:

| Check | What it proves |
|---|---|
| load | the definition validates, numbers are finite, the id is new, lower_snake_case and at most 40 characters |
| range | geometry evaluates at every corner of the parameter ranges, with a real size under 120 m |
| ifc | the class is a concrete IFC4 `IfcElement`, and the predefined type belongs to it |
| place | it places with its defaults in the test scene and compiles to IFC geometry that tessellates |
| words | its name and tags do not make a plain house prompt place it |
| search | searching for its name finds it |

## Rules that are easy to miss

- **Metres**, z up. `origin` is the point of the geometry that lands on the placement point. For
  something standing on the floor that is the centre of its base: `["w / 2", "d / 2", 0]` for a box
  whose corner is at the local origin, `[0, 0, 0]` for shapes drawn around the origin.
- **The back is local −y.** A brick fixed to a wall, or placed against a side, puts its minimum y
  against that side and faces +y. Put access space in a `keepout` in front (+y).
- **Give every size parameter a range**: `"w": [default, min, max]`. `"w": [1.2, 0.6]` drops the range.
- **Heights.** A room is 3.8 m clear in the test scene. Anything taller at its defaults needs the tag
  `outdoor` (placed on the site), `roof` (placed on the roof), `foundations` (placed on the bare
  level, may go below ground), or a parameter with `"fit": "ref_h"`.
- **Path bricks** (`"mount": "path"`) need a length parameter with `"fit": "path_length"` whose range
  includes 6 m. The run goes along local +x from the origin.
- **Predefined type.** Leave it out only when the class has none or allows `NOTDEFINED`. Use
  `USERDEFINED` when no listed type fits; the brick id is then written as the object type.
- **Connectors** are what the brick needs (`in`, the default) and supplies (`out`). Use the kinds
  already in the library where they fit: `power`, `data`, `water_cold`, `water_hot`, `drain`, `gas`,
  `flue`, `heating`, `refrigerant`, `air_supply`, `air_return`, `fire_water`. A building with rooms
  supplies `water_cold`, `drain` and `power` itself. Every other `in` must be supplied by some
  brick's `out`, or the design gets a coordination error, so give a brick an `in` only when it cannot
  work without it and a brick that supplies it exists.
- **Words.** The mock planner places a brick when a prompt contains its name, its id with spaces, or
  one of its multi-word tags. Do not use a name or tag that occurs in an ordinary request
  ("living room", "front door", "open plan").
- **`fixture` in `properties` is reserved** for the core bricks that stand in for catalogue fixtures.
- **Cuts.** `subtract` on a cut is ignored when compiling to IFC, and the clash and fit checks use the
  bounding box, not the cut shape.
- **Dimensions come from somewhere.** Use sizes from a standard or a manufacturer range, and say in
  `description` what the defaults represent ("600 kW air-cooled chiller").

## Where the definitions came from

`docs/brick-sources.md` lists the open data sources for classes, property sets, classification
codes and dimensions, with their licences.
