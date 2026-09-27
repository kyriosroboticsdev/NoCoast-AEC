"""The semantic model: generic geometric building blocks.

A `GeoModel` is a flat list of **parts** in a few **levels**, plus **openings** that void
parts, **assemblies** that group them and **instances** that place transformed copies.
Nothing in it names a building function: there is no room, no door, no window, no stair, no
roof *kind*. A part says which IFC entity it is (validated against the schema, see
`ifc/schema.py`) and how its solids are made; what it *means* lives in its `name` and in the
recipe cards under `blocks/`.

Four solid operations span the vocabulary:

    extrude   a profile swept linearly along the placement's +Z      walls, slabs, beams, gables
    revolve   a profile revolved about an axis                       domes, vaults, cones, apses
    sweep     a cross-section transported along a 3D path            tunnels, curved decks
    mesh      explicit outward-facing faces                          hip roofs, faceted shells

Ids are stable handles: a part keeps its id when it moves, so its IFC GlobalId survives the
edit. All dimensions are metres; plan coordinates are x east, y north, z up, and a part's
placement is relative to its level's elevation.
"""

from __future__ import annotations

import math
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ifc.schema import SchemaError, check_entity, check_predefined_type
from schemas.geom2d import (Edge, Pt, as_point, as_point3, band_points, bounds, ccw, circle_points, edges, facet,
                            r2, rect_points, signed_area)

Vec3 = tuple[float, float, float]
SolidOp = Literal["extrude", "revolve", "sweep", "mesh"]

LEVEL_ID = re.compile(r"^([LB])(\d+)$")
MAX_LEVELS = 60
MAX_SOLIDS = 64          # per part; a repeat multiplies this, so it is a sanity bound not a budget
MAX_REPEAT = 400
MIN_SIZE = 1e-4          # metres below which a dimension is a typo, not a thin plate
ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$")


class GeoError(ValueError):
    """The model cannot be built. The message is written for the language model."""


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-") or "part"


def _ident(value: str, what: str) -> str:
    v = str(value).strip()
    if not ID_OK.match(v):
        raise ValueError(f"{what} ids are letters, digits, '-', '_', '.' and '+' and start with a letter or digit; got {v!r}")
    return v


# --- placement ---------------------------------------------------------------

class Placement(BaseModel):
    """A local frame, exactly `IfcAxis2Placement3D`: an origin, a local +Z (`axis`) and a local
    +X (`ref`), with `rotation` an extra turn about the axis. Out-of-plane extrusion is
    therefore free — a gable roof is a chevron profile extruded along axis=[0,-1,0]."""

    model_config = ConfigDict(extra="ignore")

    at: Vec3 = (0.0, 0.0, 0.0)
    rotation: float = Field(0.0, description="Degrees about `axis`")
    axis: Vec3 = Field((0.0, 0.0, 1.0), description="Local +Z: the extrusion / revolve-plane normal")
    ref: Optional[Vec3] = Field(None, description="Local +X; null = picked perpendicular to `axis`")

    @field_validator("at", "axis", "ref", mode="before")
    @classmethod
    def _p(cls, v):
        return None if v is None else as_point3(v)

    @model_validator(mode="after")
    def _unit(self) -> "Placement":
        n = math.hypot(math.hypot(*self.axis[:2]), self.axis[2])
        if n < 1e-9:
            raise ValueError("axis must not be the zero vector")
        self.axis = (r2(self.axis[0] / n), r2(self.axis[1] / n), r2(self.axis[2] / n))
        if self.ref is not None:
            rn = math.hypot(math.hypot(*self.ref[:2]), self.ref[2])
            if rn < 1e-9:
                raise ValueError("ref must not be the zero vector")
            self.ref = (r2(self.ref[0] / rn), r2(self.ref[1] / rn), r2(self.ref[2] / rn))
            if abs(sum(a * b for a, b in zip(self.axis, self.ref))) > 0.999:
                raise ValueError("ref is parallel to axis; pick a direction across it")
        return self

    @property
    def is_identity(self) -> bool:
        return self.at == (0.0, 0.0, 0.0) and self.rotation == 0.0 and self.axis == (0.0, 0.0, 1.0) and self.ref is None

    def basis(self) -> tuple[Vec3, Vec3, Vec3]:
        """Orthonormal (x, y, z) of the frame, with `rotation` applied about z."""
        z = self.axis
        if self.ref is not None:
            x = self.ref
        else:
            # Any direction not parallel to z; prefer world +X so plan work stays intuitive.
            seed = (1.0, 0.0, 0.0) if abs(z[0]) < 0.9 else (0.0, 1.0, 0.0)
            x = seed
        # Gram-Schmidt x against z, then y = z x x.
        d = sum(a * b for a, b in zip(x, z))
        x = tuple(a - d * b for a, b in zip(x, z))
        n = math.sqrt(sum(c * c for c in x)) or 1.0
        x = tuple(c / n for c in x)
        y = (z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0])
        if self.rotation:
            a = math.radians(self.rotation)
            c, s = math.cos(a), math.sin(a)
            x, y = (tuple(c * xi + s * yi for xi, yi in zip(x, y)),
                    tuple(-s * xi + c * yi for xi, yi in zip(x, y)))
        return x, y, z  # type: ignore[return-value]

    def apply(self, p: Vec3) -> Vec3:
        x, y, z = self.basis()
        return (self.at[0] + p[0] * x[0] + p[1] * y[0] + p[2] * z[0],
                self.at[1] + p[0] * x[1] + p[1] * y[1] + p[2] * z[1],
                self.at[2] + p[0] * x[2] + p[1] * y[2] + p[2] * z[2])


class Repeat(BaseModel):
    """Array a part's solids by a transform, `count` copies including the original.

    Copy *i* is translated by `i * translate` and turned `i * rotate` degrees about the
    vertical through `about`. A helical stair is one tread repeated with a rise and a turn; a
    colonnade, a pier row and a repeated structural bay are the same step with other numbers."""

    model_config = ConfigDict(extra="ignore")

    count: int = Field(ge=1, le=MAX_REPEAT)
    translate: Vec3 = (0.0, 0.0, 0.0)
    rotate: float = Field(0.0, description="Degrees per copy, about the vertical through `about`")
    about: Pt = Field((0.0, 0.0), description="Plan centre of the rotation, in part-local coordinates")

    @field_validator("translate", mode="before")
    @classmethod
    def _t(cls, v):
        return as_point3(v)

    @field_validator("about", mode="before")
    @classmethod
    def _a(cls, v):
        return as_point(v)

    @model_validator(mode="after")
    def _moves(self) -> "Repeat":
        if self.count > 1 and self.translate == (0.0, 0.0, 0.0) and abs(self.rotate) < 1e-9:
            raise ValueError("a repeat of more than one copy needs a `translate` or a `rotate`, "
                             "otherwise every copy lands on top of the first")
        return self

    def transform(self, i: int) -> Placement:
        """The frame copy `i` sits in, as a placement in the part's own local space."""
        ang = math.radians(self.rotate * i)
        cx, cy = self.about
        dx, dy, dz = (self.translate[0] * i, self.translate[1] * i, self.translate[2] * i)
        # Rotate about (cx, cy), then translate.
        c, s = math.cos(ang), math.sin(ang)
        ox = cx + (-cx) * c - (-cy) * s
        oy = cy + (-cx) * s + (-cy) * c
        return Placement(at=(r2(ox + dx), r2(oy + dy), r2(dz)), rotation=r2(self.rotate * i))

    def spread(self) -> float:
        """Rough overall travel, for descriptions."""
        t = self.translate
        return r2((self.count - 1) * math.sqrt(t[0] ** 2 + t[1] ** 2 + t[2] ** 2))


# --- profiles ----------------------------------------------------------------

class Profile(BaseModel):
    """A 2D shape in the XY plane of whatever frame it is placed in. Exactly one of `points`,
    `rect`, `circle` or `band` describes the outer ring; `holes` are inner rings."""

    model_config = ConfigDict(extra="ignore")

    points: Optional[list[Edge]] = Field(None, description="Outline vertices counter-clockwise; an item may be {to:[x,y],through:[x,y]} for an arc")
    rect: Optional[tuple[float, float]] = Field(None, description="[width, depth], centred on the origin")
    circle: Optional[float] = Field(None, gt=0, description="Diameter, centred on the origin")
    band: Optional[list[Edge]] = Field(None, description="A polyline thickened by `width`: a wall footprint, a ring")
    width: Optional[float] = Field(None, gt=0, description="band: thickness")
    closed: bool = Field(False, description="band: join the last point back to the first (a ring wall, an annulus)")
    holes: Optional[list[list[Edge]]] = Field(None, description="Inner rings (a slab with a void, a tube)")
    at: Pt = Field((0.0, 0.0), description="Offset of the whole profile in its plane")

    @field_validator("points", "band", mode="before")
    @classmethod
    def _e(cls, v):
        return None if v is None else edges(v)

    @field_validator("holes", mode="before")
    @classmethod
    def _h(cls, v):
        if v is None:
            return None
        if not isinstance(v, (list, tuple)):
            raise ValueError("holes are a list of inner rings [[[x,y], …], …]")
        first = v[0] if v else None
        unwrapped = isinstance(first, (list, tuple)) and len(first) == 2 and all(isinstance(c, (int, float)) for c in first)
        rings = [v] if unwrapped else list(v)
        return [edges(ring) for ring in rings]

    @field_validator("rect", mode="before")
    @classmethod
    def _r(cls, v):
        if v is None:
            return None
        if isinstance(v, dict):
            v = [v.get("width", v.get("w")), v.get("depth", v.get("d"))]
        if isinstance(v, (int, float)):
            v = [v, v]
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            raise ValueError("rect is [width, depth]")
        return (r2(v[0]), r2(v[1]))

    @field_validator("at", mode="before")
    @classmethod
    def _at(cls, v):
        return as_point(v)

    @model_validator(mode="after")
    def _one(self) -> "Profile":
        given = [n for n, v in (("points", self.points), ("rect", self.rect), ("circle", self.circle), ("band", self.band)) if v]
        if len(given) != 1:
            raise ValueError("a profile needs exactly one of points, rect, circle or band; got " + (", ".join(given) or "none"))
        if self.band is not None and self.width is None:
            raise ValueError("a band profile needs `width`: how thick the strip is")
        if self.rect is not None and min(self.rect) <= MIN_SIZE:
            raise ValueError(f"rect sides must be greater than {MIN_SIZE} m, got {list(self.rect)}")
        # Fail here rather than at compile time, so the step is rejected with a clear message.
        self.rings()
        return self

    def rings(self) -> tuple[list[Pt], list[list[Pt]]]:
        """(outer ring counter-clockwise, inner rings clockwise), faceted and offset by `at`."""
        holes: list[list[Pt]] = []
        if self.points is not None:
            outer = ccw(facet(self.points))
        elif self.rect is not None:
            outer = rect_points(self.rect[0], self.rect[1])
        elif self.circle is not None:
            outer = circle_points(self.circle)
        else:
            pts = facet(self.band or [], closed=False)
            outer, holes = band_points(pts, self.width or 0.0, self.closed)
        if len(outer) < 3:
            raise ValueError("a profile needs at least three distinct vertices")
        if abs(signed_area(outer)) < 1e-6:
            raise ValueError("this profile has no area; check the vertex order and the numbers")
        for ring in self.holes or []:
            pts = facet(ring)
            if len(pts) >= 3:
                holes.append(ccw(pts)[::-1])
        ox, oy = self.at
        if (ox, oy) != (0.0, 0.0):
            outer = [(r2(x + ox), r2(y + oy)) for x, y in outer]
            holes = [[(r2(x + ox), r2(y + oy)) for x, y in ring] for ring in holes]
        return outer, holes

    def extent(self) -> tuple[float, float]:
        outer, _ = self.rings()
        x0, y0, x1, y1 = bounds(outer)
        return r2(x1 - x0), r2(y1 - y0)

    def describe(self) -> str:
        if self.rect is not None:
            return f"rect {self.rect[0]:g}x{self.rect[1]:g}"
        if self.circle is not None:
            return f"circle d={self.circle:g}"
        if self.band is not None:
            pts = facet(self.band, closed=False)
            return f"band {len(pts)}pt w={self.width:g}" + (" closed" if self.closed else "")
        w, d = self.extent()
        arcs = sum(1 for e in (self.points or []) if e.through)
        return f"poly {len(self.points or [])}pt{f' {arcs}arc' if arcs else ''} {w:g}x{d:g}"


# --- solids ------------------------------------------------------------------

class Solid(BaseModel):
    """One closed solid. `op` picks the operation; the fields the operation needs must be set.

    Sugar the step layer resolves before it gets here: `box`, `cylinder`, and the bare
    single-solid form. `GeoModel` only ever stores the resolved form, so there is exactly one
    representation to compile, check and migrate."""

    model_config = ConfigDict(extra="ignore")

    op: SolidOp = "extrude"
    place: Placement = Field(default_factory=Placement, description="Frame the solid sits in, inside its part")
    profile: Optional[Profile] = Field(None, description="extrude/revolve/sweep: the 2D shape")
    depth: Optional[float] = Field(None, description="extrude: distance along the frame's +Z (may be negative)")
    angle: Optional[float] = Field(None, description="revolve: degrees, 0 < angle <= 360")
    axis_at: Optional[Pt] = Field(None, description="revolve: a point on the axis, in the profile's plane")
    axis_dir: Optional[Pt] = Field(None, description="revolve: the axis direction in the profile's plane; default [0,1] (the local Y)")
    path: Optional[list[Vec3]] = Field(None, min_length=2, description="sweep: 3D polyline the cross-section is carried along")
    faces: Optional[list[list[Vec3]]] = Field(None, description="mesh: outward-facing vertex loops of a closed shell")

    @field_validator("axis_at", "axis_dir", mode="before")
    @classmethod
    def _p2(cls, v):
        return None if v is None else as_point(v)

    @field_validator("path", mode="before")
    @classmethod
    def _path(cls, v):
        if v is None:
            return None
        if not isinstance(v, (list, tuple)):
            raise ValueError("a sweep path is a list of points [[x,y,z], …]")
        return [as_point3(p) for p in v]

    @field_validator("faces", mode="before")
    @classmethod
    def _faces(cls, v):
        if v is None:
            return None
        if not isinstance(v, (list, tuple)):
            raise ValueError("mesh faces are a list of vertex loops [[[x,y,z], …], …]")
        return [[as_point3(p) for p in loop] for loop in v]

    @model_validator(mode="after")
    def _shape(self) -> "Solid":
        op = self.op
        if op in ("extrude", "revolve", "sweep") and self.profile is None:
            raise ValueError(f"a {op} solid needs a `profile`")
        if op == "extrude":
            if self.depth is None:
                raise ValueError("an extrude solid needs `depth`")
            if abs(self.depth) <= MIN_SIZE:
                raise ValueError(f"extrude depth must be more than {MIN_SIZE} m, got {self.depth}")
        elif op == "revolve":
            if self.angle is None:
                self.angle = 360.0
            if not 0 < self.angle <= 360:
                raise ValueError(f"revolve angle must be > 0 and <= 360 degrees, got {self.angle}")
            self._check_revolve()
        elif op == "sweep":
            pts = self.path or []
            total = sum(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))) for a, b in zip(pts, pts[1:]))
            if total <= MIN_SIZE:
                raise ValueError("a sweep path has no length")
        else:
            if not self.faces or len(self.faces) < 4:
                raise ValueError("a mesh solid needs at least 4 faces to close a shell")
            for loop in self.faces:
                if len(loop) < 3:
                    raise ValueError("every mesh face needs at least 3 vertices")
        return self

    def revolve_axis(self) -> tuple[Pt, Pt]:
        """(a point on the axis, its unit direction) in the profile's own plane.

        A revolve turns the profile about an axis *lying in the profile's plane*; `axis_dir`
        defaults to the profile's +Y, so the profile's x is the radius and its y runs along the
        axis. To stand the result up in the world — a dome, a tower, a cone — give the solid
        `place.axis = [0, -1, 0]`, which points the profile's +Y at world +Z."""
        ax, ay = self.axis_at or (0.0, 0.0)
        dx, dy = self.axis_dir or (0.0, 1.0)
        n = math.hypot(dx, dy) or 1.0
        return (ax, ay), (dx / n, dy / n)

    def _check_revolve(self) -> None:
        """The profile must be entirely on one side of the revolve axis, or the solid
        self-intersects and no tessellator will produce anything sane."""
        outer, _ = self.profile.rings()  # type: ignore[union-attr]
        if self.axis_dir is not None and math.hypot(*self.axis_dir) < 1e-9:
            raise ValueError("revolve axis_dir must not be the zero vector")
        (ax, ay), (dx, dy) = self.revolve_axis()
        sides = {round((p[0] - ax) * dy - (p[1] - ay) * dx, 6) for p in outer}
        neg = any(s < -1e-6 for s in sides)
        pos = any(s > 1e-6 for s in sides)
        if neg and pos:
            raise ValueError("a revolved profile must lie wholly on one side of its axis; this one crosses it, "
                            "which would make the solid pass through itself")

    def describe(self) -> str:
        if self.op == "extrude":
            return f"extrude({self.profile.describe()}, depth={self.depth:g})"  # type: ignore[union-attr]
        if self.op == "revolve":
            return f"revolve({self.profile.describe()}, {self.angle:g}deg)"     # type: ignore[union-attr]
        if self.op == "sweep":
            return f"sweep({self.profile.describe()}, {len(self.path or [])}pt path)"  # type: ignore[union-attr]
        return f"mesh({len(self.faces or [])} faces)"


# --- levels ------------------------------------------------------------------

class GeoLevel(BaseModel):
    """A spatial container. Ids keep the `L1`/`L2`/`B1` convention the viewer's storey snap and
    the frontend's level names rely on, but `elevation` may be set freely — a bridge deck level
    at +8 m or a tunnel level at -20 m is a level like any other."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: Optional[str] = None
    height: float = Field(3.0, gt=0, le=200.0, description="Nominal floor-to-floor height; a part may be taller")
    elevation: Optional[float] = Field(None, description="Metres above datum; null = stack on the level below")

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        s = str(v).strip().upper()
        if not LEVEL_ID.match(s) or int(s[1:]) < 1:
            raise ValueError(f"level ids look like 'L1', 'L2' … or 'B1', 'B2' below ground; got {v!r}")
        return s

    @property
    def below_ground(self) -> bool:
        return self.id.startswith("B")

    @property
    def index(self) -> int:
        """0 for the ground level, positive above, negative below (B1 = -1)."""
        n = int(self.id[1:])
        return -n if self.below_ground else n - 1

    @property
    def display(self) -> str:
        if self.name:
            return self.name
        if self.index < 0:
            return "Basement" if self.index == -1 else f"Basement {-self.index}"
        return "Ground Floor" if self.index == 0 else f"Level {self.index + 1}"


# --- parts, openings, assemblies, instances ---------------------------------

class GeoPart(BaseModel):
    """One IFC element: what it is, where its frame sits, and the solids that make its body."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: Optional[str] = None
    ifc: str = Field("IfcBuildingElementProxy", description="IFC entity name, validated against the configured schema")
    ifc_type: Optional[str] = Field(None, description="PredefinedType, validated against the entity")
    level: str = "L1"
    place: Placement = Field(default_factory=Placement)
    solids: list[Solid] = Field(min_length=1, max_length=MAX_SOLIDS)
    repeat: Optional[Repeat] = None
    material: Optional[str] = Field(None, description="Free-text material name, e.g. 'concrete', 'oak'")
    style: Optional[str] = Field(None, description="Free-text colour key; default by entity")

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return _ident(v, "part")

    @model_validator(mode="after")
    def _ifc(self) -> "GeoPart":
        try:
            self.ifc = check_entity(self.ifc)
            self.ifc_type = check_predefined_type(self.ifc, self.ifc_type)
        except SchemaError as exc:
            raise ValueError(str(exc)) from exc
        return self

    @property
    def copies(self) -> int:
        return self.repeat.count if self.repeat else 1

    def placements(self) -> list[Placement]:
        """The part-local frame of each repeat copy (identity when there is no repeat)."""
        if not self.repeat:
            return [Placement()]
        return [self.repeat.transform(i) for i in range(self.repeat.count)]

    def local_extent(self) -> tuple[Vec3, Vec3]:
        """Rough (min, max) corner of the part's own body in part-local coordinates, from the
        solids' profile extents. Cheap and approximate: the exact answer needs tessellation
        (`core/facts.py`), this is for opening sugar and for text descriptions."""
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        for solid in self.solids:
            corners: list[Vec3] = []
            if solid.profile is not None:
                outer, _ = solid.profile.rings()
                depth = solid.depth if solid.op == "extrude" else 0.0
                if solid.op == "sweep":
                    for base in solid.path or []:
                        for x, y in outer:
                            corners.append((base[0] + x, base[1] + y, base[2]))
                elif solid.op == "revolve":
                    # Points sweep circles in the plane across the axis; along the axis they stay put.
                    (ax, ay), (dx, dy) = solid.revolve_axis()
                    along = [(p[0] - ax) * dx + (p[1] - ay) * dy for p in outer]
                    rad = max(abs((p[0] - ax) * dy - (p[1] - ay) * dx) for p in outer)
                    lo_a, hi_a = min(along), max(along)
                    if abs(dy) >= abs(dx):      # axis along the profile's Y: radius spans local X and Z
                        corners += [(ax - rad, ay + lo_a, -rad), (ax + rad, ay + hi_a, rad)]
                    else:                       # axis along the profile's X: radius spans local Y and Z
                        corners += [(ax + lo_a, ay - rad, -rad), (ax + hi_a, ay + rad, rad)]
                else:
                    for x, y in outer:
                        corners += [(x, y, 0.0), (x, y, depth or 0.0)]
            for loop in solid.faces or []:
                corners += list(loop)
            for c in corners:
                w = solid.place.apply(c)
                for i in range(3):
                    lo[i] = min(lo[i], w[i])
                    hi[i] = max(hi[i], w[i])
        if lo[0] == float("inf"):
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        return tuple(r2(v) for v in lo), tuple(r2(v) for v in hi)  # type: ignore[return-value]

    def describe(self) -> str:
        name = f' "{self.name}"' if self.name else ""
        t = f":{self.ifc_type}" if self.ifc_type else ""
        p = self.place
        where = f"at({p.at[0]:g},{p.at[1]:g},{p.at[2]:g})"
        if p.rotation:
            where += f" rot={p.rotation:g}"
        if p.axis != (0.0, 0.0, 1.0):
            where += f" axis({p.axis[0]:g},{p.axis[1]:g},{p.axis[2]:g})"
        rep = f" repeat={self.repeat.count}x" if self.repeat else ""
        mat = f" material={self.material}" if self.material else ""
        return (f"part id={self.id}{name} {self.ifc}{t} {self.level} {where}{rep}{mat} "
                + "+".join(s.describe() for s in self.solids))


class GeoOpening(BaseModel):
    """A void cut into a host part, optionally filled by another part.

    Two ways to say where. The general one gives `solid`, in the host's own local frame. The
    short one gives `along` (distance along the host's local +X), `up` (height above the
    host's local base) and a `width`/`height`, which resolves to a box through the host — a
    purely geometric statement about the host's frame, which is why it works for a wall, a
    slab, a tunnel lining or a plate without any of them being a special case."""

    model_config = ConfigDict(extra="ignore")

    id: str
    host: str
    solid: Optional[Solid] = None
    along: Optional[float] = Field(None, description="Distance along the host's local +X to the void's near edge")
    up: Optional[float] = Field(None, description="Height above the host's local base")
    width: Optional[float] = Field(None, gt=0)
    height: Optional[float] = Field(None, gt=0)
    depth: Optional[float] = Field(None, gt=0, description="Through-thickness; null = the host's own local-Y extent + clearance")
    fill: Optional[str] = Field(None, description="Id of the part that fills this void (a leaf, a pane, a grille)")

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return _ident(v, "opening")

    @model_validator(mode="after")
    def _one(self) -> "GeoOpening":
        if self.solid is None:
            missing = [n for n, v in (("along", self.along), ("width", self.width), ("height", self.height)) if v is None]
            if missing:
                raise ValueError("an opening needs either a full `solid`, or `along`, `width` and `height` "
                                 f"(missing: {', '.join(missing)})")
            if self.up is None:
                self.up = 0.0
        return self

    def describe(self) -> str:
        what = self.solid.describe() if self.solid else f"box {self.width:g}x{self.height:g} at along={self.along:g} up={self.up:g}"
        return f"opening id={self.id} in {self.host} {what}" + (f" filled by {self.fill}" if self.fill else "")


class GeoAssembly(BaseModel):
    """A named group of parts, compiled to an `IfcElementAssembly` that aggregates them. Group
    a bridge bay, a truss, a stair with its landing; then `GeoInstance` can place copies."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: Optional[str] = None
    parts: list[str] = Field(min_length=1)
    ifc_type: Optional[str] = None
    level: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return _ident(v, "assembly")

    @model_validator(mode="after")
    def _t(self) -> "GeoAssembly":
        try:
            self.ifc_type = check_predefined_type("IfcElementAssembly", self.ifc_type)
        except SchemaError as exc:
            raise ValueError(str(exc)) from exc
        return self


class GeoInstance(BaseModel):
    """Transformed copies of an assembly's parts. Copy ids are `<instance id>-<part id>`, so a
    repeated storey or a repeated bridge bay keeps stable GlobalIds across edits."""

    model_config = ConfigDict(extra="ignore")

    id: str
    of: str = Field(description="Assembly id to copy")
    place: Placement = Field(default_factory=Placement)
    repeat: Optional[Repeat] = None
    level: Optional[str] = Field(None, description="Override the level of every copied part")

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return _ident(v, "instance")

    @property
    def copies(self) -> int:
        return self.repeat.count if self.repeat else 1


# --- the model ---------------------------------------------------------------

class GeoModel(BaseModel):
    """Everything the language model has built so far."""

    model_config = ConfigDict(extra="ignore")

    name: str = "Generated Model"
    description: Optional[str] = None
    levels: list[GeoLevel] = Field(default_factory=lambda: [GeoLevel(id="L1")])
    parts: list[GeoPart] = Field(default_factory=list)
    openings: list[GeoOpening] = Field(default_factory=list)
    assemblies: list[GeoAssembly] = Field(default_factory=list)
    instances: list[GeoInstance] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    # --- lookups ------------------------------------------------------------

    def level(self, level_id: str) -> GeoLevel | None:
        return next((l for l in self.levels if l.id == str(level_id).strip().upper()), None)

    def part(self, part_id: str) -> GeoPart | None:
        return next((p for p in self.parts if p.id == part_id), None)

    def opening(self, opening_id: str) -> GeoOpening | None:
        return next((o for o in self.openings if o.id == opening_id), None)

    def assembly(self, assembly_id: str) -> GeoAssembly | None:
        return next((a for a in self.assemblies if a.id == assembly_id), None)

    def instance(self, instance_id: str) -> GeoInstance | None:
        return next((i for i in self.instances if i.id == instance_id), None)

    def parts_on(self, level_id: str) -> list[GeoPart]:
        return [p for p in self.parts if p.level == level_id]

    def ordered_levels(self) -> list[GeoLevel]:
        return sorted(self.levels, key=lambda l: l.index)

    def elevations(self) -> dict[str, float]:
        """Level id → metres above datum. Explicit elevations win; the rest stack upward from
        the ground level at 0 and downward for basements."""
        out: dict[str, float] = {}
        z = 0.0
        for l in self.ordered_levels():
            if l.index < 0:
                continue
            out[l.id] = r2(l.elevation if l.elevation is not None else z)
            z = out[l.id] + l.height
        z = 0.0
        for l in reversed([l for l in self.ordered_levels() if l.index < 0]):
            z -= l.height
            out[l.id] = r2(l.elevation if l.elevation is not None else z)
        return out

    def storeys(self) -> int:
        return sum(1 for l in self.levels if l.index >= 0)

    def basements(self) -> int:
        return sum(1 for l in self.levels if l.index < 0)

    def all_ids(self) -> set[str]:
        return ({p.id for p in self.parts} | {o.id for o in self.openings} | {a.id for a in self.assemblies}
                | {i.id for i in self.instances} | {l.id for l in self.levels})

    def unique_id(self, base: str) -> str:
        base = slug(base)
        ids = self.all_ids()
        if base not in ids:
            return base
        n = 2
        while f"{base}-{n}" in ids:
            n += 1
        return f"{base}-{n}"

    def is_empty(self) -> bool:
        return not (self.parts or self.instances)

    # --- validation ---------------------------------------------------------

    @model_validator(mode="after")
    def _consistent(self) -> "GeoModel":
        if not self.levels:
            self.levels = [GeoLevel(id="L1")]
        if len(self.levels) > MAX_LEVELS:
            raise ValueError(f"at most {MAX_LEVELS} levels are supported, got {len(self.levels)}")
        errors: list[str] = []
        level_ids = [l.id for l in self.levels]
        if len(set(level_ids)) != len(level_ids):
            errors.append("level ids must be unique")
        seen: set[str] = set()
        for group, label in ((self.parts, "part"), (self.openings, "opening"), (self.assemblies, "assembly"),
                             (self.instances, "instance")):
            for item in group:
                if item.id in seen:
                    errors.append(f"id '{item.id}' is used twice")
                seen.add(item.id)
        for p in self.parts:
            if p.level not in level_ids:
                errors.append(f"part '{p.id}' is on unknown level '{p.level}' (levels: {', '.join(level_ids)})")
        for o in self.openings:
            host = self.part(o.host)
            if host is None:
                errors.append(f"opening '{o.id}' has unknown host part '{o.host}'")
            if o.fill is not None and self.part(o.fill) is None:
                errors.append(f"opening '{o.id}' is filled by unknown part '{o.fill}'")
        for a in self.assemblies:
            for pid in a.parts:
                if self.part(pid) is None:
                    errors.append(f"assembly '{a.id}' lists unknown part '{pid}'")
            if a.level is not None and a.level not in level_ids:
                errors.append(f"assembly '{a.id}' is on unknown level '{a.level}'")
        for i in self.instances:
            if self.assembly(i.of) is None:
                errors.append(f"instance '{i.id}' copies unknown assembly '{i.of}' "
                              f"(assemblies: {', '.join(a.id for a in self.assemblies) or 'none'})")
            if i.level is not None and i.level not in level_ids:
                errors.append(f"instance '{i.id}' is on unknown level '{i.level}'")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def total_parts(self) -> int:
        """Parts after instancing, i.e. how many IFC elements the body of the model will hold."""
        n = len(self.parts)
        for inst in self.instances:
            asm = self.assembly(inst.of)
            if asm:
                n += len(asm.parts) * inst.copies
        return n
