"""Stable IFC GlobalIds across versions.

A model's part / level / opening / assembly ids are the handles the language model and the UI
use. Each one is mapped to an IFC GlobalId the first time it is compiled, and the mapping is
stored with the project, so re-compiling the whole file after an edit still yields the same
GlobalIds for untouched (and modified-in-place) elements. That is what lets BCF issues, clash
results and external references survive editing.

The key prefixes are `element:`, `level:`, `opening:` and `assembly:`. `element:` rather than
`part:` is deliberate: a project migrated from the old room-centric spec keeps the GlobalIds it
already had wherever the migration keeps an id, so an existing file does not churn.
"""

from __future__ import annotations

import ifcopenshell.guid

from schemas.geo import GeoModel
from schemas.geosteps import expand_instances

GuidMap = dict[str, str]

FIXED_KEYS = ("project", "site", "building")


def key_for_level(level_id: str) -> str:
    return f"level:{level_id}"


def key_for_part(part_id: str) -> str:
    return f"element:{part_id}"


def key_for_opening(opening_id: str) -> str:
    return f"opening:{opening_id}"


def key_for_assembly(assembly_id: str) -> str:
    return f"assembly:{assembly_id}"


def model_keys(geo: GeoModel) -> list[str]:
    """Every key the model will produce, instanced copies included."""
    keys = list(FIXED_KEYS)
    keys += [key_for_level(l.id) for l in geo.levels]
    keys += [key_for_part(p.id) for p in expand_instances(geo)]
    keys += [key_for_opening(o.id) for o in geo.openings]
    for asm in geo.assemblies:
        keys.append(key_for_assembly(asm.id))
    for inst in geo.instances:
        if inst.copies == 1:
            keys.append(key_for_assembly(inst.id))
        else:
            keys += [key_for_assembly(f"{inst.id}-{i + 1}") for i in range(inst.copies)]
    return keys


def ensure_guids(geo: GeoModel, existing: GuidMap | None = None) -> GuidMap:
    """A map covering every entity the model will produce, reusing what is already there."""
    guids: GuidMap = dict(existing or {})
    for key in model_keys(geo):
        guids.setdefault(key, ifcopenshell.guid.new())
    return guids


def prune_guids(geo: GeoModel, guids: GuidMap) -> GuidMap:
    """Drop entries for ids the model no longer has. Kept separate from `ensure_guids` so a
    caller can decide whether a deleted-then-re-added id gets its old GlobalId back (it does
    not: re-adding is a new element)."""
    live = set(model_keys(geo))
    return {k: v for k, v in guids.items() if k in live}


# --- the room-centric spec, during the changeover -----------------------------
# These two keep the old BuildingSpec builders compiling while the generic layer is wired up.
# They go with the rest of the room layer.

def key_for_element(element_id: str) -> str:
    return f"element:{element_id}"


def ensure_spec_guids(spec, existing: GuidMap | None = None) -> GuidMap:
    guids: GuidMap = dict(existing or {})
    keys = list(FIXED_KEYS) + [key_for_level(l.id) for l in spec.levels]
    for el in spec.elements:
        keys.append(key_for_element(el.id))
        if el.type in ("door", "window") or (el.type == "stair" and el.to_level):
            keys.append(key_for_opening(el.id))
    for key in keys:
        guids.setdefault(key, ifcopenshell.guid.new())
    return guids


def prune_spec_guids(spec, guids: GuidMap) -> GuidMap:
    live = ensure_spec_guids(spec, {})
    return {k: v for k, v in guids.items() if k in live}
