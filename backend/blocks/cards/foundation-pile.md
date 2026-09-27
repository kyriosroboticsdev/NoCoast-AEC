---
id: foundation-pile
title: Foundation and pile
keywords:
- foundation
- footing
- pile
- pad
- piled
tags:
- foundation
ifc: IfcFooting
summary: A pad footing at grade with a pile continuing down below it.
ifc_type: PAD_FOOTING
ifc4x3: IfcDeepFoundation
---

IfcFooting / PAD_FOOTING is a box at z = 0, wider than the thing it carries. IfcPile / BORED is
a cylinder whose top meets the underside of the pad and whose length is the embedment: place it
at `z = -length` and extrude up by `length`. STRIP_FOOTING is the same pad stretched under a wall.
IFC4X3 would type a piled foundation more richly; the geometry does not change.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "pad",
   "name": "pad footing",
   "ifc": "IfcFooting",
   "ifc_type": "PAD_FOOTING",
   "material": "concrete",
   "at": [
    0,
    0,
    0
   ],
   "solid": {
    "box": [
     1.8,
     1.8,
     0.5
    ]
   }
  },
  {
   "step": "part",
   "id": "pile",
   "name": "bored pile",
   "ifc": "IfcPile",
   "ifc_type": "BORED",
   "material": "concrete",
   "at": [
    0,
    0,
    -8
   ],
   "solid": {
    "cylinder": [
     0.45,
     8
    ]
   }
  }
 ]
}
```
