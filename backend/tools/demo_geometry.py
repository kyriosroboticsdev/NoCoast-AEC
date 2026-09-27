"""Drive the new vocabulary end to end and write real IFC files.

    python tools/demo_geometry.py [output_dir]

Each case is authored as GeoSteps (a recipe card, or the mock for the house), compiled
with ifc/compile.py, reopened, and tessellated. Prints element counts and file sizes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ifcopenshell
import ifcopenshell.geom

from blocks import card_by_id
from ifc.compile import compile_ifc, summarize
from llm.mock import author_steps
from schemas.geo import GeoModel
from schemas.geosteps import GeoStep, apply_step

CASES = [
    ("dome", "dome"),
    ("vault", "barrel-vault"),
    ("tunnel", "tunnel"),
    ("helical-stair", "spiral-stair"),
    ("bridge", "bridge"),
    ("house", None),
]


def _from_card(card_id: str) -> GeoModel:
    card = card_by_id(card_id)
    model = GeoModel(name=card.title)
    for raw in card.steps:
        model, _ = apply_step(model, GeoStep.model_validate(raw))
    return model


def _house() -> GeoModel:
    model = GeoModel()
    for raw in author_steps("A two-storey house with a kitchen, a living room and three bedrooms, a garage and a gable roof"):
        model, _ = apply_step(model, GeoStep.model_validate(raw))
    return model


def _tessellate(model) -> tuple[int, int]:
    settings = ifcopenshell.geom.settings()
    verts = faces = 0
    for product in model.by_type("IfcProduct"):
        if not getattr(product, "Representation", None) or product.is_a("IfcOpeningElement"):
            continue
        shape = ifcopenshell.geom.create_shape(settings, product)
        if not shape.geometry.verts:
            raise RuntimeError(f"empty geometry: {product.is_a()} {product.Name}")
        verts += len(shape.geometry.verts) // 3
        faces += len(shape.geometry.faces) // 3
    return verts, faces


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv else Path("/opt/cursor/artifacts")
    out.mkdir(parents=True, exist_ok=True)
    print(f"{'case':16s} {'elements':>8s} {'verts':>8s} {'faces':>8s} {'bytes':>8s}  file")
    for name, card in CASES:
        geo = _house() if card is None else _from_card(card)
        ifc, _ = compile_ifc(geo)
        path = out / f"{name}.ifc"
        ifc.write(str(path))
        reopened = ifcopenshell.open(str(path))
        assert reopened.schema == "IFC4"
        summary = summarize(reopened)
        verts, faces = _tessellate(reopened)
        print(f"{name:16s} {summary['elements']:8d} {verts:8d} {faces:8d} {path.stat().st_size:8d}  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
