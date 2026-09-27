# Structured data sources for growing the NoCoast-AEC brick library: open standards and classification side

Research date: 2026-09-27 (all pages and files fetched between about 05:00 and 05:20 UTC that day).
Scope: open standards, classification systems, templates and freely published dimension tables.
Manufacturer catalogues and BIM object libraries are out of scope here.

## How to read this report

- "Verified" means I fetched the page or file myself and saw the fact there. Anything I did not see on a fetched page is
  marked **unverified**.
- Item counts come from files I parsed myself unless stated otherwise. My counting method is given where it matters.
- Licence statements are quoted or paraphrased from the publisher's own page. Where I add an interpretation of what a
  licence means for NoCoast-AEC, it is labelled **Interpretation** and is not legal advice.
- Ratings: **use now** (open licence and machine-readable), **use with care** (usable, but the licence or access limits
  what we can ship), **reference only** (paywalled, PDF-only, or licence forbids our use).

## Summary table

| # | Source | Format | Licence (as stated by publisher) | Rating |
|---|--------|--------|----------------------------------|--------|
| 1 | IFC4 ADD2 TC1 and IFC4.3 ADD2 schema (buildingSMART) | EXPRESS, XSD, OWL/TTL/RDF, HTML | CC BY-ND 4.0 | use now (as a lookup and validation table) |
| 2 | IFC4 and IFC4.3 property set and quantity set definitions (PSD XML) | XML, one file per set | CC BY-ND 4.0 | use now |
| 3 | IFC4.x GitHub repositories (IFC4.x-development, IFC-translations) | Markdown, UML/XMI, EXPRESS, .pot | CC BY-ND 4.0 for formal releases; development content "all rights reserved until formal release" | use with care |
| 4 | IfcOpenShell bundled schema data (pset templates as .ifc, entity/type JSON maps) | IFC-SPF, JSON | Repo LGPL-3.0; the pset content is buildingSMART's (CC BY-ND 4.0) | use now |
| 5 | Bonsai bundled libraries (steel profiles, classification .ifc files) | IFC-SPF | Repo LGPL-3.0; licence of each embedded classification is NOT cleared by that | use with care |
| 6 | buildingSMART Data Dictionary (bSDD) | REST API (JSON), GraphQL | Per dictionary; ranges from MIT and CC BY to "No license (rights reserved)" | use now for open dictionaries, with care for the rest |
| 7 | IDS 1.0 (Information Delivery Specification) | XSD plus XML examples | CC BY-ND 4.0 | use now (as an output/validation format) |
| 8 | IfcOpenShell utilities: bsdd, ifctester, ifccsv, ifc5d, ifcfm | Python packages | LGPL-3.0 (repo level) | use now (tools, not data) |
| 9 | Uniclass 2015 (NBS) | XLSX per table in a ZIP; JSON/XML API on request | CC BY-ND 4.0 | use now |
| 10 | OmniClass (CSI) | Licensed platform; older XLS downloads | CSI EULA; public redistribution through software forbidden without written approval | reference only |
| 11 | MasterFormat (CSI) | Licensed platform | Commercial licence; copyright status now contested in court | reference only |
| 12 | UniFormat (CSI) and UNIFORMAT II (NIST report) | Licensed platform; NIST PDF | CSI commercial licence; NIST report status unverified | reference only |
| 13 | CCI (Construction Classification International) and CCS (Molio) | XLSX in a ZIP; also in bSDD | CCI core tables CC BY 4.0 | use now |
| 14 | CoClass (Svensk Byggtjanst) | Web service, paid API | Paid licence; usage-rights agreement needed for software | reference only |
| 15 | ETIM 10.0 and ETIM MC | CSV, XLSX, IXF (XML), Access; API; bSDD | ODC-By 1.0 | use now |
| 16 | ECLASS | CSV, XML (BASIC/ADVANCED) | Paid licence through the ECLASS shop | reference only |
| 17 | NL-SfB | XLSX; in bSDD | Not confirmed; bSDD lists "No license (rights reserved)" | use with care |
| 18 | COBie (NBIMS-US V3/V4 resources, nima UK templates) | XLSX, XLTX | Not confirmed on the pages fetched | use with care |
| 19 | Product data templates: CIBSE PDTs on BIMHawk; ISO 23386, ISO 23387, ISO 7817-1 | Web database with XML export; paid PDFs | BIMHawk EULA, CIBSE owns IP; ISO standards are paid | reference only |
| 20a | Pipe schedules in the `fluids` Python library | Python lists in source | MIT | use now |
| 20b | AISC Shapes Database v16.0 | XLSX | Not confirmed (AISC copyright) | use with care |
| 20c | ADA Standards (ada.gov, access-board.gov, eCFR XML API) | HTML, PDF, XML API | US federal regulation; no licence statement found on page | use now for values, no tabular data |
| 20d | Approved Document M (England) | PDF | Open Government Licence v3.0 | use with care (PDF only) |
| 20e | ISO 21542:2021 | Paid PDF | ISO copyright, CHF 227 | reference only |
| 20f | NIST PS 20-20 American Softwood Lumber Standard | PDF | Not confirmed | reference only (small tables, hand entry) |
| 20g | BIA Technical Note 10 (brick sizes) | PDF | Copyright Brick Industry Association | reference only |

Nothing I found publishes standard door or window sizes as open, machine-readable data. See section 20.

---

## 1. IFC4 ADD2 TC1 and IFC4.3 ADD2 schema

**URLs visited**
- Index of all versions: https://technical.buildingsmart.org/standards/ifc/ifc-schema-specifications/
- IFC4 ADD2 TC1 EXPRESS: https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/EXPRESS/IFC4.exp (359,976 bytes)
- IFC4 ADD2 TC1 XSD: https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/XML/IFC4.xsd
- IFC4 ADD2 TC1 full package: https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/ifc4-add2-tc1.zip (102 MB, not downloaded)
- IFC4 ADD2 TC1 HTML: https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/HTML/
  - entity page pattern confirmed: `.../HTML/schema/ifchvacdomain/lexical/ifcunitaryequipment.htm`
- IFC4 ifcOWL: https://standards.buildingsmart.org/IFC/DEV/IFC4/ADD2_TC1/OWL/ontology.ttl
- IFC4.3 ADD2 EXPRESS: https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/IFC4X3_ADD2.exp (403,825 bytes)
- IFC4.3 ADD2 XSD: https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/IFC4X3_ADD2.xsd
- IFC4.3 full package: https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/IFC4.3.2.0.zip (64 MB, not downloaded)
- IFC4.3 entity page pattern confirmed: `https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcUnitaryEquipment.htm`

**Version seen.** The index lists 4.0.2.1 "IFC 4 ADD2 TC1", ISO 16739-1:2018, published 2017-10, status Official; and
4.3.2.0 "IFC 4.3 ADD2", ISO 16739-1:2024, published 2024-04, status Official. IFC 4.1 and 4.2 are Withdrawn. The header
of IFC4.exp says "Issue date: Sunday, October 29, 2017".

**What is in it (counted by parsing the two .exp files)**

| | IFC4 ADD2 TC1 | IFC4.3 ADD2 |
|---|---|---|
| Entities | 776 | 876 |
| Enumeration types | 207 | 243 |
| Enumerations named `*TypeEnum` | 151 | 191 |
| Subtypes of IfcElement | 136 | 158 |
| of which non-abstract | 130 | 150 |
| Subtypes of IfcElementType | 117 | 139 |

For IFC4, 116 of the 130 non-abstract element classes have a PredefinedType enumeration (own or inherited), with 876
enumeration values in total across them, counting USERDEFINED and NOTDEFINED. Example read from the file:
`IfcUnitaryEquipmentTypeEnum = AIRHANDLER, AIRCONDITIONINGUNIT, DEHUMIDIFIER, SPLITSYSTEM, ROOFTOPUNIT, USERDEFINED, NOTDEFINED`.

Disciplines: all. The element tree covers building elements, HVAC, plumbing, fire suppression, electrical, building
controls, furnishing, transport and civil elements; IFC4.3 adds rail, road, bridge, ports and waterways.

**How to fetch.** Plain HTTPS GET, no authentication. The server returned HTTP 403 to the default fetch tool and 200
when a browser User-Agent was sent, so set a User-Agent header. The EXPRESS file is easy to parse with two regular
expressions (`ENTITY ... SUBTYPE OF`, `TYPE ... = ENUMERATION OF`); I did exactly that to get the counts above.

**Licence.** The index page states: "IFC is licensed under the Creative Commons Attribution-NoDerivatives 4.0
International License." The header inside IFC4.exp adds that the documentation "may be photocopied, used in software
development, or translated into another computer language without prior written consent ... provided that full
attribution is given. Prior written consent is required if changes are made to the technical specification."

**Interpretation.** Using class names and enumeration values as identifiers in our own brick JSON, and bundling the
unmodified .exp file with attribution, fits those words. Publishing an edited copy of the schema would not.

**Mapping to brick fields**
- `ifc_class`: the allowed value list (130 classes for IFC4).
- `predefined_type`: allowed values per class, taken from the class's `PredefinedType` attribute.
- Validation: reject a brick whose predefined type is not in the enumeration for its class.
- Gap analysis: list every class and predefined type that no current brick covers.

**Rating: use now.**

Sample saved: `samples/ifc4_element_predefined_types.json` (derived by me from IFC4.exp: 130 classes with their
enumerations).

---

## 2. IFC property set (Pset_*) and quantity set (Qto_*) definitions

**URLs visited**
- IFC4.3 ADD2 bundle: https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/annex-a-psd.zip (793,651 bytes, downloaded and parsed)
- IFC4 ADD2 TC1 per-file URLs, confirmed HTTP 200:
  - https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/HTML/psd/Pset_DoorCommon.xml
  - https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/HTML/psd/Pset_UnitaryEquipmentTypeCommon.xml
  - https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/HTML/qto/Qto_UnitaryEquipmentBaseQuantities.xml
- PSD schema: http://standards.buildingsmart.org/IFC/RELEASE/IFC4/FINAL/PSD/PSD_IFC4.xsd (HTTP 200)

**Version seen.** Files inside the IFC4.3 ZIP are dated 2023-10-16 and carry `<IfcVersion version="IFC4X3_ADD2"/>`.

**What is in it.** The IFC4.3 ZIP holds 760 XML files: 645 `Pset_*` and 115 `Qto_*`. Each file has:
- `Name`, `Definition`
- `ApplicableClasses/ClassName` (for example IfcDoor, IfcDoorType), and `ApplicableTypeValue`
- `templatetype` (for example PSET_TYPEDRIVENOVERRIDE)
- for each property: `Name`, `Definition`, and a `PropertyType` that is one of single value with `DataType`
  (IfcLabel, IfcBoolean, IfcPowerMeasure, ...), enumerated value with the full `EnumList`, bounded value, table value,
  list value or reference value
- for each quantity: `Name`, `Definition`, `QtoType` (Q_LENGTH, Q_AREA, Q_VOLUME, Q_WEIGHT, Q_COUNT, Q_TIME)

I did not find a directory listing or single ZIP for the IFC4 ADD2 TC1 files on the pages I fetched. The per-file URL
pattern above works if the set name is known; source 4 gives the full IFC4 list in one file.

**What it does not have.** No default values and no min/max ranges for real products. It tells us which properties
exist and their types, not what a typical split-system's cooling capacity is.

**Licence.** CC BY-ND 4.0, as for source 1.

**Mapping to brick fields**
- `properties`: the canonical property set name, property name and data type for each class. This lets brick authors
  write `Pset_DoorCommon.FireRating` instead of inventing free-form keys.
- Enumerated properties give fixed value lists.
- `Qto_*` sets name the base quantities (Width, Height, GrossArea, ...) that our `params` should be able to produce.
- `ApplicableTypeValue` sometimes includes a predefined type (for example `IfcAnnotation/ContourLine`), which ties a
  set to `predefined_type`.

**Rating: use now.**

Samples saved: `samples/ifc43_Pset_DoorCommon.xml`, `samples/ifc43_Qto_DoorBaseQuantities.xml`.

---

## 3. IFC4.x GitHub repositories

**URLs visited**
- https://github.com/buildingSMART/IFC4.x-development (the old names `IFC4.3.x-development` redirect here). Default
  branch `ifc4.3-main`, last push 2026-09-24. Top-level folders: `code`, `content`, `docs`, `reference_schemas`, `schemas`.
- https://raw.githubusercontent.com/buildingSMART/IFC4.x-development/ifc4.3-main/LICENSE.md
- https://github.com/buildingSMART/IFC-translations (`IFC4.3.x-output` redirects here). Branches `input` and
  `translations`; folder `pot`. Last push 2026-08-21.
- https://github.com/buildingSMART/IFC ("IFC schema management and versioning repository", last push 2024-03-31)
- The README names `https://github.com/buildingsmart/ifc4.3-html` for formal releases; that URL returned 404 for me.
- The README names `http://ifc43-docs.standards.buildingsmart.org/`; it redirected to
  `https://standards.buildingsmart.org/IFC/DEV/IFC4_3/HTML/` and returned 403 to my client.

**What is in it.** The authoring source of IFC4.3: Markdown documentation per entity and property set, the UML model,
and generated translation templates (.pot) in 30+ languages (per the IFC-translations README).

**Licence.** LICENSE.md: CC BY-ND 4.0, with the note that the repository "contains a development version" and that
official publications are at standards.buildingsmart.org. The IFC-translations README says: "All Rights reserved untill
formal release. Final IFC is licensed under ... CC BY-ND 4.0".

**Mapping to brick fields.** Same as sources 1 and 2. The translations could supply multilingual `tags`.

**Rating: use with care.** Prefer the formal release files (sources 1 and 2). Use the repo only for translations or
for content not in the release ZIPs.

---

## 4. IfcOpenShell bundled schema data

**URLs visited** (branch `v0.9.0`, the repository default; repo last pushed 2026-09-25)
- Directory: https://github.com/IfcOpenShell/IfcOpenShell/tree/v0.9.0/src/ifcopenshell-python/ifcopenshell/util/schema
- Raw base: `https://raw.githubusercontent.com/IfcOpenShell/IfcOpenShell/v0.9.0/src/ifcopenshell-python/ifcopenshell/util/`

| File | Size | Content (verified by download unless noted) |
|---|---|---|
| `schema/Pset_IFC4_ADD2.ifc` | 3,153,156 B | IFC-SPF file generated by "buildingSMART IFCDOC 11.7", dated 2019-02-02. 513 `IfcPropertySetTemplate` (420 Pset_ and 93 Qto_) and 2,807 `IfcSimplePropertyTemplate` |
| `schema/Pset_IFC4X3.ifc` | 1,435,670 B | same idea for IFC4.3 (size checked, content not parsed) |
| `schema/Pset_IFC2X3.ifc` | not checked | listed in the directory |
| `schema/ifc4_entities.json` | 826,406 B | 776 entries; each has the entity description and per-attribute descriptions |
| `schema/ifc4_properties.json` | 722,449 B | not parsed |
| `schema/ifc4_types.json` | 137,746 B | not parsed |
| `schema/ifc_classes_suggestions.json` | 4,202 B | 22 classes; maps everyday names to a class and predefined type, e.g. "VAV Box" to IfcAirTerminalBox, "Circuit Breaker Panel" to IfcElectricDistributionBoard/DISTRIBUTIONBOARD |
| `entity_to_type_map_4.json` | 7,954 B | 126 entries, occurrence class to type class, e.g. IfcBoiler to IfcBoilerType |
| `ifc4_to_brick.json` | 1,397 B | mapping to the Brick Schema ontology (unrelated to our "bricks"); not parsed |
| `class_4_to_2x3.json`, `attribute_4x3_to_4.json`, ... | not checked | cross-version maps |

`util/pset.py` in the same folder is the loader for the template files (listed in the directory; I did not read its
code, so its API is **unverified** here).

**How to fetch.** `pip install ifcopenshell` (PyPI version 0.8.5 on the day) or raw GitHub URLs.

**Licence.** GitHub reports LGPL-3.0 for the repository. The template content is buildingSMART's property set
definitions, so CC BY-ND 4.0 applies to that content.

**Mapping to brick fields.** The single easiest way to get every IFC4 property set into our pipeline: one file, one
parser (ifcopenshell itself), and each template carries name, description, template type, applicable entity string
(including the `Class/PREDEFINEDTYPE` form), and per property the name, description, property kind and measure type.
`ifc_classes_suggestions.json` is a seed for `tags` and search synonyms.

**Rating: use now.**

---

## 5. Bonsai bundled libraries: steel profiles and classification files

**URLs visited**
- https://github.com/IfcOpenShell/IfcOpenShell/tree/v0.9.0/src/bonsai/bonsai/bim/data/libraries
- https://github.com/IfcOpenShell/IfcOpenShell/tree/v0.9.0/src/bonsai/bonsai/bim/data/classifications
- https://github.com/Moult/IfcClassification (last push 2023-01-15; no licence reported by the GitHub API)

**Libraries folder** contains: `IFC4 EU Steel.ifc` (599,337 B), `IFC4 US Steel.ifc` (2,182,594 B), `IFC4 AU Steel.ifc`
(395,262 B), `IFC4 Furniture Library.ifc` (734,664 B), `IFC4 Landscape Library.ifc`, `IFC4 Entourage Library.ifc`,
and demo libraries for IFC2X3, IFC4 and IFC4X3.

I downloaded and parsed `IFC4 EU Steel.ifc`: an `IfcProjectLibrary` named "EU Steel Profiles Library", units in
millimetres, with 711 beam types, 711 column types and 711 member types sharing 711 profiles: 191 I-shape, 220
circular hollow, 218 rectangular hollow, 39 L-shape, 37 U-shape, 6 Z-shape. Example line:
`IFCISHAPEPROFILEDEF(.AREA.,'HEA100',$,100.,96.,5.,8.,12.,$,$)`.

**Classifications folder** (and the `ifc` folder of Moult/IfcClassification) holds classification systems already
converted to IFC, including `Uniclass2015_Jan2020.ifc`, `CCI(EN).ifc`, `CCS(EN).ifc`, `NL_SfB_tabel_1_2019.ifc`,
`Omniclass_OCCS.ifc`, `MasterFormat2016Edition.ifc`, `Uniformat_2010_CSI.ifc`, `UniformatII-0918.ifc`, `RICS NRM1.ifc`,
`NS3451.ifc`, `NATSPEC 2017.ifc`, `SFG20_.ifc`, `VBIS.ifc` and about twenty more.

**Licence.** The repository is LGPL-3.0. I found no statement of where the steel dimensions came from, and no
statement that the owners of OmniClass, MasterFormat, NRM or SFG20 permit redistribution. **Unverified** in both cases.
The OmniClass EULA (section 10 below) forbids public redistribution without written approval.

**Mapping to brick fields**
- Steel libraries: `params` for structural bricks. Each profile gives exact depth, width, web and flange thickness and
  fillet radius, which become parameter presets ("size tables") for beam, column and member bricks. The profile entity
  type matches our "profiles" geometry primitive.
- Classification files: a ready parser path, since the hierarchy is already `IfcClassificationReference` trees. Use
  only for systems whose licence we have cleared (Uniclass, CCI).

**Rating: use with care.** Steel libraries are low risk (dimensions of standard sections are facts) but the origin is
undocumented. For classification files, take the data from the owner instead (sections 9 and 13).

---

## 6. buildingSMART Data Dictionary (bSDD)

**URLs visited**
- Service page: https://www.buildingsmart.org/users/services/buildingsmart-data-dictionary/
- Docs repo: https://github.com/buildingSMART/bSDD (MIT, last push 2026-09-23)
- API doc: https://raw.githubusercontent.com/buildingSMART/bSDD/master/Documentation/bSDD%20API.md
- OpenAPI contract: https://raw.githubusercontent.com/buildingSMART/bSDD/master/Documentation/bSDD%20OpenAPI.yaml (164 KB)
- Swagger UI (named in the doc, not opened): https://app.swaggerhub.com/apis/buildingSMART/Dictionaries/v1
- Live calls made: `GET https://api.bsdd.buildingsmart.org/api/Dictionary/v1?Limit=1000`,
  `GET .../api/Dictionary/v1/Classes?Uri=...`, `GET .../api/Dictionary/v1/Properties?Uri=...`,
  `GET .../api/Class/v1?Uri=...&IncludeClassProperties=true`

**What it is.** The service page describes it as "a collection of interconnected data dictionaries", free to read and
free to publish public content; paid features exist for private dictionaries. Content follows a data model based on
ISO 23386 and ISO 12006-3. The page also says "At the moment, only IFC4.3 is in bSDD".

**What I measured on 2026-09-27**
- 427 dictionary versions, 308 distinct dictionaries. Status: 302 Preview, 75 Active, 50 Inactive.
- Licence field across the 427 versions: 195 "No license (rights reserved)", 63 "No license", 33 MIT (two spellings),
  22 CC BY-NC-ND 4.0, about 40 CC BY-ND (several spellings), about 27 CC BY (several spellings), 3 ODC-By, and a tail
  of others. So more than half of bSDD content carries no open licence.

| Dictionary | URI | Licence field | Classes |
|---|---|---|---|
| IFC 4.3 | https://identifier.buildingsmart.org/uri/buildingsmart/ifc/4.3 | CC BY-ND 4.0 | 2,163 classes, 2,501 properties |
| Uniclass 2015 (NBS) | https://identifier.buildingsmart.org/uri/nbs/uniclass2015/1 | CC BY-ND 4.0 | 14,328 (release 2024-08-16, older than the NBS download) |
| ETIM 10.0 | https://identifier.buildingsmart.org/uri/etim/etim/10.0 | ODC-By | 5,799 |
| ETIM MC 2025 | https://identifier.buildingsmart.org/uri/etim/etim-mc/2025 | ODC-By | 586 (status Preview) |
| CCI Construction (Molio) | https://identifier.buildingsmart.org/uri/molio/cciconstruction/1.0 | MIT license | 1,247 |
| NL-SfB 2005 | https://identifier.buildingsmart.org/uri/nlsfb/nlsfb2005/2.2 | No license (rights reserved) | 895 |

In the IFC 4.3 dictionary, predefined types are classes of their own (for example `IfcActionRequestEMAIL`), which is
why there are 2,163 classes. `IfcUnitaryEquipment` returned 201 class properties, each with name, URI that embeds the
property set (`.../prop/Pset_UnitaryEquipmentTypeCommon/Status`), description, `dataType` and `allowedValues`.

**API**
- Base URL `https://api.bsdd.buildingsmart.org/`. Endpoints in the OpenAPI file include `/api/Dictionary/v1`,
  `/api/Dictionary/v1/Classes`, `/api/Dictionary/v1/Properties`, `/api/Class/v1`, `/api/Class/Properties/v1`,
  `/api/Class/Relations/v1`, `/api/Property/v5`, `/api/PropertyValue/v2`, `/api/TextSearch/v2`,
  `/api/SearchInDictionary/v1`, `/api/Class/Search/v1`, `/api/Unit/v1`, `/api/Language/v1`, `/api/Country/v1`,
  `/api/ReferenceDocument/v1`.
- GraphQL: `https://api.bsdd.buildingsmart.org/graphqls` (secured, POST only).
- Auth: the read calls I made needed no token. Secured methods use Azure AD B2C (OAuth2); a Client ID must be
  requested from buildingSMART. The doc says a desktop client that "only calls the non-secured APIs" is "ready to go".
- The doc asks clients to send a `User-Agent` of the form `application/version`.
- The doc warns not to use `identifier.buildingsmart.org` URIs for system-to-system calls.
- Versioning: breaking changes get a new version and the old one is supported for 6 months.
- **Rate limits: none documented** in the API doc, README or OpenAPI file, and no rate-limit headers came back on my
  calls. Treat the limit as unknown and cache.
- I did not find a bulk export endpoint for a whole dictionary. Paging `Dictionary/v1/Classes` and then one
  `Class/v1` call per class is the route I confirmed.

**Mapping to brick fields**
- `ifc_class` plus `predefined_type`: IFC 4.3 classes with human-readable names and definitions per predefined type,
  good for `description` and `tags`.
- `properties`: property lists per class with data types and allowed values.
- Classification codes: store the bSDD class URI on a brick as a stable identifier for Uniclass, ETIM or CCI.
- The API shape also includes class relations, which is where cross-dictionary mappings would appear; I did not
  confirm how well populated they are. **Unverified.**

**Rating: use now** for dictionaries with an open licence field (IFC, Uniclass, ETIM, CCI); check the `license` field
per dictionary in code before importing anything else.

Sample saved: `samples/bsdd_class_IfcUnitaryEquipment_truncated.json`.

---

## 7. IDS (Information Delivery Specification)

**URLs visited**
- https://github.com/buildingSMART/IDS (default branch `development`, last push 2026-09-25)
- https://raw.githubusercontent.com/buildingSMART/IDS/development/Schema/ids.xsd
- https://standards.buildingsmart.org/IDS/1.0/ids.xsd (HTTP 200)
- Test cases folder: `Documentation/ImplementersDocumentation/TestCases/` with sub-folders attribute, classification,
  entity, ids, material, partof, property, restriction, tolerance

**Version seen.** Release tag `v1.0.0`, published 2024-06-03.

**What it is.** An XML format for stating requirements on IFC models: which entity (and predefined type) must carry
which attributes, properties, classification references, materials and part-of relations, with value restrictions.
It contains no product data itself.

**Licence.** LICENSE file: CC BY-ND 4.0.

**Mapping to brick fields.** Not an import source. It is the natural format for a generated rule such as "every
IfcUnitaryEquipment/SPLITSYSTEM must have Pset_UnitaryEquipmentTypeCommon.Reference and a Uniclass Pr code". We could
generate one IDS file from the brick library and run it against every model the app produces.

**Rating: use now** (as a validation format).

---

## 8. IfcOpenShell utilities

**URLs visited:** `https://github.com/IfcOpenShell/IfcOpenShell/tree/v0.9.0/src/<name>` and each README.

| Package | What the README says | Use for us |
|---|---|---|
| `bsdd` | "A library to interact with the buildingSMART Data Dictionary (bSDD) API ... totally independent from other packages in IfcOpenShell". Source shows base URL `https://api.bsdd.buildingsmart.org/api/` and methods `get_dictionary`, `get_classes`, `get_properties`, `get_class`, `get_class_properties`, `get_class_relations`, `get_property`, `search_text`, `search_in_dictionary` | ready-made client for source 6 |
| `ifctester` | README is one line; it is the IDS authoring and checking library | run IDS checks (source 7) |
| `ifccsv` | export and import IFC data to CSV, ODS, XLSX and pandas | dump properties of generated models for QA |
| `ifc5d` | cost data utilities: CSV to IFC, IFC to XLSX/CSV/ODS; ships example BoQ and schedule-of-rates CSVs | not product data; low relevance |
| `ifcfm` | prototype FM extraction library that "will supersede the IfcCOBie library" | COBie-style export later |

PyPI showed version 0.8.5 for `ifcopenshell`, `bsdd` and `ifctester`. Licence: LGPL-3.0 at repository level (each
package folder has COPYING and COPYING.LESSER files).

**Rating: use now** (tools).

---

## 9. Uniclass 2015 (NBS)

**URLs visited**
- https://www.thenbs.com/our-tools/uniclass (redirects to https://www.thenbs.com/tools/uniclass)
- https://uniclass.thenbs.com/download
- https://www.thenbs.com/our-tools/uniclass/API
- Bundle endpoint found in the page source: `https://uniclass.thenbs.com/download/downloadbundle?publishDate=2026-07`

**Version seen.** July 2026 release, dated 01 July 2026 ("4 tables updated, 11 tables unchanged"). Updated quarterly.
Historic bundles back to 2015-07 use the same URL pattern with a different `publishDate`.

**What is in it.** The bundle is a 3.4 MB ZIP with one XLSX per table plus revision PDFs, a change log and a
"codes not in use" workbook. Row counts I measured (rows after the three header rows):

| Table | Rows | Table | Rows |
|---|---|---|---|
| Pr Products v1.43 | 8,491 | Ss Systems v1.43 | 2,718 |
| PC (v1.3) | 1,317 | SL Spaces/locations v1.36 | 1,154 |
| PM v1.30 | 1,107 | Ac Activities v1.27 | 961 |
| TE v1.18 | 882 | En Entities v1.34 | 591 |
| Ma (v1.1) | 447 | Co Complexes v1.22 | 415 |
| RK (v1.0) | 302 | Ro Roles v1.13 | 292 |
| EF Elements/functions v1.16 | 231 | Zz v1.3 | 134 |
| FI v1.7 | 96 | **Total** | **about 19,100** |

Columns in every table: `Code, Group, Sub group, Section, Object, Sub object, Title, NBS Code, COBie, NRM1,
IFC 2x3 TC1, IFC 4Add2 TC1, IFC 4x3Add2 TC1, CESMM`.

The IFC columns are the important find. In the Products table, **4,036 of 8,491 rows carry an IFC4 mapping**, to 396
distinct targets written as `IfcXxxType.PREDEFINEDTYPE`, for example `Pr_15_57_33_85 Spun-bonded polypropylene (PP)
membranes` maps to `IfcCoveringType.MEMBRANE`. The most common targets are catch-alls
(`IfcDiscreteAccessoryType.USERDEFINED` 499 rows, `IfcFurnitureType.USERDEFINED` 473). In the EF table 102 of 231 rows
are mapped. The Ss table has no IFC4 mappings.

Disciplines: all, including civil and infrastructure.

**How to fetch.** The download button opens a "Register to download" form, but the bundle endpoint itself returned the
ZIP to a plain GET with no cookie or token. The API (JSON or XML, endpoints
`definitions/uniclass2015/{notation}/{depth}` and `definitions/uniclass2015/ancestors/{notation}`) needs registration
through a form; NBS then "will reach out". API terms and limits are **unverified**.

**Licence.** Stated on the download page: CC BY-ND 4.0, "allowing users and organizations to share and apply the
tables on any kind of personal or commercial project. However, users should not adapt the tables and add their own
codes".

**Interpretation.** Tagging each brick with its Uniclass code and title, and shipping the unmodified tables with
attribution, is the use NBS describes. Do not invent codes and do not ship an edited table.

**Mapping to brick fields**
- Classification code and title per brick (a new `classification` property, or entries in `properties`).
- `ifc_class` and `predefined_type`: the mapping column gives both in one string. Note it names the *type* class
  (`IfcCoveringType`); use `entity_to_type_map_4.json` from source 4 in reverse to get the occurrence class.
- `tags`: the title plus the titles of the parent levels.
- Backlog: the 8,491 product rows are a candidate list of bricks to build. Filtering to rows with a specific
  (non-USERDEFINED) IFC4 mapping gives a prioritised, already-classified work list.

**Rating: use now.**

Sample saved: `samples/uniclass_Pr_v1_43_first40rows.csv` (header plus the first 40 product rows that have an IFC4
mapping).

---

## 10. OmniClass (CSI)

**URLs visited**
- https://www.csiresources.org/standards/omniclass/standards-omniclass-about
- https://www.csiresources.org/standards/omniclass
- https://theconstructionstandard.com/omniclass-download
- EULA PDF (read in full): https://higherlogicdownload.s3.amazonaws.com/CSIRESOURCES/b00cc178-1ca0-4e36-aeae-82edcd55c99c/UploadedImages/PDFs/OmniClass_EULA_2019-07-01.pdf

**What it covers.** 15 hierarchical tables for the North American industry; the About page says it draws on
MasterFormat for work results, UniFormat for elements and EPIC for products. Table 23 is Products. Item counts:
**unverified** (I did not obtain the tables).

**Access.** The Construction Standard page says access is through the "CSI Dynamic Standards" platform and that a
"company license [is] required". No free download link was present on the pages I fetched. Price not shown.

**Licence.** The 2019-07-01 EULA grants use for "nonprofit, personal or commercial use" but says that without CSI's
prior written approval you must never: modify the product; "Redistribute publicly: 1) the OmniClass Product, in whole
or in part, through a web service or by access to an application programming interface; 2) information that relates or
corresponds OmniClass classifications to classifications or information contained in other standards"; or "Provide,
license or sell commercial construction documents or other forms of information products that use OmniClass numbers
and titles". CSI may terminate the licence at any time. Whether this EULA is still the one in force after the 2026
move to CSI Dynamic Standards is **unverified**.

**Mapping to brick fields.** Would give a classification code per brick for US users.

**Rating: reference only.** Shipping OmniClass codes inside our library is exactly what the EULA restricts. A user
could still type a code into a free-form property.

---

## 11. MasterFormat (CSI)

**URLs visited**
- https://theconstructionstandard.com/license-masterformat-construction-software (redirected to `/license-masterformat-construction`)
- Trade press: https://www.buildingenclosureonline.com/articles/95142-federal-judge-rules-masterformat-numbers-titles-and-taxonomy-are-not-copyright-protected (dated 2026-09-03)

**What it covers.** Work results (specification sections), organised in divisions. The licensing page mentions a
"MasterFormat 2026" edition. Not a product or element classification, so it fits bricks less well than Uniclass Pr.

**Access and licence.** The licensing page says: if you use MasterFormat "numbers, titles, or classifications in
deliverables, templates, products, or platforms ... CSI Standards licensing is necessary", and offers a hosted API or
a data licence. No price shown.

**Reported court ruling (secondary source, not a primary document).** The trade article reports that on 1 September
2026 a US District Court (C.D. California, Judge Holcomb) granted summary judgment to ZeroDocs and held that "the
asserted numbers, titles, divisions, and taxonomy of CSI's MasterFormat are not protectable by copyright". The article
also says the ruling does not invalidate CSI's registrations or trademarks, does not cover UniFormat or OmniClass, and
may not be the final word. I did not read the order itself, so treat this as **unverified at primary-source level**.

**Rating: reference only** until the legal position settles and a lawyer has looked at it.

---

## 12. UniFormat (CSI) and UNIFORMAT II

**URLs visited**
- CSI licensing pages as in section 11 (UniFormat is licensed through the same platform).
- https://www.nist.gov/publications/uniformat-ii-elemental-classification-building-specifications-cost-estimating-and-cost
- https://www.nist.gov/copyrights-disclaimers

**What it covers.** Elemental classification (substructure, shell, interiors, services, equipment, sitework), which
matches how bricks are grouped by discipline. UNIFORMAT II is described in NIST report NISTIR 6389 (Charette and
Marshall, published 1 October 1999); the formal standard is ASTM E1557, which I did not look up.

**Format.** CSI: licensed platform. NIST: PDF report.

**Licence.** CSI: commercial. For the NIST report, the NIST copyright page only states that software by NIST employees
is not subject to US copyright; it does not address this report, and one author may not have been a NIST employee. So
the status of the UNIFORMAT II table is **unverified**.

**Rating: reference only.**

---

## 13. CCI (Construction Classification International) and CCS (Molio)

**URLs visited**
- https://cci-collaboration.org/ and https://cci-collaboration.org/the-standard/
- Download: https://cci-collaboration.org/?wpdmdl=924 (returns `CCI-tables-20241121.zip`, 136,876 bytes)
- https://molio.dk/produkter/digitale-vaerktojer/gratis-vaerktojer/ccs-cuneco-classification-system
- bSDD entry for CCI (section 6)

**Version seen.** CCI core tables version 20241121. Earlier versions 20221109, 20221004, 20220921 and 20200526 are
linked from the same page.

**What is in it.** Two XLSX workbooks, six tables, with columns `Level 1, Level 2, Level 3, Level 4, Term (EN),
Definition (EN), Examples (EN)`. Sheet row counts (including about three header rows each):

| Table | Rows |
|---|---|
| CS Built space | 166 |
| CC Construction complex (draft) | 59 |
| CE Construction entity | 190 |
| CF Functional system | 23 |
| CT Technical system | 184 |
| CO Construction component | 804 |

The tables are based on EN ISO 12006-2 and the IEC/ISO 81346 series. Codes are letter codes by function, for example
`BJB` "Power limit switch: power sensing object, with Boolean output". Disciplines: all, but by function, not product.

CCS is the Danish predecessor. The Molio page says the CCS tools are free ("gratis"); I did not confirm a licence or
download format for CCS itself.

**Licence.** The standard page states "CCI by CCI TC is licensed under CC BY 4.0". The bSDD copy is labelled
"MIT license". The site's terms-of-use page was empty when fetched.

**Mapping to brick fields**
- A second, fully open classification code per brick.
- The "Definition" and "Examples" columns are good raw material for `description` and `tags`.
- The CT (technical system) table could label `connectors` by system kind, since it names supply, drainage and
  similar systems by function.
- No IFC mapping column.

**Rating: use now.**

Sample saved: `samples/CCI-tables-20241121.zip` (the complete 137 KB download).

---

## 14. CoClass (Svensk Byggtjanst)

**URLs visited**
- https://byggtjanst.se/tjanster/coclass/
- https://coclass.byggtjanst.se/about
- API documents linked there (not read): `Guide CoClass API-eng.pdf`, `CoClass API technical documentation-eng.pdf`

**What it covers.** The Swedish classification for the whole built environment, successor to BSAB.

**Access.** Three products: CoClass Bas (free, read-only access to the base tables on the web service), CoClass Studio
and CoClass API (licensed, one year per licence). The page says CoClass will change administrator on 1 July 2027.

**Licence.** The About page says using CoClass in software "for classifying goods ... marking BIM objects or for other
purposes" requires a usage-rights agreement with AB Svensk Byggtjanst, for internal and external applications alike.

**Rating: reference only.**

---

## 15. ETIM 10.0 and ETIM MC

**URLs visited**
- https://www.etim-international.com/classification/license-info/
- https://www.etim-international.com/classification/release-policy/
- https://www.etim-international.com/downloads/?_sft_downloadcategory=model-releases
- https://etimapi.etim-international.com/
- File downloaded and parsed: https://www.etim-international.com/wp-content/uploads/2024/12/ETIM-10.0-ALL-SECTORS-CSV-METRIC-EI-2024-12-05.zip (2,895,379 bytes)

**Version seen.** ETIM 10.0, released December 2024; files dated 2024-12-05. The release policy page says official
releases come about every three years, with "dynamic releases" in between.

**What is in it.** Product classes for technical products, each with a fixed list of features. Sectors named on the
download page: electrotechnical, HVAC and plumbing, building materials, shipbuilding, tools/hardware/site supplies.
The CSV ZIP holds nine files, UTF-16 encoded and semicolon-delimited:

| File | Rows | Columns |
|---|---|---|
| ETIMARTCLASS.csv | 5,640 | ARTCLASSID; ARTGROUPID; ARTCLASSDESC; ARTCLASSVERSION; ARTCLASSVERSIONDATE |
| ETIMARTGROUP.csv | 159 | ARTGROUPID; GROUPDESC |
| ETIMFEATURE.csv | 17,377 | FEATUREID; FEATUREGROUPID; FEATUREDESC |
| ETIMVALUE.csv | 16,163 | VALUEID; VALUEDESC |
| ETIMUNIT.csv | 188 | UNITOFMEASID; UNITDESC |
| ETIMARTCLASSFEATUREMAP.csv | 76,625 | class; feature; FEATURETYPE; unit; sort order |
| ETIMARTCLASSFEATUREVALUEMAP.csv | 201,284 | allowed values per class feature |
| ETIMARTCLASSSYNONYMMAP.csv | 37,058 | ARTCLASSID; CLASSSYNONYM |
| ETIMFEATUREGROUP.csv | 18 | feature group names |

Feature types across the 76,625 class features: 27,314 numeric (N), 23,222 alphanumeric with a value list (A), 22,014
logical (L), 4,075 range (R). Example: class EC000393 "Hot water heat pump" has 49 features, including
"Connection voltage" (N, V), "Nominal content" (N, l), "Suitable for wall mounting" (L), "Air temperature" (R, deg C),
"Type of refrigerant" (A).

(The bSDD copy of ETIM 10.0 reports 5,799 classes against 5,640 in this CSV; I did not investigate the difference.)

**ETIM MC (Modelling Classes).** Named on the licence page as covered by the same licence. In bSDD the dictionary
`etim/etim-mc/2025` has 586 classes, status Preview; the first classes returned were connection types ("Pipe end",
"Combined connection type ..."). ETIM MC is ETIM's parametric geometry layer, so it is the closest published thing to
our own brick model. I did not download an MC release file, so its structure is **unverified** beyond the bSDD listing.

**Formats and fetch.** Direct HTTPS download, no login: CSV, Excel, IXF (XML, the primary release format) and Access;
metric and metric-plus-imperial variants. The API at etimapi.etim-international.com is JSON with OAuth2 and needs a
client_id and secret that must be requested; terms for non-members are **unverified**.

**Licence.** Stated on the licence page: "made available under the Open Data Commons Attribution Licence:
http://opendatacommons.org/licenses/by/1.0/ ... The ETIM model is free to use for everyone", with the plain-language
summary that you may share, create and adapt as long as you attribute and keep notices intact. Language versions other
than ETIM English may be restricted to national members. The ETIM xChange exchange format is Apache 2.0.

**What it does not have.** No typical values, no ranges of real products, no geometry in the base model. Features say
what to record, not what the number is.

**Mapping to brick fields**
- `properties`: a realistic, industry-agreed property list per product class with units, strongest for electrical,
  HVAC and plumbing.
- `params`: the numeric and range features that are dimensions (width, height, depth, nominal diameter) name the
  parameters a brick should expose.
- `tags`: 37,058 synonyms, about 6.5 per class.
- `connectors`: connection-related features and the ETIM MC connection-type classes can inform connector kinds.
- `mount`: logical features such as "Suitable for wall mounting" and "Suitable for floor mounting" map straight to our
  mount options.
- No IFC mapping in the CSV. Whether bSDD class relations link ETIM to IFC is **unverified**.

**Rating: use now.**

Sample saved: `samples/etim10_sample_class_features.txt`.

---

## 16. ECLASS (formerly eCl@ss)

**URLs visited**
- https://eclass.eu/en/eclass-standard/licenses
- https://eclass.eu/en/eclass-standard/prices
- Price list PDF linked, not read: `/fileadmin/Redaktion/pdf-Dateien/Sonstige_Dateien/ecl-prices_en-V10.1.pdf`

**What it covers.** Cross-industry product classification with properties; BASIC and ADVANCED variants. Construction
is one segment among many. Item counts and current release number: **unverified**.

**Format.** CSV and XML (BASIC), XML (ADVANCED), downloaded from the ECLASS shop after registration and order. A web
service page exists; not examined.

**Licence.** The prices page says: "To use ECLASS in accordance with our Terms of Use, it is necessary to obtain a
license via our Shop or become a member of ECLASS e.V." A Single License covers one release; a Concordance License is
a subscription. Fees depend on company size (employee count including subsidiaries). A search result mentioned free
demo versions; I did not confirm that on a fetched page.

**Rating: reference only.** ETIM covers the same need with an open licence.

---

## 17. NL-SfB

**URLs visited**
- https://ketenstandaard.nl/nl-sfb-facts/documentatie-over-nl-sfb/
- https://www.bimloket.nl/p/542/NLSfB (redirects to https://www.digigo.nu/standaarden/nlsfb/)
- https://github.com/MennoMekes/NL-SfB-tabel-1-Classification (README)
- File URL named in that README, confirmed HTTP 200 by header only:
  https://stprodeuwmystabu002stor.blob.core.windows.net/overig/NL-SfB_Tabel_0-4_Update-V202112.xlsx (330,330 bytes,
  last modified 2023-02-22)
- bSDD entries: `nlsfb/nlsfb2005` v2.2 (895 classes) and `Ketenstandaard/nlsfb` 2021 (Preview)

**What it covers.** The Dutch element classification (table 1 is building elements, with installation chapters updated
in 2019 and 2021), managed by Ketenstandaard Bouw en Techniek. The Ketenstandaard page says a complete digital list
aligned with the printed edition is available as a download.

**Licence.** I found no licence statement on the pages fetched. Both bSDD entries say "No license (rights reserved)".
**Not confirmed.**

**Mapping to brick fields.** Element-level classification code per brick for Dutch and Belgian users.

**Rating: use with care.** Ask Ketenstandaard before bundling.

---

## 18. COBie

**URLs visited**
- NBIMS-US V4 resources: https://nibs.org/nbims/v4/resources/
  - Blank spreadsheet, downloaded: https://nibs.org/wp-content/uploads/2025/04/40-Resource-COBie-v3-Blank-Spreadsheet.xlsx (55,659 bytes)
  - COBie V3 to IFC document (PDF, not read): https://nibs.org/wp-content/uploads/2025/04/40-Resource-COBie-V3_IFC.pdf
  - The JSON schema link on the page (`/sites/default/files/docs/NBIMS_COBie_v3_JSON-Schema.json`) returned 404.
- nima (UK): https://wearenima.im/resources/construction-operations-building-information-exchange-cobie/
  - UK template, latest: https://wearenima.im/wp-content/uploads/2024/06/COBie-UK-2.4-Template-2026-07.xltx.zip (465,175 bytes, not opened)
  - Responsibility matrix, downloaded: https://wearenima.im/wp-content/uploads/2024/06/2013_Responsibility_Matrix_v17_wAssetLists.xlsx.zip (126,596 bytes)
  - UK property sets: https://wearenima.im/wp-content/uploads/2024/06/COBie_PropertySets_UK.zip (16,320 bytes, not opened)

**What is in it**
- COBie V3 blank spreadsheet: sheets Instruction, Company, Facility, Level, SpaceType, Space, Zone, Type, Component,
  System, Resource, Job, Event, Package, Risk, Document, Attribute, Coordinate, PickList. The Type sheet starts
  `Name, Description, Category, AssetType, ExtSystem, ExtObject, ExtIdentifier, Manufacturer, ModelNumber,
  WarrantyGuarantorParts, WarrantyDurationParts, WarrantyGuarantorLabor, WarrantyDurationLabor, WarrantyDurationUnit`.
  The PickList sheet points at OmniClass and Uniclass tables for category values.
- Responsibility matrix v17 (COBie 2.4): sheets "Spreadsheet Schema" (288 rows: every column with key, required flag,
  type, max length and its IFC mapping), "Type Assets" (130 rows) and "Component Assets" (173 rows) listing which IFC
  type and element classes count as COBie assets, "Property Sets" (30 rows of include/exclude rules), and
  "Deliverable Requirements" (281 rows).
- The nima page says its templates use Uniclass as the preferred classification and, from July 2025, include entities
  for IFC2x3, IFC4 and IFC4.3.

**Licence.** I found no licence statement on the nima page or on the NBIMS-US V4 pages. **Not confirmed.**

**Mapping to brick fields**
- `properties`: the Type-sheet columns are the minimum handover data an FM client expects on a product type
  (manufacturer, model number, warranty, expected life, replacement cost and so on). Adding these as empty, named
  properties makes bricks COBie-ready.
- The asset lists tell us which `ifc_class` values are maintainable assets, which helps prioritise what to build.

**Rating: use with care.** The column names are easy to adopt; ask before bundling the files.

---

## 19. Product data templates and Level of Information Need

### CIBSE PDTs on the BIMHawk Toolkit

**URLs visited**
- https://www.bimhawk.co.uk/bimhawk.php, https://www.bimhawk.co.uk/pdtlist2.php, https://www.bimhawk.co.uk/terms.php
- https://www.cibse.org/knowledge-research/knowledge-resources/knowledge-toolbox/digital-engineering-series-templates/
- Two older CIBSE PDT pages returned by search (`.../damper-volume-control-product-data-template-pdt`,
  `.../storage-vessel-product-data-template-pdt`) returned **404**.

**What is in it.** The published PDT list has 68 table rows. Entries include Air To Water Heat Pump, Boiler, Cable
Tray System, Circuit Breakers, Fan Coil Unit, Isolation Valve, Luminaire, Plate Heat Exchanger, Electrical Socket
Outlet and a "COBie Parameters" template. Each has "View Template", "Generate XML File" and "Generate SP File" (Revit
shared parameters) actions. Discipline: building services (mechanical, electrical, public health). I did not open an
individual template, so field names are **unverified**.

The CIBSE "Digital Engineering Series" page offers free XLSX templates, but those are project documents (BIM
execution plan, asset information requirements), not product data.

**Licence.** The BIMHawk EULA grants use of the toolkit "free of charge" and states CIBSE owns the intellectual
property. It gives no open licence for re-using the templates in another product.

**Rating: reference only.** Useful to check that a services brick exposes the properties UK engineers expect.

### ISO 23386, ISO 23387, ISO 7817-1

**URLs visited:** https://www.iso.org/standard/75401.html, https://www.iso.org/standard/85391.html,
https://www.iso.org/standard/82914.html

| Standard | Edition seen | Price | What the ISO page says |
|---|---|---|---|
| ISO 23386:2020 (properties in interconnected data dictionaries) | Ed. 1, 2020-03, confirmed 2025 | CHF 181 | "not in the scope of this document to provide the content of the interconnected data dictionaries" |
| ISO 23387:2025 (data templates) | Ed. 2, 2025-09 | CHF 159 | provides an XSD implementing the ISO 23387 and ISO 12006-3 models; "not within the scope of this document to provide the content of any data templates" |
| ISO 7817-1:2024 (level of information need) | Ed. 1, 2024-06 | CHF 135 | concepts and principles only |

So these three define *how* to structure templates and requirements. None of them contains product data, and all are
paid. bSDD (source 6) is the freely readable implementation of the ISO 23386 / ISO 12006-3 model.

**Rating: reference only.**

### NBS

The NBS page https://www.thenbs.com/tools/digital-plan-of-work says the NBS BIM Toolkit was retired in July 2022 and
that the "LOD guides" from that project are "now available as a download". I did not fetch the guides. NBS Source is
described as free to search; it is a manufacturer product platform and out of scope here.

---

## 20. Open dimension tables

### 20a. Pipe schedules in the `fluids` Python library

**URLs visited:** https://github.com/CalebBell/fluids (MIT, last push 2026-09-15);
https://raw.githubusercontent.com/CalebBell/fluids/master/fluids/piping.py

**What is in it.** Plain Python lists in millimetres: for each schedule, nominal pipe size, inner diameter, outer
diameter and wall thickness. I saw steel schedules 5, 10, 20, 30, 40, 60, 80, 100, 120, 140, 160, STD and XS, with
comments citing ASME B36.10M (welded and seamless wrought steel pipe) and ASME B36.19M (stainless), plus plastic pipe
tables citing ASTM D1785, D2241, D2665, F441, F679 and F2619. Example, Schedule 40 NPS 2: OD 60.3, ID 52.48,
wall 3.91. STD covers NPS 1/8 to 48.

**Licence.** MIT. The numbers come from ASME and ASTM standards, which are themselves paid documents; the library
author has re-published the dimensions. **Interpretation:** dimensions are facts, and the risk is low, but this is a
secondary source and should be spot-checked.

**Mapping.** `params` presets for pipe-segment and fitting bricks (diameter, wall thickness); `connectors` sizes for
every plumbing, HVAC-hydronic and fire-suppression brick.

**Rating: use now.**

### 20b. AISC Shapes Database v16.0

**URLs visited:** https://www.aisc.org/aisc/publications/steel-construction-manual/aisc-shapes-database-v160/ ;
file header checked only: https://cloud.aisc.org/biggie_bin/aisc-shapes-database-v160-2.xlsx (2,028,540 bytes, last
modified 2026-02-20); historic shapes: `.../aisc-shapes-database-v160h.xlsx`.

The page says the database has US customary and metric units, follows the EDI naming convention, includes a Readme
sheet defining every variable, and adds 222 new shapes in v16.0. Total shape count: **unverified** (not opened).

**Licence.** No licence statement on the page; the site has a "Copyright Permissions" section I did not read.
**Not confirmed.**

**Mapping.** Same as the steel libraries in source 5, for US sections.

**Rating: use with care.**

### 20c. ADA accessibility standards (United States)

**URLs visited**
- https://www.ada.gov/law-and-regs/design-standards/2010-stds/ (full HTML text of the 2010 Standards)
- https://www.access-board.gov/ada/ (HTML; PDF at `/files/ada/ADA-Standards.pdf`, 3.95 MB; figures offered as a ZIP of .dwg files)
- eCFR API: `https://www.ecfr.gov/api/versioner/v1/titles.json` and
  `https://www.ecfr.gov/api/versioner/v1/full/2026-01-02/title-36.xml?part=1191` (560,545 bytes of XML, 2,296
  paragraphs). The API returns HTTP 406 unless the request allows compression (`Accept-Encoding: gzip`).

**What is in it.** Prose rules with explicit dimensions in inches and millimetres. Examples read from the fetched
text: clear floor space "30 inches (760 mm) minimum by 48 inches (1220 mm) minimum" (305.3); toe clearance "30 inches
(760 mm) wide minimum" (306.2.5); knee clearance between 9 inches (230 mm) and 27 inches (685 mm) above the floor
(306.3.1). It is not tabular data; values must be extracted from sentences.

**Licence.** I found no licence or public-domain statement on ada.gov. It is a US federal regulation (36 CFR Part
1191). Works of the US federal government are generally not subject to US copyright, but that statement was not on a
page I fetched, so: **not confirmed on page**.

**Mapping.** `keep-out clearance volumes`: clear floor space in front of fixtures, door manoeuvring clearances, knee
and toe space under lavatories and counters. `params` min/max: mounting heights, reach ranges, grab-bar heights, door
clear width.

**Rating: use now** for the values; plan on a hand-curated table of perhaps 50 to 100 rules, each citing its section
number.

Sample saved: `samples/ecfr_36cfr1191_excerpt.xml`.

### 20d. Approved Document M (England)

**URL visited:** https://www.gov.uk/government/publications/access-to-and-use-of-buildings-approved-document-m
(published 1 March 2015, last updated 1 October 2024).

PDF only: Volume 1 dwellings (1.66 MB) and Volume 2 buildings other than dwellings with 2024 amendments
(`https://assets.publishing.service.gov.uk/media/66f6c5eec71e42688b65ee11/ADM__V2_with_2024_amendments.pdf`).
I did not open the PDFs, so their tables are **unverified**.

**Licence.** The page footer states "All content is available under the Open Government Licence v3.0".
Whether the PDFs carry any additional third-party copyright notice is **unverified**.

**Mapping.** Same as ADA, for UK users: door widths, corridor widths, WC compartment sizes, clear access zones.

**Rating: use with care** (open licence, but PDF only and needs manual extraction).

### 20e. ISO 21542:2021

**URL visited:** https://www.iso.org/standard/71860.html. Edition 2, published 2021-06, 168 pages, CHF 227, under
review. Paid and copyrighted. **Rating: reference only.**

### 20f. NIST PS 20-20 American Softwood Lumber Standard

**URL checked (headers only):** https://www.nist.gov/system/files/documents/2021/10/26/PS%2020-20%20Revsion%201%20October%202021.pdf
(576,984 bytes, PDF). A search summary says it tabulates nominal and minimum dressed sizes in millimetres and inches;
I did not open it, so the content is **unverified**. Licence not confirmed. Small enough to enter by hand for stud,
joist and timber bricks. **Rating: reference only.**

### 20g. Brick and block sizes

**URL checked (headers only):** https://www.gobrick.com/media/file/10-dimensioning-and-estimating-brick-masonry.pdf
(297,456 bytes). Brick Industry Association Technical Note 10. Content **unverified** (not opened); another BIA note
in the search results carried "(c) 2026 Brick Industry Association". I did not research concrete block (NCMA/CMHA) or
European brick formats. **Rating: reference only.**

### 20h. Door and window sizes

I found no open, machine-readable table of standard door or window sizes from a standards body. IFC defines the
parameters (`OverallWidth`, `OverallHeight`, `Pset_DoorCommon`, `Qto_DoorBaseQuantities`) but no size series. National
size series live in paid standards, which I did not research further. The practical route is the minimum clear widths
from the accessibility documents (20c, 20d) as parameter lower bounds, plus manufacturer data, which another research
track covers.

---

## How the sources line up against brick fields

| Brick field | Best open source | Second source |
|---|---|---|
| `ifc_class` | IFC4.exp (1) | Uniclass IFC mapping column (9) |
| `predefined_type` | IFC4.exp enumerations (1) | bSDD IFC 4.3 classes, which add a definition per predefined type (6) |
| `name`, `description` | bSDD IFC definitions (6), CCI definitions (13) | `ifc4_entities.json` (4) |
| `tags` | ETIM synonyms (15), Uniclass titles (9) | `ifc_classes_suggestions.json` (4), IFC translations (3) |
| `params` names | Qto_ sets (2), ETIM numeric features (15) | COBie Type columns (18) |
| `params` default/min/max | Pipe schedules (20a), steel profiles (5, 20b), accessibility rules (20c, 20d) | none found in the standards; real ranges need manufacturer data |
| `properties` | Pset_ templates (2, 4) | ETIM features (15), COBie (18) |
| classification codes | Uniclass (9), CCI (13), ETIM class id (15) | bSDD URIs (6) |
| `connectors` | Pipe schedules for sizes (20a); ETIM MC connection types (15) | IFC port and flow-direction enumerations in IFC4.exp (1) |
| `mount` | ETIM logical features such as "Suitable for wall mounting" (15) | none |
| keep-out clearances | ADA (20c), Approved Document M (20d) | none |
| `materials` | not covered by this research | IFC material psets are in source 2 |

The clear gap: **no open standard supplies typical dimensions or performance values for equipment.** Standards say
which properties exist and which sizes pipes and steel sections come in. Realistic defaults for a fan coil unit or a
distribution board have to come from manufacturer data or from engineering judgement.

---

## Recommended import order

The five steps below are ordered by value delivered per day of work. Each one is a small script that reads a file
already confirmed to be downloadable and writes a JSON lookup table next to the brick library; none of them changes
the brick schema until step 3.

### 1. IFC4 class and predefined-type catalogue (sources 1 and 4)

Why first: it is tiny, exact, and every later step keys on it.

Import sketch:
1. Download `IFC4.exp` once and store it unmodified with its copyright header.
2. Parse entities, supertypes, the ABSTRACT flag and enumerations (two regular expressions, or `ifcopenshell`'s schema
   API). Walk up the supertype chain to find the `PredefinedType` enumeration for each non-abstract IfcElement subtype.
3. Write `ifc4_catalogue.json`: 130 classes, each with its enumeration values and its type class from
   `entity_to_type_map_4.json`.
4. Add a library check: every brick's `ifc_class` and `predefined_type` must appear in the catalogue.
5. Produce a coverage report: classes and predefined types with zero bricks. With 169 bricks against 130 classes and
   about 640 specific predefined types (876 minus the USERDEFINED/NOTDEFINED pairs), this list is the growth plan.

### 2. Property set and quantity set templates (sources 2 and 4)

Why second: it replaces free-form property names with standard ones and makes exported IFC files pass validation.

Import sketch:
1. Open `Pset_IFC4_ADD2.ifc` with ifcopenshell; iterate the 513 `IfcPropertySetTemplate` objects.
2. For each, split `ApplicableEntity` into class and optional predefined type; record property name, description,
   template kind, measure type and enumeration values.
3. Write `ifc4_psets.json` keyed by class, then by predefined type.
4. In the brick authoring tool, offer these as the default property list for a new brick. Flag existing brick
   properties whose names nearly match a standard property.
5. Cross-check with the IFC4.3 XML ZIP if we later target IFC4.3.

### 3. Uniclass 2015 Products, Systems and Elements tables (source 9)

Why third: it gives classification codes, a ready-made list of thousands of candidate bricks, and an IFC mapping that
a standards body maintains.

Import sketch:
1. Download the quarterly bundle by its dated URL; keep the ZIP unmodified and record the release (2026-07).
2. Read the Pr, Ss and EF workbooks; the header is on row 3. Keep `Code`, `Title`, the level columns and
   `IFC 4Add2 TC1`.
3. Split the IFC column on the dot into type class and predefined type; convert the type class to the occurrence
   class with the map from step 1.
4. Match existing bricks to Uniclass rows by class, predefined type and name similarity; have a person confirm the
   match; store the code and title on the brick.
5. Rank unmatched product rows that have a specific IFC4 mapping as the build backlog.
6. Show the attribution and the CC BY-ND 4.0 notice in the app's credits. Never write new codes into the table.

### 4. ETIM 10.0 classes, features and synonyms (source 15)

Why fourth: it is the only open source that says what a specifier records about a particular product, and it is
strongest exactly where our library is thinnest per class (electrical, HVAC, plumbing).

Import sketch:
1. Download the all-sectors metric CSV ZIP; decode as UTF-16, split on semicolons.
2. Join class to features to units to allowed values; attach synonyms.
3. Build the ETIM-to-IFC link ourselves: match ETIM class names and synonyms against brick names and tags, then
   confirm by hand. Store the ETIM class id (for example EC000393) on the brick.
4. For each linked brick, propose: numeric dimension features as `params`, other features as `properties` with units,
   mounting-suitability features as allowed `mount` values, synonyms as `tags`.
5. Keep ETIM's notices and add the ODC-By attribution.
6. Follow-up: download an ETIM MC release and compare its parametric classes with our geometry primitives.

### 5. Dimension pack: pipe sizes, steel sections, accessibility clearances (sources 20a, 5, 20c)

Why fifth: these are the only verified open sources of real numbers, and they fill `params` ranges, connector sizes
and keep-out volumes across plumbing, fire, HVAC, structure and architecture.

Import sketch:
1. Pipes: read the schedule lists from `fluids/piping.py` (import the package or parse the file), convert millimetres
   to metres, write `pipe_sizes.json` keyed by standard and schedule. Use it as the allowed-value list for diameter
   parameters and connector sizes. Spot-check ten values against a second source.
2. Steel: open `IFC4 EU Steel.ifc` (and the US and AU files) with ifcopenshell, read each profile definition, write
   `steel_profiles.json` with designation and dimensions in metres. Use as presets for beam, column and member bricks.
3. Accessibility: fetch 36 CFR Part 1191 from the eCFR API, extract the numbered clauses that contain dimensions for
   the fixtures and openings we model, and hand-build `clearances_ada.json` where each rule has the section number,
   the value in metres and the brick classes it applies to. Attach these as named keep-out volumes and parameter
   bounds. Repeat from Approved Document M for a UK rule set.

**Runner-up: bSDD (source 6).** Use it as the lookup service behind steps 1, 3 and 4 when a human-readable definition
or a stable URI is needed, through the `bsdd` Python package, with local caching because no rate limit is published.
CCI (source 13) is a half-day add-on at any point: one small ZIP, CC BY 4.0.

---

## Open questions to settle before shipping

1. **CC BY-ND and derived data.** IFC, Uniclass and IDS are all CC BY-ND 4.0. We plan to ship extracts (a JSON
   catalogue, a filtered Uniclass list). Whether a filtered or reformatted extract counts as a derivative needs a
   decision from someone qualified. The cautious route is to ship the original files unmodified and build the lookup
   tables at install time.
2. **Uniclass download.** The website shows a registration form before download, although the file URL works without
   it. Register an account before automating the fetch.
3. **Steel library provenance.** Ask the IfcOpenShell maintainers where the profile dimensions came from.
4. **COBie and NL-SfB licences.** Not stated on the pages fetched; ask the owners.
5. **CSI standards.** Keep OmniClass, MasterFormat and UniFormat out of the shipped library for now.

---

