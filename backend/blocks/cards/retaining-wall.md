---
id: retaining-wall
title: Retaining wall
keywords:
- retaining wall
- retaining
- batter
- embankment
tags:
- civil
- wall
ifc: IfcWall
summary: A retaining wall is a battered cross-section extruded along its length.
ifc_type: SOLIDWALL
ifc4x3: IfcRetainingWall
---

The cross-section is a trapezoid, wide at the base, extruded along the wall. Point the solid's
`axis` along the wall (`[1, 0, 0]` runs it east); the profile's x is then across the wall and
its y is up. IFC4 has no IfcRetainingWall — IfcWall / SOLIDWALL is the closest — and the card
would say IfcRetainingWall on IFC4X3. Name the part "retaining wall" so a check can find it.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "retaining",
   "name": "retaining wall",
   "ifc": "IfcWall",
   "ifc_type": "SOLIDWALL",
   "material": "concrete",
   "axis": [
    1,
    0,
    0
   ],
   "solid": {
    "op": "extrude",
    "depth": 12,
    "profile": {
     "points": [
      [
       0,
       0
      ],
      [
       1.4,
       0
      ],
      [
       0.45,
       4
      ],
      [
       0,
       4
      ]
     ]
    }
   }
  }
 ]
}
```
