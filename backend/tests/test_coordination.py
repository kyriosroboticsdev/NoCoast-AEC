"""Coordination: clashes, service ports, placement rules and the rule-of-thumb structure check."""

from core.checks import check
from core.coordinate import coordinate, errors, fix_lines
from core.derive import analyze
from core.stream import StepStream
from schemas.design import Design
from schemas.requirements import Requirement
from schemas.steps import Step, apply_step


def _design(*steps) -> Design:
    d = Design(name="t")
    for s in steps:
        d, _ = apply_step(d, Step(**s))
    return d


def _issues(d: Design, kind: str | None = None):
    found = coordinate(d, analyze(d))
    return [i for i in found if kind is None or i.kind == kind]


def _apply_suggestions(d: Design, issues) -> Design:
    for issue in issues:
        for s in issue.suggestions:
            d, _ = apply_step(d, Step(**s))
    return d


ROOMS = (dict(step="room", name="Kitchen", rect=[0, 0, 5, 4]), dict(step="room", name="Utility", rect=[5, 0, 3, 4]))


def test_two_bricks_in_the_same_place_clash_but_different_heights_do_not():
    d = _design(*ROOMS, dict(step="brick", brick="fridge", room="kitchen", side="N"),
                dict(step="brick", brick="dishwasher", id="dw", room="kitchen", side="N"))
    clash = _issues(d, "clash")
    assert len(clash) == 1 and set(clash[0].ids) == {"fridge-kitchen", "dw"}
    ok = _design(*ROOMS, dict(step="brick", brick="dining_table", room="kitchen"), dict(step="brick", brick="pendant_light", room="kitchen"))
    assert not _issues(ok, "clash")


def test_bricks_do_not_clash_with_legacy_furniture_pairs_or_overlap_ok_pieces():
    d = _design(*ROOMS, dict(step="furniture", room="kitchen", kind="sofa", side="N"),
                dict(step="furniture", room="kitchen", kind="armchair", side="N"),
                dict(step="brick", brick="rug", room="kitchen"))
    assert not _issues(d, "clash")


def test_the_stream_rejects_a_brick_step_that_clashes():
    events = []
    stream = StepStream(lambda *a: events.append(a), _design(*ROOMS, dict(step="brick", brick="fridge", room="kitchen", side="N")))
    assert not stream.apply({"step": "brick", "brick": "washing_machine", "id": "wm", "room": "kitchen", "side": "N"})
    assert "overlap" in stream.rejected[0][2]
    assert stream.apply({"step": "brick", "brick": "washing_machine", "id": "wm", "room": "kitchen", "side": "S"})
    stream.close()


def test_missing_services_name_providers_and_suggestions_resolve_them():
    d = _design(*ROOMS, dict(step="brick", brick="gas_boiler", room="utility", side="N"))
    service = _issues(d, "service")
    assert {i.message.split(" needs ")[1].split(",")[0] for i in service} == {"flue", "gas"}
    assert all(i.suggestions for i in service)
    d = _apply_suggestions(d, service)
    assert not _issues(d, "service")


def test_hot_water_comes_from_a_heater_and_base_services_need_nothing():
    d = _design(*ROOMS, dict(step="brick", brick="kitchen_sink", room="kitchen", side="S"))
    [hot] = _issues(d, "service")
    assert "needs hot water" in hot.message and "water_heater" in hot.message
    assert hot.suggestions[0]["brick"].endswith("water_heater")
    d = _apply_suggestions(d, [hot])
    assert not _issues(d, "service")
    assert not _issues(_design(*ROOMS, dict(step="brick", brick="fridge", room="kitchen", side="N")), "service")


def test_rules_warn_about_the_wrong_room_kind():
    d = _design(*ROOMS, dict(step="brick", brick="bathtub", room="kitchen", side="S"))
    [rule] = _issues(d, "rule")
    assert rule.severity == "warning" and "bathroom" in rule.message


def test_a_wide_room_needs_a_beam_and_the_suggested_beam_fixes_it():
    d = _design(dict(step="room", name="Hall", rect=[0, 0, 12, 10]))
    [issue] = _issues(d, "structure")
    assert "10.0 m unsupported" in issue.message and issue.suggestions[0]["brick"] == "steel_beam"
    d = _apply_suggestions(d, [issue])
    assert not _issues(d, "structure")


def test_timber_walls_carry_shorter_spans_than_concrete():
    room = dict(step="room", name="Studio", rect=[0, 0, 9, 6.5])
    assert _issues(_design(room, dict(step="material", material="timber")), "structure")
    assert not _issues(_design(room, dict(step="material", material="concrete")), "structure")


def test_a_very_wide_room_gets_several_beams():
    d = _design(dict(step="room", name="Barn", rect=[0, 0, 20, 16]))
    [issue] = _issues(d, "structure")
    beams = [s for s in issue.suggestions if s["brick"] == "steel_beam"]
    assert len(beams) == 2
    assert not _issues(_apply_suggestions(d, [issue]), "structure")


def test_an_overlong_beam_gets_a_column_under_it():
    d = _design(dict(step="room", name="Hall", rect=[0, 0, 14, 6]),
                dict(step="brick", brick="glulam_beam", start=[0.2, 3], end=[13.8, 3]))
    [issue] = _issues(d, "structure")
    assert "glulam_beam" in issue.message and all(s["brick"] == "steel_column" for s in issue.suggestions)
    assert not _issues(_apply_suggestions(d, [issue]), "structure")


def test_an_upper_storey_overhanging_by_more_than_a_metre_needs_posts():
    d = _design(dict(step="room", name="Living", rect=[0, 0, 6, 5]), dict(step="level", id="L2"),
                dict(step="room", name="Studio", level="L2", rect=[0, 0, 6, 7]))
    [issue] = _issues(d, "structure")
    assert "overhangs" in issue.message and issue.suggestions
    assert not _issues(_apply_suggestions(d, [issue]), "structure")
    small = _design(dict(step="room", name="Living", rect=[0, 0, 6, 5]), dict(step="level", id="L2"),
                    dict(step="room", name="Studio", level="L2", rect=[0, 0, 6, 5.8]))
    assert not _issues(small, "structure")


def test_fix_lines_carry_the_suggested_steps():
    d = _design(dict(step="room", name="Hall", rect=[0, 0, 12, 10]))
    lines = fix_lines(coordinate(d, analyze(d)))
    assert lines and '"brick":"steel_beam"' in lines[0]
    assert errors([]) == []


def test_asset_structure_and_furniture_requirements():
    d = _design(dict(step="room", name="Hall", rect=[0, 0, 12, 10]), dict(step="brick", brick="double_bed", room="hall"),
                dict(step="brick", brick="air_source_heat_pump", position=[14, 2]))
    reqs = [Requirement(text="a heat pump", kind="asset", item="heat pump"),
            Requirement(text="an elevator", kind="asset", item="passenger_elevator"),
            Requirement(text="it stands up", kind="structure"),
            Requirement(text="a double bed", kind="furniture", item="double bed", room="hall")]
    status = [r.status for r in check(d, analyze(d), reqs)]
    assert status == ["met", "unmet", "unmet", "met"]
