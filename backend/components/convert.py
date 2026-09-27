"""An attached IFC file as a brick.

Every building element with geometry in the file is tessellated in world coordinates and metres
(IfcOpenShell converts the file's units), so IFC2X3, IFC4 and IFC4X3 files in any length unit come
out the same. The triangles are grouped by surface colour into `mesh` nodes, moved so the origin is
the centre of the base, and wrapped in a `Brick`: the file becomes one rigid asset that the model
places with a `brick` step like any other. The source elements' identities are not kept — the
component compiles to a single IFC element of the source's class (a proxy when the file mixes
classes) with the file name, schema, element count and names in its properties.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Callable, Iterable, Sequence

import ifcopenshell
import ifcopenshell.geom

from bricks import Brick, library
from bricks.geometry import bounds
from bricks.model import predefined_types
from components.attachment import IfcAttachment
from schemas.design import Design

MAX_PRODUCTS = 2000        # a component is a part, not a building
MAX_TRIANGLES = 60_000     # the mesh is stored with every version of the design
MAX_EXTENT = 60.0          # metres
MIN_EXTENT = 0.001
MAX_MESHES = 24            # colours beyond this join the nearest larger group
SKIP = ("IfcFeatureElement", "IfcVirtualElement")   # openings, projections, provisions
GREY = (0.8, 0.8, 0.8, 1.0)

Emit = Callable[[str, str, dict | None], None]


class ComponentError(ValueError):
    """The file cannot be used as a component; the message says why, in words a user can act on."""


def _slug(text: str, limit: int = 24) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:limit].strip("_") or "component"


def _colour(material) -> tuple[float, float, float, float]:
    try:
        d = material.diffuse
        rgb = (d.r(), d.g(), d.b())
        opacity = 1.0 - float(material.transparency or 0.0) if material.has_transparency() else 1.0
    except (AttributeError, RuntimeError, TypeError):
        return GREY
    if any(c != c for c in rgb):   # NaN: no colour set
        return GREY
    return (*[round(min(1.0, max(0.0, c)), 3) for c in rgb], round(min(1.0, max(0.05, opacity)), 2))


def _open(attachment: IfcAttachment) -> ifcopenshell.file:
    try:
        return ifcopenshell.file.from_string(attachment.raw.decode("latin-1"))
    except Exception as exc:  # noqa: BLE001 - IfcOpenShell raises its own error types on unparseable files
        raise ComponentError(f"'{attachment.name}' cannot be read as IFC: {exc}") from exc


def _identity(products: Sequence) -> tuple[str, str | None]:
    """IFC4 class and predefined type for the whole component."""
    classes = Counter(p.is_a() for p in products)
    if len(classes) == 1:
        cls = next(iter(classes))
        try:
            enum = predefined_types(cls)
        except Exception:  # noqa: BLE001 - not an IFC4 class (an IFC4X3 or IFC2X3-only entity)
            enum = None
            cls = ""
        if cls:
            given = getattr(products[0], "PredefinedType", None) if len(products) == 1 else None
            if enum and given in enum:
                return cls, given
            return cls, ("NOTDEFINED" if enum and "NOTDEFINED" in enum else "USERDEFINED" if enum else None)
    return "IfcBuildingElementProxy", "COMPLEX"


def to_brick(attachment: IfcAttachment, taken: Iterable[str] = ()) -> Brick:
    model = _open(attachment)
    products = [p for p in model.by_type("IfcElement") if p.Representation and not any(p.is_a(s) for s in SKIP)]
    if not products:
        raise ComponentError(f"'{attachment.name}' has no building elements with geometry")
    if len(products) > MAX_PRODUCTS:
        raise ComponentError(f"'{attachment.name}' has {len(products)} elements; a component may have {MAX_PRODUCTS}. "
                             "Open a whole building with Open IFC instead.")

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    groups: dict[tuple, dict] = {}       # colour -> {"index": {vertex: i}, "faces": [[a, b, c]]}
    triangles = 0
    drawn: list = []
    for product in products:
        try:
            shape = ifcopenshell.geom.create_shape(settings, product)
        except Exception:  # noqa: BLE001 - one element that does not tessellate should not lose the rest
            continue
        drawn.append(product)
        geo = shape.geometry
        verts, faces, ids = geo.verts, geo.faces, geo.material_ids
        colours = [_colour(m) for m in geo.materials]
        triangles += len(faces) // 3
        if triangles > MAX_TRIANGLES:
            raise ComponentError(f"'{attachment.name}' is too detailed: more than {MAX_TRIANGLES} triangles. "
                                 "Export it at a lower level of detail.")
        for t in range(len(faces) // 3):
            mid = ids[t] if t < len(ids) else -1
            group = groups.setdefault(colours[mid] if 0 <= mid < len(colours) else GREY, {"index": {}, "faces": []})
            tri = []
            for k in faces[3 * t:3 * t + 3]:
                v = (round(verts[3 * k], 4), round(verts[3 * k + 1], 4), round(verts[3 * k + 2], 4))
                tri.append(group["index"].setdefault(v, len(group["index"])))
            if len(set(tri)) == 3:     # rounding can collapse a sliver
                group["faces"].append(tri)
    groups = {c: g for c, g in groups.items() if g["faces"]}
    if not groups:
        raise ComponentError(f"'{attachment.name}': none of its {len(products)} elements has geometry that can be drawn")

    # Few, reasonably sized meshes: small colour groups join the largest one.
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]["faces"]))
    keep, merge = ranked[:MAX_MESHES], ranked[MAX_MESHES:]
    merge += [kv for kv in keep[1:] if len(kv[1]["faces"]) < 4 or len(kv[1]["index"]) < 4]
    keep = [kv for kv in keep if kv not in merge]
    main = keep[0][1]
    for _, g in merge:
        points = sorted(g["index"], key=g["index"].get)
        remap = [main["index"].setdefault(p, len(main["index"])) for p in points]
        main["faces"] += [[remap[i] for i in f] for f in g["faces"]]
    if len(main["faces"]) < 4 or len(main["index"]) < 4:
        raise ComponentError(f"'{attachment.name}' has too little geometry to be a solid object")

    xs, ys, zs = zip(*(p for _, g in keep for p in g["index"]))
    size = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    if max(size) > MAX_EXTENT:
        raise ComponentError(f"'{attachment.name}' is {size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} m; a component may be "
                             f"{MAX_EXTENT:g} m at most. Check the file's units.")
    if min(size) < MIN_EXTENT:
        raise ComponentError(f"'{attachment.name}' is flat: {size[0]:.3f} × {size[1]:.3f} × {size[2]:.3f} m")
    ox, oy, oz = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, min(zs)

    materials, geometry = {}, []
    for i, (colour, g) in enumerate(keep):
        key = f"m{i}"
        materials[key] = {"color": list(colour[:3]), "opacity": colour[3]}
        points = sorted(g["index"], key=g["index"].get)
        geometry.append({"shape": "mesh", "material": key, "faces": g["faces"],
                         "vertices": [[round(x - ox, 4), round(y - oy, 4), round(z - oz, 4)] for x, y, z in points]})

    stem = attachment.name.rsplit(".", 1)[0]
    taken = set(taken) | set(library().bricks)
    brick_id = f"{_slug(stem)}_{attachment.sha1[:6]}"
    if not brick_id[0].isalpha():
        brick_id = "c_" + brick_id
    if brick_id in taken:
        raise ComponentError(f"'{attachment.name}': the id {brick_id} is already used by a library brick")
    cls, predefined = _identity(drawn)
    counts = Counter(p.is_a() for p in drawn)
    names = "; ".join(dict.fromkeys(p.Name for p in drawn if p.Name))[:200]
    brick = Brick.model_validate({
        "id": brick_id,
        "name": re.sub(r"[_\-]+", " ", stem).strip()[:80] or "Component",
        "description": (f"Attached IFC file {attachment.name}: {len(drawn)} element(s) ({', '.join(f'{n} {c}' for c, n in counts.most_common(4))}), "
                        f"{size[0]:.2f} × {size[1]:.2f} × {size[2]:.2f} m. One rigid object; its origin is the centre of its base."),
        "tags": ["component", "attached"] + sorted({re.sub(r"(?<!^)(?=[A-Z])", " ", c[3:]).lower() for c in counts}),
        "ifc_class": cls, "predefined_type": predefined,
        "geometry": geometry, "materials": materials, "mount": "rest", "origin": [0.0, 0.0, 0.0], "elevation": 0.0,
        "properties": {"source_file": attachment.name, "source_schema": model.schema, "source_sha1": attachment.sha1,
                       "source_elements": float(len(drawn)), "source_names": names, "triangles": float(sum(len(g["faces"]) for _, g in keep))},
    })
    box = bounds(brick.solids(brick.resolve()))     # the same check an `asset` step makes: it evaluates to a real solid
    if not all(b > a for a, b in zip(box[:3], box[3:])):
        raise ComponentError(f"'{attachment.name}' did not produce a solid")
    return brick


def attach(design: Design, attachments: Sequence[IfcAttachment], emit: Emit | None = None) -> tuple[list[Brick], list[str]]:
    """Add every attached file to the design's own library (replacing the same file attached before).
    Returns the bricks that went in, and a message for each file that could not be used."""
    added: list[Brick] = []
    problems: list[str] = []
    for a in attachments:
        try:
            brick = to_brick(a)
        except ComponentError as exc:
            problems.append(str(exc))
            continue
        except ValueError as exc:     # the brick validators: a file that converts but is not a usable asset
            problems.append(f"'{a.name}' cannot be used as a component: {str(exc)[:300]}")
            continue
        design.library = [b for b in design.library if b.id != brick.id] + [brick]
        added.append(brick)
    if emit and (added or problems):
        emit("components", (f"{len(added)} IFC component(s) attached: " + ", ".join(f"{b.id} ({b.size_text()})" for b in added) if added
                            else "no usable IFC component") + (f"; {len(problems)} rejected" if problems else ""),
             {"components": [{"id": b.id, "name": b.name, "ifc_class": b.ifc_class, "size": b.size_text(),
                              "file": b.properties.get("source_file"), "elements": b.properties.get("source_elements"),
                              "triangles": b.properties.get("triangles")} for b in added],
              "rejected": problems})
    return added, problems


def component_lines(bricks: Sequence[Brick]) -> list[str]:
    """How the prompt names the attached components: what to place, by which id, how big."""
    return [f'{b.id}: "{b.name}" from {b.properties.get("source_file")}, {b.size_text()}, {b.ifc_class}' for b in bricks]
