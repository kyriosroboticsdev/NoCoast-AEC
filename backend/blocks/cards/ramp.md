---
id: ramp
title: Ramp
keywords:
- ramp
- slope
- inclined
tags:
- circulation
ifc: IfcRamp
summary: 'A straight ramp is a wedge: a right triangle extruded across its width.'
ifc_type: STRAIGHT_RUN_RAMP
---

The triangle's base is the run and its height is the rise. Point `axis` along the width
(`[0, 1, 0]` extrudes north) so the triangle stands in a vertical plane along the run. IfcRamp /
STRAIGHT_RUN_RAMP. A spiral ramp is the same section swept along a rising helix, or one wedge
repeated with a turn — see the helical stair, which is the same move.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "ramp",
   "name": "ramp",
   "ifc": "IfcRamp",
   "ifc_type": "STRAIGHT_RUN_RAMP",
   "material": "concrete",
   "axis": [
    0,
    1,
    0
   ],
   "solid": {
    "op": "extrude",
    "depth": 2,
    "profile": {
     "points": [
      [
       0,
       0
      ],
      [
       8,
       0
      ],
      [
       8,
       1.2
      ]
     ]
    }
   }
  }
 ]
}
```
