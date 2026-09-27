"""Headless screenshots (render/): the PNG, the camera a View describes, plan cuts with solid caps, x-ray
targets, labels' bookkeeping, and the messages a bad view gets."""

import numpy as np
import pytest

from core.derive import derive, space_id
from ifc.builder import compile_ifc
from render import ViewError, render, scene_of
from render.png import encode_png, png_size
from render.raster import clip
from schemas.design import Design
from schemas.look import LookTurn, View
from schemas.steps import Step, apply_step


def _house() -> Design:
    d = Design(name="t")
    for s in [dict(step="room", name="Kitchen", rect=[0, 0, 5, 4]), dict(step="room", name="Living", rect=[5, 0, 6, 4]),
              dict(step="door", room="kitchen", to="living"), dict(step="brick", brick="fridge", ref="kitchen", side="N"),
              dict(step="brick", brick="tree", ref="site", position=[-4, 2])]:
        d, _ = apply_step(d, Step(**s))
    return d


@pytest.fixture(scope="module")
def scene():
    design = _house()
    model, guids = compile_ifc(derive(design)[0])
    return scene_of(model, guids, {space_id(r.level, r.id): r.id for r in design.rooms})


@pytest.fixture(scope="module")
def shoot(scene):
    return lambda view: render(scene, view)


def shares(shot) -> dict[str, float]:
    return dict(shot.visible)


def test_png_encoding_round_trips_its_size():
    data = encode_png(np.zeros((30, 50, 3), np.uint8))
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and png_size(data) == (50, 30)


def test_clipping_keeps_the_part_on_the_positive_side():
    tri = np.array([[[0.0, 0, 0], [2, 0, 0], [0, 2, 0]]])
    whole, _ = clip(tri, np.array([1.0, 0, 0]), -1)
    gone, _ = clip(tri, np.array([1.0, 0, 0]), 5)
    half, src = clip(tri, np.array([-1.0, 0, 0]), -1)       # keep x <= 1: a quad, so two triangles
    assert len(whole) == 1 and len(gone) == 0 and len(half) == 2 and set(src) == {0}
    assert half[..., 0].max() == pytest.approx(1)


def test_the_default_view_shows_the_whole_model_with_what_is_visible(shoot):
    shot = shoot(View())
    assert png_size(shot.png) == (1024, 768)
    seen = shares(shot)
    assert "roof" in seen and "tree-site" in seen and any(i.startswith("L1-wall") for i in seen)
    assert "view of everything from azimuth 225° elevation 30°" in shot.caption()


def test_a_plan_cuts_the_level_and_draws_cut_walls_solid(shoot):
    plan = shoot(View(level="L1", elevation=90, azimuth=180))
    seen = shares(plan)
    assert "roof" not in seen and "fridge-kitchen" in seen and "L1-floor" in seen
    assert sum(p for i, p in seen.items() if i.startswith("L1-wall")) > 1.5    # caps, not hollow shells
    assert "L1-floor" not in shares(shoot(View(level="L1", elevation=90, hide=["IfcSlab"])))


def test_a_target_is_framed_and_seen_through_what_stands_in_front(shoot):
    # From the north the kitchen's north wall stands between the camera and the fridge backed onto it.
    shot = shoot(View(target="fridge-kitchen", azimuth=0, elevation=10))
    seen = shares(shot)
    assert seen["fridge-kitchen"] > 10 and "drawn through" in shot.caption()
    assert shares(shoot(View(target="kitchen", level="L1", elevation=60)))["L1-floor"] > 5


def test_hide_position_and_size(scene, shoot):
    assert "roof" not in shares(shoot(View(hide=["IfcRoof"])))
    inside = shoot(View(position=[1, 1, 1.6], look_at=[4, 3, 1]))
    assert any(i.startswith("L1-wall") for i in shares(inside))
    assert png_size(render(scene, View(), 320, 200).png) == (320, 200)


def test_rooms_are_known_by_their_design_ids(scene):
    assert {r.id for r in scene.rooms} == {"kitchen", "living"}
    lo, hi = scene.find("Kitchen")
    assert lo[:2] == pytest.approx((0, 0), abs=0.2) and hi[:2] == pytest.approx((5, 4), abs=0.2)


@pytest.mark.parametrize("view, match", [
    (View(target="toaster"), "nothing called 'toaster'.*kitchen"),
    (View(level="L9"), "unknown level 'L9'.*L1"),
    (View(cut=-100, hide=["ground"]), "nothing left to show"),
    (View(position=[1, 1, 1], look_at=[1, 1, 1]), "the camera position is the point it looks at"),
])
def test_bad_views_are_explained(shoot, view, match):
    with pytest.raises(ViewError, match=match):
        shoot(view)


def test_views_and_turns_validate_what_the_model_sends():
    assert View(look_at=[1, 2]).look_at == [1.0, 2.0, 0.0] and View(hide="IfcRoof").hide == ["IfcRoof"]
    with pytest.raises(ValueError, match=r"expected \[x, y, z\]"):
        View(position=[1])
    turn = LookTurn.model_validate({"views": [{}] * 5})
    assert len(turn.views) == 3 and not turn.done
