"""Plumbing and electrical rough-in: a riser (water or electrical conduit), outlets, ceiling
lights, the distribution panel, and branch-circuit wire runs. The runs follow the walls and
the roof (core/routing.py); each segment is a thin box, including a vertical drop at a device."""

from __future__ import annotations

import math

import ifcopenshell.api.root

from ifc.geometry import body, box, oriented_box
from ifc.project import BuildContext, finish_element, translate
from schemas.bim import LightFixture, Outlet, Panel, Pipe, Wire

PIPE_IFC = {"water": ("IfcPipeSegment", "RIGIDSEGMENT", "Pipe:water"), "electrical": ("IfcCableCarrierSegment", "CONDUITSEGMENT", "Pipe:electrical")}


def add_pipe(ctx: BuildContext, pipe: Pipe) -> None:
    m = ctx.model
    bottom, top = ctx.level(pipe.bottom_level), ctx.level(pipe.top_level)
    height = top.elevation + top.height - bottom.elevation
    ifc_class, predefined, style = PIPE_IFC[pipe.kind]
    element = ifcopenshell.api.root.create_entity(m, ifc_class=ifc_class, predefined_type=predefined, name=pipe.name or pipe.id)
    x, y = pipe.position
    item = box(m, -pipe.diameter / 2, -pipe.diameter / 2, 0, pipe.diameter, pipe.diameter, height)
    finish_element(ctx, element, body(ctx, [item]), translate(x, y, bottom.elevation), style, pipe.bottom_level, item=pipe)


def add_outlet(ctx: BuildContext, outlet: Outlet) -> None:
    m = ctx.model
    level = ctx.level(outlet.level)
    size = 0.1
    element = ifcopenshell.api.root.create_entity(m, ifc_class="IfcOutlet", predefined_type="POWEROUTLET", name=outlet.name or outlet.id)
    x, y = outlet.position
    item = box(m, -size / 2, -0.015, 0, size, 0.03, size)
    finish_element(ctx, element, body(ctx, [item]), translate(x, y, level.elevation + outlet.height), "Outlet", outlet.level, item=outlet)


def add_light(ctx: BuildContext, light: LightFixture) -> None:
    m = ctx.model
    level = ctx.level(light.level)
    size = 0.3
    element = ifcopenshell.api.root.create_entity(m, ifc_class="IfcLightFixture", predefined_type="POINTSOURCE", name=light.name or light.id)
    x, y = light.position
    item = box(m, -size / 2, -size / 2, 0, size, size, 0.1)
    finish_element(ctx, element, body(ctx, [item]), translate(x, y, level.elevation + level.height - 0.15), "Light", light.level, item=light)


def add_panel(ctx: BuildContext, panel: Panel) -> None:
    m = ctx.model
    level = ctx.level(panel.level)
    w, h, d = 0.4, 0.6, 0.15
    element = ifcopenshell.api.root.create_entity(
        m, ifc_class="IfcElectricDistributionBoard", predefined_type="DISTRIBUTIONBOARD", name=panel.name or panel.id)
    x, y = panel.position
    item = box(m, -w / 2, -d / 2, 0, w, d, h)
    finish_element(ctx, element, body(ctx, [item]), translate(x, y, level.elevation + 1.2), "Panel", panel.level, item=panel)


def _cable_item(m, a, b, za: float, zb: float, size: float = 0.02):
    """A short box for one run of cable: horizontal at za, or a vertical drop when the plan point repeats."""
    horiz = math.hypot(b[0] - a[0], b[1] - a[1])
    if horiz < 0.01:
        drop = abs(zb - za)
        if drop < 0.01:
            return None
        return box(m, a[0] - size / 2, a[1] - size / 2, min(za, zb), size, size, drop)
    return oriented_box(m, a, b, size, min(za, zb), size)


def add_wire(ctx: BuildContext, wire: Wire) -> None:
    """The branch cable itself (IfcCableSegment) — distinct from the riser's conduit
    (IfcCableCarrierSegment, ifc/mep.py::add_pipe) so the two never collide in a phase filter."""
    m = ctx.model
    level = ctx.level(wire.level)
    if wire.heights:
        items = [item for a, b, za, zb in zip(wire.path, wire.path[1:], wire.heights, wire.heights[1:])
                 if (item := _cable_item(m, a, b, za, zb)) is not None]
        place_z = level.elevation
    else:
        items = [oriented_box(m, a, b, 0.02, 0, 0.02) for a, b in zip(wire.path, wire.path[1:])
                 if math.hypot(b[0] - a[0], b[1] - a[1]) > 0.01]
        place_z = level.elevation + wire.elevation
    if not items:
        return
    element = ifcopenshell.api.root.create_entity(m, ifc_class="IfcCableSegment", predefined_type="CABLESEGMENT", name=wire.name or wire.id)
    finish_element(ctx, element, body(ctx, items), translate(z=place_z), "Wire", wire.level, item=wire)
