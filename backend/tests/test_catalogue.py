"""The brick catalogue: bricks found by search and kept out of the system prompts, and the checker
every catalogue brick must pass (tools/check_bricks.py)."""

import json

import pytest

from bricks import Brick, Library, library
from bricks.registry import CATALOGUE_DIR, LIBRARY_DIR
from tools import check_bricks
from tools.brick_coverage import coverage

BOX = {"name": "Box", "tags": ["box"], "ifc_class": "IfcBuildingElementProxy", "predefined_type": "ELEMENT",
       "params": {"w": [1.0, 0.5, 2.0]}, "geometry": [{"shape": "box", "size": ["w", 1, 1]}]}


def test_catalogue_bricks_load_with_the_core_and_stay_out_of_the_index():
    lib = library()
    assert lib.catalogue, "the catalogue folder has bricks"
    assert set(lib.catalogue) <= set(lib.bricks)
    core = set(lib.bricks) - set(lib.catalogue)
    assert {p.stem for p in LIBRARY_DIR.glob("*.json")} and core
    head, _, tail = lib.index_text().partition("\nCATALOGUE")
    assert set(head.split(", ")) == core
    assert f"({len(lib.catalogue)} more bricks" in tail
    for topic in {t for t in lib.catalogue.values()}:
        assert topic in tail
    assert len(lib.index_text()) < 4000


def test_a_catalogue_brick_is_found_by_search_and_by_id():
    lib = library()
    some = next(iter(lib.catalogue))
    brick = lib.get(some)
    assert brick is not None
    assert some in [b.id for b, _ in lib.search(brick.name, limit=5)]


def test_topics_come_from_the_file_names():
    lib = library()
    assert set(lib.catalogue.values()) == {p.stem.replace("_", " ") for p in CATALOGUE_DIR.glob("*.json")}


def test_index_without_a_catalogue_is_the_plain_id_list():
    lib = Library([Brick.model_validate({**BOX, "id": "box_a"}), Brick.model_validate({**BOX, "id": "box_b"})])
    assert lib.index_text() == "box_a, box_b"


def test_every_catalogue_brick_passes_the_checker(capsys):
    assert check_bricks.main_with([]) == 0, capsys.readouterr().out


@pytest.mark.parametrize("change,expected", [
    ({"tags": ["Box"]}, "lower-case"),
    ({"properties": {"fixture": "sofa"}}, "reserved"),
    ({"params": {"w": [1.0, 0.5, 500.0]}}, "larger than"),
    ({"geometry": [{"shape": "box", "size": ["w", 1, "5"]}]}, "place:"),          # 5 m tall in a 3.8 m room
    ({"predefined_type": "NOPE"}, "load:"),
    ({"name": "Living room", "tags": ["living room"]}, "words:"),
    ({"params": {"w": []}}, "load: IndexError"),
])
def test_checker_names_what_is_wrong(tmp_path, capsys, change, expected):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"bricks": [{**BOX, "id": "probe_box", **change}]}), encoding="utf-8")
    assert check_bricks.main_with([str(path)]) == 1
    assert expected in capsys.readouterr().out


def test_checker_passes_a_good_brick_outside_the_library(tmp_path, capsys):
    path = tmp_path / "good.json"
    path.write_text(json.dumps({"bricks": [{**BOX, "id": "probe_box", "description": "a box"}]}), encoding="utf-8")
    assert check_bricks.main_with([str(path)]) == 0, capsys.readouterr().out


def test_coverage_counts_classes_and_types():
    c = coverage()
    assert c["classes"] == 130 and 0 < c["classes_covered"] <= 130
    assert c["types_covered"] <= c["types"]
    assert "IfcChiller" in c["unused_classes"] or c["classes_covered"] > 46
