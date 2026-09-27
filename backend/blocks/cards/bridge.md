---
id: bridge
title: Bridge deck on piers
keywords:
- bridge
- viaduct
- deck
- pier
- span
- curved deck
tags:
- civil
- bridge
ifc: IfcSlab
summary: Piers stand on the ground; a swept slab follows a curve at deck level.
ifc_type: FLOOR
ifc4x3: IfcBridge
---

IFC4 has no IfcBridge. Type the deck as IfcSlab / FLOOR (or IfcCivilElement if it is not a
floor in any sense) and each pier as IfcColumn. The deck is a `sweep`: a wide, thin rectangle
carried along a 3D polyline at the deck elevation, so the deck can curve in plan and change
level. Put a pier under the path, not on a straight grid — a `repeat` is right only for a
straight viaduct. Group deck and piers in one assembly. IFC4X3 would use IfcBridge and
IfcBridgePart for the span and the piers.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "pier-1",
   "name": "pier 1",
   "ifc": "IfcColumn",
   "ifc_type": "COLUMN",
   "material": "concrete",
   "at": [
    0,
    0,
    0
   ],
   "solid": {
    "box": [
     0.9,
     0.9,
     8
    ]
   }
  },
  {
   "step": "part",
   "id": "pier-2",
   "name": "pier 2",
   "ifc": "IfcColumn",
   "ifc_type": "COLUMN",
   "material": "concrete",
   "at": [
    10,
    0,
    0
   ],
   "solid": {
    "box": [
     0.9,
     0.9,
     8
    ]
   }
  },
  {
   "step": "part",
   "id": "pier-3",
   "name": "pier 3",
   "ifc": "IfcColumn",
   "ifc_type": "COLUMN",
   "material": "concrete",
   "at": [
    20,
    0,
    0
   ],
   "solid": {
    "box": [
     0.9,
     0.9,
     8
    ]
   }
  },
  {
   "step": "part",
   "id": "pier-4",
   "name": "pier 4",
   "ifc": "IfcColumn",
   "ifc_type": "COLUMN",
   "material": "concrete",
   "at": [
    30,
    0,
    0
   ],
   "solid": {
    "box": [
     0.9,
     0.9,
     8
    ]
   }
  },
  {
   "step": "part",
   "id": "deck",
   "name": "curved deck",
   "ifc": "IfcSlab",
   "ifc_type": "FLOOR",
   "material": "concrete",
   "solid": {
    "op": "sweep",
    "profile": {
     "rect": [
      8,
      0.45
     ]
    },
    "path": [
     [
      0,
      0.0,
      8
     ],
     [
      5,
      0.5753,
      8
     ],
     [
      10,
      1.0098,
      8
     ],
     [
      15,
      1.197,
      8
     ],
     [
      20,
      1.0912,
      8
     ],
     [
      25,
      0.7182,
      8
     ],
     [
      30,
      0.1693,
      8
     ]
    ]
   }
  },
  {
   "step": "assembly",
   "id": "bridge",
   "name": "bridge",
   "parts": [
    "pier-1",
    "pier-2",
    "pier-3",
    "pier-4",
    "deck"
   ],
   "ifc_type": "RIGID_FRAME"
  }
 ]
}
```
