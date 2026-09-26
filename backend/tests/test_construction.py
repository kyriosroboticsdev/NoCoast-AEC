import time

import ifcopenshell

from core.construction import ConstructionJob, build_order
from ifc.builder import compile_ifc
from schemas.bim import Column, Door, Roof, Slab, Space, Wall, Window
from solver.layout import solve
from store.db import VersionData
from agents.template_planner import parse_program


def _version(spec, guids) -> VersionData:
    return VersionData(
        project_id="p", number=1, parent=None, prompt=None, mode="design", llm=None, notes=[],
        summary={}, ops=[], ifc_path="", created=0.0, spec=spec, program=None, guids=guids,
    )


def test_build_order_is_phase_grouped_and_covers_every_element():
    spec = solve(parse_program("two storey house with a kitchen, living room and two bedrooms, a garage and a front porch"))
    order = build_order(spec)

    assert {el.id for el in order} == {el.id for el in spec.elements}  # every element appears exactly once
    kinds = [type(el) for el in order]
    phase_of = {Slab: 0, Wall: 1, Column: 1, Roof: 2, Space: 3, Door: 4, Window: 4}
    phases = [phase_of[k] for k in kinds]
    assert phases == sorted(phases)  # foundation -> structure -> roof -> spaces -> details, never out of order


def test_construction_job_writes_one_valid_ifc_file_per_element_and_keeps_guids():
    spec = solve(parse_program("one storey cabin"))
    _, guids = compile_ifc(spec, {})
    job = ConstructionJob(_version(spec, guids), step_seconds=0.0)

    for _ in range(200):  # generous bound; a one-storey cabin has well under a hundred elements
        if job.done:
            break
        time.sleep(0.02)
    assert job.done and job.error is None
    assert job.total == len(spec.elements)
    assert len(job.urls) == job.total

    last_file = job._dir / f"step-{job.total - 1:04d}.ifc"
    model = ifcopenshell.open(str(last_file))
    # the last step has every element the final spec does, and the GlobalIds match the real compile
    final_model, _ = compile_ifc(spec, guids)
    tags = lambda m: sorted(p.Tag for p in m.by_type("IfcElement") if not p.is_a("IfcOpeningElement"))  # noqa: E731
    assert tags(model) == tags(final_model)
    wall = next(p for p in model.by_type("IfcWall"))
    final_wall = next(p for p in final_model.by_type("IfcWall") if p.Tag == wall.Tag)
    assert wall.GlobalId == final_wall.GlobalId

    first_file = job._dir / "step-0000.ifc"
    first_model = ifcopenshell.open(str(first_file))
    first_products = [p for p in first_model.by_type("IfcElement") if not p.is_a("IfcOpeningElement")]
    assert len(first_products) == 1
    assert first_products[0].is_a("IfcSlab")  # foundation goes up first
