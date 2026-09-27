"""The parametric geometry kernel: every node kind resolves to solids with the right extent, the
modifiers (at, rotate, repeat, when, subtract, group) compose, and every solid kind compiles to IFC
geometry that tessellates to the same box."""

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import pytest
from pydantic import TypeAdapter

from bricks.geometry import (MAX_REPEAT, CircleProfile, Extrusion, GeometryError, MeshSolid, Node, Pipe, Revolution, bounds,
                             evaluate)
from ifc.solids import items, representation_type

NODES = TypeAdapter(list[Node])


def solids(nodes: list[dict], **values) -> list:
    return evaluate(NODES.validate_python(nodes), values)


def box_of(nodes: list[dict], **values) -> tuple:
    return tuple(round(v, 3) for v in bounds(solids(nodes, **values)))


@pytest.mark.parametrize("node, expected", [
    ({"shape": "box", "size": [2, 1, 0.5]}, (0, 0, 0, 2, 1, 0.5)),
    ({"shape": "cylinder", "radius": 0.5, "height": 2}, (-0.5, -0.5, 0, 0.5, 0.5, 2)),
    ({"shape": "cone", "radius": 1, "height": 2, "top_radius": 0.2}, (-1, -1, 0, 1, 1, 2)),
    ({"shape": "sphere", "radius": 1}, (-1, -1, -1, 1, 1, 1)),
    ({"shape": "extrude", "profile": [[0, 0], [2, 0], [0, 3]], "height": 1}, (0, 0, 0, 2, 3, 1)),
    ({"shape": "extrude", "profile": {"ngon": 6, "radius": 1}, "height": 1}, (-1, -0.866, 0, 1, 0.866, 1)),
    ({"shape": "revolve", "profile": [[0, 0], [0.4, 0], [0.2, 1], [0, 1]]}, (-0.4, -0.4, 0, 0.4, 0.4, 1)),
    ({"shape": "sweep", "profile": {"circle": 0.1}, "path": [[0, 0, 0], [0, 0, 2], [1, 0, 2]]}, (-0.1, -0.1, -0.1, 1.1, 0.1, 2.1)),
    ({"shape": "loft", "sections": [{"z": 0, "profile": {"rect": [2, 2], "centered": True}},
                                    {"z": 1, "profile": {"rect": [1, 1], "centered": True}}]}, (-1, -1, 0, 1, 1, 1)),
    ({"shape": "mesh", "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], "faces": [[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]]},
     (0, 0, 0, 1, 1, 1)),
])
def test_each_node_kind_has_the_right_extent(node, expected):
    assert box_of([node]) == pytest.approx(expected, abs=0.02)


def test_primitives_resolve_to_their_ifc_friendly_kinds():
    kinds = [type(s) for s in solids([
        {"shape": "box", "size": [1, 1, 1]},
        {"shape": "cylinder", "radius": 0.5, "height": 1, "inner": 0.4},
        {"shape": "cone", "radius": 1, "height": 1},
        {"shape": "sphere", "radius": 1},
        {"shape": "sweep", "profile": {"circle": 0.1}, "path": [[0, 0, 0], [0, 0, 1]]},
        {"shape": "sweep", "profile": {"rect": [0.1, 0.1], "centered": True}, "path": [[0, 0, 0], [0, 0, 1], [1, 0, 1]]},
    ])]
    assert kinds == [Extrusion, Extrusion, Revolution, MeshSolid, Pipe, Extrusion, Extrusion]
    tube = solids([{"shape": "cylinder", "radius": 0.5, "height": 1, "inner": 0.4}])[0]
    assert isinstance(tube.profile, CircleProfile) and tube.profile.inner == 0.4


def test_expressions_parameterise_every_number():
    nodes = [{"shape": "box", "size": ["w", "d", "h * 2"], "at": [0, 0, "h"]}]
    assert box_of(nodes, w=1, d=2, h=0.5) == (0, 0, 0.5, 1, 2, 1.5)


def test_at_and_rotate_place_a_node_in_its_parent():
    turned = [{"shape": "box", "size": [2, 1, 1], "rotate": [0, 0, 90], "at": [5, 0, 0]}]
    assert box_of(turned) == pytest.approx((4, 0, 0, 5, 2, 1))
    tipped = [{"shape": "cylinder", "radius": 0.1, "height": 2, "rotate": [0, 90, 0]}]
    assert box_of(tipped) == pytest.approx((0, -0.1, -0.1, 2, 0.1, 0.1), abs=1e-6)


def test_repeat_copies_a_node_with_its_index():
    ring = [{"shape": "sphere", "radius": 0.1, "at": ["cos(360 * i / n)", "sin(360 * i / n)", 0], "repeat": {"count": "n"}}]
    assert len(solids(ring, n=6)) == 6
    assert box_of(ring, n=4) == pytest.approx((-1.1, -1.1, -0.1, 1.1, 1.1, 0.1))
    shelves = [{"shape": "box", "size": [1, 0.3, 0.02], "at": [0, 0, "k * 0.4"], "repeat": {"count": 3, "var": "k"}}]
    assert box_of(shelves)[5] == pytest.approx(0.82)
    with pytest.raises(GeometryError, match="repeat"):
        solids([{"shape": "box", "size": [1, 1, 1], "repeat": {"count": MAX_REPEAT + 1}}])


def test_when_and_zero_sizes_switch_parts_off():
    nodes = [{"shape": "box", "size": [1, 1, 1]}, {"shape": "box", "size": [1, 1, 1], "at": [0, 0, 1], "when": "top"},
             {"shape": "box", "size": ["arm", 1, 1]}]
    assert len(solids(nodes, top=0, arm=0)) == 1
    assert len(solids(nodes, top=1, arm=0.3)) == 3


def test_groups_share_a_transform_and_cuts_reach_every_child():
    nodes = [{"shape": "group", "at": [10, 0, 0], "rotate": [0, 0, 180],
              "subtract": [{"shape": "box", "size": [0.2, 0.2, 5]}],
              "children": [{"shape": "box", "size": [1, 1, 1]}, {"shape": "box", "size": [1, 1, 1], "at": [0, 0, 1]}]}]
    out = solids(nodes)
    assert box_of(nodes) == pytest.approx((9, -1, 0, 10, 0, 2))
    assert len(out) == 2 and all(len(s.cuts) == 1 for s in out)


def test_bad_geometry_is_explained():
    with pytest.raises(GeometryError, match="same number of vertices"):
        solids([{"shape": "loft", "sections": [{"z": 0, "profile": {"ngon": 4, "radius": 1}}, {"z": 1, "profile": {"ngon": 5, "radius": 1}}]}])
    with pytest.raises(GeometryError, match="r >= 0"):
        solids([{"shape": "revolve", "profile": [[-1, 0], [1, 0], [0, 1]]}])
    with pytest.raises(GeometryError, match="0..3"):
        solids([{"shape": "mesh", "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], "faces": [[0, 1, 9], [0, 1, 3], [1, 2, 3], [0, 3, 2]]}])
    with pytest.raises(GeometryError):
        solids([{"shape": "box", "size": ["1 / w", 1, 1]}], w=0)


EVERY_KIND = [
    {"shape": "box", "size": [1, 0.5, 0.3], "subtract": [{"shape": "cylinder", "radius": 0.1, "height": 0.3, "at": [0.5, 0.25, 0]}]},
    {"shape": "cylinder", "radius": 0.3, "height": 0.5, "inner": 0.25, "at": [2, 0, 0]},
    {"shape": "extrude", "profile": {"points": [[0, 0], [1, 0], [1, 1], [0, 1]], "holes": [[[0.3, 0.3], [0.7, 0.3], [0.7, 0.7], [0.3, 0.7]]]},
     "height": 0.2, "at": [4, 0, 0]},
    {"shape": "revolve", "profile": [[0, 0], [0.3, 0], [0.1, 0.8], [0, 0.8]], "angle": 270, "at": [6, 0, 0], "rotate": [0, 0, 30]},
    {"shape": "sweep", "profile": {"circle": 0.05, "inner": 0.03}, "path": [[8, 0, 0], [8, 0, 1], [9, 0, 1]]},
    {"shape": "loft", "sections": [{"z": 0, "profile": {"ngon": 5, "radius": 0.4}}, {"z": 1, "profile": {"ngon": 5, "radius": 0.1}}], "at": [10, 0, 0]},
    {"shape": "sphere", "radius": 0.3, "at": [12, 0, 0.3]},
]


@pytest.mark.parametrize("node", EVERY_KIND, ids=lambda n: n["shape"])
def test_every_solid_kind_compiles_to_ifc_with_the_same_extent(node):
    resolved = solids([node])
    model = ifcopenshell.file(schema="IFC4")
    ctx = model.createIfcGeometricRepresentationContext(None, "Model", 3, 1e-5, model.createIfcAxis2Placement3D(
        model.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None), None)
    rep = model.createIfcShapeRepresentation(ctx, "Body", representation_type(resolved), items(model, resolved))
    proxy = model.createIfcBuildingElementProxy(ifcopenshell.guid.new(), None, "p", None, None,
                                                model.createIfcLocalPlacement(None, model.createIfcAxis2Placement3D(
                                                    model.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None)),
                                                model.createIfcProductDefinitionShape(None, None, [rep]), None, None)
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    shape = ifcopenshell.geom.create_shape(settings, proxy)   # the vertex buffer lives only as long as the shape
    verts = np.array(shape.geometry.verts).reshape(-1, 3)
    x0, y0, z0, x1, y1, z1 = bounds(resolved)
    if node["shape"] in ("revolve", "sweep"):   # part revolutions and flat pipe ends sit within the conservative bound
        assert (verts.min(0) >= np.array([x0, y0, z0]) - 0.01).all() and (verts.max(0) <= np.array([x1, y1, z1]) + 0.01).all()
        return
    assert verts.min(0) == pytest.approx([x0, y0, z0], abs=0.02)
    assert verts.max(0) == pytest.approx([x1, y1, z1], abs=0.02)
