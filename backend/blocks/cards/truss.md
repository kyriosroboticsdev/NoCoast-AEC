---
id: truss
title: Truss
keywords:
- truss
- rafter
- chord
- roof truss
tags:
- structure
ifc: IfcMember
summary: A truss is members whose axis follows each bar, grouped as an IfcElementAssembly
  / TRUSS.
ifc_type: CHORD
---

Each bar is its own IfcMember. A horizontal chord uses an ordinary extrusion. A sloping rafter
sets `axis` to the bar's direction and extrudes a small rectangle by the bar's length, with the
part origin at the bar's start. CHORD for the tie, RAFTER for the slopes. The assembly's
predefined type is TRUSS.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "tie",
   "name": "bottom chord",
   "ifc": "IfcMember",
   "ifc_type": "CHORD",
   "material": "timber",
   "at": [
    3,
    0,
    0.1
   ],
   "solid": {
    "op": "extrude",
    "profile": {
     "rect": [
      6,
      0.12
     ]
    },
    "depth": 0.2
   }
  },
  {
   "step": "part",
   "id": "rafter-w",
   "name": "west rafter",
   "ifc": "IfcMember",
   "ifc_type": "RAFTER",
   "material": "timber",
   "at": [
    0,
    0,
    0.2
   ],
   "axis": [
    0.8944,
    0,
    0.4472
   ],
   "solid": {
    "op": "extrude",
    "profile": {
     "rect": [
      0.12,
      0.16
     ]
    },
    "depth": 3.354
   }
  },
  {
   "step": "part",
   "id": "rafter-e",
   "name": "east rafter",
   "ifc": "IfcMember",
   "ifc_type": "RAFTER",
   "material": "timber",
   "at": [
    6,
    0,
    0.2
   ],
   "axis": [
    -0.8944,
    0,
    0.4472
   ],
   "solid": {
    "op": "extrude",
    "profile": {
     "rect": [
      0.12,
      0.16
     ]
    },
    "depth": 3.354
   }
  },
  {
   "step": "assembly",
   "id": "truss",
   "name": "truss",
   "parts": [
    "tie",
    "rafter-w",
    "rafter-e"
   ],
   "ifc_type": "TRUSS"
  }
 ]
}
```
