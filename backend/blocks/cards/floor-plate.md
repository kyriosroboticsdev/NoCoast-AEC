---
id: floor-plate
title: Floor plate
keywords:
- floor
- slab
- floor plate
- deck plate
tags:
- slab
ifc: IfcSlab
summary: A floor is a polygon extruded by its thickness, sitting on its level.
ifc_type: FLOOR
---

One IfcSlab / FLOOR per storey. The profile is the outline in plan, counter-clockwise, extruded
by the slab thickness (0.2 m is a ordinary plate). A hole in the plate — a stair well, an atrium —
is a ring in `holes`, wound either way. BASESLAB is the plate on the ground; LANDING is a stair
landing. The plate's part sits at local z = 0 of its level unless it is raised.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "floor",
   "name": "floor plate",
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
       10,
       0
      ],
      [
       10,
       8
      ],
      [
       0,
       8
      ]
     ],
     "holes": [
      [
       [
        4,
        3
       ],
       [
        6,
        3
       ],
       [
        6,
        5
       ],
       [
        4,
        5
       ]
      ]
     ]
    }
   }
  }
 ]
}
```
