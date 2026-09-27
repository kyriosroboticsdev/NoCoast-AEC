---
id: spire
title: Cone and spire
keywords:
- spire
- cone
- steeple
tags:
- curved
- roof
ifc: IfcRoof
summary: A spire is a triangle revolved about its upright side.
ifc_type: FREEFORM
---

The profile is a thin closed triangle on one side of the axis: the base radius at the bottom,
nearly nothing at the tip, and a small thickness so it is a shell rather than a solid cone of
the whole radius. Revolve 360° and stand it up with `axis: [0, -1, 0]`. IfcRoof / FREEFORM.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "spire",
   "name": "spire",
   "ifc": "IfcRoof",
   "ifc_type": "FREEFORM",
   "material": "copper",
   "solid": {
    "op": "revolve",
    "angle": 360,
    "axis": [
     0,
     -1,
     0
    ],
    "axis_dir": [
     0,
     1
    ],
    "profile": {
     "points": [
      [
       2.2,
       0
      ],
      [
       0.15,
       7
      ],
      [
       0.05,
       7
      ],
      [
       0.15,
       0
      ]
     ]
    }
   }
  }
 ]
}
```
