"""Automatic room placement for rooms that come without a rectangle.

Used by the mock LLM (which has no spatial sense) and by `derive` as a fallback when
a model leaves `rect` null. Rooms are packed into two rows per storey — public
rooms in the front (south) row, private rooms in the back row — east of whatever is
already placed on that storey, so the result is always a compact rectilinear plan.
"""

from __future__ import annotations

import math

from schemas.design import Rect, RoomDef

ROW_DEPTH = 5.0  # deep enough for a straight stair along a side wall
MIN_BAY, MAX_BAY = 3.0, 8.0
GARAGE = (6.0, 6.5)
PUBLIC = {"living", "kitchen", "dining", "office", "hall", "other", "utility", "storage"}


def _bay(rooms: list[RoomDef]) -> float:
    areas = [r.area for r in rooms if r.area]
    if not areas:
        return 4.0
    return min(MAX_BAY, max(MIN_BAY, sum(areas) / len(areas) / ROW_DEPTH))


def place_rooms(existing: list[Rect], rooms: list[RoomDef]) -> dict[str, Rect]:
    """Rectangles for `rooms`, laid out east of `existing` (rects already on the same storey)."""
    x = max((r[0] + r[2] for r in existing), key=float, default=0.0)
    y0 = min((r[1] for r in existing), default=0.0)
    out: dict[str, Rect] = {}
    garages = [r for r in rooms if r.kind == "garage"]
    rooms = [r for r in rooms if r.kind != "garage"]
    front = [r for r in rooms if r.kind in PUBLIC]
    back = [r for r in rooms if r.kind not in PUBLIC]
    cols = max(1, math.ceil(len(rooms) / 2))
    while len(front) > cols:
        back.append(front.pop())
    while len(back) > cols:
        front.append(back.pop())
    bay = round(_bay(rooms), 1) if rooms else 0.0
    for c in range(cols):
        f = front[c] if c < len(front) else None
        b = back[c] if c < len(back) else None
        if f and b:
            out[f.id] = (round(x + c * bay, 2), y0, bay, ROW_DEPTH)
            out[b.id] = (round(x + c * bay, 2), round(y0 + ROW_DEPTH, 2), bay, ROW_DEPTH)
        elif f or b:
            r = f or b
            out[r.id] = (round(x + c * bay, 2), y0, bay, 2 * ROW_DEPTH if (existing or cols > 1) else ROW_DEPTH * 1.5)
    x = round(x + cols * bay, 2)
    for g in garages:
        out[g.id] = (x, y0, GARAGE[0], GARAGE[1])
        x = round(x + GARAGE[0], 2)
    return out
