---
id: void-shaft
title: Void and shaft
keywords:
- void
- shaft
- atrium
- stair well
- lightwell
tags:
- opening
- residential
ifc: IfcSlab
summary: A shaft is a hole through a slab with a wall around the hole.
ifc_type: FLOOR
---

The slab's profile carries the shaft as a `hole`. The shaft wall is a closed band on the hole's
outline, extruded the storey height, sitting on the slab. Nothing is named "void" in IFC: the
hole is an inner ring, and a vertical shaft people occupy can also be an IfcSpace inside it.
An opening element is for a void cut through a host that you did not model as a hole in the
profile — a door, a window, a well cut into an existing plate.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "slab",
   "name": "floor with shaft",
   "ifc": "IfcSlab",
   "ifc_type": "FLOOR",
   "material": "concrete",
   "solid": {
    "op": "extrude",
    "depth": 0.2,
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
       6
      ],
      [
       0,
       6
      ]
     ],
     "holes": [
      [
       [
        3,
        2
       ],
       [
        5,
        2
       ],
       [
        5,
        4
       ],
       [
        3,
        4
       ]
      ]
     ]
    }
   }
  },
  {
   "step": "part",
   "id": "shaft",
   "name": "shaft wall",
   "ifc": "IfcWall",
   "ifc_type": "SOLIDWALL",
   "material": "concrete",
   "at": [
    0,
    0,
    0.2
   ],
   "solid": {
    "op": "extrude",
    "depth": 3,
    "profile": {
     "band": [
      [
       3,
       2
      ],
      [
       5,
       2
      ],
      [
       5,
       4
      ],
      [
       3,
       4
      ]
     ],
     "width": 0.2,
     "closed": true
    }
   }
  }
 ]
}
```
