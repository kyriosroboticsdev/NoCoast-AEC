import pytest

from core.ops import OpError, apply_ops
from schemas.bim import BuildingSpec
from schemas.ops import AddElement, DeleteElement, DeleteLevel, ModifyElement, ModifyLevel, SetBuilding


def base() -> BuildingSpec:
    return BuildingSpec.model_validate({
        "levels": [{"id": "L1", "name": "Ground", "height": 3}, {"id": "L2", "name": "First", "height": 3}],
        "elements": [
            {"type": "wall", "id": "w1", "level": "L1", "start": [0, 0], "end": [6, 0], "external": True},
            {"type": "wall", "id": "w2", "level": "L2", "start": [0, 0], "end": [6, 0]},
            {"type": "door", "id": "d1", "wall": "w1", "offset": 1},
            {"type": "window", "id": "win1", "wall": "w1", "offset": 3},
            {"type": "slab", "id": "s1", "level": "L1", "outline": [[0, 0], [6, 0], [6, 4], [0, 4]]},
        ],
    })


def test_modify_and_add():
    spec, notes = apply_ops(base(), [
        ModifyElement(id="w1", set={"end": [8, 0]}),
        AddElement(element={"type": "window", "id": "win2", "wall": "w1", "offset": 6.5}),
    ])
    w1 = next(e for e in spec.elements if e.id == "w1")
    assert w1.end == (8, 0) and w1.external is True  # untouched fields survive
    assert {e.id for e in spec.elements} == {"w1", "w2", "d1", "win1", "s1", "win2"}
    assert notes == []


def test_delete_wall_cascades_to_openings():
    spec, notes = apply_ops(base(), [DeleteElement(id="w1")])
    assert {e.id for e in spec.elements} == {"w2", "s1"}
    assert any("d1" in n for n in notes) and any("win1" in n for n in notes)


def test_delete_level_cascades():
    spec, notes = apply_ops(base(), [DeleteLevel(id="L1")])
    assert [l.id for l in spec.levels] == ["L2"]
    assert {e.id for e in spec.elements} == {"w2"}
    assert spec.levels[0].elevation == 0  # restacked


def test_modify_level_restacks():
    spec, _ = apply_ops(base(), [ModifyLevel(id="L1", set={"height": 4.5})])
    assert spec.levels[1].elevation == 4.5


def test_set_building():
    spec, _ = apply_ops(base(), [SetBuilding(set={"name": "Casa"})])
    assert spec.building.name == "Casa"


@pytest.mark.parametrize("ops, fragment", [
    ([DeleteElement(id="nope")], "does not exist"),
    ([DeleteElement(id="wall-w1")], "did you mean 'w1'"),
    ([ModifyElement(id="w1", set={"type": "slab"})], "cannot change the type"),
    ([ModifyElement(id="w1", set={"id": "w9"})], "immutable"),
    ([ModifyElement(id="w1", set={"end": [2, 0]})], "runs past the end"),  # d1/win1 no longer fit
    ([AddElement(element={"type": "door", "id": "d1", "wall": "w1", "offset": 0})], "already exists"),
    ([ModifyElement(id="win1", set={"width": -1})], "greater than 0"),
    ([ModifyElement(id="w1", set={})], "no fields to change"),
])
def test_errors_are_readable(ops, fragment):
    with pytest.raises(OpError) as exc:
        apply_ops(base(), ops)
    assert fragment in str(exc.value)


def test_flat_ops_convert_and_explain():
    from schemas.ops import OpsResponse

    resp = OpsResponse.model_validate({"ops": [
        {"op": "add_element", "element": {"type": "window", "id": "win2", "wall": "w1", "offset": 4.5}},
        {"op": "modify_element", "id": "w1", "set": {"thickness": 0.3}},
        {"op": "modify_level", "id": "L1", "set": {"height": 3.5}},
        {"op": "set_building", "set": {"name": "Casa"}},
        {"op": "delete_element", "id": "d1"},
    ]})
    typed = resp.typed_ops()
    assert [op.op for op in typed] == ["add_element", "modify_element", "modify_level", "set_building", "delete_element"]
    spec, _ = apply_ops(base(), typed)
    assert spec.building.name == "Casa" and spec.levels[1].elevation == 3.5 and "win2" in {e.id for e in spec.elements}

    for flat, fragment in [
        ({"op": "add_element"}, "needs `element`"),
        ({"op": "add_element", "element": {"type": "window", "id": "x"}}, "wall"),  # window needs a host wall
        ({"op": "modify_element", "id": "w1", "set": {}}, "non-null field"),
        ({"op": "modify_level", "id": "L1", "set": {"thickness": 1}}, "not level fields"),
        ({"op": "set_building", "set": {"height": 1}}, "not building fields"),
        ({"op": "delete_element"}, "needs `id`"),
    ]:
        with pytest.raises(OpError) as exc:
            OpsResponse.model_validate({"ops": [flat]}).typed_ops()
        assert fragment in str(exc.value), str(exc.value)


def test_input_is_not_mutated():
    spec = base()
    apply_ops(spec, [DeleteElement(id="w1")])
    assert len(spec.elements) == 5
