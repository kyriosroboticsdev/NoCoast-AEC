---
id: party-wall
title: Party wall
keywords:
- party wall
- terrace
- semi-detached
- dwelling
- multi-storey
- two storey
tags:
- wall
- residential
ifc: IfcWall
summary: Two dwellings share one wall; each habitable room is an IfcSpace, stacked
  on storeys.
ifc_type: SOLIDWALL
---

A party wall is just a wall whose two faces each bound a different space. Model each dwelling as
an IfcSpace with a name (`dwelling A`, `bedroom`), on a level. Stack storeys with `level` steps
(L1 then L2); a part may be taller than its level, so one party wall can rise through both.
Give each storey its own floor slab. Do not invent a room type: the name on the space is the
whole of the label.

```json
{
 "steps": [
  {
   "step": "level",
   "id": "L2",
   "name": "Upper",
   "height": 3
  },
  {
   "step": "part",
   "id": "slab-l1",
   "name": "ground floor",
   "ifc": "IfcSlab",
   "ifc_type": "FLOOR",
   "level": "L1",
   "material": "concrete",
   "solid": {
    "op": "extrude",
    "profile": {
     "points": [
      [
       0,
       0
      ],
      [
       12,
       0
      ],
      [
       12,
       8
      ],
      [
       0,
       8
      ]
     ]
    },
    "depth": 0.2
   }
  },
  {
   "step": "part",
   "id": "slab-l2",
   "name": "upper floor",
   "ifc": "IfcSlab",
   "ifc_type": "FLOOR",
   "level": "L2",
   "material": "concrete",
   "solid": {
    "op": "extrude",
    "profile": {
     "points": [
      [
       0,
       0
      ],
      [
       12,
       0
      ],
      [
       12,
       8
      ],
      [
       0,
       8
      ]
     ]
    },
    "depth": 0.2
   }
  },
  {
   "step": "part",
   "id": "party",
   "name": "party wall",
   "ifc": "IfcWall",
   "ifc_type": "SOLIDWALL",
   "level": "L1",
   "material": "masonry",
   "at": [
    6,
    4,
    0
   ],
   "solid": {
    "op": "extrude",
    "profile": {
     "rect": [
      0.3,
      8
     ]
    },
    "depth": 6
   }
  },
  {
   "step": "part",
   "id": "space-a1",
   "name": "dwelling A",
   "ifc": "IfcSpace",
   "ifc_type": "SPACE",
   "level": "L1",
   "at": [
    3,
    4,
    0.2
   ],
   "solid": {
    "box": [
     5.4,
     7.4,
     2.7
    ]
   }
  },
  {
   "step": "part",
   "id": "space-b1",
   "name": "dwelling B",
   "ifc": "IfcSpace",
   "ifc_type": "SPACE",
   "level": "L1",
   "at": [
    9,
    4,
    0.2
   ],
   "solid": {
    "box": [
     5.4,
     7.4,
     2.7
    ]
   }
  },
  {
   "step": "part",
   "id": "space-a2",
   "name": "bedroom A",
   "ifc": "IfcSpace",
   "ifc_type": "SPACE",
   "level": "L2",
   "at": [
    3,
    4,
    0.2
   ],
   "solid": {
    "box": [
     5.4,
     7.4,
     2.7
    ]
   }
  },
  {
   "step": "part",
   "id": "space-b2",
   "name": "bedroom B",
   "ifc": "IfcSpace",
   "ifc_type": "SPACE",
   "level": "L2",
   "at": [
    9,
    4,
    0.2
   ],
   "solid": {
    "box": [
     5.4,
     7.4,
     2.7
    ]
   }
  }
 ]
}
```
