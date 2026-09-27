"""Branch-circuit routes that stay in the building fabric.

A cable is not a chord between the riser and a device. Endpoints snap to the nearest
passable wall (or roof-edge) run, the run follows those centerlines, and only the last
stub leaves the wall: across the roof plane to a ceiling light, or a vertical drop at
the wall down to an outlet. Openings that occupy the cable's height are cut out of the
graph, so the path goes around them when another wall or roof run exists.
"""

from __future__ import annotations

import heapq
import math

from shapely.geometry import LineString, MultiLineString, Point as ShpPoint, Polygon
from shapely.ops import unary_union

from core.rooms import WallSeg, r2
from schemas.bim import Door, Window
from schemas.design import Pt

# A cable this far above an opening head (or below a sill) may pass in the wall.
_CLEAR = 0.02


def opening_span(el: Door | Window) -> tuple[float, float]:
    """Vertical range of an opening above the level, in metres."""
    if isinstance(el, Window):
        return el.sill_height, el.sill_height + el.height
    return 0.0, el.height


def blocks_at(walls: list[WallSeg], elements: list, elevation: float) -> dict[str, list[tuple[float, float]]]:
    """Distances along each wall that a cable at `elevation` must not cross."""
    spans = {el.id: opening_span(el) for el in elements if isinstance(el, (Door, Window))}
    out: dict[str, list[tuple[float, float]]] = {}
    for wall in walls:
        blocked: list[tuple[float, float]] = []
        for offset, width, oid in wall.openings:
            z0, z1 = spans.get(oid, (0.0, 2.1))
            if z0 + _CLEAR < elevation < z1 - _CLEAR:
                blocked.append((max(0.0, offset), offset + width))
        merged = _merge(blocked)
        if merged:
            out[wall.id] = merged
    return out


def route_cable(
    start: Pt,
    goal: Pt,
    walls: list[WallSeg],
    blocked: dict[str, list[tuple[float, float]]] | None = None,
    *,
    contain: Polygon | None = None,
    avoid: list[Polygon] | None = None,
) -> list[Pt] | None:
    """Polyline from `start` to `goal` along wall centerlines.

    The first and last segments are the stubs from the riser and to the device. Every
    other vertex lies on a wall. `contain`, when set, keeps the final stub inside that
    polygon (the room under the roof). `avoid` polygons are columns and other full-height
    obstacles the final stub should not cross when another wall attachment exists.
    Returns None when the fabric does not connect the two snaps.
    """
    blocked = blocked or {}
    edges = _edges(walls, blocked)
    if not edges:
        return None
    start_hit = _closest(start, edges, penalize=False, avoid=None)
    goal_hit = _closest(goal, edges, penalize=True, contain=contain, avoid=avoid)
    if start_hit is None or goal_hit is None:
        return None
    graph: dict[Pt, list[tuple[Pt, float]]] = {}
    for a, b in edges:
        _link(graph, a, b)
    start_n, start_edge = start_hit
    goal_n, goal_edge = goal_hit
    _attach(graph, start_n, start_edge)
    _attach(graph, goal_n, goal_edge)
    if start_edge == goal_edge:
        _link(graph, start_n, goal_n)
    origin = _node(start)
    dest = _node(goal)
    _link(graph, origin, start_n)
    _link(graph, goal_n, dest)
    path = _shortest(graph, origin, dest)
    if path is None:
        return None
    path = _simplify(path)
    if len(path) < 2 or sum(math.dist(a, b) for a, b in zip(path, path[1:])) < 0.05:
        return None
    return path


def _edges(walls: list[WallSeg], blocked: dict[str, list[tuple[float, float]]]) -> list[tuple[Pt, Pt]]:
    """Passable wall runs, split where centerlines meet so a corner is one node.

    Exterior walls are drawn past the corner, so they cross instead of sharing an endpoint.
    Noding the runs joins them; a gap cut for an opening stays a gap.
    """
    pieces: list[LineString] = []
    for wall in walls:
        line = wall.line
        if line is None or line.length < 0.05:
            continue
        for d0, d1 in _passable(line.length, blocked.get(wall.id, [])):
            pts = _between(line, d0, d1)
            if len(pts) >= 2:
                pieces.append(LineString(pts))
    if not pieces:
        return []
    noded = unary_union(pieces)
    geoms = list(noded.geoms) if isinstance(noded, MultiLineString) else [noded]
    edges: list[tuple[Pt, Pt]] = []
    for geom in geoms:
        if geom.is_empty or not isinstance(geom, LineString):
            continue
        coords = [_node(p) for p in geom.coords]
        for a, b in zip(coords, coords[1:]):
            if a != b and math.dist(a, b) >= 0.02:
                edges.append((a, b))
    return edges


def _passable(length: float, blocked: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    cursor = 0.0
    for a, b in _merge(blocked):
        a, b = max(0.0, a), min(length, b)
        if a > cursor + 0.05:
            ranges.append((cursor, a))
        cursor = max(cursor, b)
    if length > cursor + 0.05:
        ranges.append((cursor, length))
    return ranges


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(spans):
        if b <= a:
            continue
        if out and a <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _between(line: LineString, d0: float, d1: float) -> list[Pt]:
    """Vertices of `line` from distance d0 to d1, endpoints included."""
    pts = [_at(line, d0)]
    walked = 0.0
    coords = list(line.coords)
    for a, b in zip(coords, coords[1:]):
        seg = math.dist(a, b)
        at_b = walked + seg
        if d0 + 1e-4 < at_b < d1 - 1e-4:
            pts.append(_node(b))
        walked = at_b
    end = _at(line, d1)
    if math.dist(pts[-1], end) >= 0.02:
        pts.append(end)
    return pts


def _at(line: LineString, dist: float) -> Pt:
    p = line.interpolate(max(0.0, min(line.length, dist)))
    return _node((p.x, p.y))


def _node(p) -> Pt:
    return (r2(float(p[0])), r2(float(p[1])))


def _closest(point: Pt, edges: list[tuple[Pt, Pt]], *, penalize: bool, contain: Polygon | None = None,
             avoid: list[Polygon] | None = None) -> tuple[Pt, tuple[Pt, Pt]] | None:
    """Nearest point on the fabric. A final stub that leaves `contain` or crosses `avoid` loses."""
    scored: list[tuple] = []
    for edge in edges:
        pt = _project(edge[0], edge[1], point)
        dist = math.dist(pt, point)
        if contain is not None and dist > 0.02 and not contain.buffer(0.12).covers(LineString([pt, point])):
            continue
        penalty = 1000.0 if penalize and _hits(pt, point, avoid) else 0.0
        scored.append((penalty + dist, dist, pt, edge))
    if not scored and contain is not None:
        return _closest(point, edges, penalize=penalize, contain=None, avoid=avoid)
    if not scored:
        return None
    scored.sort()
    _penalty, _dist, pt, edge = scored[0]
    return pt, edge


def _project(a: Pt, b: Pt, p: Pt) -> Pt:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 < 1e-8:
        return a
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return _node((a[0] + t * dx, a[1] + t * dy))


def _hits(a: Pt, b: Pt, obstacles: list[Polygon] | None) -> bool:
    if not obstacles or math.dist(a, b) < 0.05:
        return False
    line = LineString([a, b])
    for poly in obstacles:
        piece = line.intersection(poly)
        if not piece.is_empty and piece.length > 0.05:
            return True
    return False


def _link(graph: dict[Pt, list[tuple[Pt, float]]], a: Pt, b: Pt) -> None:
    if a == b:
        return
    w = math.dist(a, b)
    if w < 0.01:
        return
    graph.setdefault(a, [])
    graph.setdefault(b, [])
    if not any(n == b for n, _ in graph[a]):
        graph[a].append((b, w))
        graph[b].append((a, w))


def _attach(graph: dict[Pt, list[tuple[Pt, float]]], snap: Pt, edge: tuple[Pt, Pt]) -> None:
    _link(graph, snap, edge[0])
    _link(graph, snap, edge[1])


def _shortest(graph: dict[Pt, list[tuple[Pt, float]]], start: Pt, goal: Pt) -> list[Pt] | None:
    if start not in graph or goal not in graph:
        return None
    if start == goal:
        return [start]
    dist = {start: 0.0}
    prev: dict[Pt, Pt | None] = {start: None}
    heap = [(0.0, start)]
    done: set[Pt] = set()
    while heap:
        d, node = heapq.heappop(heap)
        if node in done:
            continue
        done.add(node)
        if node == goal:
            break
        for nxt, w in sorted(graph.get(node, ())):
            nd = d + w
            if nd < dist.get(nxt, float("inf")) - 1e-6:
                dist[nxt] = nd
                prev[nxt] = node
                heapq.heappush(heap, (nd, nxt))
    if goal not in dist:
        return None
    path: list[Pt] = []
    node: Pt | None = goal
    while node is not None:
        path.append(node)
        node = prev.get(node)
    path.reverse()
    return path


def _simplify(path: list[Pt]) -> list[Pt]:
    cleaned: list[Pt] = []
    for p in path:
        if cleaned and math.dist(cleaned[-1], p) < 0.02:
            continue
        if len(cleaned) >= 2:
            a, b = cleaned[-2], cleaned[-1]
            span = max(math.dist(a, p), 0.01)
            cross = (b[0] - a[0]) * (p[1] - b[1]) - (b[1] - a[1]) * (p[0] - b[0])
            if abs(cross) <= 0.02 * span:
                cleaned[-1] = p
                continue
        cleaned.append(p)
    return cleaned


def on_fabric(point: Pt, walls: list[WallSeg], tol: float = 0.06) -> bool:
    """True when `point` lies on a wall centerline (a routed vertex, not a stub end)."""
    pt = ShpPoint(point)
    return any(w.line is not None and w.line.distance(pt) <= tol for w in walls)


def with_drop(path: list[Pt], walls: list[WallSeg], run_z: float, end_z: float) -> tuple[list[Pt], list[float] | None]:
    """Keep the run at `run_z` in the wall and roof, and drop vertically to `end_z` at the wall.

    The drop is a repeated plan point. The short stub from that point to a device that sits
    just off the wall stays at `end_z`. Returns heights aligned with the path, or None when
    the whole run is already at one height.
    """
    if len(path) < 2 or abs(run_z - end_z) < 0.05:
        return path, None
    run_z, end_z = r2(run_z), r2(end_z)
    end = path[-1]
    if on_fabric(end, walls):
        return path + [end], [run_z] * len(path) + [end_z]
    return path[:-1] + [path[-2], end], [run_z] * (len(path) - 1) + [end_z, end_z]
