"""A tiny vector canvas that renders to SVG and to PDF, with no dependencies.

Drawing sheets are built once as a display list in sheet millimetres (origin top-left, y down) and
then written out either as an SVG (for the browser) or as pages of one PDF (for the drawing set a
reviewer prints or marks up). The PDF writer covers only what the sheets use — lines, filled
polygons, circles and Helvetica text — which is why it fits in a page of code.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field
from html import escape

Pt = tuple[float, float]
MM = 72 / 25.4


@dataclass
class Canvas:
    width: float = 420.0
    height: float = 297.0
    items: list[tuple] = field(default_factory=list)

    def line(self, a: Pt, b: Pt, w: float = 0.25, color: str = "#000", dash: tuple[float, ...] | None = None) -> None:
        self.items.append(("path", [a, b], None, color, w, dash, False))

    def polyline(self, pts: list[Pt], w: float = 0.25, color: str = "#000", dash=None, closed: bool = False) -> None:
        if len(pts) >= 2:
            self.items.append(("path", list(pts), None, color, w, dash, closed))

    def polygon(self, pts: list[Pt], fill: str | None = None, stroke: str | None = None, w: float = 0.25,
                dash=None) -> None:
        if len(pts) >= 3:
            self.items.append(("path", list(pts), fill, stroke, w, dash, True))

    def shape(self, rings: list[list[Pt]], fill: str | None = None, stroke: str | None = None, w: float = 0.25) -> None:
        """A filled region with holes (even-odd), e.g. the union of a storey's walls."""
        rings = [list(r) for r in rings if len(r) >= 3]
        if rings:
            self.items.append(("shape", rings, fill, stroke, w))

    def rect(self, x: float, y: float, w: float, h: float, fill: str | None = None, stroke: str | None = "#000",
             lw: float = 0.25, dash=None) -> None:
        self.polygon([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], fill, stroke, lw, dash)

    def circle(self, c: Pt, r: float, fill: str | None = None, stroke: str | None = "#000", w: float = 0.25) -> None:
        self.items.append(("circle", c, r, fill, stroke, w))

    def arc(self, c: Pt, r: float, a0: float, a1: float, w: float = 0.18, color: str = "#000", dash=None) -> None:
        n = max(6, int(abs(a1 - a0) / (math.pi / 24)))
        pts = [(c[0] + r * math.cos(a0 + (a1 - a0) * i / n), c[1] + r * math.sin(a0 + (a1 - a0) * i / n))
               for i in range(n + 1)]
        self.polyline(pts, w, color, dash)

    def text(self, p: Pt, s: str, size: float = 2.5, bold: bool = False, anchor: str = "start",
             color: str = "#000", angle: float = 0.0) -> None:
        if s:
            self.items.append(("text", p, str(s), size, bold, anchor, color, angle))

    # --- output -----------------------------------------------------------

    def svg(self) -> str:
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width:g} {self.height:g}" '
               f'width="{self.width:g}mm" height="{self.height:g}mm" font-family="Helvetica, Arial, sans-serif">',
               f'<rect width="{self.width:g}" height="{self.height:g}" fill="#fff"/>']
        for item in self.items:
            kind = item[0]
            if kind == "path":
                _, pts, fill, stroke, w, dash, closed = item
                d = "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in pts) + (" Z" if closed else "")
                out.append(f'<path d="{d}" fill="{fill or "none"}"' + (
                    f' stroke="{stroke}" stroke-width="{w:g}" stroke-linejoin="round"' if stroke else "") + (
                    f' stroke-dasharray="{" ".join(f"{v:g}" for v in dash)}"' if dash and stroke else "") + "/>")
            elif kind == "shape":
                _, rings, fill, stroke, w = item
                d = " ".join("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in ring) + " Z" for ring in rings)
                out.append(f'<path d="{d}" fill="{fill or "none"}" fill-rule="evenodd"' + (
                    f' stroke="{stroke}" stroke-width="{w:g}" stroke-linejoin="round"' if stroke else "") + "/>")
            elif kind == "circle":
                _, (cx, cy), r, fill, stroke, w = item
                out.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill or "none"}"' +
                           (f' stroke="{stroke}" stroke-width="{w:g}"' if stroke else "") + "/>")
            else:
                _, (x, y), s, size, bold, anchor, color, angle = item
                rot = f' transform="rotate({-angle:g} {x:.2f} {y:.2f})"' if angle else ""
                weight = ' font-weight="bold"' if bold else ""
                out.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size:g}" fill="{color}"{weight} '
                           f'text-anchor="{_ANCHOR[anchor]}"{rot}>{escape(s)}</text>')
        out.append("</svg>")
        return "\n".join(out)

    def pdf_ops(self) -> bytes:
        H = self.height
        ops: list[str] = ["1 J 1 j"]

        def P(x: float, y: float) -> str:
            return f"{x * MM:.2f} {(H - y) * MM:.2f}"

        for item in self.items:
            kind = item[0]
            if kind == "path":
                _, pts, fill, stroke, w, dash, closed = item
                path = f"{P(*pts[0])} m " + " ".join(f"{P(*p)} l" for p in pts[1:]) + (" h" if closed else "")
                ops.append(_style(fill, stroke, w, dash) + " " + path + " " + _paint(fill, stroke))
            elif kind == "shape":
                _, rings, fill, stroke, w = item
                path = " ".join(f"{P(*r[0])} m " + " ".join(f"{P(*p)} l" for p in r[1:]) + " h" for r in rings)
                paint = _paint(fill, stroke)
                ops.append(_style(fill, stroke, w, None) + " " + path + " " + (paint + "*" if paint in ("f", "B") else paint))
            elif kind == "circle":
                _, (cx, cy), r, fill, stroke, w = item
                k = 0.5523 * r
                c = [(cx + r, cy), (cx + r, cy + k, cx + k, cy + r, cx, cy + r),
                     (cx - k, cy + r, cx - r, cy + k, cx - r, cy), (cx - r, cy - k, cx - k, cy - r, cx, cy - r),
                     (cx + k, cy - r, cx + r, cy - k, cx + r, cy)]
                path = f"{P(*c[0])} m " + " ".join(
                    f"{P(s[0], s[1])} {P(s[2], s[3])} {P(s[4], s[5])} c" for s in c[1:]) + " h"
                ops.append(_style(fill, stroke, w, None) + " " + path + " " + _paint(fill, stroke))
            else:
                _, (x, y), s, size, bold, anchor, color, angle = item
                text = _pdf_text(s)
                width = text_width(s, size, bold)
                shift = {"start": 0.0, "middle": width / 2, "end": width}[anchor]
                a = math.radians(angle)
                ca, sa = math.cos(a), math.sin(a)
                tx, ty = x - shift * ca, y + shift * sa
                ops.append(f"BT {_rgb(color)} rg /{'F2' if bold else 'F1'} {size * MM * 1.0:.2f} Tf "
                           f"{ca:.4f} {sa:.4f} {-sa:.4f} {ca:.4f} {P(tx, ty)} Tm ({text}) Tj ET")
        return "\n".join(ops).encode("latin-1")


_ANCHOR = {"start": "start", "middle": "middle", "end": "end"}


def _rgb(color: str) -> str:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return f"{r:.3f} {g:.3f} {b:.3f}"


def _style(fill, stroke, w, dash) -> str:
    parts = []
    if fill:
        parts.append(f"{_rgb(fill)} rg")
    if stroke:
        parts.append(f"{_rgb(stroke)} RG {w * MM:.2f} w")
        parts.append(f"[{' '.join(f'{v * MM:.2f}' for v in dash)}] 0 d" if dash else "[] 0 d")
    return " ".join(parts)


def _paint(fill, stroke) -> str:
    return "B" if fill and stroke else "f" if fill else "S" if stroke else "n"


_SUBS = {"≥": ">=", "≤": "<=", "→": "->", "←": "<-", "✓": "", "⚠": "!", "✕": "x", "−": "-", "…": "...", "′": "'",
         "″": '"', "Ø": "O", "\u2009": " ", "\u202f": " "}


def _pdf_text(s: str) -> str:
    for a, b in _SUBS.items():
        s = s.replace(a, b)
    raw = s.encode("cp1252", errors="replace").decode("latin-1")
    return raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_width(s: str, size: float, bold: bool = False) -> float:
    """Approximate Helvetica advance width, in the same units as `size`."""
    total = 0.0
    for ch in s:
        if ch in " ":
            total += 0.278
        elif ch in "il.,:;'|!":
            total += 0.24
        elif ch in "fjtr()[]-":
            total += 0.33
        elif ch.isdigit():
            total += 0.556
        elif ch in "MW":
            total += 0.85
        elif ch.isupper():
            total += 0.68
        else:
            total += 0.53
    return total * size * (1.06 if bold else 1.0)


def pdf(pages: list[Canvas], title: str = "Drawings") -> bytes:
    """Write canvases as the pages of one PDF."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")
    pages_id = add(b"")
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    for page in pages:
        data = zlib.compress(page.pdf_ops())
        content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
        kids.append(add((f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {page.width * MM:.2f} "
                         f"{page.height * MM:.2f}] /Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> "
                         f"/Contents {content} 0 R >>").encode()))
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    objects[pages_id - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                             f"/Count {len(kids)} >>").encode()
    info = add(f"<< /Title ({_pdf_text(title)}) /Producer (NoCoast AEC) >>".encode("latin-1"))
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)
