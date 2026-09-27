"""What a brick is: one reusable, parametric asset definition — anything that has a shape.

A brick is data, never code: an IFC identity (any non-abstract IfcElement class), named parameters
with limits, a geometry tree (bricks/geometry.py) whose numbers are expressions over the parameters,
and a little generic metadata:

  * `origin`     the point of the geometry that lands on the placement point
  * `mount`      how it attaches when placed against something (bricks/place.py): `rest` on an upward
                 surface, `fix` its back (local -y) against a vertical face, `hang` from a downward
                 surface, or run along a `path` between two points
  * `elevation`  default gap between that surface and the origin (a wall cabinet at 1.5 m)
  * `materials`  named colours; geometry nodes pick one by key, the first is the default
  * `connectors` what it needs (`in`) and supplies (`out`), as free-form kinds ("water", "power", "air")
  * `keepout`    volumes (geometry nodes) nothing else may stand in — access space, swing, clearance
  * `properties` free-form values written to IFC and read by whatever rules a project applies

A parameter can `fit` its placement: an expression over PLACEMENT_VARS (`ref_w`, `ref_d`, `ref_h`
— the size of what it is placed in or on — and `path_length`) that sets it when the step leaves
it out, so a column fills its storey and a beam takes the length of its path.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional, Union

import ifcopenshell.ifcopenshell_wrapper as ifc_wrapper
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bricks.expr import ExprError, evaluate, names_in
from bricks.geometry import Bounds, GeometryError, Node, bounds, corners, evaluate as evaluate_geometry, transform, unknown_names

Number = Union[float, str]
Mount = Literal["rest", "fix", "hang", "path"]
PLACEMENT_VARS = ("ref_w", "ref_d", "ref_h", "path_length")
MOUNT_HINTS: dict[Mount, str] = {
    "rest": "stands on an upward surface: the floor of `ref`, or the top of a solid `ref`; `side`/`near` puts its back against a side",
    "fix": "fixed by its back to a vertical side of `ref` (`side` or `near`), `elevation` above its base",
    "hang": "hangs from a downward surface: the ceiling of `ref`, or the underside of a solid `ref`",
    "path": "runs from `start` to `end`; its length is the distance between them",
}
IFC_SCHEMA = ifc_wrapper.schema_by_name("IFC4")


class Param(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    default: float
    min: Optional[float] = None
    max: Optional[float] = None
    unit: str = "m"
    description: str = ""
    fit: Optional[str] = Field(None, description="Expression over the placement (ref_w, ref_d, ref_h, path_length) used when not given")

    @model_validator(mode="after")
    def _range(self) -> "Param":
        if (self.min is not None and self.default < self.min) or (self.max is not None and self.default > self.max):
            raise ValueError(f"param {self.name}: default {self.default} is outside [{self.min}, {self.max}]")
        if self.fit is not None and names_in(self.fit) - set(PLACEMENT_VARS):
            raise ValueError(f"param {self.name}: fit may only use {', '.join(PLACEMENT_VARS)}")
        return self

    def check(self, owner: str, v: float) -> float:
        if (self.min is not None and v < self.min) or (self.max is not None and v > self.max):
            lo = "-inf" if self.min is None else f"{self.min:g}"
            hi = "inf" if self.max is None else f"{self.max:g}"
            raise ValueError(f"brick {owner}: {self.name}={v:g} is outside {lo}..{hi} {self.unit}")
        return v


class Material(BaseModel):
    model_config = ConfigDict(extra="forbid")
    color: tuple[float, float, float] = Field((0.8, 0.8, 0.8), description="RGB, 0..1")
    opacity: float = Field(1.0, ge=0.05, le=1.0)
    name: Optional[str] = Field(None, description="IFC material name, e.g. Timber, Steel")

    @field_validator("color")
    @classmethod
    def _rgb(cls, v):
        if any(not 0 <= c <= 1 for c in v):
            raise ValueError(f"colour components are 0..1, got {v}")
        return v


class Connector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str
    direction: Literal["in", "out"] = "in"

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        v = v.strip().lower().replace(" ", "_").replace("-", "_")
        if not v:
            raise ValueError("a connector needs a kind")
        return v

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.direction}"


PropertyValue = Union[bool, float, str]


class Brick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    ifc_class: str = "IfcBuildingElementProxy"
    predefined_type: Optional[str] = None
    params: list[Param] = Field(default_factory=list)
    geometry: list[Node] = Field(min_length=1)
    origin: tuple[Number, Number, Number] = (0, 0, 0)
    mount: Mount = "rest"
    elevation: Number = 0
    materials: dict[str, Material] = Field(default_factory=lambda: {"default": Material()})
    connectors: list[Connector] = Field(default_factory=list)
    keepout: list[Node] = Field(default_factory=list)
    collides: bool = Field(True, description="False: may overlap other things (a rug, a light over a table)")
    properties: dict[str, PropertyValue] = Field(default_factory=dict)

    @field_validator("params", mode="before")
    @classmethod
    def _params(cls, v):
        """Compact form: {"w": [default, min, max, unit, description], "n": 3}."""
        if not isinstance(v, dict):
            return v
        out = []
        for name, spec in v.items():
            if isinstance(spec, (int, float)):
                spec = [spec]
            if isinstance(spec, dict):
                out.append({"name": name, **spec})
                continue
            item = {"name": name, "default": spec[0]}
            if len(spec) > 2:
                item["min"], item["max"] = spec[1], spec[2]
            for key, value in zip(("unit", "description"), spec[3:]):
                item[key] = value
            out.append(item)
        return out

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not v or not all(c.islower() or c.isdigit() or c == "_" for c in v):
            raise ValueError(f"brick ids are lower_snake_case, got {v!r}")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "Brick":
        names = [p.name for p in self.params]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.id}: duplicate params")
        _check_ifc(self.ifc_class, self.predefined_type)
        known = set(names) | set(PLACEMENT_VARS)
        bad = unknown_names(self.geometry + self.keepout, known)
        if bad:
            text, missing = bad[0]
            raise ValueError(f"{self.id}: {text!r} uses unknown names {sorted(missing)} (params: {', '.join(names) or 'none'})")
        for text in [v for v in (*self.origin, self.elevation) if isinstance(v, str)]:
            if names_in(text) - known:
                raise ValueError(f"{self.id}: {text!r} uses unknown names {sorted(names_in(text) - known)}")
        if not self.materials:
            raise ValueError(f"{self.id}: needs at least one material")
        used = _materials_used(self.geometry)
        if used - set(self.materials):
            raise ValueError(f"{self.id}: geometry uses materials {sorted(used - set(self.materials))} it does not define")
        if self.mount == "path" and self.path_param is None:
            raise ValueError(f"{self.id}: a path brick needs a param with fit \"path_length\" (its length)")
        return self

    # --- evaluation ---------------------------------------------------------

    @property
    def path_param(self) -> Param | None:
        return next((p for p in self.params if p.fit and "path_length" in names_in(p.fit)), None)

    @property
    def default_material(self) -> str:
        return next(iter(self.materials))

    def param(self, name: str) -> Param | None:
        return next((p for p in self.params if p.name == name), None)

    def resolve(self, given: dict[str, float] | None = None, context: dict[str, float] | None = None) -> dict[str, float]:
        """Parameter values — defaults, then fitted to `context`, then `given` — each checked against its
        limits, plus the context itself (geometry may read ref_w … path_length)."""
        context = context or {}
        values = {p.name: p.default for p in self.params}
        for p in self.params:
            if p.fit and p.name not in (given or {}) and names_in(p.fit) <= set(context):
                values[p.name] = p.check(self.id, round(evaluate(p.fit, context), 4))
        for name, value in (given or {}).items():
            p = self.param(name)
            if p is None:
                raise ValueError(f"brick {self.id} has no param '{name}' (params: {', '.join(values) or 'none'})")
            values[name] = p.check(self.id, float(value))
        return {**{k: 0.0 for k in PLACEMENT_VARS}, **context, **values}

    def _num(self, v: Number, values: dict[str, float]) -> float:
        return float(v) if not isinstance(v, str) else evaluate(v, values)

    def solids(self, values: dict[str, float]) -> list:
        """The evaluated solids with the origin moved to (0, 0, 0)."""
        try:
            solids = evaluate_geometry(self.geometry, values)
            shift = transform(tuple(-self._num(v, values) for v in self.origin))
        except (GeometryError, ExprError) as exc:
            raise ValueError(f"brick {self.id}: {exc}") from exc
        if not solids:
            raise ValueError(f"brick {self.id}: every part has zero size with these params")
        return [_moved(s, shift) for s in solids]

    def keepout_boxes(self, values: dict[str, float]) -> list[Bounds]:
        """Each keepout volume's bounding box, in the same frame as `solids`."""
        try:
            shift = transform(tuple(-self._num(v, values) for v in self.origin))
            out = []
            for node in self.keepout:
                solids = evaluate_geometry([node], values)
                if solids:
                    pts = corners(solids, shift)
                    out.append(tuple(round(float(v), 4) for v in (*pts.min(axis=0), *pts.max(axis=0))))
            return out
        except (GeometryError, ExprError) as exc:
            raise ValueError(f"brick {self.id} keepout: {exc}") from exc

    def elevation_of(self, values: dict[str, float]) -> float:
        return self._num(self.elevation, values)

    @property
    def provides(self) -> list[str]:
        return [c.kind for c in self.connectors if c.direction == "out"]

    @property
    def needs(self) -> list[str]:
        return [c.kind for c in self.connectors if c.direction == "in"]

    # --- text for the model ------------------------------------------------

    def size_text(self) -> str:
        try:
            x0, y0, z0, x1, y1, z1 = bounds(self.solids(self.resolve()))
        except ValueError:
            return "size varies"
        return f"{x1 - x0:.2g}x{y1 - y0:.2g}x{z1 - z0:.2g} m"

    def line(self) -> str:
        """One-line summary for search results."""
        conn = " connectors=" + ",".join(f"{c.kind}{'↑' if c.direction == 'out' else ''}" for c in self.connectors) if self.connectors else ""
        tags = f" [{', '.join(self.tags[:5])}]" if self.tags else ""
        return f"{self.id} — {self.name}{tags} mount={self.mount} {self.size_text()}{conn}"

    def card(self) -> str:
        """Everything the model needs to place it correctly."""
        lines = [self.line(), f"  {self.description}" if self.description else None,
                 f"  ifc: {self.ifc_class}" + (f".{self.predefined_type}" if self.predefined_type else "")]
        params = []
        for p in self.params:
            rng = f" {p.min:g}..{p.max:g}" if p.min is not None and p.max is not None else ""
            fit = f" (fits {p.fit})" if p.fit else ""
            params.append(f"{p.name}={p.default:g}{p.unit if p.unit != '-' else ''}{rng}{fit}" + (f" ({p.description})" if p.description else ""))
        if params:
            lines.append("  params: " + "; ".join(params))
        lines.append(f"  mount {self.mount}: {MOUNT_HINTS[self.mount]}")
        bits = []
        if isinstance(self.elevation, str) or self.elevation:
            bits.append(f"elevation {self.elevation}")
        if self.keepout:
            bits.append(f"{len(self.keepout)} keep-out volume(s)")
        if not self.collides:
            bits.append("may overlap other things")
        if self.needs:
            bits.append("needs " + ", ".join(self.needs))
        if self.provides:
            bits.append("provides " + ", ".join(self.provides))
        bits += [f"{k}={v}" for k, v in self.properties.items()]
        if bits:
            lines.append("  " + "; ".join(bits))
        return "\n".join(l for l in lines if l)


def _moved(solid, shift: np.ndarray):
    return solid.model_copy(update={"matrix": _mul(shift, solid), "cuts": [_moved(c, shift) for c in solid.cuts]})


def _mul(shift: np.ndarray, solid) -> tuple[float, ...]:
    return tuple(round(float(v), 6) for v in (shift @ solid.m)[:3, :].reshape(-1))


def _materials_used(nodes: list) -> set[str]:
    out = set()
    for n in nodes:
        if n.material:
            out.add(n.material)
        out |= _materials_used(n.subtract)
        out |= _materials_used(getattr(n, "children", []))
    return out


@lru_cache(maxsize=512)
def _check_ifc(ifc_class: str, predefined_type: str | None) -> None:
    try:
        decl = IFC_SCHEMA.declaration_by_name(ifc_class)
    except (RuntimeError, IndexError) as exc:
        raise ValueError(f"'{ifc_class}' is not an IFC4 class") from exc
    if not hasattr(decl, "is_abstract") or decl.is_abstract():
        raise ValueError(f"{ifc_class} is abstract or not an entity; use a concrete class such as IfcBuildingElementProxy")
    parent, chain = decl, set()
    while parent is not None:
        chain.add(parent.name())
        parent = parent.supertype()
    if "IfcElement" not in chain:
        raise ValueError(f"{ifc_class} is not an IfcElement; use an element class such as IfcBuildingElementProxy")
    if predefined_type is None:
        return
    enum = predefined_types(ifc_class)
    if not enum or predefined_type not in enum:
        raise ValueError(f"{ifc_class} has no predefined type {predefined_type!r}" + (f" (one of {', '.join(enum)})" if enum else ""))


@lru_cache(maxsize=512)
def predefined_types(ifc_class: str) -> tuple[str, ...]:
    for attr in IFC_SCHEMA.declaration_by_name(ifc_class).all_attributes():
        if attr.name() == "PredefinedType":
            t = attr.type_of_attribute()
            while hasattr(t, "declared_type"):
                t = t.declared_type()
            return tuple(t.enumeration_items())
    return ()
