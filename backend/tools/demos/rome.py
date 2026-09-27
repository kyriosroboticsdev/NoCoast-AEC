"""Prebuilt demo: the Colosseum valley in Rome, c. 320 AD, as a NoCoast BuildingSpec → IFC4.

Everything is expressed in the backend's own spec schema and compiled by its IfcOpenShell builder,
so the result is a native NoCoast model (it can be opened, lifted into a project and edited by prompt).

Scope: the Colosseum at the centre, then what stood around it — Meta Sudans, the Colossus, the Arch of
Constantine, the Ludus Magnus (with its tunnel), the Via Sacra, the Temple of Venus and Roma, the Arch of
Titus and the Basilica of Maxentius. It stops at the edge of the Forum.

Dimensions follow published figures (Colosseum 189 × 156 × 48 m, 80 bays; Arch of Constantine
25.9 × 7.4 × 21 m; Arch of Titus 13.5 × 4.75 × 15.4 m; temple platform 145 × 100 m; basilica 100 × 65 m).
Site positions are approximate. The plan is rotated ~20° so the Via Sacra runs along +x (x ≈ ESE, y ≈ NNE).

Run from the repo root (uses the backend venv):

    backend/.venv/Scripts/python backend/tools/demos/rome.py      # Windows; backend/.venv/bin/python elsewhere

It writes frontend/public/samples/rome_colosseum_valley.ifc (open it in the app with
?autoload=samples/rome_colosseum_valley.ifc, or Open IFC…). Pass an output path to write elsewhere.
"""

from __future__ import annotations

import bisect
import json
import math
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else BACKEND.parent / "frontend" / "public" / "samples" / "rome_colosseum_valley.ifc"
sys.path.insert(0, str(BACKEND))

from schemas.bim import BuildingSpec  # noqa: E402
from ifc.builder import write_ifc  # noqa: E402

E: list[dict] = []  # elements


def add(**el) -> dict:
    E.append(el)
    return el


# --- geometry helpers ----------------------------------------------------------------------------

class Ellipse:
    """Arc-length parametrised ellipse (so bays come out evenly spaced along the facade)."""

    def __init__(self, a: float, b: float, cx: float = 0.0, cy: float = 0.0, n: int = 6000):
        self.a, self.b, self.cx, self.cy = a, b, cx, cy
        self.ts = [2 * math.pi * i / n for i in range(n + 1)]
        self.s = [0.0]
        for t0, t1 in zip(self.ts, self.ts[1:]):
            self.s.append(self.s[-1] + math.dist(self._p(t0), self._p(t1)))
        self.length = self.s[-1]

    def _p(self, t: float):
        return (self.cx + self.a * math.cos(t), self.cy + self.b * math.sin(t))

    def at(self, s: float):
        s %= self.length
        i = max(1, bisect.bisect_left(self.s, s))
        k = (s - self.s[i - 1]) / (self.s[i] - self.s[i - 1])
        t = self.ts[i - 1] + k * (self.ts[i] - self.ts[i - 1])
        x, y = self._p(t)
        return (round(x, 3), round(y, 3))

    def arc(self, s0: float, s1: float, n: int):
        return [self.at(s0 + (s1 - s0) * i / n) for i in range(n + 1)]

    def polygon(self, n: int = 96):
        return self.arc(0, self.length, n)[:-1]


def ring_wall(prefix, ell: Ellipse, level, *, thickness, height, elevation=0.0, material="masonry", pieces=4, pts=40,
              external=False, name=""):
    """A closed elliptical wall, split into `pieces` faceted arcs (a closed path has no clean mitre)."""
    q = ell.length / pieces
    for k in range(pieces):
        add(type="wall", id=f"{prefix}-{k}", name=f"{name} {k + 1}/{pieces}".strip(), level=level,
            start=[0, 0], end=[1, 0], path=ell.arc(k * q, (k + 1) * q, pts), thickness=thickness, height=height,
            elevation=elevation, material=material, external=external)


def arcade(prefix, ell: Ellipse, level, *, bays, pier_len, thickness, arch_h, tier_h, elevation=0.0,
           material="masonry", name=""):
    """One arcaded tier: `bays` straight piers set on the ellipse (arches centred on the axes), plus the
    faceted band that carries them."""
    step = ell.length / bays
    for i in range(bays):
        s = (i + 0.5) * step
        add(type="wall", id=f"{prefix}-p{i:02d}", name=f"{name} pier {i + 1}", level=level,
            start=ell.at(s - pier_len / 2), end=ell.at(s + pier_len / 2), thickness=thickness,
            height=arch_h, elevation=elevation, material=material, external=True)
    ring_wall(f"{prefix}-band", ell, level, thickness=thickness, height=tier_h - arch_h - elevation,
              elevation=elevation + arch_h, material=material, pieces=4, pts=bays // 4 * 2, external=True,
              name=f"{name} entablature")


def ring_segments(inner: Ellipse, outer: Ellipse, n: int, pts: int = 6):
    """Curved trapezoids tiling the band between two ellipses (slab outlines can't have holes)."""
    polys = []
    for k in range(n):
        s0, s1 = inner.length * k / n, inner.length * (k + 1) / n
        o0, o1 = outer.length * k / n, outer.length * (k + 1) / n
        polys.append(inner.arc(s0, s1, pts) + outer.arc(o0, o1, pts)[::-1])
    return polys


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def box_walls(prefix, x0, y0, x1, y1, level, *, thickness, height, elevation=0.0, material="masonry",
              external=True, name="", gaps=None):
    """Four walls on a rectangle (centre lines). `gaps` = {side: [(offset, width), ...]} leaves openings
    by splitting that side into separate walls. Sides: s, e, n, w."""
    sides = {"s": ((x0, y0), (x1, y0)), "e": ((x1, y0), (x1, y1)), "n": ((x1, y1), (x0, y1)), "w": ((x0, y1), (x0, y0))}
    for side, (a, b) in sides.items():
        length = math.dist(a, b)
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        cuts = sorted((gaps or {}).get(side, []))
        at, part = 0.0, 0
        for off, width in cuts + [(length, 0.0)]:
            if off - at > 0.3:
                add(type="wall", id=f"{prefix}-{side}{part}", name=f"{name} {side.upper()} wall".strip(), level=level,
                    start=[round(a[0] + ux * at, 3), round(a[1] + uy * at, 3)],
                    end=[round(a[0] + ux * off, 3), round(a[1] + uy * off, 3)],
                    thickness=thickness, height=height, elevation=elevation, material=material, external=external)
                part += 1
            at = off + width


# --- levels ----------------------------------------------------------------------------------------
# Colosseum storey heights: 10.5 / 11.85 / 11.6 / 14.2 m (48.15 m to the top of the attic).

LEVELS = [
    {"id": "HY", "name": "Hypogeum and tunnels", "elevation": -6.5, "height": 6.5},
    {"id": "G", "name": "Valley floor / Colosseum tier 1", "elevation": 0.0, "height": 10.5},
    {"id": "VR", "name": "Velia platform (Temple of Venus and Roma)", "elevation": 5.0, "height": 17.5},
    {"id": "T2", "name": "Colosseum tier 2", "elevation": 10.5, "height": 11.85},
    {"id": "T3", "name": "Colosseum tier 3", "elevation": 22.35, "height": 11.6},
    {"id": "T4", "name": "Colosseum attic", "elevation": 33.95, "height": 14.2},
]

# --- 1. Colosseum ------------------------------------------------------------------------------------

A, B = 94.5, 78.0                      # outer facade semi-axes (189 × 156 m)
ARENA_A, ARENA_B = 43.0, 27.0          # arena 86 × 54 m
outer = Ellipse(A, B)
second = Ellipse(A - 6.5, B - 6.5)     # second arcade ring (inner ambulatory wall)

# Tiers 1–3: two arcaded rings, 80 bays each (Tuscan / Ionic / Corinthian orders on the real facade).
tiers = [("G", 7.05, 10.5, 0.0), ("T2", 6.45, 11.85, 0.8), ("T3", 6.45, 11.6, 0.8)]
for n, (lvl, arch_h, tier_h, base) in enumerate(tiers, start=1):
    arcade(f"COL-O{n}", outer, lvl, bays=80, pier_len=2.55, thickness=2.4, arch_h=arch_h + base, tier_h=tier_h,
           name=f"Colosseum outer arcade, tier {n},")
    arcade(f"COL-I{n}", second, lvl, bays=80, pier_len=2.3, thickness=2.0, arch_h=arch_h + base, tier_h=tier_h,
           name=f"Colosseum inner arcade, tier {n},")
    if n > 1:  # projecting cornice at the foot of tiers 2 and 3
        ring_wall(f"COL-C{n}", outer, lvl, thickness=3.2, height=0.8, pts=80, external=True,
                  name=f"Colosseum cornice under tier {n}")

# Tier 4: the solid attic (it carried the velarium masts), with its cornice.
ring_wall("COL-C4", outer, "T4", thickness=3.2, height=0.8, pts=80, external=True, name="Colosseum cornice under attic")
ring_wall("COL-ATTIC", outer, "T4", thickness=2.0, height=13.4, elevation=0.8, pts=80, external=True,
          name="Colosseum attic wall")
ring_wall("COL-TOP", outer, "T4", thickness=2.8, height=0.6, elevation=13.6, pts=80, external=True,
          name="Colosseum crowning cornice")

# Vaulted ambulatory floors between the two arcades.
for lvl in ("T2", "T3", "T4"):
    for k, poly in enumerate(ring_segments(Ellipse(A - 7.4, B - 7.4), Ellipse(A - 1.3, B - 1.3), 16)):
        add(type="slab", id=f"COL-AMB-{lvl}-{k:02d}", name=f"Colosseum ambulatory floor ({lvl}) {k + 1}/16",
            level=lvl, outline=poly, thickness=0.8)

# Arena podium, then the cavea: 14 stepped bands rising from the podium to the inner arcade.
podium = Ellipse(ARENA_A + 0.6, ARENA_B + 0.6)
ring_wall("COL-POD", podium, "G", thickness=1.2, height=4.0, material="plaster", pts=40, name="Arena podium wall")
for k in range(14):
    d = 1.2 + 1.5 + k * 3.0
    band = Ellipse(ARENA_A + 0.6 + d, ARENA_B + 0.6 + d)
    ring_wall(f"COL-CAV{k:02d}", band, "G", thickness=3.05, height=round(4.5 + k * 2.2, 2), material="concrete",
              pts=30, name=f"Colosseum seating band {k + 1}")

# Arena floor (timber and sand) — cut away over the west end to show the hypogeum.
arena = Ellipse(ARENA_A, ARENA_B)
tc = math.acos(-12 / ARENA_A)  # the floor runs from the east end back to x = -12
floor = [[round(ARENA_A * math.cos(t), 3), round(ARENA_B * math.sin(t), 3)]
         for t in (-tc + 2 * tc * i / 80 for i in range(81))]
add(type="slab", id="COL-ARENA", name="Arena floor (cut away to show the hypogeum)", level="G", outline=floor,
    thickness=0.4)
add(type="space", id="SP-ARENA", name="Arena", level="G", outline=arena.polygon(48), height=4.0)

# Hypogeum: floor, perimeter and the long corridors parallel to the major axis.
add(type="slab", id="HY-FLOOR", name="Hypogeum floor", level="HY", outline=arena.polygon(96), thickness=0.5)
ring_wall("HY-RIM", Ellipse(ARENA_A - 0.5, ARENA_B - 0.5), "HY", thickness=1.0, height=6.0, material="stone",
          pts=30, name="Hypogeum perimeter wall")
for j, y in enumerate([-20, -15, -10, -5, -1.5, 1.5, 5, 10, 15, 20]):
    half = (ARENA_A - 2) * math.sqrt(max(0.0, 1 - (y / (ARENA_B - 1.5)) ** 2))
    if half > 3:
        add(type="wall", id=f"HY-W{j}", name=f"Hypogeum corridor wall {j + 1}", level="HY", start=[-half, y],
            end=[half, y], thickness=0.9, height=6.0, material="stone")
add(type="space", id="SP-HYPOGEUM", name="Hypogeum", level="HY", outline=arena.polygon(48), height=6.0)

# Ground under and around the Colosseum (piazza), tiled so the arena stays open.
colo_pad = Ellipse(A + 0.2, B + 0.2)
for k, poly in enumerate(ring_segments(Ellipse(ARENA_A, ARENA_B), colo_pad, 8, pts=10)):
    add(type="slab", id=f"GR-COL-{k}", name=f"Colosseum footprint {k + 1}/8", level="G", outline=poly, thickness=0.75, elevation=0.15)
for qx, qy in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
    arcq = colo_pad.arc(0, colo_pad.length / 4, 16)
    arcq = [(qx * x, qy * y) for x, y in arcq]
    add(type="slab", id=f"GR-PIAZZA-{qx}{qy}", name="Travertine piazza", level="G",
        outline=arcq + [(0, qy * 110), (qx * 125, qy * 110), (qx * 125, 0)], thickness=0.75, elevation=0.15)

# --- 2. Meta Sudans and the Colossus -------------------------------------------------------------------

add(type="custom", id="META-SUDANS", name="Meta Sudans (monumental fountain)", level="G", position=[-128, -48], parts=[
    {"shape": "round", "w": 16.0, "h": 1.2},
    {"shape": "round", "w": 9.0, "h": 3.0, "z": 1.2},
    {"shape": "round", "w": 7.8, "h": 3.0, "z": 4.2},
    {"shape": "round", "w": 6.6, "h": 3.0, "z": 7.2},
    {"shape": "round", "w": 5.2, "h": 3.0, "z": 10.2},
    {"shape": "round", "w": 3.8, "h": 3.0, "z": 13.2},
    {"shape": "round", "w": 2.4, "h": 2.0, "z": 16.2},
    {"shape": "round", "w": 1.4, "h": 1.2, "z": 18.2},
])
add(type="wall", id="COLOSSUS-BASE", name="Colossus pedestal", level="G", start=[-142.5, 45], end=[-127.5, 45],
    thickness=12.5, height=6.0, material="masonry", external=True)
add(type="custom", id="COLOSSUS", name="Colossus of Sol (bronze, c. 30 m)", level="G", position=[-135, 45], elevation=6.0,
    parts=[
        {"x": -1.4, "w": 2.2, "d": 2.4, "h": 13.0},                      # legs
        {"x": 1.4, "w": 2.2, "d": 2.4, "h": 13.0},
        {"w": 6.0, "d": 3.2, "h": 9.0, "z": 13.0},                       # torso
        {"x": -3.7, "w": 1.3, "d": 1.3, "h": 8.0, "z": 13.5},            # arm at side
        {"x": 3.7, "w": 1.3, "d": 1.3, "h": 10.0, "z": 20.0},            # raised arm
        {"shape": "round", "w": 3.2, "h": 3.4, "z": 22.0},              # head
        {"shape": "round", "w": 5.0, "h": 0.6, "z": 25.0},              # radiate crown
        {"x": 0, "y": 0, "w": 0.4, "d": 0.4, "h": 2.4, "z": 25.4},
    ])

# --- 3. Arch of Constantine (315 AD): 25.9 × 7.4 × 21 m, three passages -------------------------------

AC_X, AC_Y, AC_D = -115.0, -112.0, 7.4
x = AC_X - 12.95
parts = [("pier", 3.04), ("side", 3.36), ("pier", 3.3), ("centre", 6.5), ("pier", 3.3), ("side", 3.36), ("pier", 3.04)]
for i, (kind, w) in enumerate(parts):
    if kind == "pier":
        add(type="wall", id=f"AC-PIER{i}", name="Arch of Constantine pier", level="G", start=[x, AC_Y], end=[x + w, AC_Y],
            thickness=AC_D, height=11.45, material="plaster", external=True)
        for side in (-1, 1):  # free-standing Corinthian columns on pedestals, both faces
            cy = AC_Y + side * (AC_D / 2 + 0.8)
            add(type="column", id=f"AC-PED{i}{side}", name="Arch of Constantine pedestal", level="G",
                position=[x + w / 2, cy], width=1.5, depth=1.5, height=3.2)
            add(type="column", id=f"AC-COL{i}{side}", name="Arch of Constantine column (giallo antico)", level="G",
                position=[x + w / 2, cy], width=0.95, depth=0.95, height=10.2, elevation=3.2)
    elif kind == "side":
        add(type="wall", id=f"AC-LINTEL{i}", name="Arch of Constantine spandrel over side passage", level="G",
            start=[x, AC_Y], end=[x + w, AC_Y], thickness=AC_D, height=4.05, elevation=7.4, material="plaster", external=True)
    x += w
add(type="wall", id="AC-ATTIC", name="Arch of Constantine attic", level="G", start=[AC_X - 12.95, AC_Y],
    end=[AC_X + 12.95, AC_Y], thickness=AC_D, height=9.55, elevation=11.45, material="plaster", external=True)
add(type="wall", id="AC-CORNICE", name="Arch of Constantine cornice", level="G", start=[AC_X - 13.4, AC_Y],
    end=[AC_X + 13.4, AC_Y], thickness=AC_D + 2.0, height=0.7, elevation=13.4, material="plaster", external=True)

# --- 4. Ludus Magnus (gladiator school) and its tunnel ---------------------------------------------------

LX0, LY0, LX1, LY1 = 140.0, -84.0, 232.0, -8.0
LCX, LCY = (LX0 + LX1) / 2, (LY0 + LY1) / 2
box_walls("LM-OUT", LX0, LY0, LX1, LY1, "G", thickness=1.2, height=10.5, name="Ludus Magnus outer",
          gaps={"n": [(40.0, 6.0)], "w": [(34.0, 6.0)]})
IX0, IY0, IX1, IY1 = LX0 + 6.5, LY0 + 6.5, LX1 - 6.5, LY1 - 6.5
box_walls("LM-IN", IX0, IY0, IX1, IY1, "G", thickness=0.8, height=10.5, name="Ludus Magnus courtyard",
          gaps={"n": [(33.0, 6.0)], "w": [(28.0, 6.0)]})
# Cells for the gladiators between the two rings, each with a door onto the courtyard portico.
cell = 4.6
for side, (a, b) in {"s": ((IX0, IY0), (IX1, IY0)), "n": ((IX1, IY1), (IX0, IY1))}.items():
    length = abs(b[0] - a[0])
    for i in range(1, int(length // cell)):
        xx = a[0] + (i * cell if side == "s" else -i * cell)
        yo = LY0 if side == "s" else LY1
        if abs(xx - (IX0 + 33.0 + 3.0)) < 5 and side == "n":
            continue
        add(type="wall", id=f"LM-CELL-{side}{i:02d}", name="Ludus Magnus cell partition", level="G",
            start=[round(xx, 3), yo], end=[round(xx, 3), a[1]], thickness=0.5, height=10.5, material="masonry")
wall_ids = {el["id"]: el for el in E if el["id"].startswith("LM-IN-")}
for wid, wall in wall_ids.items():
    length = math.dist(wall["start"], wall["end"])
    for i in range(int(length // cell)):
        off = i * cell + (cell - 1.2) / 2
        if off + 1.2 < length - 0.2:
            add(type="door", id=f"LM-D-{wid[6:]}-{i:02d}", name="Gladiator cell door", wall=wid, offset=round(off, 3),
                width=1.2, height=2.4)
for k, (x0, y0, x1, y1) in enumerate([(LX0, LY0, LX1, IY0), (LX0, IY1, LX1, LY1), (LX0, IY0, IX0, IY1), (IX1, IY0, LX1, IY1)]):
    add(type="roof", id=f"LM-ROOF{k}", name="Ludus Magnus cell-block roof", level="G", outline=rect(x0, y0, x1, y1),
        thickness=0.4)
ludus_arena = Ellipse(31.0, 22.5, LCX, LCY)
add(type="slab", id="LM-ARENA", name="Ludus Magnus training arena", level="G", outline=ludus_arena.polygon(64),
    thickness=0.3, elevation=0.05)
ring_wall("LM-POD", Ellipse(31.5, 23.0, LCX, LCY), "G", thickness=1.0, height=2.8, material="plaster", pts=24,
          name="Ludus Magnus arena podium")
for k in range(3):
    d = 1.0 + 1.0 + k * 2.0
    ring_wall(f"LM-CAV{k}", Ellipse(31.5 + d, 23.0 + d, LCX, LCY), "G", thickness=2.05, height=3.5 + k * 1.2,
              material="concrete", pts=24, name=f"Ludus Magnus seating band {k + 1}")
add(type="space", id="SP-LUDUS", name="Ludus Magnus arena", level="G", outline=ludus_arena.polygon(32), height=3.0)
# Underground passage from the Colosseum hypogeum to the Ludus Magnus.
for j, off in enumerate((-1.6, 1.6)):
    add(type="wall", id=f"TUN-W{j}", name="Tunnel wall (Colosseum → Ludus Magnus)", level="HY",
        start=[ARENA_A - 1.0, -4.0 + off], end=[LX0 + 2.0, LCY + off], thickness=0.8, height=5.2, material="stone")
add(type="slab", id="TUN-FLOOR", name="Tunnel floor", level="HY",
    outline=[[ARENA_A - 1.0, -6.0], [LX0 + 2.0, LCY - 2.0], [LX0 + 2.0, LCY + 2.0], [ARENA_A - 1.0, -2.0]], thickness=0.4)

# --- 5. Temple of Venus and Roma (rebuilt by Maxentius, 307 AD) ------------------------------------------

PX0, PY0, PX1, PY1 = -310.0, -30.0, -165.0, 70.0          # platform 145 × 100 m
TCX, TCY = (PX0 + PX1) / 2, (PY0 + PY1) / 2
add(type="slab", id="VR-PODIUM", name="Temple of Venus and Roma platform", level="G", outline=rect(PX0, PY0, PX1, PY1),
    thickness=5.0, elevation=5.0)
TX0, TY0, TX1, TY1 = TCX - 55, TCY - 26.5, TCX + 55, TCY + 26.5   # temple 110 × 53 m
add(type="slab", id="VR-STYLOBATE", name="Temple stylobate", level="VR", outline=rect(TX0 - 1.5, TY0 - 1.5, TX1 + 1.5, TY1 + 1.5),
    thickness=0.6, elevation=0.6)
# Decastyle peristyle: 10 columns on the ends, 22 along each flank.
cols = set()
for i in range(10):
    y = TY0 + 1.0 + i * (TY1 - TY0 - 2.0) / 9
    cols |= {(TX0 + 1.0, round(y, 2)), (TX1 - 1.0, round(y, 2))}
for i in range(22):
    xx = TX0 + 1.0 + i * (TX1 - TX0 - 2.0) / 21
    cols |= {(round(xx, 2), TY0 + 1.0), (round(xx, 2), TY1 - 1.0)}
for k, (cx, cy) in enumerate(sorted(cols)):
    add(type="column", id=f"VR-COL{k:02d}", name="Temple of Venus and Roma column (Proconnesian marble)", level="VR",
        position=[cx, cy], width=1.7, depth=1.7, height=16.9, elevation=0.6)
# Two cellae back to back — Venus facing east (the Colosseum), Roma facing west (the Forum) — each with an apse.
CX0, CY0, CX1, CY1 = TCX - 34.5, TCY - 16.0, TCX + 34.5, TCY + 16.0
box_walls("VR-CELLA", CX0, CY0, CX1, CY1, "VR", thickness=2.4, height=16.9, elevation=0.6, material="plaster",
          name="Temple cella", gaps={"e": [(11.0, 10.0)], "w": [(11.0, 10.0)]})
add(type="wall", id="VR-DIVIDE", name="Wall between the two cellae", level="VR", start=[TCX, CY0], end=[TCX, CY1],
    thickness=4.0, height=16.9, elevation=0.6, material="plaster")
for j, sgn in enumerate((1, -1)):  # apses bulge back towards the dividing wall
    cx0 = TCX + sgn * 2.0
    apse = [[round(cx0 + sgn * 11.0 * math.sin(math.pi * i / 16), 3), round(TCY - 11.0 * math.cos(math.pi * i / 16), 3)]
            for i in range(17)]
    add(type="wall", id=f"VR-APSE{j}", name=f"Apse of the cella of {'Venus' if sgn > 0 else 'Roma'}", level="VR",
        start=apse[0], end=apse[-1], path=apse, thickness=1.6, height=16.9, elevation=0.6, material="plaster")
    add(type="space", id=f"SP-CELLA-{j}", name=f"Cella of {'Venus' if sgn > 0 else 'Roma'}", level="VR", height=16.9,
        outline=rect(TCX + 2.0, CY0 + 1.2, CX1 - 1.2, CY1 - 1.2) if sgn > 0 else rect(CX0 + 1.2, CY0 + 1.2, TCX - 2.0, CY1 - 1.2))
add(type="roof", id="VR-ROOF", name="Temple of Venus and Roma roof (gilded bronze tiles)", level="VR",
    outline=rect(TX0 - 1.5, TY0 - 1.5, TX1 + 1.5, TY1 + 1.5), shape="gable", pitch=14, ridge="x", thickness=0.8)
# Granite porticoes along the long sides of the platform.
for side, yy, back in (("S", PY0 + 5.0, PY0 + 0.6), ("N", PY1 - 5.0, PY1 - 0.6)):
    for i in range(26):
        add(type="column", id=f"VR-PORT-{side}{i:02d}", name="Platform portico column (grey granite)", level="VR",
            position=[round(PX0 + 4.0 + i * (PX1 - PX0 - 8.0) / 25, 2), yy], width=1.0, depth=1.0, height=10.0)
    add(type="wall", id=f"VR-PORT-{side}-BACK", name="Platform portico back wall", level="VR", start=[PX0, back], end=[PX1, back],
        thickness=1.2, height=10.6, material="masonry", external=True)
    add(type="slab", id=f"VR-PORT-{side}-ROOF", name="Platform portico roof", level="VR",
        outline=rect(PX0, min(back, yy) - 1.0, PX1, max(back, yy) + 1.0), thickness=0.6, elevation=10.6)

# --- 6. Arch of Titus (81 AD) on the Via Sacra: 13.5 × 4.75 × 15.4 m, one passage -------------------------

AT_X, AT_Y0 = -332.0, -41.0 - 6.75
for i, (y0, y1) in enumerate(((AT_Y0, AT_Y0 + 4.07), (AT_Y0 + 9.43, AT_Y0 + 13.5))):
    add(type="wall", id=f"AT-PIER{i}", name="Arch of Titus pier", level="G", start=[AT_X, y0], end=[AT_X, y1],
        thickness=4.75, height=8.3, material="plaster", external=True)
add(type="wall", id="AT-ATTIC", name="Arch of Titus attic (dedication to Divus Titus)", level="G", start=[AT_X, AT_Y0],
    end=[AT_X, AT_Y0 + 13.5], thickness=4.75, height=7.1, elevation=8.3, material="plaster", external=True)
add(type="wall", id="AT-CORNICE", name="Arch of Titus cornice", level="G", start=[AT_X, AT_Y0 - 0.4], end=[AT_X, AT_Y0 + 13.9],
    thickness=5.6, height=0.6, elevation=10.6, material="plaster", external=True)

# --- 7. Basilica of Maxentius and Constantine (312 AD): 100 × 65 m, nave 39 m high ------------------------

BX0, BY0, BX1, BY1 = -445.0, 62.0, -345.0, 127.0
NY0, NY1 = 82.0, 107.0
box_walls("BM-OUT", BX0, BY0, BX1, BY1, "G", thickness=3.0, height=24.5, material="concrete", name="Basilica outer",
          gaps={"e": [(8.0, 8.0), (28.5, 8.0), (49.0, 8.0)], "s": [(44.0, 12.0)]})
apse = [[round(BX0 - 10.0 * math.sin(math.pi * i / 16), 3), round((NY0 + NY1) / 2 - 10.0 * math.cos(math.pi * i / 16), 3)]
        for i in range(17)]
add(type="wall", id="BM-APSE-W", name="Basilica west apse", level="G", start=apse[0], end=apse[-1], path=apse,
    thickness=3.0, height=24.5, material="concrete", external=True)
bay_x = [BX0 + 1.5 + i * (BX1 - BX0 - 3.0) / 3 for i in range(4)]
for side, yy in (("S", NY0), ("N", NY1)):
    for i, px in enumerate(bay_x):  # massive piers carrying the nave vaults
        add(type="wall", id=f"BM-PIER-{side}{i}", name="Basilica nave pier", level="G", start=[round(px - 3.5, 2), yy],
            end=[round(px + 3.5, 2), yy], thickness=6.0, height=24.5, material="concrete")
    add(type="wall", id=f"BM-CLER-{side}", name="Basilica clerestory wall", level="G", start=[BX0, yy], end=[BX1, yy],
        thickness=3.0, height=14.5, elevation=24.5, material="concrete", external=True)
    for i in range(3):
        add(type="window", id=f"BM-WIN-{side}{i}", name="Basilica clerestory window", wall=f"BM-CLER-{side}",
            offset=round(9.5 + i * 32.3, 2), width=13.0, height=8.0, sill_height=3.0)
for i, px in enumerate(bay_x[1:3]):  # transverse walls between the aisle bays, pierced by great arches
    for side, (ya, yb) in (("S", (BY0, NY0)), ("N", (NY1, BY1))):
        add(type="wall", id=f"BM-TR-{side}{i}a", name="Basilica aisle cross wall", level="G", start=[round(px, 2), ya],
            end=[round(px, 2), ya + 4.0], thickness=4.0, height=24.5, material="concrete")
        add(type="wall", id=f"BM-TR-{side}{i}b", name="Basilica aisle cross wall", level="G", start=[round(px, 2), yb - 4.0],
            end=[round(px, 2), yb], thickness=4.0, height=24.5, material="concrete")
for side, (ya, yb) in (("S", (BY0, NY0)), ("N", (NY1, BY1))):
    add(type="roof", id=f"BM-ROOF-{side}", name="Basilica aisle roof", level="G", outline=rect(BX0, ya, BX1, yb),
        thickness=0.8, elevation=14.0)
add(type="roof", id="BM-ROOF-NAVE", name="Basilica nave roof", level="G", outline=rect(BX0, NY0, BX1, NY1),
    shape="gable", pitch=18, ridge="x", thickness=0.8, elevation=28.5)
add(type="space", id="SP-NAVE", name="Basilica nave", level="G", outline=rect(BX0 + 1.5, NY0 + 3.0, BX1 - 1.5, NY1 - 3.0),
    height=35.0)

# --- 8. Landscape: lawns, hills, roads, trees ----------------------------------------------------------

import random  # noqa: E402

rng = random.Random(320)  # deterministic scatter

for k, (x0, y0, x1, y1) in enumerate([(-520, -260, -125, 260), (125, -260, 320, 260), (-125, 110, 125, 260),
                                       (-125, -260, 125, -110)]):
    add(type="slab", id=f"GR-{k}", name="Lawn", level="G", outline=rect(x0, y0, x1, y1), thickness=0.75, elevation=0.15)

# Hills framing the valley, as stepped grassy terraces (each slab's top sits at its elevation).
HILLS = {
    "Palatine Hill": ([(-520, -260), (-160, -260), (-160, -120), (-230, -70), (-520, -70)], [4.0, 8.0, 12.0]),
    "Caelian Hill": ([(60, -260), (320, -260), (320, -110), (95, -110), (60, -150)], [3.0, 6.0, 9.0]),
    "Oppian Hill": ([(10, 130), (320, 130), (320, 260), (10, 260)], [3.0, 6.5, 10.0]),
}


def inset(poly, d):
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    return [(round(cx + (x - cx) * d, 2), round(cy + (y - cy) * d, 2)) for x, y in poly]


HILL_TOPS = {}
for name, (poly, heights) in HILLS.items():
    prev = 0.0
    for i, h in enumerate(heights):
        shape = inset(poly, 1.0 - 0.22 * i)
        add(type="slab", id=f"HILL-{name.split()[0].upper()}-{i}", name=f"{name} (terrace {i + 1})", level="G",
            outline=shape, thickness=round(h - prev + 0.05, 2), elevation=h)
        prev = h
    HILL_TOPS[name] = (inset(poly, 1.0 - 0.22 * (len(heights) - 1)), heights[-1])

# Roads: basalt paving (basoli) laid on the lawn.
ROADS = [
    ("RD-SACRA", "Via Sacra (to the Forum)", rect(-520, -46, -118, -36)),
    ("RD-TRIUMPH", "Via Triumphalis (to the Circus Maximus)", rect(-122, -260, -108, -104)),
    ("RD-LABICANA", "Via Labicana", rect(125, -2, 320, 10)),
    ("RD-BASILICA", "Road to the Basilica of Maxentius", rect(-345, 88, -125, 98)),
    ("RD-CLIVUS", "Clivus from the Via Sacra to the Basilica", rect(-400, -36, -390, 62)),
    ("RD-CAELIAN", "Clivus Scauri (to the Caelian)", [[40, -108], [52, -110], [64, -150], [52, -152]]),
]
for sid, name, poly in ROADS:
    add(type="slab", id=sid, name=name, level="G", outline=poly, thickness=0.12, elevation=0.27)

# Grand stairs up to the temple platform (5 m): from the Colosseum side and from the Via Sacra.
add(type="stair", id="VR-STAIR-E", name="Temple platform stairs (east, facing the Colosseum)", level="G",
    position=[-150.0, TCY], direction=180.0, width=30.0, rise=5.0, riser=0.18, going=0.5)
add(type="stair", id="VR-STAIR-S", name="Temple platform stairs (from the Via Sacra)", level="G",
    position=[TCX, -45.0 + 0.1], direction=90.0, width=24.0, rise=5.0, riser=0.18, going=0.5)

# Velarium masts on the Colosseum attic (they carried the awning over the cavea).
for i in range(80):
    x, y = outer.at((i + 0.5) * outer.length / 80)
    add(type="column", id=f"COL-MAST{i:02d}", name="Colosseum velarium mast", level="T4", position=[x, y],
        width=0.45, depth=0.45, height=7.0, elevation=14.2)


def pine(tid, x, y, z=0.0, h=None):
    h = h or rng.uniform(10.0, 14.0)
    crown = rng.uniform(8.0, 11.0)
    add(type="custom", id=tid, name="Umbrella pine (Pinus pinea)", level="G", position=[round(x, 2), round(y, 2)],
        elevation=z, rotation=rng.uniform(0, 90), parts=[
            {"shape": "round", "w": 0.7, "h": h - 1.0},
            {"shape": "round", "w": crown, "h": 1.6, "z": h - 1.6},
            {"shape": "round", "w": crown * 0.7, "h": 1.4, "z": h},
        ])


def cypress(tid, x, y, z=0.0):
    add(type="custom", id=tid, name="Italian cypress", level="G", position=[round(x, 2), round(y, 2)], elevation=z,
        parts=[
            {"shape": "round", "w": 0.4, "h": 1.5},
            {"shape": "round", "w": 2.4, "h": 5.0, "z": 1.2},
            {"shape": "round", "w": 1.8, "h": 3.5, "z": 6.0},
            {"shape": "round", "w": 1.0, "h": 2.5, "z": 9.3},
        ])


def inside(poly, x, y):
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


n = 0
for name, (top, z) in HILL_TOPS.items():
    xs, ys = [p[0] for p in top], [p[1] for p in top]
    placed = 0
    while placed < 14:
        x, y = rng.uniform(min(xs), max(xs)), rng.uniform(min(ys), max(ys))
        if inside(top, x, y):
            pine(f"TREE-P{n:03d}", x, y, z)
            n += 1
            placed += 1
for i in range(9):  # pines in the lawns north of the Ludus
    pine(f"TREE-P{n:03d}", 250 + rng.uniform(-40, 50), 40 + rng.uniform(-10, 60))
    n += 1
for i, xx in enumerate(range(-330, -140, 16)):  # cypress avenue along the road to the Basilica
    cypress(f"TREE-C{i:02d}a", xx, 101.5)
for i, yy in enumerate(range(-250, -120, 16)):  # and along the Via Triumphalis
    cypress(f"TREE-C{i:02d}b", -126.0, yy)
    cypress(f"TREE-C{i:02d}c", -104.0, yy)


# --- build ------------------------------------------------------------------------------------------------

spec = BuildingSpec.model_validate({
    "building": {"name": "Rome — the Colosseum valley, c. 320 AD",
                 "description": "Colosseum and its surroundings: Meta Sudans, Colossus, Arch of Constantine, Ludus Magnus, "
                                "Via Sacra, Temple of Venus and Roma, Arch of Titus, Basilica of Maxentius. "
                                "Prebuilt NoCoast demo; site positions approximate."},
    "levels": LEVELS,
    "elements": E,
})
out = OUT
t0 = time.perf_counter()
summary = write_ifc(spec, out)
compile_s = time.perf_counter() - t0


# --- beautify: real surface colours and better IFC classes (post-process; the backend stays untouched) ------

import re  # noqa: E402

import ifcopenshell  # noqa: E402
import ifcopenshell.api.root  # noqa: E402
import ifcopenshell.api.style  # noqa: E402

PALETTE = [  # first match wins
    (r"^Lawn|Hill \(terrace", "Grass", (0.44, 0.58, 0.29)),
    (r"^Via |^Road|^Clivus", "Basalt paving", (0.34, 0.34, 0.36)),
    (r"piazza|Colosseum footprint", "Travertine paving", (0.80, 0.76, 0.66)),
    (r"seating band", "Marble seating", (0.90, 0.89, 0.85)),
    (r"Arena floor|training arena", "Arena sand", (0.87, 0.77, 0.55)),
    (r"podium wall", "White marble", (0.94, 0.93, 0.90)),
    (r"ambulatory floor", "Travertine", (0.72, 0.68, 0.60)),
    (r"velarium mast", "Timber", (0.50, 0.36, 0.22)),
    (r"^Colosseum", "Travertine", (0.86, 0.80, 0.67)),
    (r"Hypogeum|Tunnel", "Tufa", (0.56, 0.51, 0.44)),
    (r"Temple of Venus and Roma roof", "Gilded bronze tiles", (0.78, 0.62, 0.30)),
    (r"Platform portico column", "Grey granite", (0.52, 0.53, 0.56)),
    (r"Platform portico roof", "Terracotta tiles", (0.64, 0.35, 0.25)),
    (r"Temple|cella|Apse of|two cellae|stylobate|Platform portico", "Proconnesian marble", (0.94, 0.93, 0.90)),
    (r"giallo antico", "Giallo antico marble", (0.86, 0.73, 0.42)),
    (r"Arch of (Constantine|Titus)", "Pentelic marble", (0.93, 0.92, 0.88)),
    (r"Basilica.*roof", "Terracotta tiles", (0.64, 0.35, 0.25)),
    (r"Basilica", "Brick-faced concrete", (0.75, 0.53, 0.41)),
    (r"Ludus Magnus cell-block roof", "Terracotta tiles", (0.64, 0.35, 0.25)),
    (r"Ludus|Gladiator", "Travertine and brick", (0.81, 0.71, 0.58)),
    (r"Colossus pedestal", "Travertine", (0.84, 0.80, 0.72)),
    (r"Colossus of Sol", "Bronze", (0.58, 0.44, 0.24)),
    (r"Meta Sudans", "Brick and marble", (0.83, 0.77, 0.67)),
]
TREE_COLOURS = {"trunk": ("Bark", (0.36, 0.26, 0.18)), "pine": ("Pine canopy", (0.22, 0.38, 0.19)),
                "cypress": ("Cypress foliage", (0.15, 0.30, 0.16))}
WATER = ("Water", (0.36, 0.56, 0.70))

model = ifcopenshell.open(str(out))
styles: dict[str, object] = {}


def style(name, rgb):
    if name not in styles:
        s = ifcopenshell.api.style.add_style(model, name=name)
        ifcopenshell.api.style.add_surface_style(model, style=s, ifc_class="IfcSurfaceStyleShading", attributes={
            "SurfaceColour": {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]}, "Transparency": 0.0})
        styles[name] = s
    return styles[name]


def items(product):
    for rep in (product.Representation.Representations if product.Representation else []):
        for it in rep.Items:
            if it.is_a("IfcMappedItem"):
                yield from it.MappingSource.MappedRepresentation.Items
            else:
                yield it


def paint(item, s):
    if item.StyledByItem:
        for styled in item.StyledByItem:
            styled.Styles = [s]
    else:
        model.createIfcStyledItem(item, [s], None)


painted = 0
for product in model.by_type("IfcProduct"):
    name = product.Name or ""
    if product.is_a("IfcOpeningElement") or not product.Representation:
        continue
    its = list(items(product))
    if name.startswith(("Umbrella pine", "Italian cypress")):
        canopy = TREE_COLOURS["pine" if name.startswith("Umbrella") else "cypress"]
        for i, it in enumerate(its):
            paint(it, style(*(TREE_COLOURS["trunk"] if i == 0 else canopy)))
        painted += 1
        continue
    if name.startswith("Meta Sudans") and its:
        paint(its[0], style(*WATER))
        its = its[1:]
    for pattern, label, rgb in PALETTE:
        if re.search(pattern, name):
            for it in its:
                paint(it, style(label, rgb))
            painted += 1
            break

# Classes that say what these things are (the builder only knows slabs and generic furniture).
reclassed = 0
for product in list(model.by_type("IfcProduct")):
    name = product.Name or ""
    target = None
    if name.startswith(("Lawn", "Palatine Hill", "Caelian Hill", "Oppian Hill")):
        target, ptype, otype = "IfcGeographicElement", "TERRAIN", None
    elif name.startswith(("Umbrella pine", "Italian cypress")):
        target, ptype, otype = "IfcGeographicElement", "USERDEFINED", "Vegetation"
    elif name.startswith("Colossus of Sol"):
        target, ptype, otype = "IfcBuildingElementProxy", "USERDEFINED", "Statue"
    elif name.startswith("Meta Sudans"):
        target, ptype, otype = "IfcBuildingElementProxy", "USERDEFINED", "Fountain"
    if target:
        new = ifcopenshell.api.root.reassign_class(model, product=product, ifc_class=target, predefined_type=ptype)
        if otype:
            new.ObjectType = otype
        reclassed += 1
model.write(str(out))

counts: dict[str, int] = {}
for p in model.by_type("IfcProduct"):
    if not p.is_a("IfcOpeningElement") and p.Representation:
        counts[p.is_a()] = counts.get(p.is_a(), 0) + 1
print(json.dumps({"elements_in_spec": len(E), "compile_s": round(compile_s, 1), "painted": painted, "reclassed": reclassed,
                  "ifc_mb": round(out.stat().st_size / 1e6, 2), "storeys": summary["storeys"], "counts": counts}, indent=1))
