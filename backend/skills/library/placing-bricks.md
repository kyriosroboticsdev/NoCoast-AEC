---
name: placing-bricks
title: How to place any brick (read this first)
tags: placement
triggers: brick, bricks, asset, place, furniture, equipment, fixture
bricks:
---
A brick step: {"step":"brick","brick":<brick or asset id>,"id":<optional id>,"ref":<what it goes in or on>,
"side"|"near"|"position","at","rotation","params":[{"name":"w","value":1.2}, …]}. Only give params you want to
change from the defaults, and stay inside the ranges on the brick card.
`ref` names a frame:
- a room id: the space from its floor to its ceiling; its walls are its sides and bricks keep clear of them.
- a wall, slab, column, beam, roof or another brick's id: a solid body. Resting bricks stand on its top, hanging
  bricks hang under it, fixed bricks go on one of its faces (`near` picks the face).
- "roof": on top of the top roof. "site": the ground around the building; its sides are the building's outer faces.
- a level id, or null: that level's datum (give `position`, or `start`/`end`).
Where in the frame: `side` N|S|E|W puts the brick's back against that side (`at` 0..1 along it), `near` [x,y] against
the nearest side, `position` [x,y] exactly there (its origin; [x,y,z] also sets the height), nothing = the middle.
The card's mount decides the height:
- rest: on the floor of the room (or the top of a solid ref), lifted by its elevation.
- fix: back to a side at its elevation above the floor (wall cabinets, sockets, radiators).
- hang: from the ceiling (or under a solid ref) — lights, detectors, diffusers.
- path: from `start` to `end` ([x,y] or [x,y,z]); its length param follows the distance (beams, ducts, fences).
A param with "fits ref_h" (or ref_w, ref_d) takes the size of its ref when you leave it out: a column fills the storey.
Pieces may not overlap each other or a stair unless their card says they may; keep each brick's keep-out space free.
Unknown brick ids are rejected with the closest matches — search_bricks first when unsure, or write an asset.
