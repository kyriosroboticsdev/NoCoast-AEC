---
id: barrel-vault
title: Barrel vault
keywords:
- vault
- barrel vault
- wagon vault
tags:
- curved
- roof
ifc: IfcRoof
summary: A barrel vault is a semicircle revolved halfway about its diameter.
ifc_type: BARREL_ROOF
---

The profile is a semicircle standing above its diameter. `axis_dir` `[1, 0]` lays the axis
along the profile's X, and `angle` 180 sweeps a half-cylinder. The vault's length is the
diameter; for a longer nave, sweep the same semicircular section along a straight path instead
of revolving it. IfcRoof / BARREL_ROOF.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "vault",
   "name": "barrel vault",
   "ifc": "IfcRoof",
   "ifc_type": "BARREL_ROOF",
   "material": "masonry",
   "solid": {
    "op": "revolve",
    "angle": 180,
    "axis_dir": [
     1,
     0
    ],
    "profile": {
     "points": [
      [
       3.0,
       0.0
      ],
      [
       2.8978,
       0.7765
      ],
      [
       2.5981,
       1.5
      ],
      [
       2.1213,
       2.1213
      ],
      [
       1.5,
       2.5981
      ],
      [
       0.7765,
       2.8978
      ],
      [
       0.0,
       3.0
      ],
      [
       -0.7765,
       2.8978
      ],
      [
       -1.5,
       2.5981
      ],
      [
       -2.1213,
       2.1213
      ],
      [
       -2.5981,
       1.5
      ],
      [
       -2.8978,
       0.7765
      ],
      [
       -3.0,
       0.0
      ]
     ]
    }
   }
  }
 ]
}
```
