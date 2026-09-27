---
id: column-grid
title: Column grid
keywords:
- column
- colonnade
- grid
- bay
- pier row
- posts
tags:
- structure
- array
ifc: IfcColumn
summary: A repeated bay is one column, grouped, then instanced on a grid.
ifc_type: COLUMN
---

Model one column. Group it in an assembly. `instance` with `repeat` places a row; a second
instance with a different `at` places the next row. Copy ids are `<instance>-<part>`, stable
across edits. Do not also set `repeat` on the column itself — an instance copies the part's own
repeat and you would get a row of rows. A colonnade is this card with one row.

```json
{
 "steps": [
  {
   "step": "part",
   "id": "col",
   "name": "column",
   "ifc": "IfcColumn",
   "ifc_type": "COLUMN",
   "material": "concrete",
   "solid": {
    "box": [
     0.4,
     0.4,
     4
    ]
   }
  },
  {
   "step": "assembly",
   "id": "bay",
   "name": "bay",
   "parts": [
    "col"
   ]
  },
  {
   "step": "instance",
   "id": "row-a",
   "of": "bay",
   "repeat": {
    "count": 4,
    "translate": [
     4,
     0,
     0
    ]
   }
  },
  {
   "step": "instance",
   "id": "row-b",
   "of": "bay",
   "at": [
    0,
    4,
    0
   ],
   "repeat": {
    "count": 4,
    "translate": [
     4,
     0,
     0
    ]
   }
  }
 ]
}
```
