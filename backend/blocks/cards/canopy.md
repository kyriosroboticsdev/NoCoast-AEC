---
id: canopy
title: Canopy
keywords:
- canopy
- porch roof
- overhang
- awning
tags:
- roof
ifc: IfcRoof
summary: A canopy is a thin plate on posts, larger than the posts' footprint so it
  overhangs.
ifc_type: FLAT_ROOF
---

Two or more IfcColumns carry an IfcRoof / FLAT_ROOF (or IfcSlab / ROOF) placed at the top of the
posts. The plate's outline extends past the posts on the open sides; that overhang is just
geometry, not a separate kind of element. Name it "canopy".

```json
{
 "steps": [
  {
   "step": "part",
   "id": "post-a",
   "name": "post",
   "ifc": "IfcColumn",
   "ifc_type": "COLUMN",
   "material": "steel",
   "at": [
    0.5,
    0.5,
    0
   ],
   "solid": {
    "box": [
     0.15,
     0.15,
     3
    ]
   }
  },
  {
   "step": "part",
   "id": "post-b",
   "name": "post",
   "ifc": "IfcColumn",
   "ifc_type": "COLUMN",
   "material": "steel",
   "at": [
    0.5,
    3.5,
    0
   ],
   "solid": {
    "box": [
     0.15,
     0.15,
     3
    ]
   }
  },
  {
   "step": "part",
   "id": "canopy",
   "name": "canopy",
   "ifc": "IfcRoof",
   "ifc_type": "FLAT_ROOF",
   "material": "steel",
   "at": [
    2,
    2,
    3
   ],
   "solid": {
    "op": "extrude",
    "profile": {
     "rect": [
      6,
      5
     ]
    },
    "depth": 0.08
   }
  }
 ]
}
```
