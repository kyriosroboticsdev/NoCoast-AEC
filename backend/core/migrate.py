"""One-way BuildingSpec → GeoModel.

The spec is the geometric truth of a stored project. Each legacy element becomes a part
with the same id, so GlobalIds survive, and the IFC entity it always compiled to. There
is no path back to the room model.
"""

from __future__ import annotations

import math

from schemas.bim import (Beam, BuildingSpec, Column, CustomFixture, Door, Fixture, LightFixture, Outlet, Panel, Pipe,
                         Railing, Roof, Slab, Space, Stair, Wall, Window, Wire)
from schemas.geo import GeoLevel, GeoModel, GeoOpening, GeoPart, Placement, Profile, Repeat, Solid

# kind → (ifc class, predefined type). One box stands in for the old catalogue of parts.
_FIXTURE = {
    "bed": ("IfcFurniture", "BED"), "double_bed": ("IfcFurniture", "BED"), "bunk_bed": ("IfcFurniture", "BED"),
    "sofa": ("IfcFurniture", "SOFA"), "armchair": ("IfcFurniture", "CHAIR"), "coffee_table": ("IfcFurniture", "TABLE"),
    "tv_stand": ("IfcFurniture", "USERDEFINED"), "dining_table": ("IfcFurniture", "TABLE"), "chair": ("IfcFurniture", "CHAIR"),
    "desk": ("IfcFurniture", "DESK"), "bookshelf": ("IfcFurniture", "SHELF"), "wardrobe": ("IfcFurniture", "USERDEFINED"),
    "dresser": ("IfcFurniture", "USERDEFINED"), "kitchen_counter": ("IfcFurniture", "USERDEFINED"),
    "island": ("IfcFurniture", "USERDEFINED"), "fridge": ("IfcElectricAppliance", "FRIDGE_FREEZER"),
    "oven": ("IfcElectricAppliance", "ELECTRICCOOKER"), "sink": ("IfcSanitaryTerminal", "SINK"),
    "dishwasher": ("IfcElectricAppliance", "DISHWASHER"), "washing_machine": ("IfcElectricAppliance", "WASHINGMACHINE"),
    "toilet": ("IfcSanitaryTerminal", "TOILETPAN"), "shower": ("IfcSanitaryTerminal", "SHOWER"),
    "bathtub": ("IfcSanitaryTerminal", "BATH"), "washbasin": ("IfcSanitaryTerminal", "WASHHANDBASIN"),
    "fireplace": ("IfcBuildingElementProxy", "USERDEFINED"), "car": ("IfcBuildingElementProxy", "USERDEFINED"),
}

_ROOF = {"flat": "FLAT_ROOF", "gable": "GABLE_ROOF", "hip": "HIP_ROOF"}
_DOOR = {"garage": "GATE", "single": "DOOR", "double": "DOOR", "sliding": "DOOR", "french": "DOOR"}


def _extrude(profile: Profile, depth: float, at=(0.0, 0.0, 0.0), rotation: float = 0.0, axis=(0.0, 0.0, 1.0)) -> Solid:
    return Solid(op="extrude", place=Placement(at=at, rotation=rotation, axis=axis), profile=profile, depth=depth)


def _box(w: float, d: float, h: float, at=(0.0, 0.0, 0.0), rotation: float = 0.0) -> Solid:
    return _extrude(Profile(rect=(w, d)), h, at=at, rotation=rotation)


def _part(el, ifc: str, solids: list[Solid], level: str, **kw) -> GeoPart:
    data = dict(id=el.id, name=el.name or el.id, ifc=ifc, level=level, solids=solids)
    data.update(kw)
    return GeoPart(**data)


def _level_height(spec: BuildingSpec, level_id: str) -> float:
    level = next(l for l in spec.levels if l.id == level_id)
    return level.height


def _rect(outline) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    return min(xs), min(ys), max(xs), max(ys)


def _wall(spec: BuildingSpec, wall: Wall) -> GeoPart:
    height = wall.height or _level_height(spec, wall.level)
    return _part(wall, "IfcWall", [_extrude(Profile(band=[list(p) for p in wall.axis], width=wall.thickness), height,
                                   at=(0, 0, wall.elevation))], wall.level,
                 ifc_type="SOLIDWALL" if wall.external else "PARTITIONING", material=wall.material)


def _opening_for(host: Wall, item, fill: str) -> GeoOpening:
    sill = item.sill_height if isinstance(item, Window) else 0.0
    point, angle = host.frame_at(item.offset + item.width / 2)
    solid = _box(item.width, host.thickness + 0.1, item.height, at=(point[0], point[1], sill), rotation=math.degrees(angle))
    return GeoOpening(id=f"{item.id}-void", host=host.id, solid=solid, fill=fill)


def _door(spec: BuildingSpec, door: Door, walls: dict[str, Wall]) -> tuple[GeoPart, GeoOpening]:
    host = walls[door.wall]
    point, angle = host.frame_at(door.offset + door.width / 2)
    part = _part(door, "IfcDoor", [_box(door.width * 0.96, 0.05, door.height,
                                        at=(point[0], point[1], host.elevation), rotation=math.degrees(angle))],
                 host.level, ifc_type=_DOOR.get(door.kind, "DOOR"), material="timber")
    return part, _opening_for(host, door, door.id)


def _window(spec: BuildingSpec, window: Window, walls: dict[str, Wall]) -> tuple[GeoPart, GeoOpening]:
    host = walls[window.wall]
    point, angle = host.frame_at(window.offset + window.width / 2)
    part = _part(window, "IfcWindow", [_box(window.width * 0.96, 0.05, window.height,
                                            at=(point[0], point[1], host.elevation + window.sill_height),
                                            rotation=math.degrees(angle))],
                 host.level, ifc_type="WINDOW", material="glass")
    return part, _opening_for(host, window, window.id)


def _slab(slab: Slab) -> GeoPart:
    return _part(slab, "IfcSlab", [_extrude(Profile(points=[list(p) for p in slab.outline]), slab.thickness,
                                   at=(0, 0, slab.elevation))], slab.level, ifc_type="FLOOR", material="concrete")


def _roof(spec: BuildingSpec, roof: Roof) -> GeoPart:
    z = _level_height(spec, roof.level) + roof.elevation
    kind = _ROOF[roof.shape]
    if roof.shape == "flat":
        solid = _extrude(Profile(points=[list(p) for p in roof.outline]), roof.thickness, at=(0, 0, z))
        return _part(roof, "IfcRoof", [solid], roof.level, ifc_type=kind, name=roof.name or "flat roof")
    x0, y0, x1, y1 = _rect(roof.outline)
    w, d = x1 - x0, y1 - y0
    if roof.shape == "hip":
        return _part(roof, "IfcRoof", [_hip(roof, x0, y0, x1, y1, z)], roof.level, ifc_type=kind, name=roof.name or "hip roof")
    return _part(roof, "IfcRoof", _gable(roof, x0, y0, w, d, z), roof.level, ifc_type=kind, name=roof.name or "gable roof")


def _gable(roof: Roof, x0: float, y0: float, w: float, d: float, z: float) -> list[Solid]:
    ridge = roof.ridge or ("x" if w >= d else "y")
    pitch = math.radians(roof.pitch)
    thick = roof.thickness / math.cos(pitch)
    if ridge == "x":
        half, span, origin, axis, depth = d / 2, d, (x0, 0.0, z), (1.0, 0.0, 0.0), w
        along = (1.0, 0.0, 0.0)
        def prof(h, t):
            return [[y0, 0], [y0 + half, h], [y0 + span, 0], [y0 + span, t], [y0 + half, h + t], [y0, t]]
    else:
        half, span, origin, axis, depth = w / 2, w, (0.0, y0, z), (0.0, 1.0, 0.0), d
        along = (0.0, 1.0, 0.0)
        def prof(h, t):
            return [[x0, 0], [x0 + half, h], [x0 + span, 0], [x0 + span, t], [x0 + half, h + t], [x0, t]]
    h = half * math.tan(pitch)
    chevron = _extrude(Profile(points=prof(h, thick)), depth, at=origin, axis=axis)
    outer = prof(h, thick)[:3]
    cap = 0.2
    start = _extrude(Profile(points=outer), cap, at=origin, axis=axis)
    far = tuple(origin[i] + along[i] * (depth - cap) for i in range(3))
    end_cap = _extrude(Profile(points=outer), cap, at=far, axis=axis)
    return [chevron, start, end_cap]


def _hip(roof: Roof, x0, y0, x1, y1, z) -> Solid:
    w, d = x1 - x0, y1 - y0
    half = min(w, d) / 2
    h = half * math.tan(math.radians(roof.pitch))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if abs(w - d) < 1e-6:
        apex = (cx, cy, h)
        base = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)]
        faces = [list(reversed(base))]
        for i in range(4):
            faces.append([base[i], base[(i + 1) % 4], apex])
    elif w > d:
        r0, r1 = (cx - (w - d) / 2, cy, h), (cx + (w - d) / 2, cy, h)
        a, b, c, e = (x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)
        faces = [[e, c, b, a], [a, b, r1, r0], [b, c, r1], [c, e, r0, r1], [e, a, r0]]
    else:
        r0, r1 = (cx, cy - (d - w) / 2, h), (cx, cy + (d - w) / 2, h)
        a, b, c, e = (x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)
        faces = [[e, c, b, a], [a, b, r0], [b, c, r1, r0], [c, e, r1], [e, a, r0, r1]]
    return Solid(op="mesh", place=Placement(at=(0, 0, z)), faces=faces)


def _column(spec: BuildingSpec, column: Column) -> GeoPart:
    height = column.height or _level_height(spec, column.level)
    return _part(column, "IfcColumn", [_box(column.width, column.depth, height,
                                            at=(column.position[0], column.position[1], column.elevation))],
                 column.level, ifc_type="COLUMN", material="concrete")


def _beam(spec: BuildingSpec, beam: Beam) -> GeoPart:
    length = math.dist(beam.start, beam.end)
    angle = math.degrees(math.atan2(beam.end[1] - beam.start[1], beam.end[0] - beam.start[0]))
    mid = ((beam.start[0] + beam.end[0]) / 2, (beam.start[1] + beam.end[1]) / 2)
    z = _level_height(spec, beam.level) - beam.depth + beam.elevation
    return _part(beam, "IfcBeam", [_box(length, beam.width, beam.depth, at=(mid[0], mid[1], z), rotation=angle)],
                 beam.level, ifc_type="BEAM", material="concrete")


def _space(spec: BuildingSpec, space: Space) -> GeoPart:
    height = space.height or _level_height(spec, space.level)
    return _part(space, "IfcSpace", [_extrude(Profile(points=[list(p) for p in space.outline]), height)],
                 space.level, ifc_type="SPACE")


def _stair(spec: BuildingSpec, stair: Stair) -> tuple[GeoPart, GeoOpening | None]:
    rise = stair.rise or _level_height(spec, stair.level)
    n = stair.steps(rise)
    step_rise = rise / n
    ang = math.radians(stair.direction)
    dx, dy = math.cos(ang) * stair.going, math.sin(ang) * stair.going
    part = GeoPart(
        id=stair.id, name=stair.name or "straight stair", ifc="IfcStair", ifc_type="STRAIGHT_RUN_STAIR",
        level=stair.level, material="timber",
        repeat=Repeat(count=n, translate=(dx, dy, step_rise)),
        solids=[_box(stair.going * 0.96, stair.width, 0.04, at=(stair.position[0], stair.position[1], 0))],
    )
    opening = None
    if stair.to_level:
        slabs = [e for e in spec.elements if isinstance(e, Slab) and e.level == stair.to_level]
        if slabs:
            host = slabs[0]
            run = n * stair.going
            x, y = stair.position
            c, s = math.cos(ang), math.sin(ang)
            half = stair.width / 2 + 0.05
            px, py = -s * half, c * half
            x0, y0 = x + run * 0.3 * c, y + run * 0.3 * s
            x1, y1 = x + run * c, y + run * s
            well = [[x0 + px, y0 + py], [x1 + px, y1 + py], [x1 - px, y1 - py], [x0 - px, y0 - py]]
            opening = GeoOpening(id=f"{stair.id}-well", host=host.id,
                                 solid=_extrude(Profile(points=well), host.thickness + 0.1, at=(0, 0, -0.05)))
    return part, opening


def _fixture(fx: Fixture) -> GeoPart:
    ifc, ifc_type = _FIXTURE[fx.kind]
    return _part(fx, ifc, [_box(fx.width, fx.depth, fx.height, at=(fx.position[0], fx.position[1], 0), rotation=fx.rotation)],
                 fx.level, ifc_type=ifc_type)


def _custom(cs: CustomFixture) -> GeoPart:
    solids = []
    for p in cs.parts:
        if p.shape == "round":
            solids.append(_extrude(Profile(circle=p.w), p.h, at=(p.x + p.w / 2, p.y + p.w / 2, p.z)))
        else:
            solids.append(_box(p.w, p.d, p.h, at=(p.x + p.w / 2, p.y + p.d / 2, p.z)))
    return GeoPart(id=cs.id, name=cs.name or cs.id, ifc="IfcFurniture", ifc_type="USERDEFINED", level=cs.level,
                   place=Placement(at=(cs.position[0], cs.position[1], 0), rotation=cs.rotation), solids=solids)


def _railing(rail: Railing) -> GeoPart:
    return _part(rail, "IfcRailing", [_extrude(Profile(band=[list(p) for p in rail.path], width=rail.thickness), rail.height,
                                      at=(0, 0, rail.elevation))], rail.level, ifc_type="GUARDRAIL")


def _pipe(spec: BuildingSpec, pipe: Pipe) -> GeoPart:
    bottom = next(l for l in spec.levels if l.id == pipe.bottom_level)
    top = next(l for l in spec.levels if l.id == pipe.top_level)
    height = (top.elevation or 0) + top.height - (bottom.elevation or 0)
    ifc, ifc_type = ("IfcPipeSegment", "RIGIDSEGMENT") if pipe.kind == "water" else ("IfcCableCarrierSegment", "CONDUITSEGMENT")
    return _part(pipe, ifc, [_extrude(Profile(circle=pipe.diameter), max(height, 0.2),
                                     at=(pipe.position[0], pipe.position[1], 0))],
                 pipe.bottom_level, ifc_type=ifc_type)


def _outlet(outlet: Outlet) -> GeoPart:
    return _part(outlet, "IfcOutlet", [_box(0.08, 0.04, 0.08, at=(outlet.position[0], outlet.position[1], outlet.height))],
                 outlet.level, ifc_type="POWEROUTLET")


def _light(spec: BuildingSpec, light: LightFixture) -> GeoPart:
    z = _level_height(spec, light.level) - 0.08
    return _part(light, "IfcLightFixture", [_box(0.2, 0.2, 0.08, at=(light.position[0], light.position[1], z))],
                 light.level, ifc_type="POINTSOURCE")


def _panel(panel: Panel) -> GeoPart:
    return _part(panel, "IfcElectricDistributionBoard", [_box(0.45, 0.12, 0.7, at=(panel.position[0], panel.position[1], 1.4))],
                 panel.level, ifc_type="DISTRIBUTIONBOARD")


def _wire(wire: Wire) -> GeoPart:
    return _part(wire, "IfcCableSegment", [_extrude(Profile(band=[list(p) for p in wire.path], width=0.02), 0.02,
                                           at=(0, 0, wire.elevation))], wire.level, ifc_type="CABLESEGMENT")


def from_spec(spec: BuildingSpec) -> GeoModel:
    """The spec's elements as a GeoModel. Ids are preserved."""
    walls = {el.id: el for el in spec.elements if isinstance(el, Wall)}
    parts: list[GeoPart] = []
    openings: list[GeoOpening] = []
    for el in spec.elements:
        if isinstance(el, Wall):
            parts.append(_wall(spec, el))
        elif isinstance(el, Slab):
            parts.append(_slab(el))
        elif isinstance(el, Roof):
            parts.append(_roof(spec, el))
        elif isinstance(el, Column):
            parts.append(_column(spec, el))
        elif isinstance(el, Beam):
            parts.append(_beam(spec, el))
        elif isinstance(el, Space):
            parts.append(_space(spec, el))
        elif isinstance(el, Stair):
            part, opening = _stair(spec, el)
            parts.append(part)
            if opening:
                openings.append(opening)
        elif isinstance(el, Door):
            part, opening = _door(spec, el, walls)
            parts.append(part)
            openings.append(opening)
        elif isinstance(el, Window):
            part, opening = _window(spec, el, walls)
            parts.append(part)
            openings.append(opening)
        elif isinstance(el, Fixture):
            parts.append(_fixture(el))
        elif isinstance(el, CustomFixture):
            parts.append(_custom(el))
        elif isinstance(el, Railing):
            parts.append(_railing(el))
        elif isinstance(el, Pipe):
            parts.append(_pipe(spec, el))
        elif isinstance(el, Outlet):
            parts.append(_outlet(el))
        elif isinstance(el, LightFixture):
            parts.append(_light(spec, el))
        elif isinstance(el, Panel):
            parts.append(_panel(el))
        elif isinstance(el, Wire):
            parts.append(_wire(el))
    levels = [GeoLevel(id=l.id, name=l.name, height=l.height, elevation=l.elevation) for l in spec.levels]
    return GeoModel(name=spec.building.name, description=spec.building.description, levels=levels, parts=parts, openings=openings)
