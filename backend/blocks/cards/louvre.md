---
id: louvre
title: Louvre
keywords:
- louvre
- louver
- brise-soleil
- screen
- fins
tags:
- array
ifc: IfcPlate
summary: A louvre is one tilted blade repeated on a regular pitch.
ifc_type: SHEET
---

One blade: a thin rectangle extruded along its length, with `axis` leaned off vertical so the
blade tilts. `repeat` steps the next blade along the pitch. IfcPlate / SHEET. The tilt is the
solid's axis, not a rotation of the whole screen, so every copy leans the same way.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "blade",
   "name": "louvre",
   "ifc": "IfcPlate",
   "ifc_type": "SHEET",
   "material": "aluminium",
   "axis": [
    0,
    0.35,
    0.937
   ],
   "repeat": {
    "count": 10,
    "translate": [
     0,
     0.22,
     0
    ]
   },
   "solid": {
    "op": "extrude",
    "profile": {
     "rect": [
      2.4,
      0.02
     ]
    },
    "depth": 0.4
   }
  }
 ]
}
```
