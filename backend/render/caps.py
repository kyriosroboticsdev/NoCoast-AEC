"""Section caps: where a horizontal cut passes through a solid, fill its cross-section so a plan shows
walls and furniture as solid shapes instead of hollow shells."""

from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

SNAP = 5   # decimals: the same edge crossed from two triangles must give the same point


def _segments(tris: np.ndarray, cut: float) -> list[LineString]:
    out = []
    for tri in tris:
        pts = []
        for k in range(3):
            a, b = tri[k], tri[(k + 1) % 3]
            if (a[2] - cut) * (b[2] - cut) < 0:
                p = a + (b - a) * ((cut - a[2]) / (b[2] - a[2]))
                pts.append((round(float(p[0]), SNAP), round(float(p[1]), SNAP)))
        if len(pts) == 2 and pts[0] != pts[1]:
            out.append(LineString(pts))
    return out


def _inside(tris: np.ndarray, x: float, y: float, cut: float) -> bool:
    """Nonzero winding of the faces straight above (x, y, cut): inside, even where an element's parts overlap."""
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    det = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    ok = np.abs(det) > 1e-12
    safe = np.where(ok, det, 1.0)
    w0 = ((b[:, 1] - c[:, 1]) * (x - c[:, 0]) + (c[:, 0] - b[:, 0]) * (y - c[:, 1])) / safe
    w1 = ((c[:, 1] - a[:, 1]) * (x - c[:, 0]) + (a[:, 0] - c[:, 0]) * (y - c[:, 1])) / safe
    w2 = 1 - w0 - w1
    hit = ok & (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    z = w0 * a[:, 2] + w1 * b[:, 2] + w2 * c[:, 2]
    return int(np.sign(det[hit & (z > cut)]).sum()) != 0


def caps(tris: np.ndarray, owner: np.ndarray, cut: float) -> tuple[np.ndarray, np.ndarray]:
    """Cap triangles at height `cut` for every element the plane passes through, and their owners."""
    z = tris[..., 2]
    crossing = (z.min(1) < cut) & (z.max(1) > cut)
    out, who = [], []
    for item in np.unique(owner[crossing]):
        mine = tris[owner == item]
        segs = _segments(tris[crossing & (owner == item)], cut)
        if len(segs) < 3:
            continue
        for face in polygonize(unary_union(segs)):
            probe = face.representative_point()
            if face.area < 1e-8 or not _inside(mine, probe.x, probe.y, cut):
                continue
            for t in shapely.get_parts(shapely.constrained_delaunay_triangles(face)):
                xy = np.array(t.exterior.coords[:3])
                out.append(np.column_stack([xy, np.full(3, cut)]))
                who.append(item)
    if not out:
        return np.zeros((0, 3, 3)), np.zeros(0, int)
    return np.array(out), np.array(who)
