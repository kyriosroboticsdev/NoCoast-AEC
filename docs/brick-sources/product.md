# Product, family and dimension data sources for the brick library

Research date: 2026-09-27. Scope: Revit side, product portals, and dimension tables.

## How to read this report

- **Verified** means I fetched the page, file or API response and read the fact there. Everything else is marked **unverified**.
- Most web pages were read through a fetch tool that summarises the page. Numbers quoted from web pages should be re-checked against the page before they are committed as brick defaults. Facts taken from raw files and API responses (GitHub raw files, bSDD API, ENERGY STAR API) were read directly.
- Bricks store metres. Almost every source below is in millimetres or inches, so an import step must convert.
- Copyright note that applies throughout: a single standard dimension (a 2x4 is 38 x 89 mm) is a fact and is generally not copyrightable. A compiled table, catalogue or database can be protected (compilation copyright in the US, database right in the EU and UK), and a website's terms of use can forbid copying even where copyright would not. Where a source is a compiled table under restrictive terms, I rate it "reference only" even though the individual numbers are facts.
- Ratings: **use now** (open licence or public data, fetchable by program), **use with care** (usable, but licence is unclear, share-alike, or the data needs checking), **reference only** (read it to sanity-check values, do not copy or redistribute).

## 1. Summary table

| # | Source | What it gives | Format / access | Licence (as verified) | Rating |
|---|---|---|---|---|---|
| R1 | Autodesk revit-ifc (GitHub) | IFC class to Revit category map in code, IFC shared parameter files, certified entity and Pset list | C# source, TXT, JSON over raw.githubusercontent.com | LGPL v2 per README | use now |
| R2 | Revit export mapping tables (osarch fork, jmirtsch/RevitIfcClassMap, OpeningDesign) | Revit category to IFC class and type, tab-delimited | TXT, raw GitHub | jmirtsch: MIT. osarch fork: not separately stated. OpeningDesign: not checked | use with care |
| R3 | Revit API docs, BuiltInCategory | Category enum names | HTML (revitapidocs.com) | Third-party doc site, not checked | reference only |
| R4 | Autodesk Help (type catalogue, shared parameters, part types, door properties, new categories) | File formats and standard parameter names | HTML | Autodesk documentation, licence not checked | reference only |
| R5 | Speckle speckle-sharp | Object schema and Revit category handling | C# source | Apache-2.0 (GitHub API) | reference only |
| O1 | Bonsai IFC project libraries (IfcOpenShell repo) | 9 IFC library files: steel profiles (EU, US, AU), furniture, landscape, demo types | IFC-SPF, raw GitHub | Repo LGPL-3.0, Bonsai GPL-3.0-or-later; no separate data licence found | use with care |
| O2 | FreeCAD BIM `profiles.csv` | 1,268 section profiles in mm | CSV, raw GitHub | LGPL-2.1 (repo) | use now |
| O3 | FreeCAD-library (parts) | About 5 GB of FCStd/STEP parts | Git repo | CC-BY 3.0 per README | use with care |
| O4 | BOLTS | Pipes, I/C/L/Z/hollow profiles, fasteners as YAML tables | `.blt` YAML, raw GitHub | Per file: MIT (pipes), LGPL 2.1+ (profile_i); repo GPL-3.0 per GitHub API | use with care |
| O5 | ETIM Modelling Classes 2025 via bSDD | 586 classes: parametric MEP objects with dimensions, ports, IFC mapping, SVG drawing | REST JSON, no key needed | ODC-By 1.0 | use now |
| O6 | ETIM classification 10.0 / 10.1 via bSDD | Product classes and features | REST JSON | ODC-By 1.0 (9.0 and older: rights reserved) | use now |
| O7 | bSDD IFC 4.3 dictionary | 1,418 classes incl. predefined types, property sets | REST JSON | CC BY-ND 4.0 | use now (names and enums only) |
| O8 | buildingSMART IFC4.x-development (GitHub) | IFC specification source | Markdown, schemas | CC BY-ND 4.0 | reference only |
| O9 | GLDF (Global Lighting Data Format) | Luminaire data format with bounding dimensions | XML schema; examples repo | Format repo MIT; examples repo has no licence | use with care |
| O10 | OSArch community threads | Pointers to libraries | HTML | n/a | reference only |
| P1 | BIMobject | Manufacturer BIM objects | Web, login | Proprietary terms, no redistribution, no AI training | reference only |
| P2 | NBS Source (was NBS National BIM Library) | Generic and manufacturer objects | Web | Site terms forbid scraping and unlicensed commercial use of content | reference only |
| P3 | bimstore | Manufacturer BIM components | Web | Proprietary terms | reference only |
| P4 | MagiCAD Cloud | Over 1 million MEP objects | Web, login | Terms not found | reference only (unconfirmed) |
| P5 | MEPcontent (Trimble) | 614,225 files from 481 manufacturers | Web | Terms page not retrieved | reference only (unconfirmed) |
| D1 | AISC Shapes Database v15.0 as CSV (ambaker1/aisc-csv) | US steel shapes, 80+ columns, SI and US | CSV, raw GitHub | Wrapper MIT; AISC's own terms not confirmed | use with care |
| D2 | Other AISC copies (shinho76, claudioperez, jonsadka) | v16.0 XLSX, v15.0 JSON/CSV | GitHub | No licence on the repos | reference only |
| D3 | `fluids` Python library, `piping.py` | Pipe schedules (ASME B36.10M, B36.19M, plastics) in mm | Python lists, raw GitHub or `pip` | MIT | use now |
| D4 | Wikipedia tables | NPS pipe, rebar, lumber, bricks, blocks, copper tube, EMT conduit, doors, kitchens, parking, lanes, stairs, kerbs, sprinklers | HTML, MediaWiki API | CC BY-SA 4.0 | use with care |
| D5 | ADA Standards (US Access Board) | Accessibility clearances, doors, ramps, stairs, parking, sanitary, elevator cars | HTML | US federal site; no explicit statement found | use now |
| D6 | UK Approved Documents (gov.uk) | Stairs, ramps, guarding | PDF | Open Government Licence v3.0 | use now |
| D7 | NREL SAM libraries | PV module length and width (m), inverters, wind turbines | CSV, raw GitHub | BSD-3-Clause (repo) | use now |
| D8 | ENERGY STAR product data | Appliance, water heater, UPS, room AC dimensions | Socrata JSON API, no key needed | US EPA data; licence not confirmed on page | use with care |
| D9 | EPREL (EU energy label registry) | EU product models | API with key | Custom terms: reuse and derivatives allowed, not resale of the data itself | use with care |
| D10 | Engineering ToolBox | Round duct sizes | HTML | No terms found on page | reference only |
| D11 | SCI "Blue Book" | UK steel sections | Web only | "© 2026 SCI, All rights reserved" | reference only |
| D12 | ISO 8100-30, EN 1506, EN 10365, ASME B36.10M, Neufert, Architectural Graphic Standards | Lifts, ducts, sections, pipes, anthropometrics | Paid documents | Copyrighted | reference only |
| D13 | CEC Solar Equipment Lists | PV, inverters, batteries, storage | Web app, Excel | State agency; no dimensions in battery lists | reference only |
| X1 | Wikidata, data.gov | Nothing confirmed | SPARQL timed out; CKAN API returned 404 | n/a | unverified |

## 2. Autodesk Revit

### 2.1 Built-in categories

Source: `https://www.revitapidocs.com/2025/ba1c5b30-242f-5fdc-8ea9-ec3b61e6e722.htm` (fetched). The enumeration has hundreds of members; a web search result states 747 for an older version, and an older stub file I sampled contained 973 `OST_` occurrences. I did not get an exact count for 2025 (**unverified**). Most members are subcategories, tags and line styles, not model categories.

Model categories returned from the 2025 page, grouped by me:

- Architecture (from the 2024 page): `OST_Walls, OST_Floors, OST_Roofs, OST_Ceilings, OST_Doors, OST_Windows, OST_Stairs, OST_Railings, OST_Ramps, OST_Columns, OST_CurtainWallPanels, OST_CurtainWallMullions, OST_Casework, OST_Furniture, OST_FurnitureSystems, OST_GenericModel, OST_Mass, OST_Entourage, OST_Planting, OST_SpecialityEquipment`.
- Structure: `OST_StructuralFraming, OST_StructuralColumns, OST_StructuralFoundation, OST_StructuralTruss, OST_Truss, OST_Rebar, OST_AreaRein, OST_PathRein, OST_FabricReinforcement, OST_FabricAreas, OST_StructConnections, OST_Coupler, OST_StructuralTendons`.
- Mechanical: `OST_DuctCurves, OST_DuctFitting, OST_DuctAccessory, OST_DuctTerminal, OST_FlexDuctCurves, OST_MechanicalEquipment, OST_MechanicalControlDevices, OST_FabricationDuctwork, OST_FabricationHangers`.
- Piping and plumbing: `OST_PipeCurves, OST_PipeFitting, OST_PipeAccessory, OST_FlexPipeCurves, OST_PlumbingFixtures, OST_PlumbingEquipment, OST_FabricationPipework`.
- Fire protection: `OST_Sprinklers, OST_FireProtection, OST_FireAlarmDevices`.
- Electrical and data: `OST_ElectricalEquipment, OST_ElectricalFixtures, OST_LightingFixtures, OST_LightingDevices, OST_CableTray, OST_CableTrayFitting, OST_Conduit, OST_ConduitFitting, OST_Wire, OST_DataDevices, OST_CommunicationDevices, OST_TelephoneDevices, OST_NurseCallDevices, OST_SecurityDevices, OST_AudioVisualDevices, OST_FabricationContainment`.
- Infrastructure: `OST_Roads, OST_BridgeAbutments, OST_BridgePiers, OST_BridgeTowers, OST_BridgeCables, OST_BridgeArches, OST_BridgeDecks, OST_BridgeFoundations, OST_BridgeGirders, OST_BridgeBearings, OST_BridgeFraming, OST_AbutmentFoundations, OST_AbutmentPiles, OST_AbutmentWalls, OST_ApproachSlabs, OST_PierCaps, OST_PierColumns, OST_PierPiles, OST_PierWalls, OST_VibrationManagement, OST_VibrationDampers, OST_VibrationIsolators, OST_ExpansionJoints`.
- Site: `OST_Site, OST_Topography, OST_Parking, OST_Hardscape, OST_Sewer, OST_Property`.
- Other newer categories: `OST_MedicalEquipment, OST_FoodServiceEquipment, OST_VerticalCirculation, OST_Signage, OST_TemporaryStructure`.

Autodesk's "Additional Model Categories" page (`https://help.autodesk.com/cloudhelp/2026/ENU/Revit-WhatsNew/files/GUID-F9280850-2007-42BE-B261-91EF87EF6C73.htm`, fetched) confirms eight categories added in Revit 2022 (Food Service Equipment, Medical Equipment, Fire Protection, Vertical Circulation, Audio Visual Devices, Signage, Hardscape, Temporary Structures) and ten infrastructure categories that accept loadable families (Roads, Abutments, Bearings, Piers, Bridge Framing, Bridge Cables, Bridge Decks, Vibration Management, Expansion Joints, Structural Tendons). It states these "behave as generic models with respect to discipline and visibility/graphics settings".

Caveat: Revit does not publish a category-to-discipline table that I could find. The grouping above is mine. No CSV of categories was found on GitHub; the list has to be scraped from the API docs or dumped from a running Revit.

### 2.2 Standard parameters per category

Revit has no single published table of parameters per category. What I verified:

- **Doors, type parameters** (`https://help.autodesk.com/cloudhelp/2014/ENU/Revit/files/GUID-29905EE0-3D7D-422E-A627-5A7A8AC34D7B.htm`): Construction (Wall Closure, Construction Type, Function); Materials (Door Material, Frame Material); Dimensions (Thickness, Height, Width, Trim Projection Ext, Trim Projection Int, Trim Width, Rough Width, Rough Height); Identity Data (Keynote, Model, Manufacturer, Type Comments, URL, Description, Assembly Code, Assembly Description, Type Mark, Fire Rating, Cost, OmniClass Number, OmniClass Title); IFC (Operation); Analytical (Heat Transfer Coefficient U, Thermal Resistance R, Solar Heat Gain Coefficient, Visual Light Transmittance). The Identity Data group is common to loadable families in general.
- **MEP Part Type per category** (`https://help.autodesk.com/cloudhelp/2019/ENU/Revit-Customize/files/GUID-54F9DD0A-6F46-4B52-8F58-B8FA630F14EA.htm`). This is the nearest Revit equivalent of an IFC predefined type:

| Family category | Part types |
|---|---|
| Air Terminals, Plumbing Fixtures, Sprinklers | Normal |
| Cable Tray Fitting | Channel or Ladder x (Cross, Elbow, Multi Port, Offset, Tee, Transition, Union, Vertical Elbow) |
| Conduit Fittings | Cap, Cross, Elbow, Junction Box Elbow, Multi Port, Tee, Transition, Union |
| Duct Accessories | Attaches To, Breaks Into, Damper |
| Duct Fittings | Cap, Cross, Elbow, Lateral Cross, Lateral Tee, Multi Port, Offset, Pants, Tap - Adjustable, Tap - Perpendicular, Tee, Transition, Union, Wye |
| Electrical Equipment | Equipment Switch, Other Panel, Panelboard, Switchboard, Transformer |
| Electrical Fixtures, Lighting Devices, Nurse Call Devices, Security Devices | Junction Box, Normal, Switch |
| Communication, Data, Fire Alarm, Telephone Devices, Lighting Fixtures | Junction Box, Normal |
| Mechanical Equipment | Breaks Into, EndCap, Inline Sensor, Normal, Valve - Breaks into |
| Pipe Accessories | Attaches To, Breaks Into, End Cap, Inline Sensor, Normal, Sensor, Valve - Breaks Into, Valve Normal |
| Pipe Fittings | Cap, Cross, Elbow, Flange, Lateral Cross, Lateral Tee, Mechanical Coupling, Multi Port, Spud - Adjustable, Spud - Perpendicular, Tee, Transition, Union, Wye |

- **Connectors** (`https://help.autodesk.com/cloudhelp/2018/ENU/Revit-API/Revit_API_Developers_Guide/Discipline_Specific_Functionality/MEP_Engineering/Family_Creation.html`): five connector kinds exist, created by `CreateDuctConnector`, `CreatePipeConnector`, `CreateElectricalConnector`, `CreateCableTrayConnector`, `CreateConduitConnector`. Parameters named on the page: `CONNECTOR_RADIUS`, `RBS_PIPE_FLOW_DIRECTION_PARAM`. System types shown: Supply Hydronic, Return Hydronic.
- **IFC property mapping**: revit-ifc holds the full Revit-parameter to IFC property set mapping in `Source/Revit.IFC.Export/Exporter/ExporterInitializer_PsetDef.cs` (8.3 MB) and `PropertySet/PropertySetEntryMap.cs`, plus per-property calculators (for example `RiserHeightCalculator.cs`, `FireRatingCalculator.cs`). I confirmed the files exist; I did not read them.

Brick mapping: Revit Dimensions group to `params`; Identity Data and IFC group to `properties`; Part Type to `predefined_type` or `tags`; connector kind to `connectors[].kind` (duct to air, pipe to water or gas or drainage, electrical to power, cable tray and conduit to a containment kind), flow direction to `connectors[].direction`.

### 2.3 Type catalogue (.txt) format

Source: `https://help.autodesk.com/cloudhelp/2015/ENU/Revit-Customize/files/GUID-FFA71D72-D4C5-416D-BF65-1757657C3CE9.htm` (fetched).

- Plain text file with the same base name as the `.rfa` family.
- First line declares parameters. The first character of the first line is the delimiter (comma by default). Each declaration is `param_name##type##units`.
- Declarations shown on the page: `##OTHER##` (text, integer, number, yes/no as 1 or 0, and identity data such as Keynote, Model, Manufacturer), `##LENGTH##FEET`, `##AREA##SQUARE_FEET`, `##VOLUME##CUBIC_FEET`, `##ANGLE##DEGREES`, `##SLOPE##SLOPE_DEGREES`, `##CURRENCY##`. A search result from the same help family shows `##LENGTH##MILLIMETERS`.
- Each following line is one type: the type name, then values in declaration order.

```
,Length##length##inches,Width##length##inches,Height##length##inches
36x12x36,36,12,36
```

Brick mapping: one catalogue row is one size of one family. The spread of a column across the rows gives `min` and `max`, and a chosen row gives `default`. A type catalogue converts to brick `params` almost one to one. The catalogues themselves ship with Autodesk or manufacturer content, so the files are not open; only the format is.

### 2.4 Shared parameter file format

Sources: `https://help.autodesk.com/cloudhelp/2018/ENU/Revit-API/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Parameters/Shared_Parameters/Definition_File.html` (fetched) and the raw file `Source/RevitIFCTools/IFC Shared Parameters-RevitIFCBuiltIn.txt` in revit-ifc (fetched).

- Tab-delimited text with three blocks: META, GROUP, PARAM. The real file is UTF-16 with a byte order mark.
- Header lines, read from the revit-ifc file:

```
# This is a Revit shared parameter file.
# Do not edit manually.
*META	VERSION	MINVERSION
META	2	1
*GROUP	ID	NAME
GROUP	2	IFC Properties
*PARAM	GUID	NAME	DATATYPE	DATACATEGORY	GROUP	VISIBLE	DESCRIPTION	USERMODIFIABLE
PARAM	f440bb0c-7518-406c-9b84-1de93ecb2d67	ClassificationCode	TEXT		2	1		1
```

- revit-ifc ships ready-made IFC shared parameter files: `IFC Shared Parameters-RevitIFCBuiltIn_ALL.txt` (about 750 KB), `...-Type_ALL.txt` (about 770 KB) and `IFC4_Shared_Parameters.txt` (290 KB). These list IFC property names with data types, which is a usable vocabulary for brick `properties`.

### 2.5 Revit category to IFC class mapping

- The user-editable export table is `exportlayers-ifc-IAI.txt`, stored under `C:\ProgramData\Autodesk\RVT <version>\` (web search result), tab-delimited. From Revit 2025 the mapping sits inside the IFC export dialog; in 2024 and older it is under File, Export, Options, IFC Options (`https://autodesk.ifc-manual.com/revit/ifc-export-category-mapping`, fetched). Setting the class to "Not Exported" excludes a category.
- File layout, read from two copies: comment header, then `Category <tab> Subcategory <tab> IFC class <tab> IFC type <tab> ...`.
- I could not fetch a pristine Autodesk default file. I fetched three community copies:
  - `https://raw.githubusercontent.com/Moult/revit-ifc/osarch/Install/Program%20Files%20to%20Install/exportlayers-ifc-osarch.txt` (475 lines, 180 main category rows). An OSArch-improved mapping.
  - `https://github.com/jmirtsch/RevitIfcClassMap` (MIT, last push 2020): `RevitIfcExportClassMap.txt` (332 lines, includes bridge categories) and `RevitIfcImportClassMap.txt`.
  - `https://github.com/OpeningDesign/IFCopenHouse_Lantern_Hollow/blob/master/Models/exportlayers-ifc-IAI_modified.txt` (423 lines, a project-modified copy).
- The import direction is in code, under LGPL: `Source/Revit.IFC.Import/Utility/IFCCategoryUtil.cs` in `https://github.com/Autodesk/revit-ifc`. It maps IFC entity (and entity plus predefined type) to a BuiltInCategory. This is the most authoritative mapping I could read, because it is Autodesk's own code. Its header comment says the same table is duplicated in native code.
- Warnings about the community tables: they contain names that are not IFC classes (`IfcAssembly`, `IfcReinforcementMesh`), use type classes where an occurrence class is meant (`IfcValveType`, `IfcLightFixtureType`, `IfcAlarmType`), and map Structural Rebar to `IfcReinforcingMesh`, which looks swapped. Most MEP equipment categories default to `IfcBuildingElementProxy`. Treat these tables as hints, not truth.
- `Install/Program Files to Install/IFCCertifiedEntitiesAndPSets.json` (80 KB) lists the entities and property sets per certified model view, starting with `IFC2X3CV2`.

Rating: revit-ifc **use now** for the mapping logic (LGPL applies to the code; a category name paired with a class name is a fact). Community tables **use with care**.

### 2.6 Speckle

`https://github.com/specklesystems/speckle-sharp`: Apache-2.0, last push 2025-07-11 (GitHub API). It is a schema and converter codebase, not a content library. Category handling is in `Objects/Converters/ConverterRevit/ConverterRevitShared/AllRevitCategories.cs` and `ConnectorRevit/RevitSharedResources/Helpers/Categories.cs`. No dimension data. **Reference only**.

## 3. Open-source and openly licensed libraries

### 3.1 Bonsai (formerly BlenderBIM) IFC project libraries

- URL: `https://github.com/IfcOpenShell/IfcOpenShell/tree/v0.9.0/src/bonsai/bonsai/bim/data/libraries` (listed through the GitHub API; default branch is `v0.9.0`).
- Files and contents (I counted entities by streaming each file):

| File | Size | Contents |
|---|---|---|
| IFC4 Demo Library.ifc | 85 KB | 4 wall types, 3 covering, 3 column, 2 slab, 2 beam, 1 each of ramp, pile, window, door, furniture; 10 material layer sets; 6 profile sets |
| IFC2X3 Demo Library.ifc, IFC4X3 Demo Library.ifc | 142 KB, 85 KB | Same idea for other schemas (not opened) |
| IFC4 EU Steel.ifc | 599 KB | 711 profiles, each as IfcBeamType, IfcColumnType and IfcMemberType. 191 I-shapes, 37 U, 39 L, 6 Z, 220 circular hollow, 218 rectangular hollow. Names such as HEA100 |
| IFC4 US Steel.ifc | 2.2 MB | 2,091 profiles x 3 types. 351 I, 325 T, 72 U, 776 L, 179 CHS, 388 RHS, plus composite profiles. Names such as W44X335 |
| IFC4 AU Steel.ifc | 395 KB | 443 profiles x 3 types. Names such as 610UB125 |
| IFC4 Furniture Library.ifc | 735 KB | 56 IfcFurnitureType, 21 IfcSanitaryTerminalType, 9 IfcElectricApplianceType, 64 IfcSpaceType |
| IFC4 Landscape Library.ifc | 2.0 MB | 66 IfcGeographicElementType (trees) |
| IFC4 Entourage Library.ifc | 126 KB | 2 proxy types (people) |

- Format: IFC-SPF text. Parse with ifcopenshell, which the project already uses. Units in the demo file are metres.
- Licence: GitHub reports LGPL-3.0 for the repository. The README table lists the `bonsai` component as GPL-3.0-or-later. I found no separate licence statement for the `.ifc` data files. **Not confirmed** which applies to the data.
- Risk: furniture type names include "Neufert Single Person Wardrobe", "Neufert Retail Dining Chair" and "ADG Main Bedroom Wardrobe". The dimensions appear to be taken from Neufert and the Australian Apartment Design Guide. The numbers are facts, but do not carry the "Neufert" name into brick names or descriptions.
- Brick mapping: profile entity to extruded-profile geometry and `params` (depth, width, web and flange thickness, fillet radius); type class to `ifc_class` (IfcBeam, IfcColumn, IfcMember); type name to `name` and `tags`.
- Rating: **use with care**. Steel profiles are safe as facts. Ask upstream about the data licence before copying geometry.

### 3.2 FreeCAD BIM workbench

- `profiles.csv`: `https://raw.githubusercontent.com/FreeCAD/FreeCAD/main/src/Mod/BIM/Presets/profiles.csv`, 46 KB, 1,386 lines, 1,268 data rows. Saved as `samples/freecad-profiles.csv`.
- Layout: `Category,Name,Profile class,dimensions...`, all in mm. Profile classes in the header: C circular tube, H (H or I), R rectangular, RH rectangular hollow, U. The data also uses L, T and TSLOT.
- Row counts by category: RHS 312, CHS 168, American Wide Flange 132, UB 80, IPE 75, IS Angle 72, IS Beam 65, IS SHS 58, HEA 48, Eurocode timber 35, UC 31, IS Channel 27, IS RHS 26, HEB 24, HEM 21, IS Tee 21, Aluminium C Channel 20, North America Lumber 18, INP 17, UPE 14, T-slot 4.
- Other preset files in the same folder: `ifc_products_IFC4.json` (380 KB), `ifc_types_IFC4.json`, `pset_definitions.csv` (120 KB), `qto_definitions.csv`, `properties_conversion.csv`. Not opened.
- Licence: LGPL-2.1 (GitHub API). LGPL is written for code; applied to a data file it means keep the notice and keep changes to that file under LGPL. Reading values out into bricks is low risk.
- Rating: **use now**. This is the quickest way to real IPE, HEA, HEB, UB, UC, W and timber sizes.
- FreeCAD-library (`https://github.com/FreeCAD/FreeCAD-library`): README states "All Parts in this repository are licensed under CC-BY 3.0", each part attributed to its author. About 5 GB. Folders include Architectural Parts, Electrical Parts, HVAC, Hydraulics, Pipes and tubes. Geometry files, not parameter tables. **Use with care**, and do not clone it.

### 3.3 BOLTS

- `https://github.com/boltsparts/BOLTS_archive` (last push 2023-05). Data in `data/*.blt`, YAML with tables. Files: `pipes.blt`, `profile_i.blt`, `profile_c.blt`, `profile_l.blt`, `profile_z.blt`, `profile_hollow.blt`, `flanges.blt`, `hex.blt`, `nut.blt`, `washer.blt`, `bearings.blt`, `extrusions.blt`, `batteries.blt` and others.
- Each class carries `parameters.free`, `parameters.defaults`, `parameters.types` (for example `Length (mm)`), `parameters.description`, and `tables` with an index column. `profile_i.blt` includes HEA and BlueScope profiles with columns `h, b, tf, tw, r`.
- Licence: stated per file. `pipes.blt` says MIT; `profile_i.blt` says LGPL 2.1+. GitHub reports GPL-3.0 for the repository as a whole.
- Brick mapping: the structure is close to a brick already. `defaults` to `params.default`, table range to `min` and `max`, `description` to parameter labels.
- Rating: **use with care** (mixed licences, unmaintained).

### 3.4 ETIM Modelling Classes through bSDD

This is the most useful find for MEP.

- Dictionary URI: `https://identifier.buildingsmart.org/uri/etim/etim-mc/2025`. Owner ETIM International, status "Preview", released 2025-01-01, licence **ODC-By 1.0** (read from the API response).
- Fetch:
  - `GET https://api.bsdd.buildingsmart.org/api/Dictionary/v1/Classes?Uri=<dictionary uri>&Limit=1000`
  - `GET https://api.bsdd.buildingsmart.org/api/Class/v1?Uri=<class uri>&IncludeClassProperties=true&IncludeClassRelations=true`
  - Header `Accept: application/json`. No key was needed. Responses are paged, 1,000 at most.
- Size: 586 classes. 485 modelling classes (MC), 55 groups (MG), 46 connection types (CT).
- Connection types include: Pipe end, Pipe sleeve, Pipe flange round, Duct end round, Duct end rectangular, Duct end oval, Duct flange rectangular, Storz.
- Modelling classes include: valves, pumps (inline circulation, multistage centrifugal, block), expansion vessels, boilers and hot water cylinders, wall-mounted gas combination boiler, air and dirt separators, floor drains, rectangular and round air ducts with bends, reducers and branches, fire dampers, sound absorbers, roof fans, grilles, cable trays and cable ladders with bends and tees, wall ducts, underfloor ducts.
- One class read in full, MC000066 "Wall-mounted gas combination boiler" (`samples/bsdd-etim-mc-MC000066.json`):
  - 119 class properties. Each has `name`, `propertyCode` (ETIM feature code such as EF000049), `dataType`, `units` (`mm`), `description`.
  - `propertySet` is used as a port index: "PortCode 0" is the body (Depth and so on); "PortCode 1" to "PortCode 12" are connections (supply, return, cold tap water, hot tap water, fuel, condensate, expansion, circulation, air supply, flue), each with nominal diameter and outer pipe diameter.
  - `classRelations` links to ETIM class EC011396 and to **IfcUnitaryEquipment** in IFC 4.3. `relatedIfcEntityNames` is populated.
  - `visualRepresentationUri` points to a dimensioned drawing: `https://cdn.etim-international.com/drawings/MC000066_3.svg`.
- What it lacks: values. ETIM MC defines which parameters and ports a product has. It holds no product instances, so it gives no defaults or ranges. Those must come from another source or from judgement.
- Brick mapping: `relatedIfcEntityNames` to `ifc_class`; PortCode 0 length properties to `params` names; PortCode n groups to `connectors` (kind inferred from the property name, size from the diameter property); ETIM codes to `properties` and `tags`; the SVG to a modelling guide for the geometry tree.
- Licence detail (`https://www.etim-international.com/classification/license-info/`, fetched): ODC-By 1.0 allows sharing, derived works and commercial use, with attribution and the licence notice kept.
- Note: bSDD lists ETIM 9.0, 8.0 and 7.0 as "No license (rights reserved)". Use 10.0, 10.1 and MC 2025 only.
- Related: Open UOB (`https://www.openuob.nl/`, fetched) is a Dutch platform that fills ETIM MC templates with manufacturer data. Licence terms not stated on the page.
- Rating: **use now**.

### 3.5 bSDD IFC 4.3 dictionary and the IFC repository

- `https://identifier.buildingsmart.org/uri/buildingsmart/ifc/4.3`, licence CC BY-ND 4.0 (API response). 1,418 classes; predefined types appear as child classes, for example `IfcUnitaryEquipmentSPLITSYSTEM`. IfcUnitaryEquipment returned 201 properties across sets such as `Pset_UnitaryEquipmentTypeCommon`, `Pset_ElementSize` (Nominal Height, Length, Width) and `Pset_ElectricalDeviceCommon`.
- Long child codes are truncated in the list response (`IfcMobileTelecommunicationsApplianceBASETRANSCEIVE`). Use the class URI, not the code, to recover the predefined type.
- `https://github.com/buildingSMART/IFC4.x-development` (branch `ifc4.3-main`): `LICENSE.md` states CC BY-ND 4.0. The copyright notice adds that the documentation "may be photocopied, used in software development, or translated into another computer language without prior written consent ... provided that full attribution is given".
- No-derivatives means: do not publish a modified copy of the specification. Using class names, enum values and property names inside bricks is ordinary use of the standard.
- The project targets IFC4. IFC 4.3 classes must not leak into `ifc_class`; see section 7.
- Rating: **use now** for names and enums; **reference only** for descriptive text.

### 3.6 GLDF

- `https://github.com/globallightingdata/gldf`: MIT, by DIAL and RELUX. README says about 90% complete and "still volatile". Supports simple geometry (cuboid or cylinder with length, width, height or diameter), mounting definitions and "optional use of all ~350 ZVEI BIM properties (CEN/TS 17623)".
- `https://github.com/globallightingdata/examples`: real luminaire examples, last push 2026-04. No licence on the repo.
- Brick mapping: housing width, length, height to `params`; mounting type to `mount` (ceiling, wall, pendant); photometric and electrical data to `properties`.
- Rating: **use with care**. Good schema for luminaire bricks, no open bulk catalogue.

### 3.7 OSArch pointers

- `https://community.osarch.org/discussion/685/open-free-ifc-repository-for-building-components` (fetched) lists portals offering IFC downloads: National BIM Library, Hilti CADclick, Polantis, BIMstore, BIM and Co, MepContent, Bimetica, BCB Online. These are portals, not openly licensed libraries. Participants proposed CC0 for steel profiles and CC-BY for other components.
- `https://community.osarch.org/discussion/524/profile-section-libraries-for-structural-engineering-and-beyond` (fetched) lists BOLTS, FreeCAD profiles, Strupy (GPL), StructPy (MIT), OpeningDesign/BIM_Profiles and the "Profili" spreadsheet from the University of Brescia. I did not open the last four.

### 3.8 Open Revit family libraries

I found no openly licensed library of `.rfa` families. A GitHub search for IFC object libraries returned only small projects. One, `woodfine/woodfine-bim-library` (Apache-2.0), holds a few 2 KB furniture IFC files named after Steelcase and Coalesse products; too small and too brand-specific to use.

## 4. Commercial and free-to-use portals

All confirmed as reference only, or unconfirmed and treated as reference only.

| Portal | Data held | Terms (verified text) |
|---|---|---|
| BIMobject | Manufacturer objects. Category page returned 403, so counts are unverified | Terms of Service effective 2025-06-24, `https://business.bimobject.com/terms-of-service-eula`. 4.3: "non-exclusive, non-sublicensable and non-transferable right to access and use the Services". 4.7 forbids: (f) "rent, lease, distribute, sell, sublicense, transfer or provide access to the Services to a third party"; (g) "incorporate any Services into a product or service you provide to a third party"; (j) "use any Content ... to train or otherwise improve or enhance any artificial intelligence, machine learning, large language models"; (k) use "for competitive analysis or to build competitive products or services". 8.1: no ownership transfers |
| NBS Source | Generic and manufacturer objects. Category counts on the page: doors, windows and hatches 2,158; plumbing fixtures and accessories 3,475; general building products 1,770. Plug-ins for Revit, Archicad, Bentley, Vectorworks | The old terms URL redirects to NBS Source. The library page says "All are free to download and use in your projects". The general site terms at `https://www.thenbs.com/terms-and-conditions` (operator Hubexo) forbid "text or data mining or web scraping" and commercial use of content without a licence. Object-specific terms were **not retrieved**. A search result quoted the older library terms as forbidding sub-licensing and limiting reproduction to individual objects, not "a material proportion" |
| bimstore | Manufacturer components | `https://www.bimstore.co/terms-and-conditions`, operator BIMSTORE LIMITED. Download allowed for non-commercial personal use, education, or "inclusion in any drawings or contract documents used ... in connection with a building contract". "you may not use, copy, decompile, disassemble, adapt, merge, translate, reverse engineer, or in any way modify BIM components, nor make available BIM components in any form". No use to build a competing or similar service |
| MagiCAD Cloud | Over 1 million objects, more than 100,000 downloadable; RFA and DXF; manufacturer-verified dimensions and technical data; free subscription (`https://www.magicad.com/cloud/for-designers/faq/`, page served in Swedish) | Terms **not found** |
| MEPcontent | 614,225 files, 481 manufacturers; RFA, DWG, IFC; operator Trimble Europe BV (`https://www.mepcontent.com/en/`) | The terms URL I tried returned 404. **Not confirmed** |
| Manufacturer portals | Not researched individually | Assume proprietary |

Conclusion: read these portals by hand to check that a brick's dimensions are realistic. Do not download in bulk, do not copy geometry, and do not use their content to train or tune models. The third point matters for this project because it has an LLM in the loop.

## 5. Dimension tables by discipline

### 5.1 Structure

**Steel sections, US (AISC)**

- `https://github.com/ambaker1/aisc-csv` (MIT for the repository). `v15.0/Shapes-SI.csv` (442 KB) and `Shapes-US.csv` (445 KB). Header sample saved as `samples/aisc-csv-SI-head.csv`.
- Columns (84): `EDI_Std_Nomenclature, AISC_Manual_Label, Type, T_F, W, A, d, ddet, Ht, h, OD, bf, bfdet, B, b, ID, tw, twdet, tf, tfdet, t, tnom, tdes, kdes, kdet, k1, ... Ix, Zx, Sx, rx, Iy, Zy, Sy, ry, J, Cw, ...`. First row: `W1100X499, type W, W=499, A=63500, d=1120, bf=404, tw=26.2, tf=45`.
- The README reproduces AISC's disclaimer, which is about liability and says nothing about redistribution.
- AISC's own page returned 403 to the fetch tool, and a second attempt landed on a different page. **AISC's terms for the database were not confirmed.** AISC's site has a "Copyright Permissions" page, which I did not read.
- v16.0: `shinho76/section_database` holds `source/aisc-shapes-database-v160-2.xlsx` (2.0 MB) and its README says 2,299 sections. It also holds Korean KS section text files and states rebar #3 to #18 data. No licence. `claudioperez/aisc` has v15.0 as JSON (4.4 MB), no licence. `jonsadka/steel-explorer` has a 114 KB CSV, no licence.
- Rating: aisc-csv **use with care**; the others **reference only**. Safer route: take US W-shapes from FreeCAD `profiles.csv` (132 rows) or the Bonsai US Steel library (2,091 profiles).

**Steel sections, Europe, UK, Australia, India**

- FreeCAD `profiles.csv` and Bonsai EU and AU Steel, as above.
- SCI Blue Book (`https://www.steelforlifebluebook.co.uk/`): UB, UC, bearing piles, channels, angles, tees, hollow sections, to Eurocode 3 and BS 5950. Web tables only, no download found, "© 2026 SCI, All rights reserved". **Reference only**.
- EN 10365 defines the European series (search result only, **unverified**). Paid standard.

**Rebar** (`https://en.wikipedia.org/wiki/Rebar`, fetched): tables for US imperial (#2 to #18), Canadian metric (10M to 55M), European metric (6 to 50 mm), Australian, New Zealand, India. Values read: #3 = 9.53 mm, #4 = 12.7 mm, #5 = 15.9 mm, #8 = 25.4 mm. European 8 mm = 50.3 mm2 and 0.395 kg/m; 12 mm = 113 mm2 and 0.888 kg/m; 16 mm = 201 mm2 and 1.58 kg/m; 20 mm = 314 mm2 and 2.47 kg/m; 25 mm = 491 mm2 and 3.85 kg/m; 32 mm = 804 mm2 and 6.31 kg/m. No open CSV or JSON of rebar sizes was found on GitHub.

**Timber**

- Dimensional lumber (`https://en.wikipedia.org/wiki/Lumber`, fetched), nominal to actual in mm: 2x2 = 38x38, 2x3 = 38x64, 2x4 = 38x89, 2x6 = 38x140, 2x8 = 38x184, 2x10 = 38x235, 2x12 = 38x286, 4x4 = 89x89, 4x6 = 89x140, 6x6 = 140x140, 8x8 = 191x191. One-inch boards are 19 mm thick.
- FreeCAD `profiles.csv` has 18 North America Lumber rows and 35 Eurocode timber rows.
- Glulam: no open table found. **Unverified.**
- CLT (`https://en.wikipedia.org/wiki/Cross-laminated_timber`, fetched): at least three layers, usually an odd number; the page gives no standard panel sizes. Manufacturer data would be needed. **Unverified.**

**Precast hollow-core** (`https://en.wikipedia.org/wiki/Hollow-core_slab`, fetched): typically 120 cm wide, standard thickness 15 to 50 cm; extruded elements 600 to 2400 mm wide, 150 to 500 mm thick, up to 24 m long. The page's "up to 200 meters" refers to the casting bed, not a slab.

**Masonry**

- Bricks (`https://en.wikipedia.org/wiki/Brick`, fetched), mm: UK 215 x 102.5 x 65; US 194 x 92 x 57; Germany 240 x 115 x 71; Australia 230 x 110 x 76; India 228 x 107 x 69; Russia 250 x 120 x 65; Sweden 250 x 120 x 62; South Africa 222 x 106 x 73; Japan 210 x 100 x 60; Denmark 228 x 108 x 54; China 240 x 155 x 53 as returned, which looks wrong (the usual figure is 240 x 115 x 53) and must be checked.
- Concrete blocks (`https://en.wikipedia.org/wiki/Concrete_block`, fetched): US nominal 16 x 8 in face, actual 3/8 in less, in 4, 6, 8 and 12 in thicknesses; UK and Ireland 440 x 215 x 100 mm; Australia, New Zealand, Canada 390 x 190 x 190 mm.

### 5.2 MEP

**Steel and plastic pipe: `fluids`** (best source)

- `https://raw.githubusercontent.com/CalebBell/fluids/master/fluids/piping.py`, MIT (GitHub API), last push 2026-09-15.
- Python lists per schedule: `NPS40` (nominal sizes), `S40i` (inner diameter, mm), `S40o` (outer diameter, mm), `S40t` (wall, mm). Present for schedules 5, 10, 20, 30, 40, 60, 80, 100, 120, 140, 160, STD, XS, XXS, stainless 5S, 10S, 40S, 80S, and plastics to ASTM D1527, D2680, AWWA C900 and C905.
- Sample read from the file: NPS 1/2 Sch 40 OD 21.3, wall 2.77, ID 15.76; NPS 2 OD 60.3, wall 3.91; NPS 4 OD 114.3, wall 6.02; NPS 12 OD 323.8, wall 10.31.
- Fetch: `pip install fluids` and import the lists, or parse the raw file.
- Brick mapping: pipe brick `params.outer_diameter` and `wall_thickness` with `min` and `max` from the ends of the list; nominal size as a property; connector size from OD.
- Rating: **use now**.

**NPS and DN cross-check** (`https://en.wikipedia.org/wiki/Nominal_Pipe_Size`, fetched): tables from NPS 1/8 to NPS 36 and beyond, columns NPS, DN, OD in inches and mm, wall by schedule. NPS 1/2 = DN 15, 21.34 mm; NPS 1 = DN 25, 33.40 mm; NPS 2 = DN 50, 60.33 mm; NPS 4 = DN 100, 114.30 mm; NPS 12 = DN 300, 323.85 mm. A search result noted that one commercial site refuses bulk CSV download because the ASME table is copyrighted; this is the compiled-table risk in practice.

**Copper tube** (`https://en.wikipedia.org/wiki/Copper_tubing`, fetched): US types K, L, M with nominal 1/4 to 3 in; OD is nominal plus 1/8 in (1/2 nominal = 5/8 OD, 1 = 1-1/8, 2 = 2-1/8). EN 1057 outside diameters: 8, 10, 15, 22, 28, 35, 42, 54, 66.7, 76.1, 108 mm.

**PEX**: the Wikipedia page has no size table. **Unverified.**

**Ducts**

- Round, metric: 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250 mm (`https://www.engineeringtoolbox.com/circular-ducts-d_1009.html`, fetched; the page does not name the standard). A search result attributes this series to EN 1506, with wall thickness covered by EN 12237. I did not read the standard.
- Round, imperial (`https://en.wikipedia.org/wiki/Duct_(flow)`, fetched): stock sizes 4 to 24 in, 6 to 12 in most common; flexible duct 4 to 18 in; rectangular duct commonly in 4 ft sections.
- Rectangular standard sizes (EN 1505, SMACNA): **unverified**, no open table found.

**Conduit** (`https://en.wikipedia.org/wiki/Electrical_conduit`, fetched): EMT table with trade size 1/2 to 4 in, metric designator 16 to 103. 1/2 in: OD 17.9 mm, wall 1.07 mm; 3/4 in: OD 23.4 mm, wall 1.25 mm; 4 in: OD 114.3 mm, wall 2.11 mm. No table for RMC, IMC or metric conduit.

**Cable tray** (`https://en.wikipedia.org/wiki/Cable_tray`, fetched): types are solid-bottom, ventilated, ladder, wire mesh, channel. Ladder rung spacing 100 to 300 mm. No widths given. Standard widths: **unverified**. ETIM MC has classes for cable tray, ladder, bends and tees, which give the parameter set.

**Sprinklers** (`https://en.wikipedia.org/wiki/Fire_sprinkler`, fetched): temperature classes. Ordinary 57 to 77 C (uncoloured or black), Intermediate 79 to 107 C (white), High 121 to 149 C (blue), Extra High 163 to 191 C (red), Very Extra High 204 to 246 C (green), Ultra High 260 to 302 C (orange). Good for `properties`. K-factors, thread sizes and spacing: **unverified** (NFPA 13, copyrighted).

**Radiators** (`https://en.wikipedia.org/wiki/Radiator_(heating)`, fetched): explains type codes (first digit is panels, second is fin sets, so Type 21 is two panels and one fin set). No dimensions. **Unverified.**

**Appliances, water heaters, UPS, room air conditioners: ENERGY STAR**

- Socrata API at `https://data.energystar.gov`. Catalogue: `/api/views.json` (90 datasets). Data: `/resource/<id>.json?$limit=...`. Count: `?$select=count(*)`. No key was needed.
- Datasets with dimension fields (field names and row counts read from the API):

| Dataset id | Name | Rows | Dimension fields |
|---|---|---|---|
| p5st-her9 | Residential Refrigerators | 4,830 | height_in, width_in, capacity_total_volume_ft3 |
| q8py-6w3f | Residential Dishwashers | 756 | width_inches, depth_inches |
| bghd-e2wd | Residential Clothes Washers | 412 | height_inches, width_inches, depth_inches, volume_cubic_feet |
| 5xn2-dv4h | Room Air Conditioners | 515 | height_inches, width_inches, depth_inches, weight_lbs, cooling_capacity_btu_hour |
| pbpq-swnu | Water Heaters | 1,252 | tank_height_inches, tank_diameter_inches, storage_volume_gallons |
| ifxy-2uty | Uninterruptible Power Supplies | 923 | height_mm, width_mm, depth_mm |

- Datasets without dimensions: Air-Source Heat Pumps (w7cv-9xjt, 283,901 rows, capacities only), Boilers (6rww-hpns, 658 rows, 13 fields), EV Supply Equipment AC (5jwe-c8xm, 475 rows, only `output_cord_length_ft`). Light Commercial HVAC, Furnaces, Geothermal Heat Pumps and Commercial Boilers exist but I did not check their fields.
- Licence: US EPA programme data. No licence statement was confirmed on a fetched page. Brand and model numbers are in the data; do not put them in bricks.
- Use: compute percentile ranges per product class to get `default`, `min`, `max` for generic bricks. Capacity to `properties`. Maps to IfcElectricAppliance (REFRIGERATOR, DISHWASHER, WASHINGMACHINE), IfcElectricFlowStorageDevice (UPS), IfcUnitaryEquipment (room air conditioner), IfcTank or IfcBoiler (water heater).
- Rating: **use with care**.

**PV modules: NREL SAM**

- `https://github.com/NatLabRockies/SAM` (redirected from NREL/SAM), BSD-3-Clause, folder `deploy/libraries`.
- `CEC Modules.csv` (6.3 MB): `Name, Manufacturer, Technology, Bifacial, STC, PTC, A_c, Length, Width, N_s, ...`, with a units row (`m2, m, m`). Example row: a 270 W mono-c-Si module, Length 1.64 m, Width 0.992 m, 60 cells. Already in metres.
- Also `CEC Inverters.csv` (390 KB), `Wind Turbines.csv` (165 KB), `SRCC Collectors.csv` (43 KB). Not opened.
- The module data originates from the California Energy Commission lists. CEC's page (`https://www.energy.ca.gov/programs-and-topics/programs/solar-equipment-lists`, fetched) says lists update three times a month and that CEC makes "no claim or warranty". It does not indicate dimensions for batteries or storage systems.
- Brick mapping: IfcSolarDevice with predefined type SOLARPANEL; `params.length` and `params.width`; rated power to `properties`; DC power connector out.
- Rating: **use now** for aggregate ranges. The file is 6 MB, so stream it and keep only statistics.

**EU products: EPREL**

- `https://energy-efficient-products.ec.europa.eu/eprel_en` (fetched): EU registry of energy-labelled products, including heating equipment, lighting, refrigeration, displays.
- API terms PDF (fetched and text-extracted): the API gives "access to public data for models registered in EPREL. The API key is provided separately." Rights granted include "to reproduce, share and distribute the Data for commercial and non-commercial purposes ... but not commercialize or sell the data per se", to create a derivative work, and to do research. Attribution is required. A search result said CC BY 4.0; I did not find those words in the PDF text I extracted.
- Whether entries carry external dimensions: stated in a search result, **not confirmed** on a fetched page.
- Rating: **use with care**. Needs a key request first.

**No open structured source confirmed** for: air handling units, fan coils, chillers, boilers and heat pumps (envelope sizes), hydrants, electrical panels and switchboards, transformers, battery storage, EV chargers, rectangular ducts, cable tray widths, radiators. For these, take the parameter set and ports from ETIM MC and ETIM 10, take the class and predefined type from IFC4, and set dimensions by reading manufacturer catalogues as reference only. Mark such bricks as "typical, not sourced".

### 5.3 Architecture and interior

**Accessibility: ADA Standards** (best source for clearances)

Pages fetched: `https://www.access-board.gov/ada/` and chapters `ch03`, `ch04`, `ch05`, `ch06` under `https://www.access-board.gov/ada/chapter/`. The pages carry no explicit copyright or public-domain statement. Works of the US federal government are generally not subject to US copyright; I did not verify that on the site.

| Item | Section | Value |
|---|---|---|
| Clear floor space | 305.3 | 760 x 1220 mm min |
| Turning space, circular | 304.3.1 | 1525 mm diameter min |
| Turning space, T-shaped | 304.3.2 | 1525 mm square, arms and base 915 mm wide min |
| Knee and toe clearance width | 306.2.5, 306.3.5 | 760 mm min |
| Reach range | 308.2.1, 308.3.1 | 380 mm min to 1220 mm max |
| Protruding objects | 307.2 | 100 mm max between 27 and 80 in high |
| Headroom | 307.4 | 2030 mm min |
| Accessible route width | 403.5.1 | 915 mm min |
| Door clear width | 404.2.3 | 815 mm min |
| Ramp slope | 405.2 | 1:12 max |
| Ramp clear width | 405.5 | 915 mm min |
| Ramp rise per run | 405.6 | 760 mm max |
| Ramp landing length | 405.7.3 | 1525 mm min |
| Kerb ramp flare | 406.3 | 1:10 max |
| Car parking space | 502 | 2440 mm wide min |
| Van parking space | 502 | 3350 mm wide min, or 2440 with a 2440 aisle |
| Access aisle | 502 | 1525 mm wide min |
| Van vertical clearance | 502 | 2490 mm min |
| Passenger loading zone | 503 | 2440 x 6100 mm min |
| Stair riser | 504 | 100 to 180 mm |
| Stair tread | 504 | 280 mm min |
| Handrail height | 505 | 865 to 965 mm |
| Handrail diameter | 505 | 32 to 51 mm |
| Handrail wall clearance | 505 | 38 mm min |
| Drinking fountain spout | 602.4 | 915 mm max |
| WC clearance | 604.3.1 | 1525 mm from side wall, 1420 mm from rear wall |
| WC seat height | 604.4 | 430 to 485 mm |
| WC centreline from side wall | 604.2 | 405 to 455 mm |
| Grab bar height | 609.4 | 840 to 915 mm |
| Urinal rim | 605.2 | 430 mm max, 345 mm deep min |
| Lavatory rim | 606.3 | 865 mm max |
| Transfer shower | 608.2.1 | 915 x 915 mm |
| Roll-in shower | 608.2.2 | 760 x 1525 mm min |

Elevator cars, table 407.4.1 (inches, minimum):

| Door location | Door width | Side to side | Back wall to front return | Back wall to door |
|---|---|---|---|---|
| Centred | 42 | 80 | 51 | 54 |
| Side (off-centred) | 36 | 68 | 51 | 54 |
| Any | 36 | 54 | 80 | 80 |
| Any | 36 | 60 | 60 | 60 |

Brick mapping: these are mostly `clearances` (keep-out volumes) and `params.min` or `params.max`, not defaults. Put the section number in `properties` as the source reference. Rating: **use now**.

**UK Approved Documents**: Approved Document K (`https://www.gov.uk/government/publications/protection-from-falling-collision-and-impact-approved-document-k`, fetched) is a 2.0 MB PDF covering stairs, ladders, ramps, guarding and vehicle barriers. The page states "All content is available under the Open Government Licence v3.0, except where otherwise stated". OGL allows commercial reuse with attribution. I did not open the PDF. UK values via Wikipedia (`https://en.wikipedia.org/wiki/Stairs`, fetched): rise 150 to 220 mm, going 220 to 300 mm, max pitch 42 degrees, 2R + G between 550 and 700 mm, headroom 2000 mm, guarding at least 900 mm. Check against the PDF before use. Rating: **use now**.

**Stairs, US values via Wikipedia** (same page): 2R + T = 625 mm; tread min 254 mm in residences; handrail 864 to 965 mm; headroom at least 2110 mm; adjacent-step variance 4.76 mm max. The IBC itself is ICC copyright: **reference only**.

**Doors** (`https://en.wikipedia.org/wiki/Door`, fetched): US widths 18, 24, 26, 28, 30, 36 in; heights 78 or 80 in; thickness 1-3/8 in interior, 1-3/4 in exterior. Germany (DIN 18101): most common 860 x 1985 mm; 1985 series widths 610, 735, 860, 985, 1110; 2014 edition ranges 485 to 1360 wide and 1610 to 2735 high in 125 mm steps. UK 762 x 1981. Australia 820 x 2040. South Africa 813 x 2032. India 800 x 2045 internal.

**Windows**: no source fetched. **Unverified.**

**Kitchens** (`https://en.wikipedia.org/wiki/Kitchen_cabinet`, fetched): Europe: 720 mm carcass + 150 mm plinth + 40 mm worktop = 910 mm; widths in multiples of 100 mm with 600 mm common; depth 600 mm. North America: base 875 mm high and 610 mm deep, worktop 915 mm, wall cabinets 300 mm deep and typically 760 mm high, 460 mm between worktop and wall cabinet.

**Lifts**: ISO 8100-30:2019 "Class I, II, III and VI lifts installation" replaces ISO 4190-1:2010 and gives the dimensions needed for installation; not applicable above 6.0 m/s (search results only; the ISO page returned 403). Paid standard: **reference only**. The Wikipedia Elevator page has no car size table. Use ADA table 407.4.1 for minimum accessible car sizes. IFC4 class: IfcTransportElement, type ELEVATOR.

**Escalators** (`https://en.wikipedia.org/wiki/Escalator`, fetched): incline 30 or 35 degrees, speed 0.3 to 0.9 m/s, rises over 18 m possible. No step width table on the page. Step widths: **unverified**.

**Sanitary fixtures**: only the ADA mounting heights and clearances above. Fixture body sizes: **unverified**. The Bonsai furniture library has 21 IfcSanitaryTerminalType entries to inspect.

**Furniture and anthropometrics**: Neufert "Architects' Data" and "Architectural Graphic Standards" are copyrighted books. I did not fetch them. **Reference only.** See the Neufert naming warning in section 3.1.

### 5.4 Site, civil, transport

**Parking** (`https://en.wikipedia.org/wiki/Parking_space`, fetched): US width 2.6 to 2.7 m, length 4.9 to 6.1 m, parallel 6.1 to 7.3 m; UK 2.4 x 4.8 m with 2.6 x 5.0 m proposed; Australia (AS 2890) 2.4 x 5.4 m; France minimum width 2.20 to 2.30 m. No aisle widths. Accessible bays from ADA 502.

**Lanes** (`https://en.wikipedia.org/wiki/Lane`, fetched): general range 2.7 to 4.6 m; US Interstate 3.7 m; Europe minimum 2.5 to 3.25 m; German Bundesstrasse 3.5 m; Autobahn 3.75 m. Truck width limits 2.59 m (US) and 2.55 m (Europe). The FHWA lane width page returned 403: **unverified**.

**Kerbs** (`https://en.wikipedia.org/wiki/Curb`, fetched): reveal 100 to 200 mm, total height often 406 mm, gutter 610 mm, UK high containment kerb 360 mm. Standard unit sizes (BS EN 1340): **unverified**.

**Manholes** (`https://en.wikipedia.org/wiki/Manhole`, fetched): spacing figures only; no diameters or depths. **Unverified.**

**Rail** (`https://en.wikipedia.org/wiki/Rail_profile`, fetched): masses of 40, 50 and 60 kg/m for Europe, as a list. No table of profile dimensions. EN 13674-1 is named. **Unverified** beyond that.

**Street furniture, bridge components**: no dimension source found. **Unverified.**

**IFC 4.3 classes for infrastructure** (bSDD, verified): IfcBridge, IfcBridgePart (ABUTMENT, DECK, PIER, PYLON, FOUNDATION and others), IfcBearing (CYLINDRICAL, DISK, ELASTOMERIC, GUIDE, POT, ROCKER, ROLLER, SPHERICAL), IfcRail (BLADE, CHECKRAIL, GUARDRAIL, RACKRAIL, RAIL, STOCKRAIL), IfcKerb, IfcPavement (FLEXIBLE, RIGID), IfcCourse, IfcRoad, IfcEarthworksCut, IfcMooringDevice, IfcNavigationElement, IfcImpactProtectionDevice, IfcConveyorSegment, IfcLiquidTerminal. My list response held the first 1,000 of 1,418 classes, so classes I did not see (IfcTrackElement, IfcSign, IfcSignal) may still exist. None of IfcBearing, IfcKerb, IfcRail, IfcPavement, IfcCourse is in the IFC4 schema dump in `samples/ifc4_element_predefined_types.json` (a file produced by another task). Under the current IFC4 rule, bridge and rail bricks must use IfcCivilElement, IfcBuildingElementProxy, or structural classes.

## 6. Open datasets on GitHub, Wikidata, data.gov

GitHub repository search, run through the API on 2026-09-27:

| Query | Result |
|---|---|
| AISC shapes database | 4 repos. `ambaker1/aisc-csv` (MIT), `paddymills/aisc-shapes-rs` (MIT, not opened), `runtosolve/ShapesAISC` and `softwarebyze/find-a-beam` (no licence) |
| steel sections json; european steel profiles csv; steel section database IPE HEA | Nothing useful. European sections exist only inside FreeCAD, BOLTS and Bonsai |
| pipe schedule dimensions | `EngineeringUniversity/Schedule.Pipe.Dimensions` (GPL-3.0, 0 stars, not opened). `fluids` is the better source |
| revit categories ifc mapping | `jmirtsch/RevitIfcClassMap` (MIT) |
| rebar sizes json | Nothing |
| lumber sizes json | `mark-brannan/xylarium` (Apache-2.0): wood species properties in `data/species.json`; lumber sizes not seen in the tree |
| duct sizes standard | Calculator apps only, no tables |
| revit family categories list csv | Nothing. Only API stubs such as `gtalarico/ironpython-stubs` (old) |

- **Wikidata**: a SPARQL count of items with width and height timed out. I confirmed nothing. My expectation, unverified, is that Wikidata holds little product dimension data. Low priority.
- **data.gov**: the CKAN endpoint `https://catalog.data.gov/api/3/action/package_search` returned 404, so I could not search it. The ENERGY STAR Socrata API above is the federal open data that proved useful.

## 7. Revit category to IFC class to brick discipline

Column meanings:

- **Export class**: from the community mapping tables `exportlayers-ifc-osarch.txt` and `RevitIfcExportClassMap.txt`, corrected only where the file used a name that is not an IFC class (noted). These are not Autodesk's pristine defaults.
- **Imports from**: IFC classes that Autodesk's `IFCCategoryUtil.cs` places into this category. Verified in source.
- **Suggested brick class**: my recommendation, checked against the IFC4 schema dump. Not from a source.
- A dash means no entry was found in the files I read.

### Architecture and interior

| Revit category | BuiltInCategory | Export class (community tables) | Imports from (revit-ifc) | Suggested brick ifc_class | Brick discipline |
|---|---|---|---|---|---|
| Walls | OST_Walls | IfcWall | IfcWall, IfcCurtainWall | IfcWall | architecture |
| Doors | OST_Doors | IfcDoor | IfcDoor | IfcDoor | architecture |
| Windows | OST_Windows | IfcWindow | IfcWindow | IfcWindow | architecture |
| Floors | OST_Floors | IfcSlab | IfcSlab.FLOOR, IfcCovering.FLOORING | IfcSlab, IfcCovering | architecture |
| Roofs | OST_Roofs | IfcRoof | IfcRoof, IfcSlab.ROOF, IfcCovering.ROOFING | IfcRoof, IfcSlab | architecture |
| Ceilings | OST_Ceilings | IfcCovering | IfcCovering.CEILING | IfcCovering (CEILING) | architecture |
| Stairs | OST_Stairs | IfcStair | IfcStair, IfcStairFlight; IfcSlab.LANDING to OST_StairsLandings | IfcStair, IfcStairFlight | architecture |
| Railings | OST_Railings, OST_StairsRailing | IfcRailing | IfcRailing | IfcRailing | architecture |
| Ramps | OST_Ramps | IfcRamp | IfcRamp, IfcRampFlight | IfcRamp | architecture |
| Columns | OST_Columns | IfcColumn | IfcColumn (COLUMN, USERDEFINED, NOTDEFINED) | IfcColumn | architecture |
| Curtain Panels | OST_CurtainWallPanels | IfcCurtainWall | IfcPlate.CURTAIN_PANEL | IfcPlate (CURTAIN_PANEL) | architecture |
| Curtain Wall Mullions | OST_CurtainWallMullions | IfcCurtainWall | IfcMember.MULLION | IfcMember (MULLION) | architecture |
| Curtain Systems | OST_Curtain_Systems (old stub) | IfcCurtainWall | - | IfcCurtainWall | architecture |
| Casework | OST_Casework | IfcFurniture | - | IfcFurniture | interior |
| Furniture | OST_Furniture | IfcFurniture | IfcFurniture, IfcFurnishingElement, IfcSystemFurnitureElement | IfcFurniture | interior |
| Furniture Systems | OST_FurnitureSystems | IfcSystemFurnitureElement | - | IfcSystemFurnitureElement | interior |
| Generic Models | OST_GenericModel | IfcBuildingElementProxy | IfcBuildingElementProxy, IfcCovering, IfcChimney, IfcElementAssembly, IfcFlowTerminal and other abstract or unmapped classes | IfcBuildingElementProxy | any |
| Specialty Equipment | OST_SpecialityEquipment | IfcBuildingElementProxy | IfcElectricAppliance, IfcTank, IfcSensor, IfcController, IfcTransportElement, IfcFlowStorageDevice, IfcDiscreteAccessory, IfcMechanicalFastener | by object | interior, transport |
| Vertical Circulation | OST_VerticalCirculation | - | - | IfcTransportElement (ELEVATOR, ESCALATOR, MOVINGWALKWAY) | transport |
| Food Service Equipment | OST_FoodServiceEquipment | - | - | IfcElectricAppliance | interior |
| Medical Equipment | OST_MedicalEquipment | - | - | IfcMedicalDevice | interior |
| Signage | OST_Signage | - | - | IfcBuildingElementProxy | architecture, site |
| Temporary Structures | OST_TemporaryStructure | - | - | IfcBuildingElementProxy | site |
| Entourage | OST_Entourage | IfcBuildingElementProxy | - | IfcBuildingElementProxy | interior, site |
| Mass | OST_Mass | IfcBuildingElementProxy | - | not a brick | - |
| Parts | OST_Parts | IfcBuildingElementPart | IfcBuildingElementPart | IfcBuildingElementPart | architecture |
| Assemblies | OST_Assemblies (old stub) | IfcElementAssembly | - | IfcElementAssembly | any |

### Structure

| Revit category | BuiltInCategory | Export class (community tables) | Imports from (revit-ifc) | Suggested brick ifc_class | Brick discipline |
|---|---|---|---|---|---|
| Structural Framing | OST_StructuralFraming | IfcBeam (jmirtsch), IfcMember (osarch) | IfcBeam, IfcMember, IfcPlate | IfcBeam, IfcMember | structure |
| Structural Columns | OST_StructuralColumns | IfcColumn | IfcColumn with LoadBearing | IfcColumn | structure |
| Structural Foundations | OST_StructuralFoundation | IfcSlab BASESLAB; IfcFooting in the OpeningDesign copy | IfcFooting, IfcPile, IfcSlab.BASESLAB | IfcFooting, IfcPile | structure |
| Structural Trusses | OST_StructuralTruss | "IfcAssembly" TRUSS (not an IFC class) | - | IfcElementAssembly (TRUSS) | structure |
| Structural Beam Systems | - | "IfcAssembly" BEAMSYSTEM (not an IFC class) | - | IfcElementAssembly | structure |
| Structural Rebar | OST_Rebar | IfcReinforcingMesh (looks swapped) | IfcReinforcingBar | IfcReinforcingBar | structure |
| Structural Area and Path Reinforcement | OST_AreaRein, OST_PathRein | IfcReinforcingBar | - | IfcReinforcingBar | structure |
| Structural Fabric Reinforcement | OST_FabricReinforcement | "IfcReinforcementMesh" (not an IFC class) | - | IfcReinforcingMesh | structure |
| Structural Fabric Areas | OST_FabricAreas | IfcGroup | IfcReinforcingMesh | IfcReinforcingMesh | structure |
| Structural Connections | OST_StructConnections | IfcMechanicalFastener | IfcFastener | IfcMechanicalFastener, IfcFastener | structure |
| Structural Rebar Couplers | OST_Coupler | IfcMechanicalFastener | - | IfcMechanicalFastener | structure |
| Structural Stiffeners | - | IfcPlate | - | IfcPlate | structure |
| Structural Tendons | OST_StructuralTendons | IfcBuildingElementProxy | - | IfcTendon | structure |

### Mechanical (HVAC)

| Revit category | BuiltInCategory | Export class (community tables) | Imports from (revit-ifc) | Suggested brick ifc_class | Brick discipline |
|---|---|---|---|---|---|
| Mechanical Equipment | OST_MechanicalEquipment | IfcBuildingElementProxy | IfcUnitaryEquipment, IfcBoiler, IfcFan, IfcPump, IfcCoil, IfcFilter, IfcHumidifier, IfcSpaceHeater, IfcAirToAirHeatRecovery | IfcUnitaryEquipment, IfcBoiler, IfcChiller, IfcFan, IfcPump, IfcCoolingTower, IfcSpaceHeater | hvac |
| Mechanical Control Devices | OST_MechanicalControlDevices | - | IfcUnitaryControlElement | IfcUnitaryControlElement, IfcSensor, IfcActuator | hvac |
| Air Terminals | OST_DuctTerminal | IfcAirTerminal | IfcAirTerminal | IfcAirTerminal | hvac |
| Ducts | OST_DuctCurves | IfcDuctSegment | IfcDuctSegment, IfcDuctSilencer | IfcDuctSegment | hvac |
| Flex Ducts | OST_FlexDuctCurves | IfcDuctSegment FLEXIBLESEGMENT | - | IfcDuctSegment (FLEXIBLESEGMENT) | hvac |
| Duct Fittings | OST_DuctFitting | IfcDuctFitting | IfcDuctFitting | IfcDuctFitting | hvac |
| Duct Accessories | OST_DuctAccessory | IfcBuildingElementProxy | IfcDamper | IfcDamper, IfcDuctSilencer | hvac |
| Duct Insulations, Duct Linings | - | IfcCovering INSULATION, WRAPPING | - | IfcCovering | hvac |
| MEP Fabrication Ductwork, Hangers | OST_FabricationDuctwork, OST_FabricationHangers | IfcBuildingElementProxy | - | IfcDuctSegment, IfcDiscreteAccessory | hvac |
| HVAC Zones | - | IfcZone | - | not a brick | - |

### Plumbing and piping

| Revit category | BuiltInCategory | Export class (community tables) | Imports from (revit-ifc) | Suggested brick ifc_class | Brick discipline |
|---|---|---|---|---|---|
| Plumbing Fixtures | OST_PlumbingFixtures | IfcFlowTerminal (abstract in IFC4) | IfcSanitaryTerminal, IfcValve.FAUCET, IfcValve.DRAWOFFCOCK, IfcElectricAppliance.DISHWASHER | IfcSanitaryTerminal | plumbing |
| Plumbing Equipment | OST_PlumbingEquipment | - | IfcInterceptor, IfcWasteTerminal, IfcFlowTreatmentDevice | IfcTank, IfcInterceptor, IfcWasteTerminal, IfcPump | plumbing |
| Pipes | OST_PipeCurves | IfcPipeSegment | IfcPipeSegment | IfcPipeSegment | plumbing |
| Flex Pipes | OST_FlexPipeCurves | IfcPipeSegment FLEXIBLESEGMENT | - | IfcPipeSegment (FLEXIBLESEGMENT) | plumbing |
| Pipe Fittings | OST_PipeFitting | IfcPipeFitting | IfcPipeFitting | IfcPipeFitting | plumbing |
| Pipe Accessories | OST_PipeAccessory | IfcValveType (a type class) | IfcValve, IfcFlowMeter | IfcValve, IfcFlowMeter | plumbing |
| Pipe Insulations | - | IfcCovering INSULATION | - | IfcCovering | plumbing |
| MEP Fabrication Pipework | OST_FabricationPipework | IfcBuildingElementProxy | - | IfcPipeSegment | plumbing |

### Fire protection

| Revit category | BuiltInCategory | Export class (community tables) | Imports from (revit-ifc) | Suggested brick ifc_class | Brick discipline |
|---|---|---|---|---|---|
| Sprinklers | OST_Sprinklers | IfcFireSuppressionTerminalType (a type class) | IfcFireSuppressionTerminal (incl. SPRINKLER) | IfcFireSuppressionTerminal (SPRINKLER) | fire |
| Fire Protection | OST_FireProtection | - | - | IfcFireSuppressionTerminal (FIREHYDRANT, HOSEREEL, BREECHINGINLET) | fire |
| Fire Alarm Devices | OST_FireAlarmDevices | IfcAlarmType (a type class) | - | IfcAlarm, IfcSensor | fire |

### Electrical and data

| Revit category | BuiltInCategory | Export class (community tables) | Imports from (revit-ifc) | Suggested brick ifc_class | Brick discipline |
|---|---|---|---|---|---|
| Electrical Equipment | OST_ElectricalEquipment | IfcBuildingElementProxy | IfcElectricDistributionBoard, IfcTransformer, circuit breakers | IfcElectricDistributionBoard, IfcTransformer, IfcElectricGenerator | electrical |
| Electrical Fixtures | OST_ElectricalFixtures | IfcBuildingElementProxy | IfcJunctionBox, IfcSwitchingDevice, IfcOutlet.POWEROUTLET, some IfcElectricAppliance types | IfcOutlet, IfcSwitchingDevice, IfcJunctionBox | electrical |
| Lighting Fixtures | OST_LightingFixtures | IfcLightFixtureType (a type class) | IfcLightFixture | IfcLightFixture | electrical |
| Lighting Devices | OST_LightingDevices | IfcBuildingElementProxy | IfcLamp | IfcSwitchingDevice, IfcSensor | electrical |
| Cable Trays | OST_CableTray | IfcCableCarrierSegment CABLETRAYSEGMENT | IfcCableCarrierSegment | IfcCableCarrierSegment | electrical |
| Cable Tray Fittings | OST_CableTrayFitting | IfcCableCarrierFittingType (a type class) | IfcCableCarrierFitting | IfcCableCarrierFitting | electrical |
| Conduits | OST_Conduit | IfcCableCarrierSegment CONDUITSEGMENT | IfcCableSegment | IfcCableCarrierSegment (CONDUITSEGMENT) | electrical |
| Conduit Fittings | OST_ConduitFitting | IfcCableCarrierFitting | - | IfcCableCarrierFitting | electrical |
| Wires | OST_Wire | Not Exported | - | IfcCableSegment | electrical |
| MEP Fabrication Containment | OST_FabricationContainment | IfcBuildingElementProxy | - | IfcCableCarrierSegment | electrical |
| Data Devices | OST_DataDevices | IfcElectricApplianceType (a type class) | IfcCommunicationsAppliance, communications and audio-visual outlets | IfcCommunicationsAppliance, IfcOutlet (DATAOUTLET) | data |
| Communication Devices | OST_CommunicationDevices | IfcBuildingElementProxy | - | IfcCommunicationsAppliance | data |
| Telephone Devices | OST_TelephoneDevices | IfcElectricApplianceType TELEPHONE | - | IfcOutlet (TELEPHONEOUTLET) | data |
| Audio Visual Devices | OST_AudioVisualDevices | - | IfcAudioVisualAppliance | IfcAudioVisualAppliance | data |
| Security Devices | OST_SecurityDevices | IfcBuildingElementProxy | - | IfcSensor, IfcAlarm, IfcAudioVisualAppliance (CAMERA) | data |
| Nurse Call Devices | OST_NurseCallDevices | IfcSwitchingDeviceType (a type class) | - | IfcSwitchingDevice, IfcAlarm | data |

Energy discipline: Revit has no category for it. PV modules, batteries and generators are normally modelled as Electrical Equipment. Suggested classes: IfcSolarDevice (SOLARPANEL, SOLARCOLLECTOR), IfcElectricFlowStorageDevice (BATTERY, UPS), IfcElectricGenerator. EV chargers have no dedicated IFC4 class; IfcOutlet or IfcElectricAppliance with USERDEFINED is a choice the team must make.

### Site and infrastructure

| Revit category | BuiltInCategory | Export class (community tables) | Imports from (revit-ifc) | Suggested brick ifc_class (IFC4) | Brick discipline |
|---|---|---|---|---|---|
| Site | OST_Site | IfcSite | IfcSite, IfcGeographicElement | IfcGeographicElement | site |
| Topography | OST_Topography | IfcSite | IfcGeotechnicalStratum | not a brick | site |
| Planting | OST_Planting | IfcBuildingElementProxy | - | IfcGeographicElement | site |
| Parking | OST_Parking | IfcBuildingElementProxy | - | IfcBuildingElementProxy | site, transport |
| Hardscape | OST_Hardscape | - | - | IfcSlab, IfcCivilElement | site |
| Roads | OST_Roads | IfcBuildingElementProxy | IfcRoad, IfcFacilityPart.ROADSEGMENT (IFC 4.3) | IfcCivilElement | transport |
| Abutments | OST_BridgeAbutments | IfcSlab | - | IfcCivilElement | structure, transport |
| Piers | OST_BridgePiers | IfcColumn | - | IfcColumn, IfcCivilElement | structure, transport |
| Bridge Decks | OST_BridgeDecks | IfcSlab | - | IfcSlab, IfcCivilElement | structure, transport |
| Bridge Framing | OST_BridgeFraming | IfcBuildingElementProxy | - | IfcBeam, IfcMember | structure, transport |
| Bridge Cables | OST_BridgeCables | IfcBuildingElementProxy | - | IfcTendon, IfcMember | structure, transport |
| Bearings | OST_BridgeBearings | IfcBuildingElementProxy | - | IfcCivilElement (IfcBearing in IFC 4.3) | structure, transport |
| Expansion Joints | OST_ExpansionJoints | IfcBuildingElementProxy | - | IfcDiscreteAccessory, IfcCivilElement | structure, transport |
| Vibration Management | OST_VibrationManagement | IfcBuildingElementProxy | - | IfcVibrationIsolator | structure |
| Alignments | - | IfcBuildingElementProxy | IfcAlignment to Generic Model (IFC 4.3) | not a brick | - |

Revit has no rail categories. Rail bricks need IfcCivilElement under IFC4, or a schema upgrade to IFC 4.3.

Categories in the mapping tables that are annotation or analysis (tags, dimensions, sections, levels, grids, rooms, spaces, areas, analytical members, lines, text) are left out because they do not produce bricks.

## 8. Recommended import order

Before any import, use `IFCCategoryUtil.cs` from revit-ifc and the IFC4 schema dump as the vocabulary check for `ifc_class` and `predefined_type`. That is a taxonomy step, not a data import.

1. **ETIM Modelling Classes 2025 through the bSDD API** (ODC-By 1.0). 485 parametric MEP classes with named dimensions, numbered ports and an IFC class link. Fills the largest gap (hvac, plumbing, electrical containment, fire) and gives `connectors` directly. It supplies parameter names and ports, not values. Attribution to ETIM International is required.
2. **Steel and timber sections from FreeCAD `profiles.csv`, cross-checked with the Bonsai EU, US and AU steel libraries.** 1,268 rows ready to parse, in mm, LGPL-2.1. One parametric brick per profile family (IPE, HEA, HEB, HEM, UB, UC, W, CHS, RHS, UPE, angle, timber) with the table giving `default`, `min`, `max` and a list of valid designations.
3. **Pipe schedules from `fluids`** (MIT), plus the copper and EMT conduit values from Wikipedia. Gives realistic diameters and wall thicknesses for pipe, fitting and conduit bricks and for connector sizes on every MEP brick.
4. **ADA Standards and UK Approved Documents** (US federal text; OGL v3.0). About 40 verified limits for doors, ramps, stairs, handrails, parking bays, sanitary fixtures and lift cars. These set `min`, `max` and `clearances` across architecture, interior, site and transport.
5. **NREL SAM `CEC Modules.csv` and the ENERGY STAR datasets** (BSD-3-Clause; US EPA open data). Real product populations with dimensions for PV modules, refrigerators, dishwashers, washers, room air conditioners, water heaters and UPS units. Reduce to percentile ranges per class and drop brand and model fields.

Not recommended for import: BIMobject, NBS Source, bimstore, MagiCAD Cloud, MEPcontent, SCI Blue Book, and any paid standard. BIMobject's terms name AI and machine learning use as forbidden.

## 9. Gaps and open questions

- Autodesk's pristine default `exportlayers-ifc-IAI.txt` was not obtained. Someone with Revit installed can copy it from `C:\ProgramData\Autodesk\RVT <version>\`.
- Exact BuiltInCategory count for Revit 2025 or 2026 was not obtained.
- AISC's terms for the Shapes Database were not confirmed (site returned 403).
- The licence that applies to the Bonsai `.ifc` library data was not confirmed.
- NBS Source object terms, MagiCAD Cloud terms and MEPcontent terms were not retrieved.
- Whether EPREL entries carry dimensions, and whether its data is CC BY 4.0, were not confirmed.
- ENERGY STAR data licence was not confirmed on a fetched page.
- No open structured source was found for: AHU, fan coil, chiller, boiler and heat pump envelopes; hydrants; switchboards; transformers; battery storage; EV chargers; rectangular ducts; cable tray widths; radiators; escalator step widths; glulam; CLT; windows; sanitary fixture bodies; kerb units; manholes; rail profiles; street furniture; bridge components.
- Values read from Wikipedia through a summarising fetch need a second check. The brick size listed for China is one that looks wrong.

