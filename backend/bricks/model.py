"""What a brick is: one reusable, parametric building asset the model can search for and place.

A brick knows its IFC identity (class + predefined type), its size parameters and their
limits, how it is hosted (`HOSTS`: standing on the floor, fixed to a wall, hung from the
ceiling, on the roof, free-standing, spanning two points, or outside on the site), the service ports it
needs or provides (water, drain, power, air …), placement rules, and the solids it is
drawn with. The solids are expressions over the parameters, so one brick covers every
size of the thing it describes.

Parts are authored in the brick's own bounding-box frame: (0, 0, 0) is the back-left
corner on the floor, x runs across the width `w`, y from the back (against the wall)
to the front over the depth `d`, z up over the height `h`. Derivation re-centres the
footprint on the placement point, the same way catalog fixtures are placed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bricks.expr import ExprError, evaluate, names_in
from schemas.brick_types import Discipline, Finish, Host, Phase, Port, PortKind

Number = Union[float, str]

# Port kinds every building already has once it has rooms: the derived rough-in brings them to
# any room that needs them (core/derive.py::_mep).
BASE_SERVICES: tuple[PortKind, ...] = ("water_cold", "drain", "power")


@dataclass(frozen=True)
class HostRule:
    """How a brick with this host is placed: which step fields it needs and what that means."""

    hint: str
    needs: tuple[tuple[str, ...], ...] = ()   # each group: at least one of these step fields
    outside: bool = False                     # stands outside every room; a `room` is refused
    spans: bool = False                       # placed from `start` to `end`; its length replaces `d`


PLACEMENT_FIELDS = ("room", "position", "start", "end")


def given_fields(placed) -> set[str]:
    """Which of PLACEMENT_FIELDS a brick step or placed BrickDef sets."""
    return {f for f in PLACEMENT_FIELDS if getattr(placed, f) is not None}


_LINE = (("start",), ("end",))
HOSTS: dict[Host, HostRule] = {
    "floor": HostRule("stands on the floor of `room`, against `side`/`near` or at `position`", (("room",),)),
    "wall": HostRule("fixed to a wall of `room` (`side`/`near`) at its mount height", (("room",),)),
    "ceiling": HostRule("hangs under the ceiling of `room`", (("room",),)),
    "roof": HostRule("on the top roof at `position` (null = centred)"),
    "free": HostRule("free-standing at `position` on `level`, or in `room`", (("room", "position"),)),
    "span": HostRule("spans from `start` to `end` inside the building (beams)", _LINE, spans=True),
    "site": HostRule("outside the building at `position` [x, y], clear of every room", (("position",),), outside=True),
    "site_span": HostRule("runs outside the building from `start` to `end` (hedges, fences)", _LINE, outside=True, spans=True),
}
assert set(HOSTS) == set(get_args(Host)), "every host needs a HostRule"


class Param(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    default: float
    min: Optional[float] = None
    max: Optional[float] = None
    unit: str = "m"
    description: str = ""

    @model_validator(mode="after")
    def _range(self) -> "Param":
        if (self.min is not None and self.default < self.min) or (self.max is not None and self.default > self.max):
            raise ValueError(f"param {self.name}: default {self.default} is outside [{self.min}, {self.max}]")
        return self


class PartSpec(BaseModel):
    """One solid, in the brick's bounding-box frame; every coordinate may be an expression."""

    model_config = ConfigDict(extra="forbid")
    shape: Literal["box", "round"] = "box"
    x: Number = 0
    y: Number = 0
    z: Number = 0
    w: Number = "w"
    d: Number = "d"
    h: Number = "h"

    @model_validator(mode="before")
    @classmethod
    def _compact(cls, v):
        """[x, y, z, w, d, h] is a box; ["round", x, y, z, w, d, h] a cylinder."""
        if isinstance(v, (list, tuple)):
            if len(v) == 7:
                return dict(zip(("shape", "x", "y", "z", "w", "d", "h"), v))
            if len(v) == 6:
                return dict(zip(("x", "y", "z", "w", "d", "h"), v))
            raise ValueError(f"a compact part is [x, y, z, w, d, h] or [shape, x, y, z, w, d, h], got {v!r}")
        return v


class Rules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rooms: Optional[list[str]] = Field(None, description="Room kinds it belongs in; null = any room")
    not_below_ground: bool = False
    ground_only: bool = False
    min_room_area: Optional[float] = None
    clearance: float = Field(0.0, ge=0, description="Free floor in front of it, metres")
    overlap_ok: bool = Field(False, description="May overlap other pieces (rugs, wall-mounted items above a counter)")
    one_per_building: bool = False


class Brick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    discipline: Discipline
    category: str
    ifc_class: str
    predefined_type: Optional[str] = None
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    host: Host = "floor"
    params: list[Param]
    parts: list[PartSpec] = Field(default_factory=list, description="Empty = one box filling the bounding box")
    ports: list[Port] = Field(default_factory=list)
    rules: Rules = Field(default_factory=Rules)
    phase: Phase = "details"
    finish: Finish = "device"
    full_height: bool = Field(False, description="`h` defaults to the storey height (columns, lifts, shafts)")
    mount: Number = Field(0, description="Height of the brick's base above the floor; 'ceiling' hangs it under the ceiling")
    legacy_fixture: Optional[str] = Field(None, description="The FixtureKind this brick generalises, if any")
    structural: bool = Field(False, description="Carries load: counts as a support for the structure check")
    max_span: Optional[float] = Field(None, description="span bricks: the longest unsupported length it can carry")

    @field_validator("params", mode="before")
    @classmethod
    def _params(cls, v):
        """Library files write params compactly: {"w": [default, min, max], "shelves": [3, 0, 6, "-"]}."""
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
            if len(spec) > 3:
                item["unit"] = spec[3]
            if len(spec) > 4:
                item["description"] = spec[4]
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
        required = {"w", "h"} if self.spans else {"w", "d", "h"}
        missing = required - set(names)
        if missing:
            raise ValueError(f"{self.id}: needs size params {sorted(missing)}")
        known = set(names) | {"level_h", "length"}
        for i, part in enumerate(self.parts):
            for attr in ("x", "y", "z", "w", "d", "h"):
                value = getattr(part, attr)
                if isinstance(value, str):
                    unknown = names_in(value) - known
                    if unknown:
                        raise ValueError(f"{self.id}: part {i} {attr} uses unknown names {sorted(unknown)}")
        if isinstance(self.mount, str) and self.mount != "ceiling" and names_in(self.mount) - known:
            raise ValueError(f"{self.id}: mount uses unknown names {sorted(names_in(self.mount) - known)}")
        return self

    # --- evaluation ---------------------------------------------------------

    @property
    def placement(self) -> HostRule:
        return HOSTS[self.host]

    @property
    def spans(self) -> bool:
        return self.placement.spans

    @property
    def outside(self) -> bool:
        return self.placement.outside

    def placement_error(self, given: set[str]) -> str | None:
        """Why a placement giving these fields (room, position, start, end) cannot work for this host."""
        rule = self.placement
        if rule.outside and "room" in given:
            return f"brick {self.id} ({rule.hint}): drop `room`"
        missing = [" or ".join(f"`{f}`" for f in group) for group in rule.needs if not given & set(group)]
        if missing:
            return f"brick {self.id} ({rule.hint}): give " + " and ".join(missing)
        return None

    def param(self, name: str) -> Param | None:
        return next((p for p in self.params if p.name == name), None)

    def resolve(self, given: dict[str, float] | None = None) -> dict[str, float]:
        """Parameter values: the defaults overridden by `given`, each checked against its limits."""
        values = {p.name: p.default for p in self.params}
        for name, value in (given or {}).items():
            p = self.param(name)
            if p is None:
                raise ValueError(f"brick {self.id} has no param '{name}' (params: {', '.join(values)})")
            v = float(value)
            if (p.min is not None and v < p.min) or (p.max is not None and v > p.max):
                lo = "-inf" if p.min is None else f"{p.min:g}"
                hi = "inf" if p.max is None else f"{p.max:g}"
                raise ValueError(f"brick {self.id}: {name}={v:g} is outside {lo}..{hi} {p.unit}")
            values[name] = v
        return values

    def solids(self, values: dict[str, float]) -> list[tuple[str, float, float, float, float, float, float]]:
        """(shape, x, y, z, w, d, h) per part in the bounding-box frame."""
        parts = self.parts or [PartSpec(w="length", d="w") if self.spans else PartSpec()]
        out = []
        for i, part in enumerate(parts):
            try:
                nums = [_num(getattr(part, a), values) for a in ("x", "y", "z", "w", "d", "h")]
            except ExprError as exc:
                raise ValueError(f"brick {self.id} part {i}: {exc}") from exc
            x, y, z, w, d, h = nums
            if w <= 0 or h <= 0 or (part.shape == "box" and d <= 0):
                continue  # a part sized away by its parameters (e.g. no shelf when shelves=0)
            out.append((part.shape, x, y, max(z, 0.0), w, d if part.shape == "box" else w, h))
        if not out:
            raise ValueError(f"brick {self.id}: every part has zero size with these params")
        return out

    def mount_height(self, values: dict[str, float]) -> float | None:
        """Base height above the floor; None = hang under the ceiling."""
        if self.mount == "ceiling":
            return None
        return _num(self.mount, values)

    @property
    def provides(self) -> list[PortKind]:
        return [p.kind for p in self.ports if p.direction == "out"]

    @property
    def needs(self) -> list[PortKind]:
        return [p.kind for p in self.ports if p.direction == "in"]

    # --- text for the model ------------------------------------------------

    def size_text(self) -> str:
        v = {p.name: p.default for p in self.params}
        if self.spans:
            return f"{v['w']:g}x{v['h']:g} section"
        return f"{v['w']:g}x{v['d']:g}x{v['h']:g} m"

    def line(self) -> str:
        """One-line summary for search results."""
        ports = ""
        if self.ports:
            ports = " ports=" + ",".join(f"{p.kind}{'↑' if p.direction == 'out' else ''}" for p in self.ports)
        rooms = f" rooms={'|'.join(self.rules.rooms)}" if self.rules.rooms else ""
        return f"{self.id} — {self.name} [{self.discipline}/{self.category}] host={self.host} {self.size_text()}{rooms}{ports}"

    def card(self) -> str:
        """Everything the model needs to place it correctly."""
        lines = [self.line(), f"  {self.description}" if self.description else None,
                 f"  ifc: {self.ifc_class}" + (f".{self.predefined_type}" if self.predefined_type else "")]
        params = []
        for p in self.params:
            rng = f" {p.min:g}..{p.max:g}" if p.min is not None and p.max is not None else ""
            params.append(f"{p.name}={p.default:g}{p.unit if p.unit != '-' else ''}{rng}" + (f" ({p.description})" if p.description else ""))
        lines.append("  params: " + "; ".join(params))
        lines.append(f"  host {self.host}: {self.placement.hint}")
        r = self.rules
        rule_bits = []
        if r.not_below_ground:
            rule_bits.append("not below ground")
        if r.ground_only:
            rule_bits.append("ground floor only")
        if r.min_room_area:
            rule_bits.append(f"room ≥ {r.min_room_area:g} m²")
        if r.clearance:
            rule_bits.append(f"{r.clearance:g} m clear in front")
        if r.one_per_building:
            rule_bits.append("one per building")
        if self.needs:
            rule_bits.append("needs " + ", ".join(self.needs))
        if self.provides:
            rule_bits.append("provides " + ", ".join(self.provides))
        if self.max_span:
            rule_bits.append(f"spans ≤ {self.max_span:g} m unsupported")
        if rule_bits:
            lines.append("  rules: " + "; ".join(rule_bits))
        return "\n".join(l for l in lines if l)


def _num(value: Number, values: dict[str, float]) -> float:
    return float(value) if not isinstance(value, str) else evaluate(value, values)
