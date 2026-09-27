---
id: culvert
title: Culvert
keywords:
- culvert
- box culvert
- underpass
tags:
- civil
- underground
ifc: IfcCivilElement
summary: A box culvert is a rectangular tube extruded along its length.
ifc4x3: IfcTunnelPart
---

Same idea as the tunnel, shorter and rectangular. Extrude a hollow rectangle along the culvert:
`axis` along its length, the profile the cross-section (outer ring and one hole). Bury it by
putting the part on a below-ground level or at a negative local z. IFC4X3 would still call the
whole thing a civil facility; IfcTunnelPart is the closest named piece.

```json
{
 "steps": [
  {
   "step": "level",
   "id": "B1",
   "name": "culvert",
   "height": 4,
   "elevation": -3
  },
  {
   "step": "part",
   "id": "culvert",
   "name": "box culvert",
   "ifc": "IfcCivilElement",
   "level": "B1",
   "material": "concrete",
   "axis": [
    1,
    0,
    0
   ],
   "solid": {
    "op": "extrude",
    "depth": 8,
    "profile": {
     "points": [
      [
       -1.6,
       0
      ],
      [
       1.6,
       0
      ],
      [
       1.6,
       2
      ],
      [
       -1.6,
       2
      ]
     ],
     "holes": [
      [
       [
        -1.2,
        0.25
       ],
       [
        1.2,
        0.25
       ],
       [
        1.2,
        1.6
       ],
       [
        -1.2,
        1.6
       ]
      ]
     ]
    }
   }
  }
 ]
}
```
