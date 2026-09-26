"""Stable IFC GlobalIds across versions.

The spec's element/level ids are the handles the LLM and the UI use. Each one is
mapped to an IFC GlobalId the first time it is compiled, and the mapping is
stored with the project, so re-compiling the whole IFC after an edit still
yields the same GlobalIds for untouched (and modified-in-place) elements. That
is what lets BCF issues, clash results and external references survive edits.
"""

from __future__ import annotations

import ifcopenshell.guid

from schemas.bim import BuildingSpec

GuidMap = dict[str, str]

FIXED_KEYS = ("project", "site", "building")


def key_for_level(level_id: str) -> str:
    return f"level:{level_id}"


def key_for_element(element_id: str) -> str:
    return f"element:{element_id}"


def key_for_opening(element_id: str) -> str:
    return f"opening:{element_id}"


def ensure_guids(spec: BuildingSpec, existing: GuidMap | None = None) -> GuidMap:
    """Return a map that covers every entity the spec will produce, reusing existing ids."""
    guids: GuidMap = dict(existing or {})
    keys = list(FIXED_KEYS) + [key_for_level(l.id) for l in spec.levels]
    for el in spec.elements:
        keys.append(key_for_element(el.id))
        if el.type in ("door", "window") or (el.type == "stair" and el.to_level):
            keys.append(key_for_opening(el.id))
    for key in keys:
        guids.setdefault(key, ifcopenshell.guid.new())
    return guids


def prune_guids(spec: BuildingSpec, guids: GuidMap) -> GuidMap:
    """Drop entries for ids no longer in the spec. Kept separate so callers can decide
    whether a deleted-then-re-added id should get its old GlobalId back (we say no)."""
    live = ensure_guids(spec, {})
    return {k: v for k, v in guids.items() if k in live}
