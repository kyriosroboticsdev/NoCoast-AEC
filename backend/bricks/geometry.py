"""Parametric solid geometry: a tree of primitives whose every number may be an expression.

Authoring (what a definition — a library file or a model-written asset — contains) is a list of nodes:

    box       size [x, y, z], from its local origin (min corner)
    cylinder  radius, height, optional inner radius (a tube); base centred on the origin, axis +z
    cone      radius, height, top_radius (0 = a point); base centred on the origin
    sphere    radius, centred on the origin
    extrude   a 2D profile extruded `height` along +z
    revolve   a 2D profile in the (r, z) half-plane revolved `angle` degrees about the z axis
    sweep     a profile along a 3D polyline `path` (a circle profile makes a pipe)
    loft      2D profiles at increasing `z`, skinned into one closed solid (same vertex count each)
    mesh      explicit vertices and faces (0-based indices): any shape at all
    group     children sharing one transform, repeat and cut

Every node may also carry `at` [x, y, z] and `rotate` [rx, ry, rz] (degrees, applied x, then y, then z,
about `at`), `repeat` {count, var} (copies, each with `var` = 0 … count-1 in its expressions), `when`
(skipped unless the expression is non-zero), `material` (a key of the definition's materials) and
`subtract` (nodes cut out of it). A primitive whose size evaluates to zero or less is left out, so
a parameter can switch a part off.

Profiles: {"rect": [w, d], "centered": bool}, {"circle": r, "inner": r2}, {"ngon": n, "radius": r},
{"points": [[x, y], …], "holes": [[[x, y], …]]}, or a bare list of points; rect, circle and ngon take
an optional `at` [x, y] offset.

`evaluate` resolves the tree against parameter values into flat `Solid`s — four kinds (extrusion,
revolution, pipe, mesh), each with a 3x4 matrix into the definition's frame — which is all the IFC
compiler and the clash check need.
"""

from __future__ import annotations

import math
from typing import Annotated, Iterator, Literal, Optional, Union

import numpy as np
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from bricks.expr import ExprError, evaluate as eval_expr, names_in

Number = Union[float, str]
Vec2 = tuple[Number, Number]
Vec3 = tuple[Number, Number, Number]
P2 = tuple[float, float]
P3 = tuple[float, float, float]

MAX_SOLIDS = 400
MAX_REPEAT = 500
CIRCLE_SIDES = 24
SPHERE_RINGS = 8


class GeometryError(ValueError):
    pass


# --- authoring ---------------------------------------------------------------

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Repeat(_Strict):
    count: Number
    var: str = "i"


class RectProfile(_Strict):
    rect: Vec2
    centered: bool = False
    at: Vec2 = (0, 0)


class CircleProfileSpec(_Strict):
    circle: Number
    inner: Optional[Number] = None
    at: Vec2 = (0, 0)


class NgonProfile(_Strict):
    ngon: Number
    radius: Number
    at: Vec2 = (0, 0)


class PointsProfile(_Strict):
    points: list[Vec2] = Field(min_length=3)
    holes: list[list[Vec2]] = Field(default_factory=list)


def _profile_before(v):
    return {"points": v} if isinstance(v, list) else v


ProfileSpec = Annotated[Union[RectProfile, CircleProfileSpec, NgonProfile, PointsProfile], BeforeValidator(_profile_before)]


class _Node(_Strict):
    at: Vec3 = (0, 0, 0)
    rotate: Vec3 = (0, 0, 0)
    repeat: Optional[Repeat] = None
    when: Optional[Number] = None
    material: Optional[str] = None
    subtract: list["Node"] = Field(default_factory=list)


class Box(_Node):
    shape: Literal["box"] = "box"
    size: Vec3


class Cylinder(_Node):
    shape: Literal["cylinder"] = "cylinder"
    radius: Number
    height: Number
    inner: Optional[Number] = None


class Cone(_Node):
    shape: Literal["cone"] = "cone"
    radius: Number
    height: Number
    top_radius: Number = 0


class Sphere(_Node):
    shape: Literal["sphere"] = "sphere"
    radius: Number


class Extrude(_Node):
    shape: Literal["extrude"] = "extrude"
    profile: ProfileSpec
    height: Number


class Revolve(_Node):
    shape: Literal["revolve"] = "revolve"
    profile: ProfileSpec
    angle: Number = 360


class Sweep(_Node):
    shape: Literal["sweep"] = "sweep"
    profile: ProfileSpec
    path: list[Vec3] = Field(min_length=2)


class Section(_Strict):
    z: Number
    profile: ProfileSpec


class Loft(_Node):
    shape: Literal["loft"] = "loft"
    sections: list[Section] = Field(min_length=2)


class Mesh(_Node):
    shape: Literal["mesh"] = "mesh"
    vertices: list[Vec3] = Field(min_length=4)
    faces: list[list[int]] = Field(min_length=4)


class Group(_Node):
    shape: Literal["group"] = "group"
    children: list["Node"] = Field(min_length=1)


Node = Annotated[Union[Box, Cylinder, Cone, Sphere, Extrude, Revolve, Sweep, Loft, Mesh, Group], Field(discriminator="shape")]
for _cls in (_Node, Box, Cylinder, Cone, Sphere, Extrude, Revolve, Sweep, Loft, Mesh, Group):
    _cls.model_rebuild()


def expressions(nodes: list, scope: frozenset[str] = frozenset()) -> Iterator[tuple[str, frozenset[str]]]:
    """Every expression in a node tree with the repeat variables in scope where it is evaluated."""
    for node in nodes:
        inner = scope | {node.repeat.var} if node.repeat else scope
        if node.repeat and isinstance(node.repeat.count, str):
            yield node.repeat.count, scope
        for name, value in node:
            if name in ("children", "subtract", "repeat", "shape", "material"):
                continue
            for text in _strings(value):
                yield text, inner
        yield from expressions(node.subtract, inner)
        if isinstance(node, Group):
            yield from expressions(node.children, inner)


def _strings(value) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, BaseModel):
        for _, v in value:
            yield from _strings(v)


def unknown_names(nodes: list, known: set[str]) -> list[tuple[str, set[str]]]:
    """(expression, names it uses that are neither `known` nor a repeat variable in scope)."""
    out = []
    for text, scope in expressions(nodes):
        missing = names_in(text) - known - scope
        if missing:
            out.append((text, missing))
    return out


# --- resolved solids -----------------------------------------------------------

class PolygonProfile(BaseModel):
    kind: Literal["polygon"] = "polygon"
    outer: list[P2]
    holes: list[list[P2]] = Field(default_factory=list)


class CircleProfile(BaseModel):
    kind: Literal["circle"] = "circle"
    center: P2 = (0.0, 0.0)
    radius: float
    inner: Optional[float] = None


Profile = Annotated[Union[PolygonProfile, CircleProfile], Field(discriminator="kind")]


class _Solid(BaseModel):
    matrix: tuple[float, ...] = Field(description="3x4 row-major transform into the definition's frame")
    material: Optional[str] = None
    cuts: list["Solid"] = Field(default_factory=list)

    @property
    def m(self) -> np.ndarray:
        out = np.eye(4)
        out[:3, :] = np.array(self.matrix).reshape(3, 4)
        return out


class Extrusion(_Solid):
    kind: Literal["extrusion"] = "extrusion"
    profile: Profile
    height: float


class Revolution(_Solid):
    kind: Literal["revolution"] = "revolution"
    profile: Profile
    angle: float


class Pipe(_Solid):
    kind: Literal["pipe"] = "pipe"
    path: list[P3]
    radius: float
    inner: Optional[float] = None


class MeshSolid(_Solid):
    kind: Literal["mesh"] = "mesh"
    vertices: list[P3]
    faces: list[list[int]]


Solid = Annotated[Union[Extrusion, Revolution, Pipe, MeshSolid], Field(discriminator="kind")]
for _cls in (_Solid, Extrusion, Revolution, Pipe, MeshSolid):
    _cls.model_rebuild()

Bounds = tuple[float, float, float, float, float, float]   # x0, y0, z0, x1, y1, z1


# --- evaluation ------------------------------------------------------------------

def transform(at: P3 = (0.0, 0.0, 0.0), rotate: P3 = (0.0, 0.0, 0.0)) -> np.ndarray:
    """4x4: rotate about x, then y, then z (degrees), then translate to `at`."""
    rx, ry, rz = (math.radians(a) for a in rotate)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    x = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    out = np.eye(4)
    out[:3, :3] = z @ y @ x
    out[:3, 3] = at
    return out


def _flat(m: np.ndarray) -> tuple[float, ...]:
    return tuple(round(float(v), 6) for v in m[:3, :].reshape(-1))


class _Ctx:
    def __init__(self, values: dict[str, float]):
        self.values = values
        self.count = 0

    def num(self, v: Number, values: dict[str, float]) -> float:
        if not isinstance(v, str):
            return float(v)
        return eval_expr(v, values)

    def vec(self, v, values) -> tuple[float, ...]:
        return tuple(self.num(x, values) for x in v)


def evaluate(nodes: list, values: dict[str, float]) -> list:
    """Resolve a node tree into Solids in the definition's frame. Raises GeometryError."""
    ctx = _Ctx(values)
    out: list = []
    try:
        for node in nodes:
            out += _node(ctx, node, np.eye(4), values, [])
    except ExprError as exc:
        raise GeometryError(str(exc)) from exc
    return out


def _node(ctx: _Ctx, node, parent: np.ndarray, values: dict[str, float], cuts: list) -> list:
    copies = [values]
    if node.repeat:
        n = int(round(ctx.num(node.repeat.count, values)))
        if n > MAX_REPEAT:
            raise GeometryError(f"repeat count {n} is more than {MAX_REPEAT}")
        copies = [values | {node.repeat.var: float(k)} for k in range(max(n, 0))]
    out = []
    for vals in copies:
        if node.when is not None and not ctx.num(node.when, vals):
            continue
        frame = parent @ transform(ctx.vec(node.at, vals), ctx.vec(node.rotate, vals))
        own_cuts = cuts + [c for sub in node.subtract for c in _node(ctx, sub, frame, vals, [])]
        if isinstance(node, Group):
            for child in node.children:
                out += _node(ctx, child, frame, vals, own_cuts)
            continue
        for solid in _primitive(ctx, node, frame, vals):
            ctx.count += 1
            if ctx.count > MAX_SOLIDS:
                raise GeometryError(f"the geometry evaluates to more than {MAX_SOLIDS} solids")
            out.append(solid.model_copy(update={"material": node.material, "cuts": own_cuts}))
    return out


def _profile(ctx: _Ctx, spec, vals) -> PolygonProfile | CircleProfile | None:
    """None when the profile has no area with these values."""
    match spec:
        case RectProfile():
            w, d = ctx.vec(spec.rect, vals)
            ox, oy = ctx.vec(spec.at, vals)
            if w <= 0 or d <= 0:
                return None
            x0, y0 = (ox - w / 2, oy - d / 2) if spec.centered else (ox, oy)
            return PolygonProfile(outer=[(x0, y0), (x0 + w, y0), (x0 + w, y0 + d), (x0, y0 + d)])
        case CircleProfileSpec():
            r = ctx.num(spec.circle, vals)
            inner = ctx.num(spec.inner, vals) if spec.inner is not None else None
            if r <= 0:
                return None
            if inner is not None and not 0 < inner < r:
                inner = None
            return CircleProfile(center=ctx.vec(spec.at, vals), radius=r, inner=inner)
        case NgonProfile():
            n = int(round(ctx.num(spec.ngon, vals)))
            r = ctx.num(spec.radius, vals)
            ox, oy = ctx.vec(spec.at, vals)
            if n < 3 or r <= 0:
                return None
            return PolygonProfile(outer=[(ox + r * math.cos(2 * math.pi * k / n), oy + r * math.sin(2 * math.pi * k / n)) for k in range(n)])
        case PointsProfile():
            outer = [ctx.vec(p, vals) for p in spec.points]
            if abs(_area(outer)) < 1e-9:
                return None
            return PolygonProfile(outer=outer, holes=[[ctx.vec(p, vals) for p in h] for h in spec.holes])
    raise GeometryError(f"unknown profile {spec!r}")


def _area(pts: list[P2]) -> float:
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2


def _ring(profile: PolygonProfile | CircleProfile) -> list[P2]:
    if isinstance(profile, PolygonProfile):
        return profile.outer
    (cx, cy), r = profile.center, profile.radius
    return [(cx + r * math.cos(2 * math.pi * k / CIRCLE_SIDES), cy + r * math.sin(2 * math.pi * k / CIRCLE_SIDES)) for k in range(CIRCLE_SIDES)]


def _primitive(ctx: _Ctx, node, frame: np.ndarray, vals) -> list:
    m = _flat(frame)
    match node:
        case Box():
            x, y, z = ctx.vec(node.size, vals)
            if min(x, y, z) <= 0:
                return []
            return [Extrusion(matrix=m, profile=PolygonProfile(outer=[(0, 0), (x, 0), (x, y), (0, y)]), height=z)]
        case Cylinder():
            r, h = ctx.num(node.radius, vals), ctx.num(node.height, vals)
            inner = ctx.num(node.inner, vals) if node.inner is not None else None
            if r <= 0 or h <= 0:
                return []
            return [Extrusion(matrix=m, profile=CircleProfile(radius=r, inner=inner if inner and 0 < inner < r else None), height=h)]
        case Cone():
            r, h, top = ctx.num(node.radius, vals), ctx.num(node.height, vals), max(0.0, ctx.num(node.top_radius, vals))
            if r <= 0 or h <= 0:
                return []
            outline = [(0.0, 0.0), (r, 0.0), (top, h), (0.0, h)] if top > 0 else [(0.0, 0.0), (r, 0.0), (0.0, h)]
            return [Revolution(matrix=m, profile=PolygonProfile(outer=outline), angle=360.0)]
        case Sphere():
            r = ctx.num(node.radius, vals)
            return [_sphere(m, r)] if r > 0 else []
        case Extrude():
            p, h = _profile(ctx, node.profile, vals), ctx.num(node.height, vals)
            return [Extrusion(matrix=m, profile=p, height=h)] if p is not None and h > 0 else []
        case Revolve():
            p, angle = _profile(ctx, node.profile, vals), ctx.num(node.angle, vals)
            if p is None or angle <= 0:
                return []
            if min(x for x, _ in _ring(p)) < -1e-9:
                raise GeometryError("a revolve profile must lie at r >= 0 (x is the distance from the axis)")
            return [Revolution(matrix=m, profile=p, angle=min(angle, 360.0))]
        case Sweep():
            return _sweep(ctx, node, frame, vals)
        case Loft():
            return _loft(ctx, node, m, vals)
        case Mesh():
            verts = [ctx.vec(v, vals) for v in node.vertices]
            bad = [i for f in node.faces for i in f if not 0 <= i < len(verts)]
            if bad or any(len(f) < 3 for f in node.faces):
                raise GeometryError(f"mesh faces need at least 3 indices, each 0..{len(verts) - 1}")
            return [MeshSolid(matrix=m, vertices=verts, faces=[list(f) for f in node.faces])]
    raise GeometryError(f"unknown node {node!r}")


def _sphere(m, r: float) -> MeshSolid:
    """A UV sphere as a mesh — IfcSphere is not drawn by every viewer."""
    verts: list[P3] = [(0.0, 0.0, -r)]
    for i in range(1, SPHERE_RINGS):
        phi = math.pi * i / SPHERE_RINGS - math.pi / 2
        for k in range(CIRCLE_SIDES):
            t = 2 * math.pi * k / CIRCLE_SIDES
            verts.append((r * math.cos(phi) * math.cos(t), r * math.cos(phi) * math.sin(t), r * math.sin(phi)))
    verts.append((0.0, 0.0, r))
    n, top = CIRCLE_SIDES, len(verts) - 1
    faces = [[0, 1 + (k + 1) % n, 1 + k] for k in range(n)]
    for i in range(SPHERE_RINGS - 2):
        a, b = 1 + i * n, 1 + (i + 1) * n
        faces += [[a + k, a + (k + 1) % n, b + (k + 1) % n, b + k] for k in range(n)]
    last = 1 + (SPHERE_RINGS - 2) * n
    faces += [[last + k, last + (k + 1) % n, top] for k in range(n)]
    return MeshSolid(matrix=m, vertices=verts, faces=faces)


def _sweep(ctx: _Ctx, node: Sweep, frame: np.ndarray, vals) -> list:
    path = [ctx.vec(p, vals) for p in node.path]
    profile = _profile(ctx, node.profile, vals)
    if profile is None:
        return []
    if isinstance(profile, CircleProfile) and profile.center == (0.0, 0.0):
        return [Pipe(matrix=_flat(frame), path=path, radius=profile.radius, inner=profile.inner)]
    out = []
    for a, b in zip(path, path[1:]):
        d = np.subtract(b, a)
        length = float(np.linalg.norm(d))
        if length < 1e-6:
            continue
        z = d / length
        x = np.cross((0.0, 0.0, 1.0), z) if abs(z[2]) < 0.999 else np.array([1.0, 0.0, 0.0])
        x = x / np.linalg.norm(x)
        y = np.cross(z, x)
        seg = np.eye(4)
        seg[:3, 0], seg[:3, 1], seg[:3, 2], seg[:3, 3] = x, y, z, a
        out.append(Extrusion(matrix=_flat(frame @ seg), profile=profile, height=length))
    return out


def _loft(ctx: _Ctx, node: Loft, m, vals) -> list:
    rings = []
    for s in node.sections:
        p = _profile(ctx, s.profile, vals)
        if p is None:
            return []
        z = ctx.num(s.z, vals)
        rings.append([(x, y, z) for x, y in _ring(p)])
    n = len(rings[0])
    if any(len(r) != n for r in rings):
        raise GeometryError(f"loft sections need the same number of vertices (got {[len(r) for r in rings]})")
    verts = [v for r in rings for v in r]
    faces = [list(reversed(range(n)))]
    for i in range(len(rings) - 1):
        a, b = i * n, (i + 1) * n
        faces += [[a + k, a + (k + 1) % n, b + (k + 1) % n, b + k] for k in range(n)]
    faces.append(list(range((len(rings) - 1) * n, len(rings) * n)))
    return [MeshSolid(matrix=m, vertices=verts, faces=faces)]


# --- bounds ----------------------------------------------------------------------

def _local_points(solid) -> list[P3]:
    match solid:
        case Extrusion(profile=p, height=h):
            x0, y0, x1, y1 = _profile_box(p)
            return [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (0.0, h)]
        case Revolution(profile=p, angle=_):
            _, z0, r, z1 = _profile_box(p)
            return [(x, y, z) for x in (-r, r) for y in (-r, r) for z in (z0, z1)]
        case Pipe(path=path, radius=r):
            return [(x + dx, y + dy, z + dz) for x, y, z in path for dx in (-r, r) for dy in (-r, r) for dz in (-r, r)]
        case MeshSolid(vertices=v):
            return list(v)
    raise GeometryError(f"unknown solid {solid!r}")


def _profile_box(p) -> tuple[float, float, float, float]:
    if isinstance(p, CircleProfile):
        (cx, cy), r = p.center, p.radius
        return cx - r, cy - r, cx + r, cy + r
    xs, ys = [x for x, _ in p.outer], [y for _, y in p.outer]
    return min(xs), min(ys), max(xs), max(ys)


def corners(solids: list, frame: np.ndarray | None = None) -> np.ndarray:
    """Every bounding point of the solids (cuts ignored), through `frame` if given: an (n, 3) array."""
    pts = []
    for s in solids:
        local = np.array(_local_points(s), dtype=float)
        m = s.m if frame is None else frame @ s.m
        pts.append(local @ m[:3, :3].T + m[:3, 3])
    return np.vstack(pts) if pts else np.zeros((0, 3))


def bounds(solids: list) -> Bounds:
    pts = corners(solids)
    if not len(pts):
        raise GeometryError("no solids")
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    return tuple(round(float(v), 4) for v in (*lo, *hi))
