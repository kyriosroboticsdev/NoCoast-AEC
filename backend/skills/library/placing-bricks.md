---
name: placing-bricks
title: How to place any brick (read this first)
disciplines: architecture, interior, plumbing, electrical, hvac, fire, structure, site, transport, energy, data
triggers: brick, bricks, asset, place, furniture, equipment, fixture
bricks:
---
A brick step: {"step":"brick","brick":<brick id>,"id":<optional id>,"room":<room id>,"side"|"near"|"position","at",
"rotation","params":[{"name":"w","value":1.2}, …]}. Only give params you want to change from the defaults, and stay
inside the ranges on the brick card.
By host:
- floor: stands in `room`. `side` N|S|E|W puts its back to that wall (`at` 0..1 along it), "center" in the middle,
  `near` [x,y] against the nearest wall, `position` [x,y] exactly there (its centre).
- wall: fixed to a wall of `room` at the brick's mount height; `side`/`near` name the wall.
- ceiling: under the ceiling of `room`, at `position` or the room centre.
- roof: on top of the building's roof; `position` [x,y] inside the top storey's footprint (null = centred).
- free: anywhere on `level` at `position` [x,y]; `room` optional.
- span: from `start` [x,y] to `end` [x,y] on `level` (beams, ducts, handrails).
- site: outside the building at `position` [x,y], no `room`; it must stand clear of every room.
- site_span: outside the building from `start` to `end` (fences, hedges), clear of every room.
Pieces may not overlap each other or a stair unless their card says so; keep each brick's clearance free.
Unknown brick ids are rejected with the closest matches — search_bricks first when unsure.
