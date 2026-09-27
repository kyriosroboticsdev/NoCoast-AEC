---
id: curtain-wall
title: Curtain wall
keywords:
- curtain wall
- mullion
- glazing
- glass wall
tags:
- wall
ifc: IfcCurtainWall
summary: A glazed wall is a thin IfcCurtainWall; the mullions are repeated IfcMembers.
---

The glass is one IfcCurtainWall, a thin plate the size of the elevation. IfcCurtainWall's only
predefined types are USERDEFINED and NOTDEFINED, so leave `ifc_type` unset or NOTDEFINED.
Mullions are IfcMember / MULLION, one of them repeated across the bay. Give the glass
`material: glass` so it reads as transparent.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "glazing",
   "name": "curtain wall",
   "ifc": "IfcCurtainWall",
   "material": "glass",
   "solid": {
    "box": [
     8,
     0.06,
     3.4
    ]
   }
  },
  {
   "step": "part",
   "id": "mullion",
   "name": "mullion",
   "ifc": "IfcMember",
   "ifc_type": "MULLION",
   "material": "aluminium",
   "at": [
    -3.6,
    0,
    0
   ],
   "repeat": {
    "count": 7,
    "translate": [
     1.2,
     0,
     0
    ]
   },
   "solid": {
    "box": [
     0.06,
     0.12,
     3.4
    ]
   }
  }
 ]
}
```
