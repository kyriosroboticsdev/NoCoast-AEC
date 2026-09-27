"""IFC files attached as components: each becomes a brick in the design's own library and is placed
with a `brick` step like any other."""

import base64

import pytest

from bricks.geometry import bounds
from components import ComponentError, IfcAttachment, attach, component_lines, convert, to_brick
from core.derive import derive
from ifc.builder import check_geometry, compile_ifc
from schemas.bim import Asset
from schemas.design import Design
from schemas.steps import Step, apply_step
from tests.fixtures.make_components import make_island


def attachment(path) -> IfcAttachment:
    return IfcAttachment(name=path.name, data=base64.b64encode(path.read_bytes()).decode())


@pytest.fixture(scope="module")
def island(tmp_path_factory):
    return attachment(make_island(tmp_path_factory.mktemp("c") / "Kitchen_island.ifc"))


@pytest.fixture(scope="module")
def island_2x3(tmp_path_factory):
    return attachment(make_island(tmp_path_factory.mktemp("c") / "island-2x3.ifc", millimetres=False, schema="IFC2X3"))


def test_a_file_becomes_one_brick_in_metres_with_its_origin_at_the_base_centre(island):
    brick = to_brick(island)
    assert brick.id.startswith("kitchen_island_") and brick.name == "Kitchen island"
    assert brick.ifc_class == "IfcFurnishingElement" and brick.mount == "rest"
    x0, y0, z0, x1, y1, z1 = bounds(brick.solids(brick.resolve()))
    assert (x1 - x0, y1 - y0, z1 - z0) == pytest.approx((1.9, 1.0, 0.9), abs=1e-3)     # written in millimetres
    assert (x0 + x1, y0 + y1, z0) == pytest.approx((0, 0, 0), abs=1e-3)               # placed at (5, 3) in the file
    assert brick.properties["source_file"] == "Kitchen_island.ifc" and brick.properties["source_schema"] == "IFC4"
    assert brick.properties["source_elements"] == 2 and "Island top" in brick.properties["source_names"]
    assert {"component", "attached"} <= set(brick.tags)


def test_schema_and_units_of_the_file_do_not_matter(island, island_2x3):
    a, b = to_brick(island), to_brick(island_2x3)
    assert bounds(a.solids(a.resolve())) == pytest.approx(bounds(b.solids(b.resolve())), abs=1e-3)
    assert b.properties["source_schema"] == "IFC2X3" and a.id != b.id


def test_the_same_file_always_gets_the_same_id(island):
    assert to_brick(island).id == to_brick(island).id


def test_attached_component_places_and_compiles_like_any_brick(island):
    design = Design(name="t")
    for step in (dict(step="level", id="L1", height=3.0), dict(step="room", name="Kitchen", rect=[0, 0, 6, 5])):
        design, _ = apply_step(design, Step(**step))
    added, problems = attach(design, [island])
    assert [b.id for b in added] == [b.id for b in design.library] and not problems
    design, _ = apply_step(design, Step(step="brick", brick=added[0].id, ref="kitchen", id="island"))
    spec, _ = derive(design)
    assets = [e for e in spec.elements if isinstance(e, Asset)]
    assert [a.id for a in assets] == ["island"]
    model, _ = compile_ifc(spec, {}, design.model_dump_json())
    assert check_geometry(model) == []
    placed = [p for p in model.by_type("IfcFurnishingElement") if p.Name and "island" in p.Name.lower()]
    assert len(placed) == 1
    assert Design.model_validate_json(design.model_dump_json()).library[0].id == added[0].id   # survives storage


def test_attaching_the_same_file_again_replaces_it(island, island_2x3):
    design = Design(name="t")
    attach(design, [island])
    attach(design, [island, island_2x3])
    assert len(design.library) == 2


def test_a_file_that_cannot_be_used_is_reported_and_the_rest_still_attach(island):
    empty = IfcAttachment(name="empty.ifc", data=base64.b64encode(
        b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((''),'2;1');\nFILE_NAME('','',(''),(''),'','','');\n"
        b"FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n").decode())
    events = []
    design = Design(name="t")
    added, problems = attach(design, [empty, island], lambda stage, message, data: events.append((stage, message, data)))
    assert len(added) == 1 and len(problems) == 1 and "empty.ifc" in problems[0] and "no building elements" in problems[0]
    stage, message, data = events[0]
    assert stage == "components" and "1 rejected" in message
    assert data["components"][0]["id"] == added[0].id and data["rejected"] == problems


def test_limits_are_explained(island, monkeypatch):
    monkeypatch.setattr(convert, "MAX_EXTENT", 1.0)
    with pytest.raises(ComponentError, match="units"):
        to_brick(island)
    monkeypatch.setattr(convert, "MAX_EXTENT", 60.0)
    monkeypatch.setattr(convert, "MAX_TRIANGLES", 10)
    with pytest.raises(ComponentError, match="too detailed"):
        to_brick(island)
    monkeypatch.setattr(convert, "MAX_TRIANGLES", 60_000)
    monkeypatch.setattr(convert, "MAX_PRODUCTS", 1)
    with pytest.raises(ComponentError, match="2 elements"):
        to_brick(island)


@pytest.mark.parametrize("name,data,expected", [
    ("notes.ifc", base64.b64encode(b"hello").decode(), "not an IFC file"),
    ("x.ifc", "not base64 !!", "not valid base64"),
    ("x.ifc", "", "empty"),
])
def test_attachment_is_checked_by_its_bytes(name, data, expected):
    with pytest.raises(ValueError, match=expected):
        IfcAttachment(name=name, data=data)


def test_attachment_name_cannot_carry_a_path(island):
    a = IfcAttachment(name="..\\..\\etc/passwd.ifc", data=island.data)
    assert a.name == "passwd.ifc" and a.filename == f"{a.sha1}.ifc"


def test_prompt_lines_name_the_id_size_and_source(island):
    brick = to_brick(island)
    line = component_lines([brick])[0]
    assert line.startswith(f"{brick.id}: ") and "Kitchen_island.ifc" in line and "IfcFurnishingElement" in line
