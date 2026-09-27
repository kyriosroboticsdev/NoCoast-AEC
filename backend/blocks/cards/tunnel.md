---
id: tunnel
title: Tunnel bore
keywords:
- tunnel
- bore
- underground
- subway
- buried
tags:
- civil
- underground
ifc: IfcCivilElement
summary: A tunnel lining is a ring swept along the bore, on a level whose elevation
  is the crown depth.
ifc4x3: IfcTunnel
---

Add a level below ground (`B1`) and set `elevation` to the bore's datum — a tunnel is not a
basement stacked by storey height, so say the elevation explicitly (negative, metres). The
lining is a `sweep` of a circular profile with a circular `hole`: outer diameter the excavation,
inner diameter the clear bore. The path is the centre-line in 3D, so the bore can slope and
curve. IFC4 types this as IfcCivilElement. IFC4X3 would use IfcTunnel.

```json
{
 "steps": [
  {
   "step": "level",
   "id": "B1",
   "name": "bore",
   "height": 8,
   "elevation": -18
  },
  {
   "step": "part",
   "id": "lining",
   "name": "tunnel lining",
   "ifc": "IfcCivilElement",
   "level": "B1",
   "material": "concrete",
   "solid": {
    "op": "sweep",
    "profile": {
     "circle": 6.4,
     "holes": [
      [
       [
        2.6,
        0.0
       ],
       [
        2.4021,
        0.995
       ],
       [
        1.8385,
        1.8385
       ],
       [
        0.995,
        2.4021
       ],
       [
        0.0,
        2.6
       ],
       [
        -0.995,
        2.4021
       ],
       [
        -1.8385,
        1.8385
       ],
       [
        -2.4021,
        0.995
       ],
       [
        -2.6,
        0.0
       ],
       [
        -2.4021,
        -0.995
       ],
       [
        -1.8385,
        -1.8385
       ],
       [
        -0.995,
        -2.4021
       ],
       [
        -0.0,
        -2.6
       ],
       [
        0.995,
        -2.4021
       ],
       [
        1.8385,
        -1.8385
       ],
       [
        2.4021,
        -0.995
       ]
      ]
     ]
    },
    "path": [
     [
      0,
      0,
      0
     ],
     [
      12,
      0,
      0
     ],
     [
      24,
      4,
      -0.5
     ],
     [
      36,
      8,
      -1
     ]
    ]
   }
  }
 ]
}
```
