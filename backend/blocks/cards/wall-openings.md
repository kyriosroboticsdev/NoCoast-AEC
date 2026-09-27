---
id: wall-openings
title: Openings in a wall
keywords:
- opening
- door
- window
- void
- aperture
tags:
- wall
- residential
- opening
ifc: IfcWall
summary: A door or window is a void cut through a host part, filled by its own part.
ifc_type: SOLIDWALL
---

The host is an ordinary wall part. The opening's `along` is the distance along the host's local
+X to the near edge of the void, `up` is the height above the host's base, and `width` / `height`
size the hole. Leave `depth` out and the void goes right through. `fill` is the id of the part
that sits in the hole: an IfcDoor or an IfcWindow, a thin solid of the same width and height.
Add the fill part before the opening. A garage door is IfcDoor / GATE; a skylight is IfcWindow /
SKYLIGHT only when the host is a roof.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "front",
   "name": "front wall",
   "ifc": "IfcWall",
   "ifc_type": "SOLIDWALL",
   "material": "masonry",
   "solid": {
    "wall": [
     [
      0,
      0
     ],
     [
      6,
      0
     ]
    ],
    "thickness": 0.24,
    "height": 3
   }
  },
  {
   "step": "part",
   "id": "door",
   "name": "entrance door",
   "ifc": "IfcDoor",
   "ifc_type": "DOOR",
   "material": "timber",
   "at": [
    0.85,
    0,
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
   "step": "part",
   "id": "window",
   "name": "front window",
   "ifc": "IfcWindow",
   "ifc_type": "WINDOW",
   "material": "glass",
   "at": [
    3.7,
    0,
    0.9
   ],
   "solid": {
    "box": [
     1.4,
     0.05,
     1.2
    ]
   }
  },
  {
   "step": "opening",
   "id": "door-void",
   "host": "front",
   "along": 0.4,
   "up": 0,
   "width": 0.9,
   "height": 2.1,
   "fill": "door"
  },
  {
   "step": "opening",
   "id": "window-void",
   "host": "front",
   "along": 3.0,
   "up": 0.9,
   "width": 1.4,
   "height": 1.2,
   "fill": "window"
  }
 ]
}
```
