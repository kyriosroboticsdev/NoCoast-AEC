---
id: flat-roof
title: Flat roof and parapet
keywords:
- flat roof
- parapet
- roof terrace
tags:
- roof
- residential
ifc: IfcRoof
summary: A flat roof is a plate, with a low wall around it when it is a terrace.
ifc_type: FLAT_ROOF
---

IfcRoof / FLAT_ROOF, extruded by 0.2 m, at the top of the storey. A parapet is an IfcWall /
PARAPET: a closed `band` around the same outline, sitting on the roof, 0.9 m high and about
0.15 m thick. Closed means the band joins back on itself, so the parapet is a ring.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "roof",
   "name": "flat roof",
   "ifc": "IfcRoof",
   "ifc_type": "FLAT_ROOF",
   "material": "membrane",
   "at": [
    0,
    0,
    3
   ],
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
       7
      ],
      [
       0,
       7
      ]
     ]
    }
   }
  },
  {
   "step": "part",
   "id": "parapet",
   "name": "parapet",
   "ifc": "IfcWall",
   "ifc_type": "PARAPET",
   "material": "concrete",
   "at": [
    0,
    0,
    3.2
   ],
   "solid": {
    "op": "extrude",
    "depth": 0.9,
    "profile": {
     "band": [
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
       7
      ],
      [
       0,
       7
      ]
     ],
     "width": 0.15,
     "closed": true
    }
   }
  }
 ]
}
```
