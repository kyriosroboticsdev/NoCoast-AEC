---
id: spiral-stair
title: Spiral stair
keywords:
- spiral stair
- helical stair
- spiral
- helix
- winding stair
tags:
- circulation
- array
ifc: IfcStair
summary: One tread, repeated with a rise and a turn about the same centre.
ifc_type: SPIRAL_STAIR
---

A helical stair is a single part. The solid is one tread (a short extrusion), placed out from
the centre. `repeat` makes the rest: `translate` is the rise per step, `rotate` is the turn per
step in degrees, `about` is the plan centre. `count` includes the original. IfcStair /
SPIRAL_STAIR. The same pattern with no `rotate` is a straight flight; with a larger translate
and a floor profile it is a spiral ramp.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "tread",
   "name": "helical stair",
   "ifc": "IfcStair",
   "ifc_type": "SPIRAL_STAIR",
   "material": "timber",
   "repeat": {
    "count": 18,
    "translate": [
     0,
     0,
     0.18
    ],
    "rotate": 20,
    "about": [
     0,
     0
    ]
   },
   "solid": {
    "op": "extrude",
    "at": [
     0.45,
     0,
     0
    ],
    "profile": {
     "rect": [
      0.9,
      0.28
     ]
    },
    "depth": 0.04
   }
  }
 ]
}
```
