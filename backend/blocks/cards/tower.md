---
id: tower
title: Cylindrical tower
keywords:
- tower
- cylinder
- drum
- rotunda wall
tags:
- curved
- wall
ifc: IfcWall
summary: A round tower is a closed circular band extruded by its height.
ifc_type: SOLIDWALL
---

`band` with `closed: true` thickens a ring into an annulus — the wall of a tower, a drum, a
circular parapet. Extrude by the height. A cone or dome sits on top as its own part (see the
dome and spire cards). IfcWall / SOLIDWALL.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "tower",
   "name": "tower",
   "ifc": "IfcWall",
   "ifc_type": "SOLIDWALL",
   "material": "masonry",
   "solid": {
    "op": "extrude",
    "depth": 9,
    "profile": {
     "band": [
      [
       4.0,
       0.0
      ],
      [
       3.8637,
       1.0353
      ],
      [
       3.4641,
       2.0
      ],
      [
       2.8284,
       2.8284
      ],
      [
       2.0,
       3.4641
      ],
      [
       1.0353,
       3.8637
      ],
      [
       0.0,
       4.0
      ],
      [
       -1.0353,
       3.8637
      ],
      [
       -2.0,
       3.4641
      ],
      [
       -2.8284,
       2.8284
      ],
      [
       -3.4641,
       2.0
      ],
      [
       -3.8637,
       1.0353
      ],
      [
       -4.0,
       0.0
      ],
      [
       -3.8637,
       -1.0353
      ],
      [
       -3.4641,
       -2.0
      ],
      [
       -2.8284,
       -2.8284
      ],
      [
       -2.0,
       -3.4641
      ],
      [
       -1.0353,
       -3.8637
      ],
      [
       -0.0,
       -4.0
      ],
      [
       1.0353,
       -3.8637
      ],
      [
       2.0,
       -3.4641
      ],
      [
       2.8284,
       -2.8284
      ],
      [
       3.4641,
       -2.0
      ],
      [
       3.8637,
       -1.0353
      ]
     ],
     "width": 0.4,
     "closed": true
    }
   }
  }
 ]
}
```
