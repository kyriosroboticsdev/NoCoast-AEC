---
id: dome
title: Dome
keywords:
- dome
- hemisphere
- cupola
- rotunda
tags:
- curved
- roof
ifc: IfcRoof
summary: A dome is a semicircle revolved a full turn and stood upright.
ifc_type: DOME_ROOF
---

Draw the semicircle in the profile plane, entirely on one side of the axis (the axis is the
profile's Y by default, so the semicircle occupies +X). Revolve 360°. The result lies on its
side until you set the solid's `axis` to `[0, -1, 0]`, which points the profile's Y up. IfcRoof
/ DOME_ROOF. A dome on a drum is this solid sitting at `z = drum height`, with the drum a
separate cylindrical wall.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "dome",
   "name": "dome",
   "ifc": "IfcRoof",
   "ifc_type": "DOME_ROOF",
   "material": "stone",
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
       0.0,
       -4.0
      ],
      [
       0.7804,
       -3.9231
      ],
      [
       1.5307,
       -3.6955
      ],
      [
       2.2223,
       -3.3259
      ],
      [
       2.8284,
       -2.8284
      ],
      [
       3.3259,
       -2.2223
      ],
      [
       3.6955,
       -1.5307
      ],
      [
       3.9231,
       -0.7804
      ],
      [
       4.0,
       0.0
      ],
      [
       3.9231,
       0.7804
      ],
      [
       3.6955,
       1.5307
      ],
      [
       3.3259,
       2.2223
      ],
      [
       2.8284,
       2.8284
      ],
      [
       2.2223,
       3.3259
      ],
      [
       1.5307,
       3.6955
      ],
      [
       0.7804,
       3.9231
      ],
      [
       0.0,
       4.0
      ]
     ]
    }
   }
  }
 ]
}
```
