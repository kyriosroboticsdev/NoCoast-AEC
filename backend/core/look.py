"""The look loop: the model checks what it built from screenshots it chooses.

    design ─► compile ─► first views (the whole model, a plan cut of each level)
           ─► LLM: look turn {views, problems, done} with the latest screenshots attached
           ─► more views? render them ─► next turn (≤ BIM_LOOK_TURNS)
           ─► problems ─► a fix round of build steps (≤ BIM_LOOK_ROUNDS reviews per prompt)

Rendering is headless (render/), so every screenshot the model sees is also saved for the trace.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from pydantic import ValidationError

from core.derive import DesignError, derive, space_id
from core.guids import GuidMap
from ifc.builder import GeometryError, compile_ifc
from render import Shot, ViewError, render, scene_of
from schemas.design import Design
from schemas.look import MAX_VIEWS, LookTurn, View

Emit = Callable[[str, str, dict | None], None]
Complete = Callable[[list[str], list[Shot]], dict]   # the log so far and the latest shots -> one look turn's JSON
Shoot = Callable[[View], Shot]
Save = Callable[[Shot], str | None]                  # stores a screenshot; returns its URL for the trace, if any

VISIBLE_IN_TRACE = 12


def look_rounds() -> int:
    return int(os.environ.get("BIM_LOOK_ROUNDS", 1))


def look_turns() -> int:
    return int(os.environ.get("BIM_LOOK_TURNS", 3))


@dataclass
class Review:
    problems: list[str] = field(default_factory=list)
    shots: int = 0


def shooter(design: Design, guids: GuidMap) -> Shoot:
    """Compile the design once and return a camera over it."""
    spec, _ = derive(design)
    model, compiled = compile_ifc(spec, dict(guids))
    scene = scene_of(model, compiled, {space_id(r.level, r.id): r.id for r in design.rooms})
    return lambda view: render(scene, view)


def first_views(levels: list[str]) -> list[View]:
    """The whole model from the south-west, then a plan of each level from the ground up."""
    plans = [View(level=lid, elevation=90, azimuth=180, note=f"plan of {lid}") for lid in levels]
    return ([View(note="the whole model")] + plans)[:MAX_VIEWS]


def look(complete: Complete, shoot: Shoot, emit: Emit, first: list[View], save: Save | None = None,
         turns: int | None = None) -> Review:
    """Show the model `first`, then whatever views it asks for, until it reports problems, is done, or
    runs out of turns. `complete(log, shots)` makes one LLM call."""
    log: list[str] = []
    review = Review()
    views = first
    for turn in range(look_turns() if turns is None else turns):
        shots = []
        for view in views:
            try:
                shot = shoot(view)
            except ViewError as exc:
                log.append(f"{view.describe()}: could not take it: {exc}")
                emit("look", f"could not take {view.describe()}: {exc}", {"view": view.model_dump(exclude_none=True), "error": str(exc)})
                continue
            shots.append(shot)
            review.shots += 1
            log.append(f"screenshot {review.shots}: {shot.caption()}" + (f" — you wanted: {view.note}" if view.note else ""))
            emit("look", f"screenshot {review.shots}: {view.describe()}",
                 {"view": view.model_dump(exclude_none=True), "visible": shot.visible[:VISIBLE_IN_TRACE],
                  "image": save(shot) if save else None})
        emit("look", f"look turn {turn + 1}: showing the model {len(shots)} screenshot(s)", {"turn": turn + 1})
        try:
            reply = LookTurn.model_validate(complete(log, shots))
        except ValidationError as exc:
            emit("look", f"look turn {turn + 1} was not valid ({exc.error_count()} error(s)); keeping the design as it is", {"error": str(exc)})
            break
        if reply.problems:
            review.problems = reply.problems
            emit("look", f"the model saw {len(reply.problems)} problem(s)", {"problems": reply.problems})
            return review
        if reply.done or not reply.views:
            break
        views = reply.views
    emit("look", f"the model looked at {review.shots} screenshot(s) and saw nothing to fix", {"shots": review.shots})
    return review


def review_design(complete: Complete, design: Design, guids: GuidMap, emit: Emit, save: Save | None = None) -> Review:
    """One review of the current design; a design that cannot be compiled is left to the other checks."""
    try:
        shoot = shooter(design, guids)
    except (DesignError, GeometryError) as exc:
        emit("look", f"cannot render the design: {exc}", {"error": str(exc)})
        return Review()
    return look(complete, shoot, emit, first_views([l.id for l in design.levels]), save)
