---
id: cantilever
title: Cantilever
keywords:
- cantilever
- overhang
- projecting
tags:
- structure
ifc: IfcSlab
summary: A cantilever is a plate that runs past the last thing holding it up.
ifc_type: FLOOR
---

Model the support (a wall or a column) and the plate as two parts. The plate's outline simply
continues past the support; there is no cantilever entity. The plate's base should meet the
support's top, and the unsupported length is whatever the outline says. IfcSlab / FLOOR or
IfcBeam for a cantilevered beam — same geometry, the beam's span past the support.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "support",
   "name": "support wall",
   "ifc": "IfcWall",
   "ifc_type": "SHEAR",
   "material": "concrete",
   "at": [
    0.2,
    2,
    0
   ],
   "solid": {
    "box": [
     0.4,
     4,
     3
    ]
   }
  },
  {
   "step": "part",
   "id": "slab",
   "name": "cantilever slab",
   "ifc": "IfcSlab",
   "ifc_type": "FLOOR",
   "material": "concrete",
   "at": [
    3,
    2,
    3
   ],
   "solid": {
    "op": "extrude",
    "profile": {
     "rect": [
      6,
      4
     ]
    },
    "depth": 0.25
   }
  }
 ]
}
```
