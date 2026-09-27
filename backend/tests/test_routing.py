"""Branch cables follow walls and the roof instead of a chord across the room."""

from shapely.geometry import LineString, Point as ShpPoint, Polygon

from core.derive import analyze
from core.routing import on_fabric
from schemas.bim import Roof, Wall, Window, Wire
from schemas.design import Design, LevelDef, RoomDef, WindowDef


def _design(**kwargs) -> Design:
    levels = kwargs.pop("levels", [LevelDef(id="L1")])
    return Design(levels=levels, rooms=kwargs.pop("rooms"), **kwargs)


def _walls(spec):
    return [e for e in spec.elements if isinstance(e, Wall)]


def _dist(point, walls) -> float:
    pt = ShpPoint(point)
    return min(LineString(w.axis).distance(pt) for w in walls)


def test_a_light_cable_follows_walls_then_the_roof_instead_of_crossing_the_room():
    d = analyze(_design(rooms=[
        RoomDef(id="hall", name="Hall", kind="hall", rect=(0, 0, 8, 3)),
        RoomDef(id="room", name="Room", kind="living", rect=(0, 3, 8, 3)),
    ]))
    wire = next(e for e in d.spec.elements if isinstance(e, Wire) and e.id == "L1-wire-room-light")
    walls = _walls(d.spec)
    straight = LineString([wire.path[0], wire.path[-1]])
    # The chord from the riser to the light crosses the hall; the route must not.
    assert _dist(straight.interpolate(0.5, normalized=True), walls) > 0.4
    assert len(wire.path) >= 4
    for a, b in zip(wire.path[1:-2], wire.path[2:-1]):
        assert _dist(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), walls) <= 0.08
    assert on_fabric(wire.path[-2], _segs(d))
    roof = next(e for e in d.spec.elements if isinstance(e, Roof))
    assert Polygon(roof.outline).buffer(0.3).covers(LineString([wire.path[-2], wire.path[-1]]))
    assert wire.path != [wire.path[0], wire.path[-1]]
    again = analyze(_design(rooms=[
        RoomDef(id="hall", name="Hall", kind="hall", rect=(0, 0, 8, 3)),
        RoomDef(id="room", name="Room", kind="living", rect=(0, 3, 8, 3)),
    ]))
    other = next(e for e in again.spec.elements if isinstance(e, Wire) and e.id == wire.id)
    assert other.path == wire.path and other.elevation == wire.elevation


def test_a_cable_goes_around_an_opening_that_occupies_its_height():
    d = analyze(_design(
        rooms=[RoomDef(id="a", name="A", kind="living", rect=(0, 0, 10, 4))],
        windows=[WindowDef(id="win", room="a", side="S", at=0.5, width=3, height=2.9, sill=0)],
    ))
    win = next(e for e in d.spec.elements if isinstance(e, Window))
    wall = next(e for e in d.spec.elements if isinstance(e, Wall) and e.id == win.wall)
    opening = wall.frame_at(win.offset + win.width / 2)[0]
    wire = next(e for e in d.spec.elements if isinstance(e, Wire) and e.id.endswith("-outlet-1") or (
        isinstance(e, Wire) and "outlet" in e.id))
    # The far outlet is the one that is not on the riser; its plan route must miss the opening.
    outlets = [e for e in d.spec.elements if isinstance(e, Wire) and "outlet" in e.id]
    assert outlets
    for cable in outlets:
        assert LineString(cable.path).distance(ShpPoint(opening)) > 0.4
    # And it is not the straight chord, which does cross the opening's x-range through the room.
    far = max(outlets, key=lambda w: w.path[-1][0] + w.path[-1][1])
    chord = LineString([far.path[0], far.path[-1]])
    assert chord.distance(ShpPoint(opening)) < 1.5 or _dist(chord.interpolate(0.5, normalized=True), _walls(d.spec)) > 0.3


def _segs(derived):
    return [w for info in derived.rooms.values() for w in info.walls]
