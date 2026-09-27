---
name: writing-assets
title: Writing your own parametric asset
tags: authoring, geometry
triggers: custom, bespoke, unique, special, sculpture, design my own, one-off, make a, build a, shaped, curved, organic, ornate
bricks:
---
When nothing in the library fits, define the thing yourself with an asset step, then place it with brick steps.
1. Name it: lower_snake id, a name, tags people would search for, and the closest concrete IFC4 class
   (IfcFurniture, IfcBuildingElementProxy, IfcFlowTerminal, IfcSanitaryTerminal, IfcColumn, IfcMember …).
2. Parameters: the sizes someone would change, each [default, min, max]. Build every number from them so one
   definition covers every size: "at": ["w - 0.05", 0, "h"]. Use "fit":"ref_h" for things that fill their room's
   height and "fit":"path_length" for the length of a path asset.
3. Geometry: compose primitives. Boxes and cylinders for most furniture; extrude a points profile for any plan
   shape (an L-shaped desk, a kidney table); revolve an (r, z) profile for anything turned (vases, balusters,
   bowls, lamp shades); sweep a profile along a path for rails, pipes and frames; loft between sections for
   tapering or twisting shapes; mesh for anything else. `repeat` with the index in expressions makes arrays
   (chairs round a table: "at": ["r * cos(360 * i / n)", "r * sin(360 * i / n)", 0], "rotate": [0, 0, "360 * i / n"]).
   `when` switches parts on and off ("when": "shelves > 0"); `subtract` cuts holes and recesses.
4. Frame: the brick's back is its min y and it faces +y. Put `origin` where it should land on the placement
   point — usually the centre of its footprint at floor level, ["w / 2", "d / 2", 0].
5. Mount: rest (stands), fix (on a wall, with an `elevation`), hang (from a ceiling), path (runs along a line).
6. Materials: one entry per visible finish, colours 0..1; pick one per node with "material". Glass gets opacity 0.3–0.5.
7. Connectors for what it needs or supplies (power, water_cold, drain, data, air_supply …), a keep-out volume for
   the space in front of it that must stay free, "collides": false for rugs and things meant to overlap.
Check it with check_asset while researching; the step is rejected with the reason if anything does not evaluate.
Example: {"id":"round_side_table","name":"Round side table","tags":["table","furniture"],"ifc_class":"IfcFurniture",
"params":{"r":[0.3,0.2,0.6],"h":[0.55,0.4,0.8]},"origin":[0,0,0],"materials":{"wood":{"color":[0.6,0.42,0.28]}},
"geometry":[{"shape":"cylinder","radius":"r","height":0.03,"at":[0,0,"h - 0.03"]},
{"shape":"cylinder","radius":0.03,"height":"h - 0.03"},{"shape":"cylinder","radius":"r * 0.6","height":0.02}]}
