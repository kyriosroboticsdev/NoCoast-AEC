"""The prompt → version pipeline.

    prompt ─► LLM: requirements checklist
           ─► LLM: GeoSteps (streamed; each step applied + previewed as it arrives)
           ─► rejected steps? ─► LLM: fix round (≤ BIM_MAX_REPAIRS)
           ─► geometric check of the compiled model against the checklist
           ─► unmet requirements? ─► LLM: fix round (≤ BIM_VERIFY_ROUNDS)
           ─► compile IFC ─► version (GlobalIds kept)

A new project starts from an empty GeoModel; an edit starts from the head version's model
and the reply contains only the steps that change it.
"""

from __future__ import annotations

import os
import time
from typing import Callable

import ifcopenshell
from pydantic import ValidationError

import config
from blocks import retrieve
from core.checks import CheckResult, check, score, unmet_lines
from core.context import describe_focus, describe_model
from core.facts import collect
from core.guids import GuidMap, prune_guids
from core.ops import OpError, apply_ops
from core.stream import StepStream
from ifc.compile import GeometryError, compile_ifc, summarize
from llm import LLM, LLMError, LLMRequest
from llm.prompts import BUILD_SYSTEM, REQUIREMENTS_SYSTEM, build_user_message, requirements_user_message
from logsetup import log
from schemas.geo import GeoModel
from schemas.geosteps import GeoStepsResponse
from schemas.requirements import Requirement, RequirementsResponse
from store.db import Store, VersionData

Emit = Callable[[str, str, dict | None], None]

REQUIREMENTS_SCHEMA = RequirementsResponse.model_json_schema()
STEPS_SCHEMA = GeoStepsResponse.model_json_schema()


def verify_rounds() -> int:
    return int(os.environ.get("BIM_VERIFY_ROUNDS", 1))


class PipelineError(Exception):
    """User-facing failure (the model never produced a valid answer, nothing to change, …)."""


class ConflictError(PipelineError):
    """The client edited against a version that is no longer the head."""


def _fmt_validation(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"] for e in exc.errors()]


def _noop(stage: str, message: str, data: dict | None = None) -> None:
    pass


def _call(llm: LLM, request: LLMRequest, emit: Emit = _noop, stream: StepStream | None = None) -> dict:
    model = getattr(llm, "model", None)
    log.info("LLM %s: %s request, system %d chars, user %d chars", llm.name, request.schema_name, len(request.system), len(request.user))
    log.debug("LLM user message:\n%s", request.user)
    emit("llm", f"sending {request.schema_name} request to {llm.name}{' ' + model if model else ''}",
         {"provider": llm.name, "model": model, "schema": request.schema_name, "system_chars": len(request.system),
          "user_chars": len(request.user), "user": request.user[-6000:]})
    t = time.perf_counter()
    try:
        raw = llm.complete(request, stream.feed if stream else None, lambda note: emit("llm", note, None))
    except LLMError as exc:
        log.error("LLM %s failed after %.1fs: %s", llm.name, time.perf_counter() - t, exc)
        raise
    finally:
        if stream:
            stream.close()
    import json
    text = json.dumps(raw)
    log.info("LLM %s replied in %.1fs (%d chars)", llm.name, time.perf_counter() - t, len(text))
    log.debug("LLM reply:\n%s", json.dumps(raw, indent=1)[:20000])
    extra = ""
    if stream:
        extra = f", {len(stream.accepted)} step(s) applied, {len(stream.rejected)} rejected, {stream.count} preview(s)"
    emit("llm", f"reply complete: {len(text)} chars in {time.perf_counter() - t:.1f}s{extra}",
         {"seconds": round(time.perf_counter() - t, 2), "chars": len(text), "previews": stream.count if stream else 0,
          "accepted": len(stream.accepted) if stream else 0, "rejected": len(stream.rejected) if stream else 0,
          "reply": json.dumps(raw, indent=1)[:30000]})
    return raw


def request_requirements(llm: LLM, prompt: str, emit: Emit = _noop, focus: str | None = None) -> RequirementsResponse:
    errors: list[str] = []
    for attempt in range(config.MAX_REPAIRS + 1):
        emit("requirements", "extracting a checklist from the request" if not attempt else f"repair attempt {attempt}", {"errors": errors})
        raw = _call(llm, LLMRequest(system=REQUIREMENTS_SYSTEM, user=requirements_user_message(prompt, errors, focus),
                                    schema=REQUIREMENTS_SCHEMA, schema_name="requirements", meta={"prompt": prompt, "focus": focus}), emit)
        try:
            resp = RequirementsResponse.model_validate(raw)
            unsupported = [r.text for r in resp.requirements if not r.supported]
            emit("requirements", f"{len(resp.requirements)} requirement(s)" + (f", {len(unsupported)} not supported" if unsupported else ""),
                 {"summary": resp.summary, "requirements": [r.model_dump(exclude_none=True) for r in resp.requirements],
                  "unsupported": unsupported})
            return resp
        except ValidationError as exc:
            errors = _fmt_validation(exc)
            log.warning("requirements rejected (attempt %d): %s", attempt + 1, "; ".join(errors))
            emit("validate", f"checklist rejected: {len(errors)} problem(s) sent back to the model", {"errors": errors})
    raise PipelineError("the model did not produce a valid checklist: " + "; ".join(errors))


def checklist_lines(reqs: list[Requirement]) -> list[str]:
    return [r.text + ("" if r.supported else " (NOT SUPPORTED — say so in a note)") for r in reqs]


def build_round(llm: LLM, prompt: str, geo: GeoModel, checklist: list[str], emit: Emit, *, guids: GuidMap,
                first_index: int, problems: list[str] | None = None, unmet: list[str] | None = None,
                editing: bool = False, focus: str | None = None) -> StepStream:
    context = describe_model(geo) if (geo.parts or geo.instances or editing or problems or unmet) else None
    what = "fixing rejected steps" if problems else "fixing unmet requirements" if unmet else "editing the model" if editing else "building the model"
    emit("build", f"{what}: asking the model for steps", {"problems": problems or [], "unmet": unmet or []})
    cards = [c.prompt_text() for c in retrieve(prompt, k=4)]
    stream = StepStream(emit, geo, guids, first_index)
    meta = {"prompt": prompt, "model": geo.model_dump(mode="json"), "problems": problems or [], "unmet": unmet or [],
            "editing": editing, "focus": focus}
    raw = _call(llm, LLMRequest(system=BUILD_SYSTEM,
                                user=build_user_message(prompt, checklist, context, problems, unmet, focus, cards),
                                schema=STEPS_SCHEMA, schema_name="build", meta=meta), emit, stream)
    try:
        steps = GeoStepsResponse.model_validate(raw).steps
    except ValidationError as exc:
        steps = []
        stream.rejected.append((first_index, raw if isinstance(raw, dict) else {"raw": raw}, "; ".join(_fmt_validation(exc))))
    while stream.applied < len(steps):
        stream.applied += 1
        stream.apply(steps[stream.applied - 1].model_dump(exclude_none=True))
    return stream


def _problem_lines(stream: StepStream) -> list[str]:
    import json
    return [f"step {i} {json.dumps(raw)[:300]}: {err}" for i, raw, err in stream.rejected]


def _persist(store: Store, project_id: str, geo: GeoModel, guids: GuidMap, *, mode: str, prompt: str | None,
             llm: str | None, ops: list[dict], notes: list[str], emit: Emit,
             model: ifcopenshell.file | None = None, checks: list[dict] | None = None) -> VersionData:
    if model is None:
        model, guids = compile_ifc(geo, guids)
    guids = prune_guids(geo, guids)
    head = store.head(project_id)
    number = head.number + 1 if head else 1
    path = store.ifc_path(project_id, number)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    log.info("project %s: wrote %s (%d parts, mode=%s)", project_id, path.name, len(geo.parts), mode)
    version = store.add_version(project_id, geo=geo, guids=guids, mode=mode, summary=summarize(model), ifc_path=path,
                                prompt=prompt, llm=llm, ops=ops, notes=notes, checks=checks or [])
    emit("done", f"version {version.number} ready", version.as_version().model_dump() | {"ifc_url": version.ifc_url})
    return version


def run_prompt(store: Store, llm: LLM, project_id: str, prompt: str, base_version: int | None = None,
               emit: Emit = _noop, focus: str | None = None) -> VersionData:
    if not prompt.strip():
        raise PipelineError("prompt is empty")
    head = store.head(project_id)
    log.info("project %s: prompt %r (head=%s, base=%s, llm=%s, focus=%s)", project_id, prompt[:120],
             head.number if head else None, base_version, llm.name, focus)
    if base_version is not None and head is not None and head.number != base_version:
        raise ConflictError(f"project is at version {head.number}, you edited version {base_version}")
    editing = head is not None
    geo = head.geo.model_copy(deep=True) if editing else GeoModel()
    guids: GuidMap = dict(head.guids) if head else {}
    notes: list[str] = []
    focus_text = describe_focus(geo, focus) if focus and str(focus).strip() and editing else None
    if focus_text:
        emit("focus", f"selected: {focus_text}", {"id": focus, "text": focus_text})
    try:
        reqs = request_requirements(llm, prompt, emit, focus_text)
        checklist = checklist_lines(reqs.requirements)
        notes += [f"not supported: {r.text}" for r in reqs.requirements if not r.supported]

        steps_total, accepted_total = 0, 0
        stream = build_round(llm, prompt, geo, checklist, emit, guids=guids, first_index=0, editing=editing, focus=focus_text)
        geo, guids = stream.geo, stream.guids
        steps_total += stream.applied
        accepted_total += len(stream.accepted)
        for _attempt in range(config.MAX_REPAIRS):
            if not stream.rejected:
                break
            stream = build_round(llm, prompt, geo, checklist, emit, guids=guids, first_index=steps_total,
                                 problems=_problem_lines(stream), editing=editing, focus=focus_text)
            geo, guids = stream.geo, stream.guids
            steps_total += stream.applied
            accepted_total += len(stream.accepted)
        if stream.rejected:
            notes += [f"step rejected: {err}" for _, _, err in stream.rejected]

        model, guids = compile_ifc(geo, guids)
        results = _verify(model, reqs.requirements, emit)
        for _ in range(verify_rounds()):
            unmet = unmet_lines(results)
            if not unmet:
                break
            stream = build_round(llm, prompt, geo, checklist, emit, guids=guids, first_index=steps_total,
                                 unmet=unmet, editing=editing, focus=focus_text)
            geo, guids = stream.geo, stream.guids
            steps_total += stream.applied
            accepted_total += len(stream.accepted)
            model, guids = compile_ifc(geo, guids)
            results = _verify(model, reqs.requirements, emit)

        if accepted_total == 0:
            raise PipelineError("the model produced no applicable steps" + (": " + stream.rejected[0][2] if stream.rejected else ""))
        if geo.is_empty():
            raise PipelineError("the model has no parts")

        emit("compile", "compiling the final IFC")
        notes = geo.notes + notes + [r.line() for r in results if r.status != "met"]
        met, total = score(results)
        if total:
            notes.append(f"requirements met: {met}/{total}")
        return _persist(store, project_id, geo, guids, mode="edit" if editing else "design", prompt=prompt, llm=llm.name,
                        ops=[], notes=notes, emit=emit, model=model,
                        checks=[{"text": r.requirement.text, "status": r.status, "detail": r.detail} for r in results])
    except LLMError as exc:
        raise PipelineError(f"language model unavailable: {exc}") from exc
    except GeometryError as exc:
        raise PipelineError(f"the model could not be built: {exc}") from exc


def _verify(model: ifcopenshell.file, reqs: list[Requirement], emit: Emit) -> list[CheckResult]:
    facts = collect(model)
    results = check(model, reqs, facts)
    met, total = score(results)
    unmet = [r for r in results if r.status == "unmet"]
    emit("verify", f"{met}/{total} checkable requirement(s) met" + (f", {len(unmet)} unmet" if unmet else ""),
         {"results": [{"text": r.requirement.text, "status": r.status, "detail": r.detail} for r in results],
          "unmet": [r.line() for r in unmet]})
    return results


def run_ops(store: Store, project_id: str, ops: list, base_version: int | None = None, emit: Emit = _noop) -> VersionData:
    head = store.head(project_id)
    if head is None:
        raise PipelineError("project has no model yet; send a prompt first")
    if base_version is not None and head.number != base_version:
        raise ConflictError(f"project is at version {head.number}, you edited version {base_version}")
    try:
        emit("apply", f"applying {len(ops)} operation(s)")
        geo, notes = apply_ops(head.geo, ops)
        return _persist(store, project_id, geo, head.guids, mode="ops", prompt=None, llm=None,
                        ops=[op.model_dump(mode="json") for op in ops], notes=notes, emit=emit)
    except (OpError, GeometryError) as exc:
        raise PipelineError(str(exc)) from exc


def revert(store: Store, project_id: str, to_number: int, emit: Emit = _noop) -> VersionData:
    target = store.get_version(project_id, to_number)
    if target is None:
        raise PipelineError(f"version {to_number} does not exist")
    return _persist(store, project_id, target.geo, target.guids, mode="revert", prompt=None, llm=None, ops=[],
                    notes=[f"reverted to version {to_number}"], emit=emit)


def import_model(store: Store, project_id: str, geo: GeoModel, guids: GuidMap, notes: list[str],
                 emit: Emit = _noop) -> VersionData:
    return _persist(store, project_id, geo, guids, mode="import", prompt=None, llm=None, ops=[], notes=notes, emit=emit)
