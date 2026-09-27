---
name: structural-spans
title: Structure: spans, beams, columns and overhangs
tags: structure
triggers: open plan, span, beam, column, structure, structural, cantilever, overhang, large room, hall, warehouse, loft, sagging, wall removal
bricks: glulam_beam, steel_beam, transfer_beam, timber_joist, steel_column, concrete_column, round_column, timber_post, pad_footing, strip_footing, shear_wall, bored_pile
---
- Floors and roofs span between exterior walls. Unsupported span limits by wall material: timber 6 m,
  masonry/plaster/stone 7 m, concrete 8 m, glass 5 m. A room whose SHORT side is longer than that needs a beam.
- To halve a span: a beam along the room's LONG direction at the middle of the short direction, e.g. room
  rect [0,0,10,8] → `steel_beam` ref the room, start [0,4] end [10,4]. `glulam_beam` spans ≤ 8 m, `steel_beam` ≤ 12 m,
  `transfer_beam` ≤ 10 m. Longer beams need a column part way: `steel_column` (ref the room) with `position` under the beam.
- Beam depth ≈ span/17 (timber) or span/20 (steel): pass it as the `h` param.
- Columns on the ground floor stand on a `pad_footing` at the same position.
- Upper storeys must sit on the storey below. An overhang (cantilever) deeper than 1.0 m needs support:
  columns on the level below at the overhang's outer corners, or a `transfer_beam` under the overhang edge.
- Removing an interior wall between two rooms (open plan): the rooms merge; if the merged short side exceeds the
  limit, add a beam where the wall was.
- The check_design tool reports every structural problem with the exact brick steps that fix it.
