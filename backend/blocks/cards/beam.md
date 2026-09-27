---
id: beam
title: Beam
keywords:
- beam
- girder
- lintel
- joist
tags:
- structure
ifc: IfcBeam
summary: A beam is a box as long as its span, sitting with its top at the level height.
ifc_type: BEAM
---

Profile a rectangle `length` by `width`, centred on the span's midpoint, rotated so local +X runs
along the span, and extrude downward... actually extrude upward from `z = storey height − depth`
so the beam hangs under the floor it carries. IfcBeam / BEAM for a girder, JOIST for a joist,
LINTEL over an opening. A sloped member (a rafter) is an IfcMember instead, with `axis` along
the member — see the truss card.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "beam",
   "name": "girder",
   "ifc": "IfcBeam",
   "ifc_type": "BEAM",
   "material": "concrete",
   "at": [
    4,
    3,
    2.6
   ],
   "solid": {
    "op": "extrude",
    "profile": {
     "rect": [
      8,
      0.3
     ]
    },
    "depth": 0.5
   }
  }
 ]
}
```
