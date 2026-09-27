"""Screenshots of a compiled model from a camera the model chooses (schemas/look.py::View).

    scene_of(ifc, guids) ─► render(scene, view) ─► Shot: PNG + which elements are visible, by share of the frame

Flat-shaded with outlines, element ids labelled where they are seen, room ids on their floors, a
north arrow, and optional section cuts, so a vision model can check what it built and name what to fix.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from render.caps import caps
from render.png import encode_png
from render.raster import Buffers, clip, draw_label, draw_line, outline, overlay, rasterize, silhouette
from render.scene import Scene, scene_of
from schemas.look import View

WIDTH, HEIGHT = 1024, 768
PLAN_CUT = 1.5
GROUND = -2
GROUND_COLOR = np.array((0.80, 0.84, 0.76))
CAP_COLOR = np.array((0.30, 0.30, 0.33))
HIGHLIGHT = np.array((1.0, 0.55, 0.1))
HIGHLIGHT_MIX = 0.3
SUN = np.array((0.5, -0.4, 0.75)) / np.linalg.norm((0.5, -0.4, 0.75))
NEAR = 0.05
MAX_LABELS = 30
MAX_VISIBLE = 40
UNLABELLED = ("IfcWall", "IfcSlab", "IfcRoof", "IfcCovering", "IfcRailing", "IfcMember", "IfcPlate", "IfcWindow", "IfcDoor")

__all__ = ["HEIGHT", "WIDTH", "Scene", "Shot", "ViewError", "render", "scene_of"]


class ViewError(ValueError):
    """The view cannot be taken (unknown target or level, nothing left to show); the message is for the model."""


@dataclass
class Shot:
    png: bytes
    view: View
    visible: list[tuple[str, float]]    # (element id, share of the frame in %), largest first
    width: int
    height: int

    def caption(self) -> str:
        seen = ", ".join(f"{i} {p:.1f}%" for i, p in self.visible) or "nothing"
        through = " (highlighted in orange, drawn through whatever stands in front of it)" if self.view.target else ""
        return f"view of {self.view.describe()}{through}; visible: {seen}"


@dataclass(frozen=True)
class Camera:
    eye: np.ndarray
    right: np.ndarray
    up: np.ndarray
    forward: np.ndarray
    ortho: bool
    scale: float    # perspective: focal length in pixels; ortho: pixels per metre
    near: float     # nothing nearer than this along the view direction is drawn

    def to_camera(self, pts: np.ndarray) -> np.ndarray:
        rel = pts - self.eye
        return np.stack([rel @ self.right, rel @ self.up, rel @ self.forward], -1)

    def project(self, cam: np.ndarray, width: int, height: int) -> np.ndarray:
        x, y, d = cam[..., 0], cam[..., 1], cam[..., 2]
        if self.ortho:
            return np.stack([width / 2 + self.scale * x, height / 2 - self.scale * y, d], -1)
        return np.stack([width / 2 + self.scale * x / d, height / 2 - self.scale * y / d, -1 / d], -1)

    def distance(self, key: float) -> float:
        """A depth-buffer key back to metres along the view direction."""
        return key if self.ortho else -1 / key



def _hidden(scene: Scene, view: View) -> np.ndarray:
    """Per item: hidden by `hide` or by being on a level above `level`."""
    hide = {h.lower() for h in view.hide}
    floor = scene.levels[view.level] if view.level else None
    out = []
    for it in scene.items:
        above = floor is not None and it.level is not None and scene.levels.get(it.level, floor) > floor + 1e-6
        out.append(above or it.id.lower() in hide or it.ifc_class.lower() in hide
                   or any(it.ifc_class.lower().startswith(h) for h in hide if h.startswith("ifc")))
    return np.array(out, bool)


def _camera(view: View, lo: np.ndarray, hi: np.ndarray, width: int, height: int) -> Camera:
    center = np.array(view.look_at) if view.look_at else (lo + hi) / 2
    radius = max(float(np.linalg.norm(hi - lo)) / 2, 0.3)
    fov = math.radians(view.fov)
    az, el = math.radians(view.azimuth), math.radians(view.elevation)
    away = np.array((math.sin(az), math.cos(az), 0.0))
    if view.position:
        eye = np.array(view.position)
        if np.linalg.norm(center - eye) < 1e-6:
            raise ViewError("the camera position is the point it looks at; move it or aim elsewhere")
        forward = (center - eye) / np.linalg.norm(center - eye)
        ortho = bool(view.ortho)
        top = np.array((0.0, 1.0, 0.0))
    else:
        direction = np.array((math.cos(el) * away[0], math.cos(el) * away[1], math.sin(el)))
        ortho = view.ortho if view.ortho is not None else view.elevation >= 85
        dist = view.distance or (radius * 4 + 20 if ortho else radius / math.sin(fov / 2) * 1.08)
        eye = center + direction * dist
        forward = -direction
        top = -away
    up_hint = top if abs(forward[2]) > 0.99 else np.array((0.0, 0.0, 1.0))
    right = np.cross(forward, up_hint)
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    if ortho and view.distance is None:
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) - center
        xs, ys = corners @ right, corners @ up
        span_x, span_y = max(xs.max() - xs.min(), 0.1), max(ys.max() - ys.min(), 0.1)
        scale = min(width / span_x, height / span_y) / 1.12
        if not view.look_at:
            eye = eye + right * (xs.max() + xs.min()) / 2 + up * (ys.max() + ys.min()) / 2
    elif ortho:
        scale = (min(width, height) / 2) / (view.distance * math.tan(fov / 2))
    else:
        scale = (height / 2) / math.tan(fov / 2)
    near = NEAR
    if view.target and not view.position:
        # Whatever stands between the camera and its target is cut away, so the target is always seen.
        depth = float(np.abs(forward) @ ((hi - lo) / 2))
        near = max(NEAR, float(np.dot((lo + hi) / 2 - eye, forward)) - depth - 0.05)
    return Camera(eye, right, up, forward, ortho, scale, near)


def _ground(lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    pad = max(8.0, 0.6 * float(max(hi[0] - lo[0], hi[1] - lo[1])))
    x0, y0, x1, y1, z = lo[0] - pad, lo[1] - pad, hi[0] + pad, hi[1] + pad, -0.002
    return np.array([[[x0, y0, z], [x1, y0, z], [x1, y1, z]], [[x0, y0, z], [x1, y1, z], [x0, y1, z]]])


def _background(width: int, height: int) -> np.ndarray:
    t = np.linspace(0, 1, height)[:, None, None]
    return np.broadcast_to((1 - t) * np.array((0.78, 0.85, 0.93)) + t * np.array((0.96, 0.97, 0.98)), (height, width, 3)).copy()


def _x_ray(scene: Scene, view: View, screen: np.ndarray, shade: np.ndarray, owner: np.ndarray, width: int, height: int) -> Buffers | None:
    """A targeted element drawn on its own, to paint over whatever stands in front of it."""
    if not view.target:
        return None
    key = view.target.lower()
    mine = np.isin(owner, [i for i, it in enumerate(scene.items) if it.id.lower() == key])
    if not mine.any():
        return None
    return rasterize(screen[mine], shade[mine], owner[mine], width, height, np.zeros((height, width, 3)))


def render(scene: Scene, view: View, width: int = WIDTH, height: int = HEIGHT) -> Shot:
    if view.level and view.level not in scene.levels:
        raise ViewError(f"unknown level '{view.level}' (levels: {', '.join(scene.levels) or 'none'})")
    cut = view.cut if view.cut is not None else (scene.levels[view.level] + PLAN_CUT if view.level else None)
    hidden = _hidden(scene, view)
    shown = ~hidden[scene.owner] if len(scene.owner) else np.zeros(0, bool)
    tris, colors, owner = scene.tris[shown], scene.colors[shown], scene.owner[shown]

    if cut is not None and len(tris):
        cap_tris, cap_owner = caps(tris, owner, cut)
        tris, src = clip(tris, np.array((0.0, 0.0, -1.0)), -cut)
        tris = np.concatenate([tris, cap_tris])
        colors = np.concatenate([colors[src], np.tile(CAP_COLOR, (len(cap_tris), 1))])
        owner = np.concatenate([owner[src], cap_owner])

    if view.target:
        box = scene.find(view.target)
        if box is None:
            known = [r.id for r in scene.rooms] + [it.id for it, off in zip(scene.items, hidden) if not off]
            raise ViewError(f"nothing called '{view.target}' in the model (e.g. {', '.join(known[:40])})")
        lo, hi = box
    elif len(tris):
        pts = tris.reshape(-1, 3)
        lo, hi = pts.min(0), pts.max(0)
    else:
        raise ViewError("nothing left to show: everything is hidden or cut away")
    if cut is not None:
        hi = np.array((hi[0], hi[1], max(min(hi[2], cut), lo[2] + 0.1)))
    cam = _camera(view, lo, hi, width, height)

    if "ground" not in {h.lower() for h in view.hide}:
        ground_box = (tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)) if len(tris) else (lo, hi)
        g = _ground(*ground_box)
        tris = np.concatenate([tris, g])
        colors = np.concatenate([colors, np.tile(GROUND_COLOR, (2, 1))])
        owner = np.concatenate([owner, [GROUND, GROUND]])

    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    light = 0.38 + 0.37 * np.abs(normals @ SUN) + 0.25 * np.abs(normals @ cam.forward)
    shade = np.clip(colors * light[:, None], 0, 1)

    cam_tris, src = clip(cam.to_camera(tris), np.array((0.0, 0.0, 1.0)), cam.near)
    screen = cam.project(cam_tris, width, height)
    buf = rasterize(screen, shade[src], owner[src], width, height, _background(width, height))
    target = _x_ray(scene, view, screen, shade[src], owner[src], width, height)
    if target is not None:
        drawn = np.isfinite(target.depth)
        target.rgb[drawn] = target.rgb[drawn] * (1 - HIGHLIGHT_MIX) + HIGHLIGHT * HIGHLIGHT_MIX
        overlay(buf, target)
    outline(buf)
    if target is not None:
        silhouette(buf.rgb, np.isfinite(target.depth), HIGHLIGHT * 0.6)

    total = width * height
    drawn = buf.ids >= 0
    counts = np.bincount(buf.ids[drawn], minlength=len(scene.items)) if drawn.any() else np.zeros(len(scene.items), int)
    order = np.argsort(-counts)
    visible = [(scene.items[i].id, 100 * counts[i] / total) for i in order if counts[i] and 100 * counts[i] / total >= 0.05][:MAX_VISIBLE]

    taken: list[tuple[int, int, int, int]] = []
    in_front = 2.0 if cut is not None else 0.3   # a plan only keeps what is below the cut, so furniture may cover the floor
    for room in scene.rooms:
        if cut is not None and room.bounds[2] >= cut:
            continue
        floor = np.array(((room.bounds[0] + room.bounds[3]) / 2, (room.bounds[1] + room.bounds[4]) / 2, room.bounds[2] + 0.05))
        c = cam.to_camera(floor[None])[0]
        if c[2] <= cam.near:
            continue
        px, py, _ = cam.project(c[None], width, height)[0]
        ix, iy = int(px), int(py)
        if 0 <= ix < width and 0 <= iy < height and np.isfinite(buf.depth[iy, ix]) and cam.distance(buf.depth[iy, ix]) >= c[2] - in_front:
            draw_label(buf.rgb, room.id, px, py, taken, scale=3)
    if drawn.any():
        ys, xs = np.nonzero(drawn)
        idx = buf.ids[drawn]
        sx, sy = np.bincount(idx, xs, len(scene.items)), np.bincount(idx, ys, len(scene.items))
        least = max(250, int(0.0005 * total))
        labelled = 0
        for i in order:
            if counts[i] < least or labelled >= MAX_LABELS:
                break
            if not scene.items[i].ifc_class.startswith(UNLABELLED):
                labelled += draw_label(buf.rgb, scene.items[i].id[:24], sx[i] / counts[i], sy[i] / counts[i], taken)

    north = np.array((cam.right[1], -cam.up[1]))
    if np.linalg.norm(north) > 0.05:
        north /= np.linalg.norm(north)
        base = np.array((width - 44.0, 44.0))
        draw_line(buf.rgb, tuple(base - north * 18), tuple(base + north * 18), (0.75, 0.1, 0.1), 3)
        draw_label(buf.rgb, "N", *(base + north * 30), taken)

    rgb = (np.clip(buf.rgb, 0, 1) * 255).astype(np.uint8)
    return Shot(encode_png(rgb), view, visible, width, height)
