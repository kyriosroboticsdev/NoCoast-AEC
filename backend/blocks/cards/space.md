---
id: space
title: Enclosed space
keywords:
- space
- room
- enclosure
- habitable
tags:
- residential
ifc: IfcSpace
summary: A room is an IfcSpace volume standing inside walls, not a special object.
ifc_type: SPACE
---

Draw the walls (bands or boxes), the floor plate, and an IfcSpace / SPACE whose box is the clear
interior, named for what it is (`bedroom`, `kitchen`, `hall`). The space is what a count of
"bedrooms" looks for: the check matches the name, it does not know a room type. A door is an
opening in a wall, filled by an IfcDoor. Give the space a height just under the storey so it
does not stick through the slab above.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "floor",
   "name": "floor",
   "ifc": "IfcSlab",
   "ifc_type": "FLOOR",
   "material": "concrete",
   "solid": {
    "op": "extrude",
    "depth": 0.2,
    "profile": {
     "rect": [
      6,
      4
     ]
    }
   }
  },
  {
   "step": "part",
   "id": "wall-s",
   "name": "south wall",
   "ifc": "IfcWall",
   "ifc_type": "SOLIDWALL",
   "material": "masonry",
   "solid": {
    "wall": [
     [
      -3,
      -2
     ],
     [
      3,
      -2
     ]
    ],
    "thickness": 0.2,
    "height": 3
   }
  },
  {
   "step": "part",
   "id": "wall-n",
   "name": "north wall",
   "ifc": "IfcWall",
   "ifc_type": "SOLIDWALL",
   "material": "masonry",
   "solid": {
    "wall": [
     [
      -3,
      2
     ],
     [
      3,
      2
     ]
    ],
    "thickness": 0.2,
    "height": 3
   }
  },
  {
   "step": "part",
   "id": "wall-w",
   "name": "west wall",
   "ifc": "IfcWall",
   "ifc_type": "SOLIDWALL",
   "material": "masonry",
   "solid": {
    "wall": [
     [
      -3,
      -2
     ],
     [
      -3,
      2
     ]
    ],
    "thickness": 0.2,
    "height": 3
   }
  },
  {
   "step": "part",
   "id": "wall-e",
   "name": "east wall",
   "ifc": "IfcWall",
   "ifc_type": "SOLIDWALL",
   "material": "masonry",
   "solid": {
    "wall": [
     [
      3,
      -2
     ],
     [
      3,
      2
     ]
    ],
    "thickness": 0.2,
    "height": 3
   }
  },
  {
   "step": "part",
   "id": "room",
   "name": "bedroom",
   "ifc": "IfcSpace",
   "ifc_type": "SPACE",
   "at": [
    0,
    0,
    0.2
   ],
   "solid": {
    "box": [
     5.5,
     3.5,
     2.7
    ]
   }
  },
  {
   "step": "part",
   "id": "door",
   "name": "door",
   "ifc": "IfcDoor",
   "ifc_type": "DOOR",
   "material": "timber",
   "at": [
    0,
    -2,
    0
   ],
   "solid": {
    "box": [
     0.9,
     0.05,
     2.1
    ]
   }
  },
  {
   "step": "opening",
   "id": "door-void",
   "host": "wall-s",
   "along": -0.45,
   "up": 0,
   "width": 0.9,
   "height": 2.1,
   "fill": "door"
  }
 ]
}
```
