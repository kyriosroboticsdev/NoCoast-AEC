---
id: arch
title: Arch
keywords:
- arch
- archway
- voussoir
tags:
- curved
- structure
ifc: IfcMember
summary: An arch is a small cross-section swept along a semicircular centre-line.
ifc_type: MEMBER
---

`sweep` carries the section (a rectangle, the arch ring's depth and width) along a semicircle
in a vertical plane. The path is the centre-line, from one springing up over the crown and down
to the other; it needs several points or the curve facets coarsely. IfcMember / MEMBER. An
assembly of the arch plus its two abutments can be typed ARCH. IFC4X3 has nothing more specific.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "arch",
   "name": "arch",
   "ifc": "IfcMember",
   "ifc_type": "MEMBER",
   "material": "stone",
   "solid": {
    "op": "sweep",
    "profile": {
     "rect": [
      0.45,
      0.3
     ]
    },
    "path": [
     [
      3.0,
      0.0,
      0.0
     ],
     [
      2.8978,
      0.0,
      0.7765
     ],
     [
      2.5981,
      0.0,
      1.5
     ],
     [
      2.1213,
      0.0,
      2.1213
     ],
     [
      1.5,
      0.0,
      2.5981
     ],
     [
      0.7765,
      0.0,
      2.8978
     ],
     [
      0.0,
      0.0,
      3.0
     ],
     [
      -0.7765,
      0.0,
      2.8978
     ],
     [
      -1.5,
      0.0,
      2.5981
     ],
     [
      -2.1213,
      0.0,
      2.1213
     ],
     [
      -2.5981,
      0.0,
      1.5
     ],
     [
      -2.8978,
      0.0,
      0.7765
     ],
     [
      -3.0,
      0.0,
      0.0
     ]
    ]
   }
  },
  {
   "step": "part",
   "id": "abutment-w",
   "name": "west abutment",
   "ifc": "IfcWall",
   "ifc_type": "SOLIDWALL",
   "material": "stone",
   "at": [
    -3,
    0,
    0
   ],
   "solid": {
    "box": [
     0.6,
     0.8,
     0.4
    ]
   }
  },
  {
   "step": "part",
   "id": "abutment-e",
   "name": "east abutment",
   "ifc": "IfcWall",
   "ifc_type": "SOLIDWALL",
   "material": "stone",
   "at": [
    3,
    0,
    0
   ],
   "solid": {
    "box": [
     0.6,
     0.8,
     0.4
    ]
   }
  },
  {
   "step": "assembly",
   "id": "archway",
   "name": "archway",
   "parts": [
    "arch",
    "abutment-w",
    "abutment-e"
   ],
   "ifc_type": "ARCH"
  }
 ]
}
```
