---
id: pitched-roof
title: Pitched roof
keywords:
- roof
- gable
- pitched roof
- pitch
tags:
- roof
- residential
ifc: IfcRoof
summary: A gable is a chevron profile extruded along the ridge.
ifc_type: GABLE_ROOF
---

The chevron lives in a vertical plane and is extruded along the ridge. Set the solid's `axis` to
`[1, 0, 0]` so local +Z (the extrusion) runs east along the ridge; the profile's x is then north
and its y is up. Rise = half the span × tan(pitch). Give the chevron a thickness perpendicular
to the slope (`thickness / cos(pitch)` measured vertically) so the solid closes. A triangular
infill at each end, same profile, extruded a short distance, closes the attic. Sit the part at
`z = storey height`. HIP_ROOF is the mesh card's territory: a hip is not an extrusion.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "gable",
   "name": "gable roof",
   "ifc": "IfcRoof",
   "ifc_type": "GABLE_ROOF",
   "material": "tile",
   "at": [
    0,
    0,
    3
   ],
   "axis": [
    1,
    0,
    0
   ],
   "solids": [
    {
     "op": "extrude",
     "depth": 8,
     "profile": {
      "points": [
       [
        0,
        0
       ],
       [
        3,
        2.1006
       ],
       [
        6,
        0
       ],
       [
        6,
        0.3052
       ],
       [
        3,
        2.4058
       ],
       [
        0,
        0.3052
       ]
      ]
     }
    },
    {
     "op": "extrude",
     "depth": 0.2,
     "profile": {
      "points": [
       [
        0,
        0
       ],
       [
        3,
        2.1006
       ],
       [
        6,
        0
       ]
      ]
     }
    },
    {
     "op": "extrude",
     "at": [
      0,
      0,
      7.8
     ],
     "depth": 0.2,
     "profile": {
      "points": [
       [
        0,
        0
       ],
       [
        3,
        2.1006
       ],
       [
        6,
        0
       ]
      ]
     }
    }
   ]
  }
 ]
}
```
