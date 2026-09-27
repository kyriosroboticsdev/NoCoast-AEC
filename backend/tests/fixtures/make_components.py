"""Build small vendor-style component IFC files for tests: a kitchen island (two furnishing
elements) in millimetres as IFC4, and the same in metres as IFC2X3 (with owner history, as
Revit-style exports have). Placed away from the origin on purpose, like real exports."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.owner
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import ifcopenshell.util.shape_builder as shape_builder

PARTS = {  # name: (x, y, z, dx, dy, dz) in metres
    "Island base": (5.0, 3.0, 0.0, 1.8, 0.9, 0.85),
    "Island top": (4.95, 2.95, 0.85, 1.9, 1.0, 0.05),
}


def _owner(f: ifcopenshell.file) -> None:
    person = f.createIfcPerson(FamilyName="Vendor")
    org = f.createIfcOrganization(Name="Vendor Co")
    user = f.createIfcPersonAndOrganization(ThePerson=person, TheOrganization=org)
    app = f.createIfcApplication(org, "1.0", "Vendor CAD", "VCAD")
    ifcopenshell.api.owner.settings.get_user = lambda _f: user
    ifcopenshell.api.owner.settings.get_application = lambda _f: app


def make_island(path: Path, *, millimetres: bool = True, schema: str = "IFC4", name: str = "Kitchen island") -> Path:
    # IFC2X3 needs owner history; the api reads the user/application from module-level settings,
    # so set them for this file only and restore them, or every later model in the process breaks.
    saved = (ifcopenshell.api.owner.settings.get_user, ifcopenshell.api.owner.settings.get_application)
    try:
        return _make_island(path, millimetres=millimetres, schema=schema, name=name)
    finally:
        ifcopenshell.api.owner.settings.get_user, ifcopenshell.api.owner.settings.get_application = saved


def _make_island(path: Path, *, millimetres: bool, schema: str, name: str) -> Path:
    f = ifcopenshell.api.project.create_file(version=schema)
    if schema == "IFC2X3":
        _owner(f)
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name=name)
    ifcopenshell.api.unit.assign_unit(f, length={"is_metric": True, "raw": "MILLIMETERS" if millimetres else "METERS"})
    model = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body",
                                                target_view="MODEL_VIEW", parent=model)
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Building")
    storey = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Level 0")
    ifcopenshell.api.aggregate.assign_object(f, relating_object=project, products=[site])
    ifcopenshell.api.aggregate.assign_object(f, relating_object=site, products=[building])
    ifcopenshell.api.aggregate.assign_object(f, relating_object=building, products=[storey])
    scale = 1000.0 if millimetres else 1.0
    builder = shape_builder.ShapeBuilder(f)
    for part, (x, y, z, dx, dy, dz) in PARTS.items():
        el = ifcopenshell.api.root.create_entity(f, ifc_class="IfcFurnishingElement", name=part)
        rect = builder.rectangle(size=np.array([dx * scale, dy * scale]))
        rep = builder.get_representation(body, [builder.extrude(rect, magnitude=dz * scale)])
        ifcopenshell.api.geometry.assign_representation(f, product=el, representation=rep)
        matrix = np.eye(4)
        matrix[:3, 3] = [x * scale, y * scale, z * scale]
        ifcopenshell.api.geometry.edit_object_placement(f, product=el, matrix=matrix, is_si=False)
        ifcopenshell.api.spatial.assign_container(f, relating_structure=storey, products=[el])
    path.parent.mkdir(parents=True, exist_ok=True)
    f.write(str(path))
    return path
