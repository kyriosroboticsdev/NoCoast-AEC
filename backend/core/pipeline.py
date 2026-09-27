"""The prompt → version pipeline.

    prompt ─► LLM: requirements checklist
           ─► LLM: research turns — tool calls into the brick library and skills (≤ BIM_TOOL_ROUNDS)
           ─► LLM: build steps (streamed; each step applied + previewed as it arrives)
           ─► rejected steps? ─► LLM: fix round (≤ BIM_MAX_REPAIRS)
           ─► deterministic check of the design against the checklist, plus coordination
              (clashes, missing services, unsupported spans — core/coordinate.py)
           ─► unmet requirements or coordination errors? ─► LLM: fix round (≤ BIM_VERIFY_ROUNDS)
           ─► derive spec ─► compile IFC ─► version (GlobalIds kept)

A new project starts from an empty Design; an edit starts from the head version's
Design and the model emits only the steps that change it. `emit` receives progress
stages so the API can stream them.
"""

from __future__ import annotations

import os
import time
from typing import Callable

import ifcopenshell
from pydantic import ValidationError

import config
from core.checks import CheckResult, check, score, unmet_lines
from core.context import describe_design, describe_focus
from core.coordinate import coordinate, errors, fix_lines
from core.derive import DesignError, analyze, derive
from core.guids import GuidMap, prune_guids
from core.issues import Issue
from core.research import Toolbox, research, tool_rounds
from core.ops import OpError, apply_ops
from core.stream import StepStream
from ifc.builder import GeometryError, compile_ifc, summarize
from llm import LLM, LLMError, LLMRequest
from llm.prompts import (BUILD_SYSTEM, REQUIREMENTS_SYSTEM, RESEARCH_SYSTEM, build_user_message, requirements_user_message,
                         research_user_message)
from logsetup import log
from schemas.bim import BuildingSpec
from schemas.design import Design
from schemas.requirements import Requirement, RequirementsResponse
from schemas.research import ResearchTurn
from schemas.steps import StepsResponse
from store.db import Store, VersionData

Emit = Callable[[str, str, dict | None], None]

REQUIREMENTS_SCHEMA = RequirementsResponse.model_json_schema()
STEPS_SCHEMA = StepsResponse.model_json_schema()
RESEARCH_SCHEMA = ResearchTurn.model_json_schema()


def verify_rounds() -> int:
    return int(os.environ.get("BIM_VERIFY_ROUNDS", 1))


class PipelineError(Exception):
    """User-facing failure (the LLM never produced a valid answer, nothing to change, …)."""


class ConflictError(PipelineError):
    """The client edited against a version that is no longer the head."""


def _fmt_validation(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"] for e in exc.errors()]


def _noop(stage: str, message: str, data: dict | None = None) -> None:
    pass


def _call(llm: LLM, request: LLMRequest, emit: Emit = _noop, stream: StepStream | None = None) -> dict:
    """One streamed LLM call with timing and (at DEBUG) the full prompt and reply."""
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


# --- requirements -------------------------------------------------------------

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


# --- research -----------------------------------------------------------------

def research_round(llm: LLM, prompt: str, design: Design, checklist: list[str], emit: Emit, focus: str | None = None) -> Toolbox:
    context = None
    if design.rooms:
        try:
            context = describe_design(design, analyze(design))
        except DesignError:
            context = describe_design(design)

    def complete(_prompt: str, log: list[str]) -> dict:
        user = research_user_message(prompt + (f"\n\n(selected: {focus})" if focus else ""), checklist, context, log)
        return _call(llm, LLMRequest(system=RESEARCH_SYSTEM, user=user, schema=RESEARCH_SCHEMA, schema_name="research",
                                     meta={"prompt": prompt, "checklist": checklist, "log": log,
                                           "design": design.model_dump(mode="json")}), emit)

    return research(complete, prompt + "\n" + "\n".join(checklist), design, emit, tool_rounds())


# --- build rounds ---------------------------------------------------------------

def build_round(llm: LLM, prompt: str, design: Design, checklist: list[str], emit: Emit, *, guids: GuidMap,
                first_index: int, problems: list[str] | None = None, unmet: list[str] | None = None,
                editing: bool = False, focus: str | None = None, issues: list[Issue] | None = None,
                toolbox: Toolbox | None = None) -> StepStream:
    context = None
    fixes = fix_lines(issues or [])
    if design.rooms or editing or problems or unmet or fixes:
        try:
            context = describe_design(design, analyze(design))
        except DesignError:
            context = describe_design(design)
    what = ("fixing rejected steps" if problems else "fixing unmet requirements" if unmet else "fixing coordination issues" if fixes
            else "editing the design" if editing else "building the design")
    emit("build", f"{what}: asking the model for steps", {"problems": problems or [], "unmet": unmet or [], "issues": fixes})
    stream = StepStream(emit, design, guids, first_index)
    meta = {"prompt": prompt, "design": design.model_dump(mode="json"), "problems": problems or [], "unmet": unmet or [],
            "editing": editing, "focus": focus, "issues": [i.as_dict() for i in errors(issues or [])],
            "bricks": toolbox.bricks if toolbox else []}
    user = build_user_message(prompt, checklist, context, problems, unmet, focus, fixes, toolbox.text() if toolbox else None)
    raw = _call(llm, LLMRequest(system=BUILD_SYSTEM, user=user,
                                schema=STEPS_SCHEMA, schema_name="build", meta=meta), emit, stream)
    # Anything the streaming parser did not see (non-streaming adapters, or a reply that only parsed whole).
    try:
        steps = StepsResponse.model_validate(raw).steps
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


# --- versions ---------------------------------------------------------------

def _persist(store: Store, project_id: str, spec: BuildingSpec, guids: GuidMap, *, mode: str, prompt: str | None,
             llm: str | None, ops: list[dict], notes: list[str], design: Design | None, emit: Emit,
             model: ifcopenshell.file | None = None, checks: list[dict] | None = None) -> VersionData:
    if model is None:
        model, guids = compile_ifc(spec, guids, design.model_dump_json() if design else None)
    guids = prune_guids(spec, guids)
    head = store.head(project_id)
    number = head.number + 1 if head else 1
    path = store.ifc_path(project_id, number)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    log.info("project %s: wrote %s (%d elements, mode=%s)", project_id, path.name, len(spec.elements), mode)
    version = store.add_version(project_id, spec=spec, guids=guids, mode=mode, summary=summarize(model), ifc_path=path,
                                prompt=prompt, llm=llm, ops=ops, notes=notes, design=design, checks=checks or [])
    emit("done", f"version {version.number} ready", version.as_version().model_dump() | {"ifc_url": version.ifc_url})
    return version


def run_prompt(store: Store, llm: LLM, project_id: str, prompt: str, base_version: int | None = None,
               emit: Emit = _noop, focus: str | None = None) -> VersionData:
    if not prompt.strip():
        raise PipelineError("prompt is empty")
    head = store.head(project_id)
    log.info("project %s: prompt %r (head=%s, base=%s, llm=%s, focus=%s)", project_id, prompt[:120], head.number if head else None, base_version, llm.name, focus)
    if base_version is not None and head is not None and head.number != base_version:
        raise ConflictError(f"project is at version {head.number}, you edited version {base_version}")
    editing = head is not None and head.design is not None
    design = head.design.model_copy(deep=True) if editing else Design()
    guids: GuidMap = dict(head.guids) if head else {}
    notes: list[str] = []
    if head is not None and not editing:
        notes.append("the previous version had no design record (older pipeline); the model started from an empty design")
    # A viewer selection travels as a spec element id; the model sees it in words, with the ids it can act on.
    focus_text = describe_focus(design, focus) if focus and focus.strip() and editing else None
    if focus_text:
        emit("focus", f"selected: {focus_text}", {"id": focus, "text": focus_text})
    try:
        reqs = request_requirements(llm, prompt, emit, focus_text)
        checklist = checklist_lines(reqs.requirements)
        notes += [f"not supported: {r.text}" for r in reqs.requirements if not r.supported]

        toolbox = research_round(llm, prompt, design, checklist, emit, focus_text)

        steps_total, accepted_total = 0, 0
        stream = build_round(llm, prompt, design, checklist, emit, guids=guids, first_index=0, editing=editing, focus=focus_text,
                             toolbox=toolbox)
        design, guids = stream.design, stream.guids
        steps_total += stream.applied
        accepted_total += len(stream.accepted)
        for attempt in range(config.MAX_REPAIRS):
            if not stream.rejected:
                break
            stream = build_round(llm, prompt, design, checklist, emit, guids=guids, first_index=steps_total,
                                 problems=_problem_lines(stream), editing=editing, focus=focus_text, toolbox=toolbox)
            design, guids = stream.design, stream.guids
            steps_total += stream.applied
            accepted_total += len(stream.accepted)
        if stream.rejected:
            notes += [f"step rejected: {err}" for _, _, err in stream.rejected]

        results, issues = _verify(design, reqs.requirements, emit)
        for _ in range(verify_rounds()):
            unmet = unmet_lines(results)
            if not unmet and not errors(issues):
                break
            stream = build_round(llm, prompt, design, checklist, emit, guids=guids, first_index=steps_total, unmet=unmet,
                                 editing=editing, issues=issues, toolbox=toolbox)
            design, guids = stream.design, stream.guids
            steps_total += stream.applied
            accepted_total += len(stream.accepted)
            results, issues = _verify(design, reqs.requirements, emit)

        if accepted_total == 0:
            raise PipelineError("the model produced no applicable steps" + (": " + stream.rejected[0][2] if stream.rejected else ""))
        if not design.rooms:
            raise PipelineError("the design has no rooms")

        emit("compile", "deriving geometry and compiling the final IFC")
        spec, derive_notes = derive(design)
        model, guids = compile_ifc(spec, guids, design.model_dump_json())
        notes = design.notes + derive_notes + notes + [r.line() for r in results if r.status != "met"] + [i.line() for i in issues]
        met, total = score(results)
        if total:
            notes.append(f"requirements met: {met}/{total}")
        return _persist(store, project_id, spec, guids, mode="edit" if editing else "design", prompt=prompt, llm=llm.name,
                        ops=[{"step": s} for s in []], notes=notes, design=design, emit=emit, model=model,
                        checks=[{"text": r.requirement.text, "status": r.status, "detail": r.detail} for r in results])
    except LLMError as exc:
        raise PipelineError(f"language model unavailable: {exc}") from exc
    except (DesignError, GeometryError) as exc:
        raise PipelineError(f"the design could not be built: {exc}") from exc


def _verify(design: Design, reqs: list[Requirement], emit: Emit) -> tuple[list[CheckResult], list[Issue]]:
    try:
        derived = analyze(design)
    except DesignError as exc:
        emit("verify", f"design not buildable: {exc}", {"errors": [str(exc)]})
        return [], []
    issues = coordinate(design, derived)
    bad = errors(issues)
    emit("coordinate", f"{len(bad)} coordination issue(s), {len(issues) - len(bad)} warning(s)" if issues else "no clashes, services covered, spans supported",
         {"issues": [i.as_dict() for i in issues]})
    results = check(design, derived, reqs, issues)
    met, total = score(results)
    unmet = [r for r in results if r.status == "unmet"]
    emit("verify", f"{met}/{total} checkable requirement(s) met" + (f", {len(unmet)} unmet" if unmet else ""),
         {"results": [{"text": r.requirement.text, "status": r.status, "detail": r.detail} for r in results],
          "unmet": [r.line() for r in unmet]})
    return results, issues


def run_ops(store: Store, project_id: str, ops: list, base_version: int | None = None, emit: Emit = _noop) -> VersionData:
    """Apply raw element ops without an LLM (the UI, a script, or a future agent tool). They are stored as
    design overrides so later design edits replay them."""
    head = store.head(project_id)
    if head is None:
        raise PipelineError("project has no design yet; send a prompt first")
    if base_version is not None and head.number != base_version:
        raise ConflictError(f"project is at version {head.number}, you edited version {base_version}")
    try:
        emit("apply", f"applying {len(ops)} operation(s)")
        spec, cascade = apply_ops(head.spec, ops)
        design = None
        if head.design is not None:
            design = head.design.model_copy(deep=True)
            design.overrides += [op.model_dump(mode="json") for op in ops]
        return _persist(store, project_id, spec, head.guids, mode="ops", prompt=None, llm=None,
                        ops=[op.model_dump(mode="json") for op in ops], notes=cascade, design=design, emit=emit)
    except (OpError, GeometryError) as exc:
        raise PipelineError(str(exc)) from exc


def revert(store: Store, project_id: str, to_number: int, emit: Emit = _noop) -> VersionData:
    target = store.get_version(project_id, to_number)
    if target is None:
        raise PipelineError(f"version {to_number} does not exist")
    return _persist(store, project_id, target.spec, target.guids, mode="revert", prompt=None, llm=None, ops=[],
                    notes=[f"reverted to version {to_number}"], design=target.design, emit=emit)


def import_spec(store: Store, project_id: str, spec: BuildingSpec, design: Design | None, guids: GuidMap, notes: list[str],
                emit: Emit = _noop) -> VersionData:
    return _persist(store, project_id, spec, guids, mode="import", prompt=None, llm=None, ops=[], notes=notes, design=design, emit=emit)
