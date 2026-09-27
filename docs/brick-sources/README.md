# Where brick data can come from

Research from 2026-09-27 into open, structured sources for growing the brick library: IFC classes and
property sets, classification systems, Revit categories, and real dimensions. Two reports:

- [standards.md](standards.md): buildingSMART (IFC4, IFC4.3, property sets, bSDD, IDS), classification
  systems (Uniclass, OmniClass, MasterFormat, UniFormat, CCI, CoClass, ETIM, ECLASS, NL-SfB), COBie and
  product data templates, open dimension tables. 26 sources.
- [product.md](product.md): Revit categories and their IFC mapping, open family and object libraries,
  BIM object portals and what their terms allow, dimension tables by discipline, open datasets.

Both reports mark each fact as verified (read on a fetched page or file) or unverified, and rate each
source **use now**, **use with care** or **reference only**. Licence notes are not legal advice.

## Where the library stands

`python backend/tools/brick_coverage.py` prints the current numbers. The IFC4 schema has 130 concrete
element classes and 644 specific predefined types; the library covers under half of the classes and
about a sixth of the types, so the uncovered list is the plan for what to write next.

## What to import first

| Order | Source | Licence | What it adds to a brick |
|---|---|---|---|
| 1 | IFC4 class and predefined-type catalogue (the schema itself, through IfcOpenShell) | CC BY-ND 4.0 | the exact `ifc_class` and `predefined_type`; the coverage report |
| 2 | IFC4 property set templates (`Pset_IFC4_ADD2.ifc`, shipped with IfcOpenShell) | as the schema | standard names for `properties`, per class and type |
| 3 | Uniclass 2015 Products, Systems and Elements tables | CC BY-ND 4.0 | a classification code, and a maintained mapping from product to IFC type |
| 4 | ETIM 10.0 and ETIM Modelling Classes (through the bSDD API) | ODC-By 1.0 | parameter names, ports (`connectors`) and features for MEP products |
| 5 | Dimension tables: FreeCAD `profiles.csv` (steel and timber sections), the `fluids` library (pipe schedules), the ADA Standards (clearances) | LGPL-2.1, MIT, public | real `params` defaults and ranges, and `keepout` clearances |

Sources 1, 2 and 5 can be read by a script that writes a lookup table next to the library. Sources 3
and 4 also need a person to confirm each match between a brick and a row.

## What not to ship

- **BIMobject, bimstore, NBS Source**: their terms forbid copying, redistribution, or use in a product.
- **OmniClass, MasterFormat, UniFormat, CoClass, ECLASS**: licensed; keep their codes out of the library.
- **CC BY-ND sources** (IFC, Uniclass): ship the original files unmodified and build lookups from them.
  Whether a filtered extract counts as a derivative is a legal question that is still open.

## Gaps

No open source was found for typical sizes of large equipment (air handling units, chillers, boilers,
switchboards, transformers), rectangular ducts, cable tray widths, radiators, escalators, glulam and
CLT, or standard door and window sizes. Bricks for these use typical manufacturer sizes and say so in
their description.
