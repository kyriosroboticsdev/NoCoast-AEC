"""A small software rasterizer: plane clipping, a z-buffered triangle fill with an element-id buffer,
outlines, and text and lines drawn over the result. Pure numpy, so it runs headless anywhere."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from render.font import text_mask


def clip(tris: np.ndarray, normal: np.ndarray, offset: float) -> tuple[np.ndarray, np.ndarray]:
    """Keep the part of each triangle where dot(p, normal) >= offset. Returns the new triangles and,
    for each, the index of the triangle it came from (one triangle can become two)."""
    side = tris @ normal - offset                    # (n, 3)
    inside = side >= 0
    count = inside.sum(1)
    keep = np.flatnonzero(count == 3)
    out, src = [tris[keep]], [keep]
    for i in np.flatnonzero((count == 1) | (count == 2)):
        poly = []
        for k in range(3):
            a, b, da, db = tris[i, k], tris[i, (k + 1) % 3], side[i, k], side[i, (k + 1) % 3]
            if da >= 0:
                poly.append(a)
            if (da >= 0) != (db >= 0):
                poly.append(a + (b - a) * (da / (da - db)))
        for j in range(1, len(poly) - 1):
            out.append(np.array([[poly[0], poly[j], poly[j + 1]]]))
            src.append(np.array([i]))
    return np.concatenate(out), np.concatenate(src)


@dataclass
class Buffers:
    rgb: np.ndarray     # (h, w, 3) float 0..1
    ids: np.ndarray     # (h, w) int, -1 = background
    depth: np.ndarray   # (h, w) float, smaller = nearer, inf = background


def rasterize(screen: np.ndarray, colors: np.ndarray, ids: np.ndarray, width: int, height: int, background: np.ndarray) -> Buffers:
    """`screen` is (n, 3, 3): pixel x, pixel y (down), and a depth key that interpolates linearly on screen."""
    buf = Buffers(background.copy(), np.full((height, width), -1, int), np.full((height, width), np.inf))
    for (p0, p1, p2), color, ident in zip(screen, colors, ids):
        x0, x1 = max(int(np.floor(min(p0[0], p1[0], p2[0]))), 0), min(int(np.ceil(max(p0[0], p1[0], p2[0]))), width - 1)
        y0, y1 = max(int(np.floor(min(p0[1], p1[1], p2[1]))), 0), min(int(np.ceil(max(p0[1], p1[1], p2[1]))), height - 1)
        if x0 > x1 or y0 > y1:
            continue
        area = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0])
        if abs(area) < 1e-9:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((p1[0] - xs) * (p2[1] - ys) - (p1[1] - ys) * (p2[0] - xs)) / area
        w1 = ((p2[0] - xs) * (p0[1] - ys) - (p2[1] - ys) * (p0[0] - xs)) / area
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        z = w0 * p0[2] + w1 * p1[2] + w2 * p2[2]
        depth = buf.depth[y0:y1 + 1, x0:x1 + 1]
        hit = inside & (z < depth)
        if hit.any():
            depth[hit] = z[hit]
            buf.rgb[y0:y1 + 1, x0:x1 + 1][hit] = color
            buf.ids[y0:y1 + 1, x0:x1 + 1][hit] = ident
    return buf


def overlay(buf: Buffers, top: Buffers) -> None:
    """Paint every pixel `top` drew over `buf`."""
    drawn = np.isfinite(top.depth)
    buf.rgb[drawn], buf.ids[drawn], buf.depth[drawn] = top.rgb[drawn], top.ids[drawn], top.depth[drawn]


def outline(buf: Buffers, strength: float = 0.45) -> None:
    """Darken pixels on element boundaries and depth steps, so parts read as separate shapes."""
    edge = np.zeros(buf.ids.shape, bool)
    for axis in (0, 1):
        ids_a, ids_b = np.moveaxis(buf.ids, axis, 0)[:-1], np.moveaxis(buf.ids, axis, 0)[1:]
        d_a, d_b = np.moveaxis(buf.depth, axis, 0)[:-1], np.moveaxis(buf.depth, axis, 0)[1:]
        finite = np.isfinite(d_a) & np.isfinite(d_b)
        gap = np.zeros(finite.shape)
        gap[finite] = np.abs(d_a[finite] - d_b[finite]) / np.maximum(np.abs(d_a[finite]), 1e-6)
        # Coplanar faces of different elements z-fight; only a real depth step between them is an edge.
        diff = (gap > 0.02) | ((ids_a != ids_b) & ((gap > 0.002) | ~finite))
        np.moveaxis(edge, axis, 0)[:-1] |= diff
    buf.rgb[edge] *= strength


def silhouette(rgb: np.ndarray, mask: np.ndarray, color: np.ndarray, width: int = 2) -> None:
    """Draw the inner boundary of `mask`, `width` pixels thick, in `color`."""
    inner = mask.copy()
    for _ in range(width):
        shrunk = inner.copy()
        shrunk[1:] &= inner[:-1]
        shrunk[:-1] &= inner[1:]
        shrunk[:, 1:] &= inner[:, :-1]
        shrunk[:, :-1] &= inner[:, 1:]
        inner = shrunk
    rgb[mask & ~inner] = color


def box_free(taken: list[tuple[int, int, int, int]], box: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = box
    return all(x1 < a or x0 > c or y1 < b or y0 > d for a, b, c, d in taken)


def draw_label(rgb: np.ndarray, text: str, cx: float, cy: float, taken: list[tuple[int, int, int, int]], scale: int = 2) -> bool:
    """Dark text on a pale box centred on (cx, cy); skipped (False) if it would overlap a placed label or leave the image."""
    mask = text_mask(text, scale)
    h, w = mask.shape
    pad = scale
    x0, y0 = int(round(cx - w / 2)) - pad, int(round(cy - h / 2)) - pad
    x1, y1 = x0 + w + 2 * pad, y0 + h + 2 * pad
    height, width, _ = rgb.shape
    if x0 < 0 or y0 < 0 or x1 >= width or y1 >= height or not box_free(taken, (x0, y0, x1, y1)):
        return False
    taken.append((x0, y0, x1, y1))
    region = rgb[y0:y1, x0:x1]
    region[:] = region * 0.25 + 0.75
    region[pad:pad + h, pad:pad + w][mask] = (0.08, 0.08, 0.1)
    return True


def draw_line(rgb: np.ndarray, a: tuple[float, float], b: tuple[float, float], color: tuple[float, float, float], width: int = 2) -> None:
    n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
    xs = np.linspace(a[0], b[0], n).round().astype(int)
    ys = np.linspace(a[1], b[1], n).round().astype(int)
    h, w, _ = rgb.shape
    for dx in range(width):
        for dy in range(width):
            ok = (xs + dx >= 0) & (xs + dx < w) & (ys + dy >= 0) & (ys + dy < h)
            rgb[ys[ok] + dy, xs[ok] + dx] = color
