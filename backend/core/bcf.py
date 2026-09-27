"""BCF 2.1 export of the design review, so the issues open in Revit, Solibri, BIMcollab, Navisworks or
any other BCF-aware tool, attached to the right elements.

Each failing or to-review check becomes one topic. Its viewpoint selects the elements the check
names by their IFC GlobalIds (which are stable across versions, see core/guids.py) and frames them
with a perspective camera from the south-west, the same way the NoCoast viewer does.
"""

from __future__ import annotations

import io
import math
import uuid
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from core.guids import key_for_element
from schemas.bim import BuildingSpec

PRIORITY = {"fail": "High", "warn": "Normal"}


def _point(spec: BuildingSpec, element_id: str) -> tuple[float, float, float] | None:
    levels = {l.id: l for l in spec.levels}
    walls = {e.id: e for e in spec.elements if e.type == "wall"}
    for e in spec.elements:
        if e.id != element_id:
            continue
        level = levels.get(getattr(e, "level", None) or "")
        z = (level.elevation or 0) + 1.2 if level else 1.2
        if getattr(e, "outline", None):
            xs, ys = [p[0] for p in e.outline], [p[1] for p in e.outline]
            return (sum(xs) / len(xs), sum(ys) / len(ys), z)
        if getattr(e, "position", None) is not None:
            return (e.position[0], e.position[1], z)
        if e.type in ("door", "window") and e.wall in walls:
            wall = walls[e.wall]
            (x, y), _ = wall.frame_at(e.offset + e.width / 2)
            lvl = levels.get(wall.level)
            return (x, y, (lvl.elevation or 0) + 1.2 if lvl else 1.2)
        if e.type == "wall":
            (x, y), _ = e.frame_at(e.length / 2)
            return (x, y, z)
    level = levels.get(element_id)
    if level is not None:
        pts = [p for e in spec.elements if getattr(e, "level", None) == element_id for p in (getattr(e, "outline", None) or [])]
        if pts:
            return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), (level.elevation or 0) + 1.2)
    return None


def _camera(points: list[tuple[float, float, float]]) -> tuple[tuple, tuple]:
    if not points:
        points = [(0.0, 0.0, 1.2)]
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    cz = sum(p[2] for p in points) / len(points)
    spread = max([math.dist(p[:2], (cx, cy)) for p in points] + [3.0])
    d = spread * 2.2 + 6
    eye = (cx - d * 0.6, cy - d * 0.6, cz + d * 0.55)
    dx, dy, dz = cx - eye[0], cy - eye[1], cz - eye[2]
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    return eye, (dx / n, dy / n, dz / n)


def _xyz(tag: str, v: tuple) -> str:
    return f"<{tag}><X>{v[0]:.4f}</X><Y>{v[1]:.4f}</Y><Z>{v[2]:.4f}</Z></{tag}>"


def bcf(spec: BuildingSpec, guids: dict, checks: list[dict], ifc_name: str, project_name: str,
        author: str = "NoCoast design review", statuses: tuple[str, ...] = ("fail", "warn")) -> bytes:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    project_guid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nocoast:{guids.get('project', project_name)}"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bcf.version", '<?xml version="1.0" encoding="UTF-8"?>\n<Version VersionId="2.1">'
                                   "<DetailedVersion>2.1</DetailedVersion></Version>\n")
        zf.writestr("project.bcfp", f'<?xml version="1.0" encoding="UTF-8"?>\n<ProjectExtension>'
                                    f'<Project ProjectId="{project_guid}"><Name>{escape(project_name)}</Name></Project>'
                                    f"<ExtensionSchema></ExtensionSchema></ProjectExtension>\n")
        for i, check in enumerate(c for c in checks if c.get("status") in statuses):
            topic = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{project_guid}:{check['id']}"))
            vp = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{topic}:viewpoint"))
            comment = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{topic}:comment"))
            ifc_guids = [guids[key_for_element(e)] for e in check.get("elements", []) if key_for_element(e) in guids]
            points = [p for p in (_point(spec, e) for e in check.get("elements", [])) if p]
            eye, direction = _camera(points)
            description = (f"{check['detail']} Measured: {check['value']}. Required: {check['target']}. "
                           f"Reference: {check['reference']}.")
            markup = [
                '<?xml version="1.0" encoding="UTF-8"?>', "<Markup>",
                f'<Header><File IfcProject="{guids.get("project", "")}" isExternal="true">'
                f"<Filename>{escape(ifc_name)}</Filename><Date>{now}</Date></File></Header>",
                f'<Topic Guid="{topic}" TopicType="{"Error" if check["status"] == "fail" else "Warning"}" TopicStatus="Open">',
                f"<Title>{escape(check['reference'] + ' — ' + check['title'])}</Title>",
                f"<Priority>{PRIORITY.get(check['status'], 'Normal')}</Priority>", f"<Index>{i + 1}</Index>",
                f"<Labels>{escape(check['category'])}</Labels>", f"<CreationDate>{now}</CreationDate>",
                f"<CreationAuthor>{escape(author)}</CreationAuthor>", "<Stage>Design review</Stage>",
                f"<Description>{escape(description)}</Description>", "</Topic>",
            ]
            if check.get("advice"):
                markup += [f'<Comment Guid="{comment}"><Date>{now}</Date><Author>{escape(author)}</Author>'
                           f"<Comment>{escape(check['advice'])}</Comment><Viewpoint Guid=\"{vp}\"/></Comment>"]
            markup += [f'<Viewpoints Guid="{vp}"><Viewpoint>viewpoint.bcfv</Viewpoint></Viewpoints>', "</Markup>"]
            zf.writestr(f"{topic}/markup.bcf", "\n".join(markup) + "\n")
            selection = "".join(f'<Component IfcGuid="{g}"/>' for g in ifc_guids)
            view = ['<?xml version="1.0" encoding="UTF-8"?>', f'<VisualizationInfo Guid="{vp}">',
                    "<Components>" + (f"<Selection>{selection}</Selection>" if selection else "") +
                    '<Visibility DefaultVisibility="true"/></Components>',
                    "<PerspectiveCamera>" + _xyz("CameraViewPoint", eye) + _xyz("CameraDirection", direction) +
                    _xyz("CameraUpVector", (0, 0, 1)) + "<FieldOfView>60</FieldOfView></PerspectiveCamera>",
                    "</VisualizationInfo>"]
            zf.writestr(f"{topic}/viewpoint.bcfv", "\n".join(view) + "\n")
    return buf.getvalue()
