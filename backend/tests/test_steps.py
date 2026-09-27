"""GeoStep apply/reject: the only streamed vocabulary."""

import pytest
from pydantic import ValidationError

from schemas.geo import GeoModel
from schemas.geosteps import GeoStep, StepError, apply_step


def _apply(model, raw):
    return apply_step(model, GeoStep.model_validate(raw))


def test_part_opening_and_remove():
    model, msg = _apply(GeoModel(), {"step": "part", "id": "wall", "name": "front", "ifc": "IfcWall",
                                     "ifc_type": "SOLIDWALL", "solid": {"wall": [[0, 0], [6, 0]], "thickness": 0.2, "height": 3}})
    assert "IfcWall" in msg
    model, _ = _apply(model, {"step": "part", "id": "door", "ifc": "IfcDoor", "ifc_type": "DOOR", "solid": {"box": [0.9, 0.05, 2.1]}})
    model, msg = _apply(model, {"step": "opening", "id": "door-void", "host": "wall", "along": 1, "width": 0.9, "height": 2.1, "fill": "door"})
    assert "door-void" in msg
    model, msg = _apply(model, {"step": "remove", "id": "wall"})
    assert model.part("wall") is None and model.openings == []
    assert "opening" in msg


def test_unknown_entity_is_rejected():
    with pytest.raises(StepError, match="not an entity"):
        _apply(GeoModel(), {"step": "part", "id": "x", "ifc": "IfcNotAThing", "solid": {"box": [1, 1, 1]}})


def test_opening_must_fit_its_host():
    model, _ = _apply(GeoModel(), {"step": "part", "id": "wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
                                   "solid": {"wall": [[0, 0], [2, 0]], "thickness": 0.2, "height": 3}})
    with pytest.raises(StepError, match="only"):
        _apply(model, {"step": "opening", "host": "wall", "along": 0, "width": 5, "height": 1})


def test_repeat_needs_a_motion():
    with pytest.raises(ValidationError, match="translate|rotate"):
        _apply(GeoModel(), {"step": "part", "id": "col", "ifc": "IfcColumn", "ifc_type": "COLUMN",
                            "repeat": {"count": 4}, "solid": {"box": [0.3, 0.3, 3]}})
