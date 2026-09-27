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
    # --- workplace and education ---
    "conference_table": ("IfcFurniture", "TABLE", "Fixture:wood", (3.0, 1.2, 0.75)),
    "reception_desk": ("IfcFurniture", "DESK", "Fixture:wood", (2.4, 0.8, 1.1)),
    "filing_cabinet": ("IfcFurniture", "FILECABINET", "Fixture:appliance", (0.9, 0.6, 1.3)),
    "locker": ("IfcFurniture", "USERDEFINED", "Fixture:appliance", (0.9, 0.5, 1.8)),
    "whiteboard": ("IfcFurniture", "USERDEFINED", "Fixture:soft", (2.0, 0.08, 1.2)),
    "lectern": ("IfcFurniture", "USERDEFINED", "Fixture:wood", (0.6, 0.5, 1.15)),
    "printer": ("IfcElectricAppliance", "USERDEFINED", "Fixture:appliance", (0.7, 0.7, 1.1)),
    "server_rack": ("IfcElectricAppliance", "USERDEFINED", "Fixture:appliance", (0.6, 1.0, 2.0)),
    "school_desk": ("IfcFurniture", "DESK", "Fixture:wood", (1.2, 0.55, 0.75)),
    # --- retail and hospitality ---
    "shelving_unit": ("IfcFurniture", "SHELF", "Fixture:appliance", (1.2, 0.5, 2.0)),
    "display_case": ("IfcFurniture", "USERDEFINED", "Fixture:soft", (1.5, 0.7, 1.1)),
    "checkout_counter": ("IfcFurniture", "USERDEFINED", "Fixture:wood", (1.8, 0.8, 1.05)),
    "cafe_table": ("IfcFurniture", "TABLE", "Fixture:wood", (0.8, 0.8, 0.75)),
    "stool": ("IfcFurniture", "CHAIR", "Fixture:wood", (0.4, 0.4, 0.75)),
    "bar_counter": ("IfcFurniture", "USERDEFINED", "Fixture:wood", (3.0, 0.7, 1.1)),
    # --- health ---
    "hospital_bed": ("IfcFurniture", "BED", "Fixture:sanitary", (1.0, 2.2, 0.9)),
    "exam_table": ("IfcFurniture", "USERDEFINED", "Fixture:sanitary", (0.7, 1.9, 0.8)),
    # --- industry and logistics ---
    "pallet_rack": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:appliance", (2.7, 1.1, 4.0)),
    "workbench": ("IfcFurniture", "TABLE", "Fixture:wood", (2.0, 0.8, 0.9)),
    "machine": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:appliance", (2.0, 1.5, 1.8)),
    "crate": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:wood", (1.2, 0.8, 1.0)),
    "conveyor": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:appliance", (6.0, 0.8, 0.9)),
    # --- sport and assembly ---
    "treadmill": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:appliance", (1.0, 2.0, 1.4)),
    "weight_bench": ("IfcFurniture", "USERDEFINED", "Fixture:soft", (1.3, 0.6, 0.5)),
    "seating_row": ("IfcFurniture", "CHAIR", "Fixture:soft", (4.0, 0.6, 0.9)),
    # --- plant, site and landscape ---
    "solar_panel": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:appliance", (1.7, 1.0, 0.45)),
    "water_tank": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:appliance", (1.6, 1.6, 2.2)),
    "hvac_unit": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:appliance", (1.6, 1.0, 1.2)),
    "boiler": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:appliance", (0.7, 0.7, 1.6)),
    "bench": ("IfcFurniture", "USERDEFINED", "Fixture:wood", (1.8, 0.6, 0.85)),
    "planter": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:wood", (1.2, 0.6, 0.7)),
    "bollard": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:appliance", (0.25, 0.25, 1.0)),
    "bicycle_rack": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:appliance", (2.0, 0.8, 0.9)),
    "lamp_post": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:appliance", (0.3, 0.3, 5.0)),
    "picnic_table": ("IfcFurniture", "TABLE", "Fixture:wood", (1.8, 1.6, 0.75)),
    "dumpster": ("IfcBuildingElementProxy", "USERDEFINED", "Fixture:appliance", (1.8, 1.0, 1.3)),
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
    if kind in ("conference_table", "cafe_table", "picnic_table", "workbench"):
        leg = 0.08
        legs = [(x, y, 0, leg, leg, h - 0.06) for x in (x0 + 0.08, x0 + w - 0.08 - leg) for y in (y0 + 0.08, y0 + d - 0.08 - leg)]
        top = [(x0, y0, h - 0.06, w, d, 0.06)]
        if kind != "picnic_table":
            return legs + top
        seat = 0.42  # a picnic table is a top with a bench either side
        return legs + top + [(x0, y0, seat, w, 0.3, 0.05), (x0, y0 + d - 0.3, seat, w, 0.3, 0.05)]
    if kind in ("reception_desk", "checkout_counter", "bar_counter"):
        return [(x0, y0, 0, w, d * 0.7, h - 0.1), (x0, y0, h - 0.1, w, d, 0.1)]  # body with an overhanging top
    if kind in ("shelving_unit", "pallet_rack", "bookshelf"):
        shelves = max(2, int(h // 0.9))
        sides = [(x0, y0, 0, 0.06, d, h), (x0 + w - 0.06, y0, 0, 0.06, d, h)]
        return sides + [(x0, y0, i * (h - 0.06) / (shelves - 1), w, d, 0.06) for i in range(shelves)]
    if kind == "locker":
        doors = max(1, int(w // 0.35))
        gap = w / doors
        return [full] + [(x0 + i * gap + 0.02, y0 - 0.005, 0.05, gap - 0.04, 0.02, h - 0.1) for i in range(doors)]
    if kind == "whiteboard":
        return [(x0, y0, h * 0.9, w, d, 0.06), (x0 + 0.05, y0, h * 0.9 + 0.06, w - 0.1, 0.02, h * 0.75)]
    if kind == "lectern":
        return [(x0 + w * 0.3, y0 + d * 0.3, 0, w * 0.4, d * 0.4, h - 0.1), (x0, y0, h - 0.1, w, d, 0.1)]
    if kind == "server_rack":
        return [full] + [(x0 + 0.03, y0 - 0.005, 0.1 + i * 0.22, w - 0.06, 0.02, 0.16) for i in range(int((h - 0.2) // 0.22))]
    if kind in ("hospital_bed", "exam_table"):
        return [(x0, y0, h - 0.2, w, d, 0.2), (x0 + 0.05, y0 + 0.05, 0, w - 0.1, d - 0.1, h - 0.2)]
    if kind == "seating_row":
        seats = max(2, int(w // 0.55))
        gap = w / seats
        return [(x0, y0, 0.35, w, d, 0.06), (x0, y0, 0.35, w, 0.08, h - 0.35)] + [
            (x0 + i * gap + 0.02, y0 + 0.1, 0, 0.06, d - 0.2, 0.35) for i in range(seats + 1)]
    if kind == "solar_panel":
        # A panel on a tilted frame: the array people picture when they say "solar on the roof".
        return [(x0, y0, 0.05, 0.08, d, 0.1), (x0 + w - 0.08, y0, 0.05, 0.08, d, h - 0.1),
                (x0, y0, h - 0.12, w, d, 0.06)]
    if kind == "hvac_unit":
        return [(x0, y0, 0, w, d, h - 0.15), (x0 + w * 0.15, y0 + d * 0.15, h - 0.15, w * 0.7, d * 0.7, 0.15)]
    if kind == "treadmill":
        return [(x0, y0, 0, w, d, 0.25), (x0, y0 + d - 0.1, 0.25, 0.08, 0.1, h - 0.25),
                (x0 + w - 0.08, y0 + d - 0.1, 0.25, 0.08, 0.1, h - 0.25), (x0, y0 + d - 0.12, h - 0.1, w, 0.12, 0.1)]
    if kind == "bicycle_rack":
        hoops = max(2, int(w // 0.7))
        gap = w / max(1, hoops - 1)
        return [(x0 + i * gap, y0, 0, 0.06, d, h) for i in range(hoops)]
    if kind in ("bollard", "lamp_post"):
        post = [(x0 + w * 0.3, y0 + d * 0.3, 0, w * 0.4, d * 0.4, h)]
        return post if kind == "bollard" else post + [(x0, y0, h - 0.15, w, d, 0.15)]
    if kind == "bench":
        return [(x0, y0, 0.42, w, d, 0.06), (x0, y0 + d - 0.08, 0.48, w, 0.08, h - 0.48),
                (x0 + 0.1, y0 + 0.05, 0, 0.08, d - 0.1, 0.42), (x0 + w - 0.18, y0 + 0.05, 0, 0.08, d - 0.1, 0.42)]
    if kind == "planter":
        return [(x0, y0, 0, w, d, h * 0.7), (x0 + w * 0.25, y0 + d * 0.25, h * 0.7, w * 0.5, d * 0.5, h * 0.3)]
    if kind == "conveyor":
        legs = [(x, y0 + d / 2 - 0.04, 0, 0.08, 0.08, h - 0.12) for x in
                (x0 + 0.2, x0 + w / 2 - 0.04, x0 + w - 0.28)]
        return legs + [(x0, y0, h - 0.12, w, d, 0.12)]
    return [full]


def add_fixture(ctx: BuildContext, fx: Fixture) -> None:
    m = ctx.model
    level = ctx.level(fx.level)
    ifc_class, ptype, style, _ = CATALOG[fx.kind]
    element = ifcopenshell.api.root.create_entity(m, ifc_class=ifc_class, predefined_type=ptype, name=fx.name or fx.id)
    if ptype == "USERDEFINED":
        element.ObjectType = fx.kind
    items = [box(m, *part) for part in _parts(fx.kind, fx.width, fx.depth, fx.height)]
    frame = placement(fx.position[0], fx.position[1], level.elevation + fx.elevation, math.radians(fx.rotation))
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
    frame = placement(cs.position[0], cs.position[1], level.elevation + cs.elevation, math.radians(cs.rotation))
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
    finish_element(ctx, element, body(ctx, [solid]), translate(z=level.elevation + beam.elevation), "Beam", beam.level, item=beam)
