"""Furniture, appliances and sanitary fittings (IfcFurniture / IfcElectricAppliance /
IfcSanitaryTerminal), plus IfcRailing, IfcBeam and model-composed CustomFixture pieces.
Everything is a few boxes (or, for a "round" custom part, a many-sided extrusion): enough
for a viewer to read a plan, cheap to tessellate."""

from __future__ import annotations

import math

import ifcopenshell.api.geometry
import ifcopenshell.api.root

from ifc.geometry import body, box, extrude, oriented_box
from ifc.project import BuildContext, finish_element, placement, translate
from schemas.bim import Beam, CustomFixture, Fixture, Railing, ShapePart

ROUND_SIDES = 16  # vertices approximating a circle for a "round" custom part

# kind -> (ifc class, predefined type, style, default (width, depth, height))
CATALOG: dict[str, tuple[str, str, str, tuple[float, float, float]]] = {
    "bed": ("IfcFurniture", "BED", "Fixture:soft", (0.95, 2.0, 0.9)),
    "double_bed": ("IfcFurniture", "BED", "Fixture:soft", (1.6, 2.0, 0.9)),
    "bunk_bed": ("IfcFurniture", "BED", "Fixture:wood", (0.95, 2.0, 1.7)),
    "sofa": ("IfcFurniture", "SOFA", "Fixture:soft", (2.0, 0.9, 0.85)),
    "armchair": ("IfcFurniture", "CHAIR", "Fixture:soft", (0.9, 0.9, 0.85)),
    "coffee_table": ("IfcFurniture", "TABLE", "Fixture:wood", (1.0, 0.6, 0.45)),
    "tv_stand": ("IfcFurniture", "USERDEFINED", "Fixture:wood", (1.6, 0.45, 1.2)),
    "dining_table": ("IfcFurniture", "TABLE", "Fixture:wood", (1.8, 0.9, 0.75)),
    "chair": ("IfcFurniture", "CHAIR", "Fixture:wood", (0.45, 0.45, 0.9)),
    "desk": ("IfcFurniture", "DESK", "Fixture:wood", (1.4, 0.7, 0.75)),
    "bookshelf": ("IfcFurniture", "SHELF", "Fixture:wood", (0.9, 0.35, 2.0)),
    "wardrobe": ("IfcFurniture", "USERDEFINED", "Fixture:wood", (1.2, 0.6, 2.1)),
    "dresser": ("IfcFurniture", "USERDEFINED", "Fixture:wood", (1.0, 0.5, 0.9)),
    "kitchen_counter": ("IfcFurniture", "USERDEFINED", "Fixture:wood", (2.4, 0.6, 0.9)),
    "island": ("IfcFurniture", "USERDEFINED", "Fixture:wood", (2.0, 0.9, 0.9)),
    "fridge": ("IfcElectricAppliance", "FRIDGE_FREEZER", "Fixture:appliance", (0.7, 0.7, 1.8)),
    "oven": ("IfcElectricAppliance", "ELECTRICCOOKER", "Fixture:appliance", (0.6, 0.6, 0.9)),
    "sink": ("IfcSanitaryTerminal", "SINK", "Fixture:sanitary", (0.8, 0.6, 0.9)),
    "dishwasher": ("IfcElectricAppliance", "DISHWASHER", "Fixture:appliance", (0.6, 0.6, 0.85)),
    "washing_machine": ("IfcElectricAppliance", "WASHINGMACHINE", "Fixture:appliance", (0.6, 0.6, 0.85)),
    "toilet": ("IfcSanitaryTerminal", "TOILETPAN", "Fixture:sanitary", (0.4, 0.7, 0.8)),
    "shower": ("IfcSanitaryTerminal", "SHOWER", "Fixture:sanitary", (0.9, 0.9, 2.0)),
    "bathtub": ("IfcSanitaryTerminal", "BATH", "Fixture:sanitary", (1.7, 0.75, 0.55)),
    "washbasin": ("IfcSanitaryTerminal", "WASHHANDBASIN", "Fixture:sanitary", (0.6, 0.45, 0.85)),
    "fireplace": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:fire", (1.2, 0.5, 1.1)),
    "car": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:car", (1.8, 4.5, 1.5)),
}


def default_size(kind: str) -> tuple[float, float, float]:
    return CATALOG[kind][3]


def _parts(kind: str, w: float, d: float, h: float) -> list[tuple[float, float, float, float, float, float]]:
    """Boxes (x, y, z, w, d, h) in the fixture's local frame: footprint centred on the origin, back at -y."""
    x0, y0 = -w / 2, -d / 2
    full = (x0, y0, 0, w, d, h)
    if kind in ("bed", "double_bed"):
        return [(x0, y0, 0, w, d, h / 2), (x0, y0, 0, w, 0.08, h)]
    if kind == "bunk_bed":
        posts = [(x, y, 0, 0.06, 0.06, h) for x in (x0, x0 + w - 0.06) for y in (y0, y0 + d - 0.06)]
        return posts + [(x0, y0, 0.3, w, d, 0.25), (x0, y0, h - 0.4, w, d, 0.25)]
    if kind in ("sofa", "armchair"):
        arm = 0.2 if kind == "sofa" else 0.15
        return [(x0, y0, 0, w, d, h * 0.5), (x0, y0, 0, w, 0.25, h), (x0, y0, 0, arm, d, h * 0.7), (x0 + w - arm, y0, 0, arm, d, h * 0.7)]
    if kind in ("coffee_table", "dining_table"):
        leg = 0.06
        legs = [(x, y, 0, leg, leg, h) for x in (x0 + 0.05, x0 + w - 0.05 - leg) for y in (y0 + 0.05, y0 + d - 0.05 - leg)]
        return legs + [(x0, y0, h - 0.05, w, d, 0.05)]
    if kind == "chair":
        leg = 0.04
        legs = [(x, y, 0, leg, leg, h / 2) for x in (x0, x0 + w - leg) for y in (y0, y0 + d - leg)]
        return legs + [(x0, y0, h / 2 - 0.04, w, d, 0.04), (x0, y0, h / 2, w, 0.04, h / 2)]
    if kind == "desk":
        return [(x0, y0, h - 0.04, w, d, 0.04), (x0, y0, 0, 0.04, d, h - 0.04), (x0 + w - 0.04, y0, 0, 0.04, d, h - 0.04)]
    if kind == "tv_stand":
        return [(x0, y0, 0, w, d, 0.5), (x0 + w * 0.1, y0 + d / 2 - 0.03, 0.5, w * 0.8, 0.06, h - 0.5)]
    if kind == "toilet":
        return [(x0, y0, 0, w, 0.2, h), (x0 + 0.01, y0 + 0.2, 0, w - 0.02, d - 0.2, h / 2)]
    if kind == "shower":
        return [(x0, y0, 0, w, d, 0.05), (x0 + w - 0.02, y0, 0, 0.02, d, h), (x0, y0 + d - 0.02, 0, w, 0.02, h)]
    if kind == "washbasin":
        return [(-0.1, -0.1, 0, 0.2, 0.2, h - 0.15), (x0, y0, h - 0.15, w, d, 0.15)]
    if kind == "sink":
        return [(x0, y0, 0, w, d, h - 0.2), (x0, y0, h - 0.2, 0.05, d, 0.2), (x0 + w - 0.05, y0, h - 0.2, 0.05, d, 0.2), (x0, y0, h - 0.2, w, 0.05, 0.2), (x0, y0 + d - 0.05, h - 0.2, w, 0.05, 0.2)]
    if kind == "car":
        return [(x0, y0, 0.25, w, d, 0.6), (x0 + 0.1, y0 + d * 0.3, 0.85, w - 0.2, d * 0.45, h - 0.85),
                (x0, y0 + 0.4, 0, 0.25, 0.7, 0.3), (x0 + w - 0.25, y0 + 0.4, 0, 0.25, 0.7, 0.3),
                (x0, y0 + d - 1.1, 0, 0.25, 0.7, 0.3), (x0 + w - 0.25, y0 + d - 1.1, 0, 0.25, 0.7, 0.3)]
    if kind == "fireplace":
        return [(x0, y0, 0, w, d, h), (x0 + w * 0.3, y0 - 0.001, 0, w * 0.4, 0.05, h * 0.6)]
    return [full]


def add_fixture(ctx: BuildContext, fx: Fixture) -> None:
    m = ctx.model
    level = ctx.level(fx.level)
    ifc_class, ptype, style, _ = CATALOG[fx.kind]
    element = ifcopenshell.api.root.create_entity(m, ifc_class=ifc_class, predefined_type=ptype, name=fx.name or fx.id)
    if ptype == "USERDEFINED":
        element.ObjectType = fx.kind
    items = [box(m, *part) for part in _parts(fx.kind, fx.width, fx.depth, fx.height)]
    frame = placement(fx.position[0], fx.position[1], level.elevation, math.radians(fx.rotation))
    finish_element(ctx, element, body(ctx, items), frame, style, fx.level, item=fx)


def part_solids(m, parts: list[ShapePart]) -> list:
    """Solids for box/round ShapeParts (min-corner x, y, z; a round part is a w-diameter cylinder)."""
    items = []
    for p in parts:
        if p.shape == "round":
            r = p.w / 2
            cx, cy = p.x + r, p.y + r
            outline = [(cx + r * math.cos(2 * math.pi * i / ROUND_SIDES), cy + r * math.sin(2 * math.pi * i / ROUND_SIDES))
                       for i in range(ROUND_SIDES)]
            items.append(extrude(m, outline, p.h, origin=(0, 0, p.z)))
        else:
            items.append(box(m, p.x, p.y, p.z, p.w, p.d, p.h))
    return items


def add_custom(ctx: BuildContext, cs: CustomFixture) -> None:
    m = ctx.model
    level = ctx.level(cs.level)
    items = part_solids(m, cs.parts)
    element = ifcopenshell.api.root.create_entity(m, ifc_class="IfcFurniture", predefined_type="USERDEFINED", name=cs.name or cs.id)
    element.ObjectType = "custom"
    frame = placement(cs.position[0], cs.position[1], level.elevation, math.radians(cs.rotation))
    finish_element(ctx, element, body(ctx, items), frame, "Fixture:wood", cs.level, item=cs)


def add_railing(ctx: BuildContext, rail: Railing) -> None:
    m = ctx.model
    level = ctx.level(rail.level)
    items = []
    for a, b in zip(rail.path, rail.path[1:]):
        items.append(oriented_box(m, a, b, rail.thickness, rail.height - 0.05, 0.05))  # handrail
        length = math.dist(a, b)
        n = max(2, math.ceil(length / 1.2) + 1)
        for i in range(n):
            t = i / (n - 1)
            px, py = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            items.append(box(m, px - 0.025, py - 0.025, 0, 0.05, 0.05, rail.height - 0.05))
    element = ifcopenshell.api.root.create_entity(m, ifc_class="IfcRailing", predefined_type="GUARDRAIL", name=rail.name or rail.id)
    finish_element(ctx, element, body(ctx, items), translate(z=level.elevation + rail.elevation), "Railing", rail.level, item=rail)


def add_beam(ctx: BuildContext, beam: Beam) -> None:
    m = ctx.model
    level = ctx.level(beam.level)
    element = ifcopenshell.api.root.create_entity(m, ifc_class="IfcBeam", predefined_type="BEAM", name=beam.name or beam.id)
    solid = oriented_box(m, beam.start, beam.end, beam.width, level.height - beam.depth, beam.depth)
    finish_element(ctx, element, body(ctx, [solid]), translate(z=level.elevation), "Beam", beam.level, item=beam)
