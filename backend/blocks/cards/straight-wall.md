---
id: straight-wall
title: Straight wall
keywords:
- wall
- straight wall
- masonry wall
- partition
tags:
- wall
- residential
ifc: IfcWall
summary: A wall is a polyline thickened into a band and extruded by its height.
ifc_type: SOLIDWALL
---

Give the wall its own part. The footprint is a `band`: the centre-line polyline thickened by
`thickness`. Extrude that by the storey height. Local +X of a band that runs east is east, so an
opening's `along` is measured from the start of the line. Use IfcWall / SOLIDWALL for a bearing
or enclosure wall and PARTITIONING only when it separates two spaces and carries nothing.
Material is free text (`masonry`, `concrete`, `timber`).

```json
{
 "steps": [
  {
   "step": "part",
   "id": "wall",
   "name": "straight wall",
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
      8,
      0
     ]
    ],
    "thickness": 0.3,
    "height": 3
   }
  }
 ]
}
```
