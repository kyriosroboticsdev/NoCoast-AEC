---
id: straight-stair
title: Straight stair
keywords:
- stair
- straight stair
- flight
- staircase
tags:
- circulation
- residential
ifc: IfcStair
summary: A straight flight is one tread repeated along its run, rising each time.
ifc_type: STRAIGHT_RUN_STAIR
---

Same part as the spiral stair with `rotate` left at 0 and `translate` equal to the going and the
riser, for example `[0.26, 0, 0.175]`. Sixteen copies climb about 2.8 m in 4.2 m of run. IfcStair
/ STRAIGHT_RUN_STAIR. Cut a hole in the slab above with an opening whose `solid` is a box over
the upper part of the flight; the hole is a void, not a room.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "flight",
   "name": "straight stair",
   "ifc": "IfcStair",
   "ifc_type": "STRAIGHT_RUN_STAIR",
   "material": "timber",
   "repeat": {
    "count": 16,
    "translate": [
     0.26,
     0,
     0.175
    ]
   },
   "solid": {
    "op": "extrude",
    "profile": {
     "rect": [
      0.28,
      1.0
     ]
    },
    "depth": 0.04
   }
  }
 ]
}
```
