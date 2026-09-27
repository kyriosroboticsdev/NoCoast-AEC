"""Write backend/blocks/cards/*.md and refuse to if an exemplar does not compile.

Run once when the cards change: python tools/write_cards.py
The markdown files are the source of truth after that; this script is how they were authored
so the numbers stay geometrically valid.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from ifc.compile import compile_ifc
from schemas.geosteps import GeoStep, apply_step
from schemas.geo import GeoModel

ROOT = Path(__file__).resolve().parents[1] / "blocks" / "cards"


def arc(r, a0, a1, n, cx=0.0, cy=0.0):
    return [[round(cx + r * math.cos(a0 + (a1 - a0) * i / n), 4),
             round(cy + r * math.sin(a0 + (a1 - a0) * i / n), 4)] for i in range(n + 1)]


def circle(diameter, n=24):
    r = diameter / 2
    return [[round(r * math.cos(2 * math.pi * i / n), 4), round(r * math.sin(2 * math.pi * i / n), 4)] for i in range(n)]


def semi_xz(r, n, y=0.0, z=0.0):
    return [[round(r * math.cos(math.pi * i / n), 4), y, round(z + r * math.sin(math.pi * i / n), 4)] for i in range(n + 1)]


def dump(steps):
    return json.dumps({"steps": steps}, indent=1)


def card(cid, title, keywords, tags, ifc, summary, notes, steps, ifc_type=None, ifc4x3=None):
    fm = {
        "id": cid, "title": title, "keywords": keywords, "tags": tags, "ifc": ifc,
        "summary": summary,
    }
    if ifc_type:
        fm["ifc_type"] = ifc_type
    if ifc4x3:
        fm["ifc4x3"] = ifc4x3
    import yaml
    lines = ["---", yaml.safe_dump(fm, sort_keys=False).rstrip(), "---"]
    lines.append("")
    lines.append(notes.strip())
    lines.append("")
    lines.append("```json")
    lines.append(dump(steps))
    lines.append("```")
    lines.append("")
    path = ROOT / f"{cid}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    model = GeoModel()
    for raw in steps:
        model, _ = apply_step(model, GeoStep.model_validate(raw))
    ifc_file, _ = compile_ifc(model)
    n = sum(1 for p in ifc_file.by_type("IfcProduct") if getattr(p, "Representation", None) and not p.is_a("IfcOpeningElement"))
    print(f"ok {cid:20s} {n:3d} products")


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    h = 3 * math.tan(math.radians(35))
    t = round(0.25 / math.cos(math.radians(35)), 4)

    card(
        "straight-wall", "Straight wall",
        ["wall", "straight wall", "masonry wall", "partition"],
        ["wall", "residential"],
        "IfcWall",
        "A wall is a polyline thickened into a band and extruded by its height.",
        """
Give the wall its own part. The footprint is a `band`: the centre-line polyline thickened by
`thickness`. Extrude that by the storey height. Local +X of a band that runs east is east, so an
opening's `along` is measured from the start of the line. Use IfcWall / SOLIDWALL for a bearing
or enclosure wall and PARTITIONING only when it separates two spaces and carries nothing.
Material is free text (`masonry`, `concrete`, `timber`).
        """,
        [{"step": "part", "id": "wall", "name": "straight wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
          "material": "masonry", "solid": {"wall": [[0, 0], [8, 0]], "thickness": 0.3, "height": 3}}],
        ifc_type="SOLIDWALL",
    )

    card(
        "wall-openings", "Openings in a wall",
        ["opening", "door", "window", "void", "aperture"],
        ["wall", "residential", "opening"],
        "IfcWall",
        "A door or window is a void cut through a host part, filled by its own part.",
        """
The host is an ordinary wall part. The opening's `along` is the distance along the host's local
+X to the near edge of the void, `up` is the height above the host's base, and `width` / `height`
size the hole. Leave `depth` out and the void goes right through. `fill` is the id of the part
that sits in the hole: an IfcDoor or an IfcWindow, a thin solid of the same width and height.
Add the fill part before the opening. A garage door is IfcDoor / GATE; a skylight is IfcWindow /
SKYLIGHT only when the host is a roof.
        """,
        [
            {"step": "part", "id": "front", "name": "front wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
             "material": "masonry", "solid": {"wall": [[0, 0], [6, 0]], "thickness": 0.24, "height": 3}},
            {"step": "part", "id": "door", "name": "entrance door", "ifc": "IfcDoor", "ifc_type": "DOOR",
             "material": "timber", "at": [0.85, 0, 0],
             "solid": {"box": [0.9, 0.05, 2.1]}},
            {"step": "part", "id": "window", "name": "front window", "ifc": "IfcWindow", "ifc_type": "WINDOW",
             "material": "glass", "at": [3.7, 0, 0.9],
             "solid": {"box": [1.4, 0.05, 1.2]}},
            {"step": "opening", "id": "door-void", "host": "front", "along": 0.4, "up": 0, "width": 0.9, "height": 2.1, "fill": "door"},
            {"step": "opening", "id": "window-void", "host": "front", "along": 3.0, "up": 0.9, "width": 1.4, "height": 1.2, "fill": "window"},
        ],
        ifc_type="SOLIDWALL",
    )

    card(
        "party-wall", "Party wall",
        ["party wall", "terrace", "semi-detached", "dwelling", "multi-storey", "two storey"],
        ["wall", "residential"],
        "IfcWall",
        "Two dwellings share one wall; each habitable room is an IfcSpace, stacked on storeys.",
        """
A party wall is just a wall whose two faces each bound a different space. Model each dwelling as
an IfcSpace with a name (`dwelling A`, `bedroom`), on a level. Stack storeys with `level` steps
(L1 then L2); a part may be taller than its level, so one party wall can rise through both.
Give each storey its own floor slab. Do not invent a room type: the name on the space is the
whole of the label.
        """,
        [
            {"step": "level", "id": "L2", "name": "Upper", "height": 3},
            {"step": "part", "id": "slab-l1", "name": "ground floor", "ifc": "IfcSlab", "ifc_type": "FLOOR",
             "level": "L1", "material": "concrete", "solid": {"op": "extrude", "profile": {"points": [[0, 0], [12, 0], [12, 8], [0, 8]]}, "depth": 0.2}},
            {"step": "part", "id": "slab-l2", "name": "upper floor", "ifc": "IfcSlab", "ifc_type": "FLOOR",
             "level": "L2", "material": "concrete", "solid": {"op": "extrude", "profile": {"points": [[0, 0], [12, 0], [12, 8], [0, 8]]}, "depth": 0.2}},
            {"step": "part", "id": "party", "name": "party wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
             "level": "L1", "material": "masonry", "at": [6, 4, 0],
             "solid": {"op": "extrude", "profile": {"rect": [0.3, 8]}, "depth": 6}},
            {"step": "part", "id": "space-a1", "name": "dwelling A", "ifc": "IfcSpace", "ifc_type": "SPACE",
             "level": "L1", "at": [3, 4, 0.2], "solid": {"box": [5.4, 7.4, 2.7]}},
            {"step": "part", "id": "space-b1", "name": "dwelling B", "ifc": "IfcSpace", "ifc_type": "SPACE",
             "level": "L1", "at": [9, 4, 0.2], "solid": {"box": [5.4, 7.4, 2.7]}},
            {"step": "part", "id": "space-a2", "name": "bedroom A", "ifc": "IfcSpace", "ifc_type": "SPACE",
             "level": "L2", "at": [3, 4, 0.2], "solid": {"box": [5.4, 7.4, 2.7]}},
            {"step": "part", "id": "space-b2", "name": "bedroom B", "ifc": "IfcSpace", "ifc_type": "SPACE",
             "level": "L2", "at": [9, 4, 0.2], "solid": {"box": [5.4, 7.4, 2.7]}},
        ],
        ifc_type="SOLIDWALL",
    )

    card(
        "floor-plate", "Floor plate",
        ["floor", "slab", "floor plate", "deck plate"],
        ["slab"],
        "IfcSlab",
        "A floor is a polygon extruded by its thickness, sitting on its level.",
        """
One IfcSlab / FLOOR per storey. The profile is the outline in plan, counter-clockwise, extruded
by the slab thickness (0.2 m is a ordinary plate). A hole in the plate — a stair well, an atrium —
is a ring in `holes`, wound either way. BASESLAB is the plate on the ground; LANDING is a stair
landing. The plate's part sits at local z = 0 of its level unless it is raised.
        """,
        [{"step": "part", "id": "floor", "name": "floor plate", "ifc": "IfcSlab", "ifc_type": "FLOOR",
          "material": "concrete",
          "solid": {"op": "extrude", "depth": 0.2, "profile": {
              "points": [[0, 0], [10, 0], [10, 8], [0, 8]],
              "holes": [[[4, 3], [6, 3], [6, 5], [4, 5]]]}}}],
        ifc_type="FLOOR",
    )

    card(
        "column-grid", "Column grid",
        ["column", "colonnade", "grid", "bay", "pier row", "posts"],
        ["structure", "array"],
        "IfcColumn",
        "A repeated bay is one column, grouped, then instanced on a grid.",
        """
Model one column. Group it in an assembly. `instance` with `repeat` places a row; a second
instance with a different `at` places the next row. Copy ids are `<instance>-<part>`, stable
across edits. Do not also set `repeat` on the column itself — an instance copies the part's own
repeat and you would get a row of rows. A colonnade is this card with one row.
        """,
        [
            {"step": "part", "id": "col", "name": "column", "ifc": "IfcColumn", "ifc_type": "COLUMN",
             "material": "concrete", "solid": {"box": [0.4, 0.4, 4]}},
            {"step": "assembly", "id": "bay", "name": "bay", "parts": ["col"]},
            {"step": "instance", "id": "row-a", "of": "bay", "repeat": {"count": 4, "translate": [4, 0, 0]}},
            {"step": "instance", "id": "row-b", "of": "bay", "at": [0, 4, 0], "repeat": {"count": 4, "translate": [4, 0, 0]}},
        ],
        ifc_type="COLUMN",
    )

    card(
        "beam", "Beam",
        ["beam", "girder", "lintel", "joist"],
        ["structure"],
        "IfcBeam",
        "A beam is a box as long as its span, sitting with its top at the level height.",
        """
Profile a rectangle `length` by `width`, centred on the span's midpoint, rotated so local +X runs
along the span, and extrude downward... actually extrude upward from `z = storey height − depth`
so the beam hangs under the floor it carries. IfcBeam / BEAM for a girder, JOIST for a joist,
LINTEL over an opening. A sloped member (a rafter) is an IfcMember instead, with `axis` along
the member — see the truss card.
        """,
        [{"step": "part", "id": "beam", "name": "girder", "ifc": "IfcBeam", "ifc_type": "BEAM",
          "material": "concrete", "at": [4, 3, 2.6],
          "solid": {"op": "extrude", "profile": {"rect": [8, 0.3]}, "depth": 0.5}}],
        ifc_type="BEAM",
    )

    card(
        "foundation-pile", "Foundation and pile",
        ["foundation", "footing", "pile", "pad", "piled"],
        ["foundation"],
        "IfcFooting",
        "A pad footing at grade with a pile continuing down below it.",
        """
IfcFooting / PAD_FOOTING is a box at z = 0, wider than the thing it carries. IfcPile / BORED is
a cylinder whose top meets the underside of the pad and whose length is the embedment: place it
at `z = -length` and extrude up by `length`. STRIP_FOOTING is the same pad stretched under a wall.
IFC4X3 would type a piled foundation more richly; the geometry does not change.
        """,
        [
            {"step": "part", "id": "pad", "name": "pad footing", "ifc": "IfcFooting", "ifc_type": "PAD_FOOTING",
             "material": "concrete", "at": [0, 0, 0], "solid": {"box": [1.8, 1.8, 0.5]}},
            {"step": "part", "id": "pile", "name": "bored pile", "ifc": "IfcPile", "ifc_type": "BORED",
             "material": "concrete", "at": [0, 0, -8], "solid": {"cylinder": [0.45, 8]}},
        ],
        ifc_type="PAD_FOOTING",
        ifc4x3="IfcDeepFoundation",
    )

    card(
        "pitched-roof", "Pitched roof",
        ["roof", "gable", "pitched roof", "pitch"],
        ["roof", "residential"],
        "IfcRoof",
        "A gable is a chevron profile extruded along the ridge.",
        """
The chevron lives in a vertical plane and is extruded along the ridge. Set the solid's `axis` to
`[1, 0, 0]` so local +Z (the extrusion) runs east along the ridge; the profile's x is then north
and its y is up. Rise = half the span × tan(pitch). Give the chevron a thickness perpendicular
to the slope (`thickness / cos(pitch)` measured vertically) so the solid closes. A triangular
infill at each end, same profile, extruded a short distance, closes the attic. Sit the part at
`z = storey height`. HIP_ROOF is the mesh card's territory: a hip is not an extrusion.
        """,
        [
            {"step": "part", "id": "gable", "name": "gable roof", "ifc": "IfcRoof", "ifc_type": "GABLE_ROOF",
             "material": "tile", "at": [0, 0, 3], "axis": [1, 0, 0],
             "solids": [
                 {"op": "extrude", "depth": 8, "profile": {"points": [[0, 0], [3, round(h, 4)], [6, 0], [6, t], [3, round(h + t, 4)], [0, t]]}},
                 {"op": "extrude", "depth": 0.2, "profile": {"points": [[0, 0], [3, round(h, 4)], [6, 0]]}},
                 {"op": "extrude", "at": [0, 0, 7.8], "depth": 0.2, "profile": {"points": [[0, 0], [3, round(h, 4)], [6, 0]]}},
             ]},
        ],
        ifc_type="GABLE_ROOF",
    )

    card(
        "flat-roof", "Flat roof and parapet",
        ["flat roof", "parapet", "roof terrace"],
        ["roof", "residential"],
        "IfcRoof",
        "A flat roof is a plate, with a low wall around it when it is a terrace.",
        """
IfcRoof / FLAT_ROOF, extruded by 0.2 m, at the top of the storey. A parapet is an IfcWall /
PARAPET: a closed `band` around the same outline, sitting on the roof, 0.9 m high and about
0.15 m thick. Closed means the band joins back on itself, so the parapet is a ring.
        """,
        [
            {"step": "part", "id": "roof", "name": "flat roof", "ifc": "IfcRoof", "ifc_type": "FLAT_ROOF",
             "material": "membrane", "at": [0, 0, 3],
             "solid": {"op": "extrude", "depth": 0.2, "profile": {"points": [[0, 0], [10, 0], [10, 7], [0, 7]]}}},
            {"step": "part", "id": "parapet", "name": "parapet", "ifc": "IfcWall", "ifc_type": "PARAPET",
             "material": "concrete", "at": [0, 0, 3.2],
             "solid": {"op": "extrude", "depth": 0.9, "profile": {"band": [[0, 0], [10, 0], [10, 7], [0, 7]], "width": 0.15, "closed": True}}},
        ],
        ifc_type="FLAT_ROOF",
    )

    path = [[round(x, 4), round(1.2 * math.sin(x / 10), 4), 8] for x in range(0, 31, 5)]
    piers = []
    for i, x in enumerate((0, 10, 20, 30)):
        piers.append({"step": "part", "id": f"pier-{i+1}", "name": f"pier {i+1}", "ifc": "IfcColumn",
                      "ifc_type": "COLUMN", "material": "concrete", "at": [x, 0, 0],
                      "solid": {"box": [0.9, 0.9, 8]}})
    card(
        "bridge", "Bridge deck on piers",
        ["bridge", "viaduct", "deck", "pier", "span", "curved deck"],
        ["civil", "bridge"],
        "IfcSlab",
        "Piers stand on the ground; a swept slab follows a curve at deck level.",
        """
IFC4 has no IfcBridge. Type the deck as IfcSlab / FLOOR (or IfcCivilElement if it is not a
floor in any sense) and each pier as IfcColumn. The deck is a `sweep`: a wide, thin rectangle
carried along a 3D polyline at the deck elevation, so the deck can curve in plan and change
level. Put a pier under the path, not on a straight grid — a `repeat` is right only for a
straight viaduct. Group deck and piers in one assembly. IFC4X3 would use IfcBridge and
IfcBridgePart for the span and the piers.
        """,
        piers + [
            {"step": "part", "id": "deck", "name": "curved deck", "ifc": "IfcSlab", "ifc_type": "FLOOR",
             "material": "concrete", "solid": {"op": "sweep", "profile": {"rect": [8, 0.45]}, "path": path}},
            {"step": "assembly", "id": "bridge", "name": "bridge", "parts": ["pier-1", "pier-2", "pier-3", "pier-4", "deck"],
             "ifc_type": "RIGID_FRAME"},
        ],
        ifc_type="FLOOR",
        ifc4x3="IfcBridge",
    )

    card(
        "retaining-wall", "Retaining wall",
        ["retaining wall", "retaining", "batter", "embankment"],
        ["civil", "wall"],
        "IfcWall",
        "A retaining wall is a battered cross-section extruded along its length.",
        """
The cross-section is a trapezoid, wide at the base, extruded along the wall. Point the solid's
`axis` along the wall (`[1, 0, 0]` runs it east); the profile's x is then across the wall and
its y is up. IFC4 has no IfcRetainingWall — IfcWall / SOLIDWALL is the closest — and the card
would say IfcRetainingWall on IFC4X3. Name the part "retaining wall" so a check can find it.
        """,
        [{"step": "part", "id": "retaining", "name": "retaining wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
          "material": "concrete", "axis": [1, 0, 0],
          "solid": {"op": "extrude", "depth": 12, "profile": {"points": [[0, 0], [1.4, 0], [0.45, 4], [0, 4]]}}}],
        ifc_type="SOLIDWALL",
        ifc4x3="IfcRetainingWall",
    )

    hole = circle(5.2, 16)
    card(
        "tunnel", "Tunnel bore",
        ["tunnel", "bore", "underground", "subway", "buried"],
        ["civil", "underground"],
        "IfcCivilElement",
        "A tunnel lining is a ring swept along the bore, on a level whose elevation is the crown depth.",
        """
Add a level below ground (`B1`) and set `elevation` to the bore's datum — a tunnel is not a
basement stacked by storey height, so say the elevation explicitly (negative, metres). The
lining is a `sweep` of a circular profile with a circular `hole`: outer diameter the excavation,
inner diameter the clear bore. The path is the centre-line in 3D, so the bore can slope and
curve. IFC4 types this as IfcCivilElement. IFC4X3 would use IfcTunnel.
        """,
        [
            {"step": "level", "id": "B1", "name": "bore", "height": 8, "elevation": -18},
            {"step": "part", "id": "lining", "name": "tunnel lining", "ifc": "IfcCivilElement", "level": "B1",
             "material": "concrete",
             "solid": {"op": "sweep", "profile": {"circle": 6.4, "holes": [hole]},
                       "path": [[0, 0, 0], [12, 0, 0], [24, 4, -0.5], [36, 8, -1]]}},
        ],
        ifc4x3="IfcTunnel",
    )

    card(
        "culvert", "Culvert",
        ["culvert", "box culvert", "underpass"],
        ["civil", "underground"],
        "IfcCivilElement",
        "A box culvert is a rectangular tube extruded along its length.",
        """
Same idea as the tunnel, shorter and rectangular. Extrude a hollow rectangle along the culvert:
`axis` along its length, the profile the cross-section (outer ring and one hole). Bury it by
putting the part on a below-ground level or at a negative local z. IFC4X3 would still call the
whole thing a civil facility; IfcTunnelPart is the closest named piece.
        """,
        [
            {"step": "level", "id": "B1", "name": "culvert", "height": 4, "elevation": -3},
            {"step": "part", "id": "culvert", "name": "box culvert", "ifc": "IfcCivilElement", "level": "B1",
             "material": "concrete", "axis": [1, 0, 0],
             "solid": {"op": "extrude", "depth": 8, "profile": {
                 "points": [[-1.6, 0], [1.6, 0], [1.6, 2], [-1.6, 2]],
                 "holes": [[[-1.2, 0.25], [1.2, 0.25], [1.2, 1.6], [-1.2, 1.6]]]}}},
        ],
        ifc4x3="IfcTunnelPart",
    )

    card(
        "dome", "Dome",
        ["dome", "hemisphere", "cupola", "rotunda"],
        ["curved", "roof"],
        "IfcRoof",
        "A dome is a semicircle revolved a full turn and stood upright.",
        """
Draw the semicircle in the profile plane, entirely on one side of the axis (the axis is the
profile's Y by default, so the semicircle occupies +X). Revolve 360°. The result lies on its
side until you set the solid's `axis` to `[0, -1, 0]`, which points the profile's Y up. IfcRoof
/ DOME_ROOF. A dome on a drum is this solid sitting at `z = drum height`, with the drum a
separate cylindrical wall.
        """,
        [{"step": "part", "id": "dome", "name": "dome", "ifc": "IfcRoof", "ifc_type": "DOME_ROOF",
          "material": "stone",
          "solid": {"op": "revolve", "angle": 360, "axis": [0, -1, 0], "axis_dir": [0, 1],
                    "profile": {"points": arc(4, -math.pi / 2, math.pi / 2, 16)}}}],
        ifc_type="DOME_ROOF",
    )

    card(
        "barrel-vault", "Barrel vault",
        ["vault", "barrel vault", "wagon vault"],
        ["curved", "roof"],
        "IfcRoof",
        "A barrel vault is a semicircle revolved halfway about its diameter.",
        """
The profile is a semicircle standing above its diameter. `axis_dir` `[1, 0]` lays the axis
along the profile's X, and `angle` 180 sweeps a half-cylinder. The vault's length is the
diameter; for a longer nave, sweep the same semicircular section along a straight path instead
of revolving it. IfcRoof / BARREL_ROOF.
        """,
        [{"step": "part", "id": "vault", "name": "barrel vault", "ifc": "IfcRoof", "ifc_type": "BARREL_ROOF",
          "material": "masonry",
          "solid": {"op": "revolve", "angle": 180, "axis_dir": [1, 0],
                    "profile": {"points": arc(3, 0, math.pi, 12)}}}],
        ifc_type="BARREL_ROOF",
    )

    card(
        "arch", "Arch",
        ["arch", "archway", "voussoir"],
        ["curved", "structure"],
        "IfcMember",
        "An arch is a small cross-section swept along a semicircular centre-line.",
        """
`sweep` carries the section (a rectangle, the arch ring's depth and width) along a semicircle
in a vertical plane. The path is the centre-line, from one springing up over the crown and down
to the other; it needs several points or the curve facets coarsely. IfcMember / MEMBER. An
assembly of the arch plus its two abutments can be typed ARCH. IFC4X3 has nothing more specific.
        """,
        [
            {"step": "part", "id": "arch", "name": "arch", "ifc": "IfcMember", "ifc_type": "MEMBER",
             "material": "stone",
             "solid": {"op": "sweep", "profile": {"rect": [0.45, 0.3]}, "path": semi_xz(3, 12)}},
            {"step": "part", "id": "abutment-w", "name": "west abutment", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
             "material": "stone", "at": [-3, 0, 0], "solid": {"box": [0.6, 0.8, 0.4]}},
            {"step": "part", "id": "abutment-e", "name": "east abutment", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
             "material": "stone", "at": [3, 0, 0], "solid": {"box": [0.6, 0.8, 0.4]}},
            {"step": "assembly", "id": "archway", "name": "archway", "parts": ["arch", "abutment-w", "abutment-e"],
             "ifc_type": "ARCH"},
        ],
        ifc_type="MEMBER",
    )

    # Cooling-tower-like shell: a closed strip of varying radius, revolved and stood up.
    outer = [[3.2, 0], [2.4, 2], [2.0, 4], [2.3, 6], [3.0, 8]]
    inner = [[2.8, 0], [2.1, 2], [1.75, 4], [2.05, 6], [2.65, 8]]
    shell_pts = outer + inner[::-1]
    card(
        "shell", "Shell of revolution",
        ["shell", "hyperboloid", "cooling tower", "thin shell"],
        ["curved"],
        "IfcRoof",
        "A shell of revolution is a thick profile, off the axis, revolved a full turn.",
        """
The profile is a closed strip: the outside meridian and the inside meridian, so the revolve
makes a hollow shell rather than a solid of the whole radius. Keep every vertex on one side of
the axis. Stand it up with `axis: [0, -1, 0]`. IfcRoof / FREEFORM is an honest IFC4 typing;
the shape is not a dome and not a slab.
        """,
        [{"step": "part", "id": "shell", "name": "shell", "ifc": "IfcRoof", "ifc_type": "FREEFORM",
          "material": "concrete",
          "solid": {"op": "revolve", "angle": 360, "axis": [0, -1, 0], "axis_dir": [0, 1],
                    "profile": {"points": shell_pts}}}],
        ifc_type="FREEFORM",
    )

    card(
        "truss", "Truss",
        ["truss", "rafter", "chord", "roof truss"],
        ["structure"],
        "IfcMember",
        "A truss is members whose axis follows each bar, grouped as an IfcElementAssembly / TRUSS.",
        """
Each bar is its own IfcMember. A horizontal chord uses an ordinary extrusion. A sloping rafter
sets `axis` to the bar's direction and extrudes a small rectangle by the bar's length, with the
part origin at the bar's start. CHORD for the tie, RAFTER for the slopes. The assembly's
predefined type is TRUSS.
        """,
        [
            {"step": "part", "id": "tie", "name": "bottom chord", "ifc": "IfcMember", "ifc_type": "CHORD",
             "material": "timber", "at": [3, 0, 0.1], "solid": {"op": "extrude", "profile": {"rect": [6, 0.12]}, "depth": 0.2}},
            {"step": "part", "id": "rafter-w", "name": "west rafter", "ifc": "IfcMember", "ifc_type": "RAFTER",
             "material": "timber", "at": [0, 0, 0.2], "axis": [0.8944, 0, 0.4472],
             "solid": {"op": "extrude", "profile": {"rect": [0.12, 0.16]}, "depth": 3.354}},
            {"step": "part", "id": "rafter-e", "name": "east rafter", "ifc": "IfcMember", "ifc_type": "RAFTER",
             "material": "timber", "at": [6, 0, 0.2], "axis": [-0.8944, 0, 0.4472],
             "solid": {"op": "extrude", "profile": {"rect": [0.12, 0.16]}, "depth": 3.354}},
            {"step": "assembly", "id": "truss", "name": "truss", "parts": ["tie", "rafter-w", "rafter-e"], "ifc_type": "TRUSS"},
        ],
        ifc_type="CHORD",
    )

    card(
        "ramp", "Ramp",
        ["ramp", "slope", "inclined"],
        ["circulation"],
        "IfcRamp",
        "A straight ramp is a wedge: a right triangle extruded across its width.",
        """
The triangle's base is the run and its height is the rise. Point `axis` along the width
(`[0, 1, 0]` extrudes north) so the triangle stands in a vertical plane along the run. IfcRamp /
STRAIGHT_RUN_RAMP. A spiral ramp is the same section swept along a rising helix, or one wedge
repeated with a turn — see the helical stair, which is the same move.
        """,
        [{"step": "part", "id": "ramp", "name": "ramp", "ifc": "IfcRamp", "ifc_type": "STRAIGHT_RUN_RAMP",
          "material": "concrete", "axis": [0, 1, 0],
          "solid": {"op": "extrude", "depth": 2, "profile": {"points": [[0, 0], [8, 0], [8, 1.2]]}}}],
        ifc_type="STRAIGHT_RUN_RAMP",
    )

    card(
        "spiral-stair", "Spiral stair",
        ["spiral stair", "helical stair", "spiral", "helix", "winding stair"],
        ["circulation", "array"],
        "IfcStair",
        "One tread, repeated with a rise and a turn about the same centre.",
        """
A helical stair is a single part. The solid is one tread (a short extrusion), placed out from
the centre. `repeat` makes the rest: `translate` is the rise per step, `rotate` is the turn per
step in degrees, `about` is the plan centre. `count` includes the original. IfcStair /
SPIRAL_STAIR. The same pattern with no `rotate` is a straight flight; with a larger translate
and a floor profile it is a spiral ramp.
        """,
        [{"step": "part", "id": "tread", "name": "helical stair", "ifc": "IfcStair", "ifc_type": "SPIRAL_STAIR",
          "material": "timber",
          "repeat": {"count": 18, "translate": [0, 0, 0.18], "rotate": 20, "about": [0, 0]},
          "solid": {"op": "extrude", "at": [0.45, 0, 0], "profile": {"rect": [0.9, 0.28]}, "depth": 0.04}}],
        ifc_type="SPIRAL_STAIR",
    )

    card(
        "straight-stair", "Straight stair",
        ["stair", "straight stair", "flight", "staircase"],
        ["circulation", "residential"],
        "IfcStair",
        "A straight flight is one tread repeated along its run, rising each time.",
        """
Same part as the spiral stair with `rotate` left at 0 and `translate` equal to the going and the
riser, for example `[0.26, 0, 0.175]`. Sixteen copies climb about 2.8 m in 4.2 m of run. IfcStair
/ STRAIGHT_RUN_STAIR. Cut a hole in the slab above with an opening whose `solid` is a box over
the upper part of the flight; the hole is a void, not a room.
        """,
        [{"step": "part", "id": "flight", "name": "straight stair", "ifc": "IfcStair", "ifc_type": "STRAIGHT_RUN_STAIR",
          "material": "timber",
          "repeat": {"count": 16, "translate": [0.26, 0, 0.175]},
          "solid": {"op": "extrude", "profile": {"rect": [0.28, 1.0]}, "depth": 0.04}}],
        ifc_type="STRAIGHT_RUN_STAIR",
    )

    card(
        "curtain-wall", "Curtain wall",
        ["curtain wall", "mullion", "glazing", "glass wall"],
        ["wall"],
        "IfcCurtainWall",
        "A glazed wall is a thin IfcCurtainWall; the mullions are repeated IfcMembers.",
        """
The glass is one IfcCurtainWall, a thin plate the size of the elevation. IfcCurtainWall's only
predefined types are USERDEFINED and NOTDEFINED, so leave `ifc_type` unset or NOTDEFINED.
Mullions are IfcMember / MULLION, one of them repeated across the bay. Give the glass
`material: glass` so it reads as transparent.
        """,
        [
            {"step": "part", "id": "glazing", "name": "curtain wall", "ifc": "IfcCurtainWall",
             "material": "glass", "solid": {"box": [8, 0.06, 3.4]}},
            {"step": "part", "id": "mullion", "name": "mullion", "ifc": "IfcMember", "ifc_type": "MULLION",
             "material": "aluminium", "at": [-3.6, 0, 0],
             "repeat": {"count": 7, "translate": [1.2, 0, 0]},
             "solid": {"box": [0.06, 0.12, 3.4]}},
        ],
    )

    card(
        "canopy", "Canopy",
        ["canopy", "porch roof", "overhang", "awning"],
        ["roof"],
        "IfcRoof",
        "A canopy is a thin plate on posts, larger than the posts' footprint so it overhangs.",
        """
Two or more IfcColumns carry an IfcRoof / FLAT_ROOF (or IfcSlab / ROOF) placed at the top of the
posts. The plate's outline extends past the posts on the open sides; that overhang is just
geometry, not a separate kind of element. Name it "canopy".
        """,
        [
            {"step": "part", "id": "post-a", "name": "post", "ifc": "IfcColumn", "ifc_type": "COLUMN",
             "material": "steel", "at": [0.5, 0.5, 0], "solid": {"box": [0.15, 0.15, 3]}},
            {"step": "part", "id": "post-b", "name": "post", "ifc": "IfcColumn", "ifc_type": "COLUMN",
             "material": "steel", "at": [0.5, 3.5, 0], "solid": {"box": [0.15, 0.15, 3]}},
            {"step": "part", "id": "canopy", "name": "canopy", "ifc": "IfcRoof", "ifc_type": "FLAT_ROOF",
             "material": "steel", "at": [2, 2, 3],
             "solid": {"op": "extrude", "profile": {"rect": [6, 5]}, "depth": 0.08}},
        ],
        ifc_type="FLAT_ROOF",
    )

    card(
        "louvre", "Louvre",
        ["louvre", "louver", "brise-soleil", "screen", "fins"],
        ["array"],
        "IfcPlate",
        "A louvre is one tilted blade repeated on a regular pitch.",
        """
One blade: a thin rectangle extruded along its length, with `axis` leaned off vertical so the
blade tilts. `repeat` steps the next blade along the pitch. IfcPlate / SHEET. The tilt is the
solid's axis, not a rotation of the whole screen, so every copy leans the same way.
        """,
        [{"step": "part", "id": "blade", "name": "louvre", "ifc": "IfcPlate", "ifc_type": "SHEET",
          "material": "aluminium", "axis": [0, 0.35, 0.937],
          "repeat": {"count": 10, "translate": [0, 0.22, 0]},
          "solid": {"op": "extrude", "profile": {"rect": [2.4, 0.02]}, "depth": 0.4}}],
        ifc_type="SHEET",
    )

    card(
        "void-shaft", "Void and shaft",
        ["void", "shaft", "atrium", "stair well", "lightwell"],
        ["opening", "residential"],
        "IfcSlab",
        "A shaft is a hole through a slab with a wall around the hole.",
        """
The slab's profile carries the shaft as a `hole`. The shaft wall is a closed band on the hole's
outline, extruded the storey height, sitting on the slab. Nothing is named "void" in IFC: the
hole is an inner ring, and a vertical shaft people occupy can also be an IfcSpace inside it.
An opening element is for a void cut through a host that you did not model as a hole in the
profile — a door, a window, a well cut into an existing plate.
        """,
        [
            {"step": "part", "id": "slab", "name": "floor with shaft", "ifc": "IfcSlab", "ifc_type": "FLOOR",
             "material": "concrete",
             "solid": {"op": "extrude", "depth": 0.2, "profile": {
                 "points": [[0, 0], [8, 0], [8, 6], [0, 6]],
                 "holes": [[[3, 2], [5, 2], [5, 4], [3, 4]]]}}},
            {"step": "part", "id": "shaft", "name": "shaft wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
             "material": "concrete", "at": [0, 0, 0.2],
             "solid": {"op": "extrude", "depth": 3, "profile": {"band": [[3, 2], [5, 2], [5, 4], [3, 4]], "width": 0.2, "closed": True}}},
        ],
        ifc_type="FLOOR",
    )

    card(
        "cantilever", "Cantilever",
        ["cantilever", "overhang", "projecting"],
        ["structure"],
        "IfcSlab",
        "A cantilever is a plate that runs past the last thing holding it up.",
        """
Model the support (a wall or a column) and the plate as two parts. The plate's outline simply
continues past the support; there is no cantilever entity. The plate's base should meet the
support's top, and the unsupported length is whatever the outline says. IfcSlab / FLOOR or
IfcBeam for a cantilevered beam — same geometry, the beam's span past the support.
        """,
        [
            {"step": "part", "id": "support", "name": "support wall", "ifc": "IfcWall", "ifc_type": "SHEAR",
             "material": "concrete", "at": [0.2, 2, 0], "solid": {"box": [0.4, 4, 3]}},
            {"step": "part", "id": "slab", "name": "cantilever slab", "ifc": "IfcSlab", "ifc_type": "FLOOR",
             "material": "concrete", "at": [3, 2, 3],
             "solid": {"op": "extrude", "profile": {"rect": [6, 4]}, "depth": 0.25}},
        ],
        ifc_type="FLOOR",
    )

    card(
        "space", "Enclosed space",
        ["space", "room", "enclosure", "habitable"],
        ["residential"],
        "IfcSpace",
        "A room is an IfcSpace volume standing inside walls, not a special object.",
        """
Draw the walls (bands or boxes), the floor plate, and an IfcSpace / SPACE whose box is the clear
interior, named for what it is (`bedroom`, `kitchen`, `hall`). The space is what a count of
"bedrooms" looks for: the check matches the name, it does not know a room type. A door is an
opening in a wall, filled by an IfcDoor. Give the space a height just under the storey so it
does not stick through the slab above.
        """,
        [
            {"step": "part", "id": "floor", "name": "floor", "ifc": "IfcSlab", "ifc_type": "FLOOR",
             "material": "concrete", "solid": {"op": "extrude", "depth": 0.2, "profile": {"rect": [6, 4]}}},
            {"step": "part", "id": "wall-s", "name": "south wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
             "material": "masonry", "solid": {"wall": [[-3, -2], [3, -2]], "thickness": 0.2, "height": 3}},
            {"step": "part", "id": "wall-n", "name": "north wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
             "material": "masonry", "solid": {"wall": [[-3, 2], [3, 2]], "thickness": 0.2, "height": 3}},
            {"step": "part", "id": "wall-w", "name": "west wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
             "material": "masonry", "solid": {"wall": [[-3, -2], [-3, 2]], "thickness": 0.2, "height": 3}},
            {"step": "part", "id": "wall-e", "name": "east wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
             "material": "masonry", "solid": {"wall": [[3, -2], [3, 2]], "thickness": 0.2, "height": 3}},
            {"step": "part", "id": "room", "name": "bedroom", "ifc": "IfcSpace", "ifc_type": "SPACE",
             "at": [0, 0, 0.2], "solid": {"box": [5.5, 3.5, 2.7]}},
            {"step": "part", "id": "door", "name": "door", "ifc": "IfcDoor", "ifc_type": "DOOR",
             "material": "timber", "at": [0, -2, 0], "solid": {"box": [0.9, 0.05, 2.1]}},
            {"step": "opening", "id": "door-void", "host": "wall-s", "along": -0.45, "up": 0, "width": 0.9, "height": 2.1, "fill": "door"},
        ],
        ifc_type="SPACE",
    )

    card(
        "tower", "Cylindrical tower",
        ["tower", "cylinder", "drum", "rotunda wall"],
        ["curved", "wall"],
        "IfcWall",
        "A round tower is a closed circular band extruded by its height.",
        """
`band` with `closed: true` thickens a ring into an annulus — the wall of a tower, a drum, a
circular parapet. Extrude by the height. A cone or dome sits on top as its own part (see the
dome and spire cards). IfcWall / SOLIDWALL.
        """,
        [{"step": "part", "id": "tower", "name": "tower", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
          "material": "masonry",
          "solid": {"op": "extrude", "depth": 9, "profile": {"band": circle(8, 24), "width": 0.4, "closed": True}}}],
        ifc_type="SOLIDWALL",
    )

    card(
        "spire", "Cone and spire",
        ["spire", "cone", "steeple"],
        ["curved", "roof"],
        "IfcRoof",
        "A spire is a triangle revolved about its upright side.",
        """
The profile is a thin closed triangle on one side of the axis: the base radius at the bottom,
nearly nothing at the tip, and a small thickness so it is a shell rather than a solid cone of
the whole radius. Revolve 360° and stand it up with `axis: [0, -1, 0]`. IfcRoof / FREEFORM.
        """,
        [{"step": "part", "id": "spire", "name": "spire", "ifc": "IfcRoof", "ifc_type": "FREEFORM",
          "material": "copper",
          "solid": {"op": "revolve", "angle": 360, "axis": [0, -1, 0], "axis_dir": [0, 1],
                    "profile": {"points": [[2.2, 0], [0.15, 7], [0.05, 7], [0.15, 0]]}}}],
        ifc_type="FREEFORM",
    )


if __name__ == "__main__":
    main()
