---
id: shell
title: Shell of revolution
keywords:
- shell
- hyperboloid
- cooling tower
- thin shell
tags:
- curved
ifc: IfcRoof
summary: A shell of revolution is a thick profile, off the axis, revolved a full turn.
ifc_type: FREEFORM
---

The profile is a closed strip: the outside meridian and the inside meridian, so the revolve
makes a hollow shell rather than a solid of the whole radius. Keep every vertex on one side of
the axis. Stand it up with `axis: [0, -1, 0]`. IfcRoof / FREEFORM is an honest IFC4 typing;
the shape is not a dome and not a slab.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "shell",
   "name": "shell",
   "ifc": "IfcRoof",
   "ifc_type": "FREEFORM",
   "material": "concrete",
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
       3.2,
       0
      ],
      [
       2.4,
       2
      ],
      [
       2.0,
       4
      ],
      [
       2.3,
       6
      ],
      [
       3.0,
       8
      ],
      [
       2.65,
       8
      ],
      [
       2.05,
       6
      ],
      [
       1.75,
       4
      ],
      [
       2.1,
       2
      ],
      [
       2.8,
       0
      ]
     ]
    }
   }
  }
 ]
}
```
