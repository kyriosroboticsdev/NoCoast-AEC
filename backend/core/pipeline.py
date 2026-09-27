"""The prompt → version pipeline.

    prompt ─► LLM: requirements checklist
           ─► LLM: research turns — tool calls into the brick library and skills (≤ BIM_TOOL_ROUNDS)
           ─► LLM: build steps (streamed; each step applied + previewed as it arrives)
           ─► rejected steps? ─► LLM: fix round (≤ BIM_MAX_REPAIRS)
           ─► deterministic check of the design against the checklist, plus coordination
              (clashes, missing services, unsupported spans — core/coordinate.py)
           ─► unmet requirements or coordination errors? ─► LLM: fix round (≤ BIM_VERIFY_ROUNDS)
           ─► LLM: look — screenshots from views it picks (core/look.py); problems it sees ─► fix round
              (≤ BIM_LOOK_ROUNDS; vision models only)
           ─► derive spec ─► compile IFC ─► version (GlobalIds kept)

A new project starts from an empty Design; an edit starts from the head version's
Design and the model emits only the steps that change it. `emit` receives progress
stages so the API can stream them. Images the user attached to the prompt go to the
checklist and to every build round (their names to a model that cannot see them) and
are stored with the version, so the history shows what the request really was.
"""

from __future__ import annotations

import inspect
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Callable

import ifcopenshell
from pydantic import ValidationError

import config
from core import export as deliverables
from core.checks import CheckResult, check, score, unmet_lines
from core.context import describe_design, describe_focus
from core.coordinate import coordinate, errors, fix_lines
from core.derive import DesignError, analyze, derive
from core.guids import GuidMap, prune_guids
from core.issues import Issue
from core.look import Review, look_rounds, look_turns, review_design
from core.research import Toolbox, research, tool_rounds
from core.ops import OpError, apply_ops
from core.remedy import remedies
from core.review import review
from core.stream import StepStream, ThoughtStream
from core.usage import Tally, usage_of
from ifc.builder import GeometryError, compile_ifc, summarize
from llm import LLM, LLMError, LLMRequest
from llm.base import EmptyReply, Image, thinking_of
from llm.prompts import (build_system, build_user_message, look_system, look_user_message, requirements_system,
                         requirements_user_message, research_system, research_user_message)
from render import Shot
from logsetup import log
from schemas.attachments import ImageAttachment
from schemas.bim import BuildingSpec
from schemas.design import Design
from schemas.look import LookTurn
from schemas.requirements import Requirement, RequirementsResponse
from schemas.research import ResearchTurn
from schemas.steps import StepsResponse
from store.db import Store, VersionData

Emit = Callable[[str, str, dict | None], None]

REQUIREMENTS_SCHEMA = RequirementsResponse.model_json_schema()
STEPS_SCHEMA = StepsResponse.model_json_schema()
RESEARCH_SCHEMA = ResearchTurn.model_json_schema()
LOOK_SCHEMA = LookTurn.model_json_schema()


def verify_rounds() -> int:
    return int(os.environ.get("BIM_VERIFY_ROUNDS", 1))


def code_rounds() -> int:
    """Fix rounds driven by the pre-issue code screen (0 turns the screen-and-fix loop off)."""
    return int(os.environ.get("BIM_CODE_ROUNDS", 1))


class PipelineError(Exception):
    """User-facing failure (the LLM never produced a valid answer, nothing to change, …)."""


class ConflictError(PipelineError):
    """The client edited against a version that is no longer the head."""


def _fmt_validation(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"] for e in exc.errors()]


def _noop(stage: str, message: str, data: dict | None = None) -> None:
    pass


def attached_images(llm: LLM, images: Sequence[ImageAttachment]) -> list[Image]:
    """The user's attachments as the adapters take them — empty for a model that cannot see images,
    which is given their names in the prompt text instead."""
    if not getattr(llm, "vision", False):
        return []
    return [Image(i.raw, f"attached by the user: {i.name}", i.media_type) for i in images]


def _call(llm: LLM, request: LLMRequest, emit: Emit = _noop, stream: StepStream | None = None) -> dict:
    """One streamed LLM call with timing and (at DEBUG) the full prompt and reply."""
    model = getattr(llm, "model", None)
    log.info("LLM %s: %s request, system %d chars, user %d chars, %d image(s)", llm.name, request.schema_name, len(request.system),
             len(request.user), len(request.images))
    log.debug("LLM user message:\n%s", request.user)
    emit("llm", f"consulting {llm.name}{' ' + model if model else ''}",
         {"provider": llm.name, "model": model, "schema": request.schema_name, "system_chars": len(request.system),
          "user_chars": len(request.user), "user": request.user[-6000:]})
    t = time.perf_counter()
    thoughts = ThoughtStream(emit, request.schema_name, stream.touch if stream else None)

    def on_text(text: str) -> None:
        if "<think>" in text:
            thoughts.feed(thinking_of(text))
        if stream:
            stream.feed(text)

    reasoning = {"on_thinking": thoughts.feed} if "on_thinking" in inspect.signature(llm.complete).parameters else {}
    try:
        raw = llm.complete(request, on_text, lambda note: emit("llm", note, None), **reasoning)
    except EmptyReply as exc:
        # Nothing to do is a valid answer to "fix these problems"; it is not one to "list the brief".
        if stream is None:
            raise
        log.info("LLM %s had no changes to make", llm.name)
        emit("llm", f"{llm.name} had nothing to change", {"empty": True})
        raw = {"steps": []}
    except LLMError as exc:
        log.error("LLM %s failed after %.1fs: %s", llm.name, time.perf_counter() - t, exc)
        # A reply that broke off (max_tokens, a dropped connection) after the model had already
        # built something is worth keeping: the steps that streamed in are applied and valid, and
        # the checks and repair rounds run on them as usual.
        if stream is None or not stream.accepted:
            raise
        log.warning("keeping %d step(s) applied before the reply broke off", len(stream.accepted))
        emit("llm", f"the reply broke off ({exc}) after {len(stream.accepted)} move(s); "
                    f"carrying on with what was built", {"error": str(exc), "recovered": True,
                                                         "accepted": len(stream.accepted)})
        raw = {"steps": []}
    finally:
        thoughts.flush()
        if stream:
            stream.close()
    text = json.dumps(raw)
    log.info("LLM %s replied in %.1fs (%d chars)", llm.name, time.perf_counter() - t, len(text))
    log.debug("LLM reply:\n%s", json.dumps(raw, indent=1)[:20000])
    extra = ""
    if stream:
        extra = f": {len(stream.accepted)} move(s) applied, {len(stream.rejected)} rejected, {stream.count} preview(s)"
    used = usage_of(request, text)
    log.info("LLM %s used %d input and %d output tokens%s", llm.name, used.input_tokens, used.output_tokens,
             " (estimated)" if used.estimated else "")
    emit("llm", f"{llm.name} finished in {time.perf_counter() - t:.1f}s{extra}",
         {"seconds": round(time.perf_counter() - t, 2), "chars": len(text), "usage": used.as_dict(),
          "previews": stream.count if stream else 0,
          "accepted": len(stream.accepted) if stream else 0, "rejected": len(stream.rejected) if stream else 0,
          "reply": json.dumps(raw, indent=1)[:30000]})
    return raw


# --- requirements -------------------------------------------------------------

def request_requirements(llm: LLM, prompt: str, emit: Emit = _noop, focus: str | None = None,
                         attached: Sequence[ImageAttachment] = ()) -> RequirementsResponse:
    errors: list[str] = []
    for attempt in range(config.MAX_REPAIRS + 1):
        emit("requirements", "reading the brief and turning it into a checklist" if not attempt
             else f"re-reading the brief (attempt {attempt + 1})", {"errors": errors})
        raw = _call(llm, LLMRequest(system=requirements_system(),
                                    user=requirements_user_message(prompt, errors, focus, [i.name for i in attached]),
                                    schema=REQUIREMENTS_SCHEMA, schema_name="requirements", meta={"prompt": prompt, "focus": focus},
                                    images=attached_images(llm, attached)), emit)
        try:
            resp = RequirementsResponse.model_validate(raw)
            unsupported = [r.text for r in resp.requirements if not r.supported]
            emit("requirements", f"{len(resp.requirements)} requirement(s) in the brief"
                 + (f", {len(unsupported)} outside what I can model" if unsupported else ""),
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

def _context(design: Design) -> str | None:
    """The current design as the model sees it; None for an empty one."""
    if not design.has_geometry():
        return None
    try:
        return describe_design(design, analyze(design))
    except DesignError:
        return describe_design(design)


def research_round(llm: LLM, prompt: str, design: Design, checklist: list[str], emit: Emit, focus: str | None = None) -> Toolbox:
    context = _context(design)
    shown = prompt + (f"\n\n(selected: {focus})" if focus else "")

    def complete(log: list[str]) -> dict:
        return _call(llm, LLMRequest(system=research_system(), user=research_user_message(shown, checklist, context, log),
                                     schema=RESEARCH_SCHEMA, schema_name="research",
                                     meta={"prompt": prompt, "checklist": checklist, "log": log,
                                           "design": design.model_dump(mode="json")}), emit)

    return research(complete, prompt + "\n" + "\n".join(checklist), design, emit, tool_rounds())


# --- build rounds ---------------------------------------------------------------

@dataclass(frozen=True)
class Feedback:
    """What a fix round is asked to fix; empty for the first round of a build or an edit."""

    problems: list[str] = field(default_factory=list)   # rejected steps
    unmet: list[str] = field(default_factory=list)      # unmet requirements
    issues: list[Issue] = field(default_factory=list)   # coordination issues; the errors are sent, with suggested steps
    seen: list[str] = field(default_factory=list)       # problems the model saw in screenshots
    code: list[str] = field(default_factory=list)       # failing clauses of the pre-issue code screen
    remedies: list[dict] = field(default_factory=list)  # design steps that would clear those clauses

    def label(self, editing: bool) -> str:
        fixing = [what for what, items in (("the moves that did not build", self.problems),
                                           ("the gaps against the brief", self.unmet),
                                           ("the coordination issues", errors(self.issues)),
                                           ("what the screenshots showed", self.seen),
                                           ("the code-review failures", self.code))
                  if items]
        if fixing:
            return "reworking " + " and ".join(fixing)
        return "working out what to change" if editing else "designing the building"

    @property
    def round(self) -> str:
        if self.problems:
            return "repair"
        if self.unmet:
            return "gaps"
        if self.issues:
            return "coordination"
        if self.seen:
            return "look"
        return "code" if self.code else "design"


def build_round(llm: LLM, prompt: str, design: Design, checklist: list[str], emit: Emit, *, guids: GuidMap,
                first_index: int, feedback: Feedback = Feedback(), editing: bool = False, focus: str | None = None,
                toolbox: Toolbox | None = None, attached: Sequence[ImageAttachment] = ()) -> StepStream:
    context = _context(design)
    fixes = fix_lines(feedback.issues)
    emit("build", feedback.label(editing),
         {"problems": feedback.problems, "unmet": feedback.unmet, "issues": fixes, "seen": feedback.seen,
          "code": feedback.code, "editing": editing, "round": "edit" if editing and feedback.round == "design" else feedback.round})
    stream = StepStream(emit, design, guids, first_index)
    meta = {"prompt": prompt, "design": design.model_dump(mode="json"), "problems": feedback.problems, "unmet": feedback.unmet,
            "editing": editing, "focus": focus, "issues": [i.as_dict() for i in errors(feedback.issues)], "seen": feedback.seen,
            "code": feedback.code, "remedies": feedback.remedies, "bricks": toolbox.bricks if toolbox else []}
    user = build_user_message(prompt, checklist, context, focus=focus, toolbox=toolbox.text() if toolbox else None,
                              problems=feedback.problems, unmet=feedback.unmet, issues=fixes, seen=feedback.seen,
                              code=feedback.code, attached=[i.name for i in attached])
    raw = _call(llm, LLMRequest(system=build_system(), user=user, schema=STEPS_SCHEMA, schema_name="build", meta=meta,
                                images=attached_images(llm, attached)), emit, stream)
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


# --- look rounds ------------------------------------------------------------------

def look_round(llm: LLM, prompt: str, design: Design, checklist: list[str], guids: GuidMap, emit: Emit,
               save: Callable[[Shot], str | None] | None = None) -> Review:
    context = _context(design)
    turns = look_turns()
    asked = [0]

    def complete(log: list[str], shots: list[Shot]) -> dict:
        asked[0] += 1
        return _call(llm, LLMRequest(system=look_system(), user=look_user_message(prompt, checklist, context, log, turns - asked[0]),
                                     schema=LOOK_SCHEMA, schema_name="look", images=[Image(s.png, s.caption()) for s in shots],
                                     meta={"prompt": prompt, "design": design.model_dump(mode="json"), "log": log, "turn": asked[0],
                                           "visible": [s.visible for s in shots]}), emit)

    return review_design(complete, design, guids, emit, save)


def _problem_lines(stream: StepStream) -> list[str]:
    return [f"step {i} {json.dumps(raw)[:300]}: {err}" for i, raw, err in stream.rejected]


def follow_up(*args, **kwargs) -> StepStream | None:
    """A repair or gap-closing round. These come after a design already exists, so a model that
    times out, returns nothing or answers with prose must not throw the building away: the failure
    becomes a note and the run finishes with what it has."""
    emit: Emit = args[4]
    try:
        return build_round(*args, **kwargs)
    except LLMError as exc:
        log.warning("follow-up round failed, keeping the design as it stands: %s", exc)
        emit("build", f"the follow-up round did not come back ({exc}); finishing with the design as it stands",
             {"error": str(exc), "recovered": True})
        return None


# --- versions ---------------------------------------------------------------

def _persist(store: Store, project_id: str, spec: BuildingSpec, guids: GuidMap, *, mode: str, prompt: str | None,
             llm: str | None, ops: list[dict], notes: list[str], design: Design | None, emit: Emit,
             model: ifcopenshell.file | None = None, checks: list[dict] | None = None,
             images: list[dict] | None = None, approach: str | None = None, usage: dict | None = None) -> VersionData:
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
                                prompt=prompt, llm=llm, ops=ops, notes=notes, design=design, checks=checks or [],
                                images=images or [], approach=approach, usage=usage)
    analysis_url = _issue(version, emit)
    emit("done", f"version {version.number} ready",
         version.as_version().model_dump() | {"ifc_url": version.ifc_url, "export_url": version.export_url,
                                              "analysis_url": analysis_url})
    return version


def _money(v: float) -> str:
    return f"${v / 1e6:,.2f}M" if v >= 1e6 else f"${v / 1e3:,.0f}k"


def _issue(version: VersionData, emit: Emit) -> str | None:
    """Review the finished model like the office would before it goes out — code screen, cost and
    carbon, drawing set — and narrate the findings into the trace. Never fails the run."""
    try:
        data = deliverables.analysis(version)
    except Exception as exc:  # noqa: BLE001 — the model is built; a review bug must not lose it
        log.exception("review of version %s failed", version.number)
        emit("code", f"the design review could not run ({exc})", {"error": str(exc)})
        return None
    rev, est = data["review"], data["estimate"]
    occ, tot, score = rev["occupancy"], rev["totals"], rev["score"]
    findings = sorted(rev["checks"], key=lambda c: {"fail": 0, "warn": 1, "info": 2, "pass": 3}[c["status"]])
    verdict = (f"{score['fail']} to fix" if score["fail"] else "nothing failing") + \
              (f", {score['warn']} to review" if score["warn"] else "")
    emit("code", f"Code screen against {rev['code']}: occupancy {occ['group']}, {occ['load']} occupants — "
                 f"{score['pass']} of {score['total']} clauses pass, {verdict}",
         {"phase": "code", "code": rev["code"], "occupancy": occ, "totals": tot, "score": score,
          "checks": findings})
    cost, carbon = est["cost"], est["carbon"]
    best = carbon["options"][0] if carbon["options"] else None
    emit("estimate", f"Concept estimate {_money(cost['total'])} (${cost['per_sf']:,}/sf, {cost['class'].split(' —')[0]}); "
                     f"upfront carbon {carbon['per_m2']} kgCO2e/m², LETI band {carbon['band']}",
         {"phase": "cost", "cost": {k: cost[k] for k in ("total", "low", "high", "per_m2", "per_sf", "class", "basis")},
          "carbon": {k: carbon[k] for k in ("total_kg", "per_m2", "band", "typology", "target_2020", "target_2030",
                                            "meets_2030", "options")},
          "best": best, "gia": tot["gia"], "gia_sf": tot["gia_sf"]})
    base = f"/projects/{version.project_id}/versions/{version.number}"
    sheets = [{"number": s.number, "title": s.title, "url": f"{base}/sheets/{s.number}.svg"} for s in data["sheets"]]
    emit("deliver", f"Drawing set issued: {len(sheets)} sheets, DXF plans, Excel schedules, BCF issues and cost plan",
         {"phase": "issue", "sheets": sheets, "pdf": f"{base}/export?format=drawings",
          "dxf": f"{base}/export?format=dxf", "xlsx": f"{base}/export?format=xlsx",
          "bcf": f"{base}/export?format=bcf", "analysis_url": f"{base}/analysis"})
    return f"{base}/analysis"


def run_prompt(store: Store, llm: LLM, project_id: str, prompt: str, base_version: int | None = None,
               emit: Emit = _noop, focus: str | None = None, attached: Sequence[ImageAttachment] = ()) -> VersionData:
    if not prompt.strip():
        raise PipelineError("prompt is empty")
    emit = tally = Tally(emit, llm.name, getattr(llm, "model", None))   # counts the tokens of every call in this run
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
    # Attachments belong to this prompt only: they are kept with the version, not carried into later edits.
    stored_images = [store.save_attachment(project_id, image) for image in attached]
    if attached:
        seen = getattr(llm, "vision", False)
        emit("attachments", f"{len(attached)} image(s) attached: " + ", ".join(i.label() for i in attached)
             + ("" if seen else f" — {llm.name} cannot see images, only their names are in the prompt"),
             {"images": stored_images, "seen": seen})
        if not seen:
            notes.append(f"{len(attached)} image(s) attached, but {llm.name} cannot read images; the text alone was used")
    try:
        reqs = request_requirements(llm, prompt, emit, focus_text, attached)
        checklist = checklist_lines(reqs.requirements)
        notes += [f"not supported: {r.text}" for r in reqs.requirements if not r.supported]

        toolbox = research_round(llm, prompt, design, checklist, emit, focus_text)

        steps_total, accepted_total = 0, 0
        stream = build_round(llm, prompt, design, checklist, emit, guids=guids, first_index=0, editing=editing, focus=focus_text,
                             toolbox=toolbox, attached=attached)
        design, guids = stream.design, stream.guids
        approach = stream.approach
        steps_total += stream.applied
        accepted_total += len(stream.accepted)
        for attempt in range(config.MAX_REPAIRS):
            if not stream.rejected:
                break
            repaired = follow_up(llm, prompt, design, checklist, emit, guids=guids, first_index=steps_total,
                                 feedback=Feedback(problems=_problem_lines(stream)), editing=editing, focus=focus_text,
                                 toolbox=toolbox, attached=attached)
            if repaired is None:
                break
            stream = repaired
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
            closing = follow_up(llm, prompt, design, checklist, emit, guids=guids, first_index=steps_total,
                                feedback=Feedback(unmet=unmet, issues=issues), editing=editing, toolbox=toolbox,
                                attached=attached)
            if closing is None:
                break
            stream = closing
            design, guids = stream.design, stream.guids
            steps_total += stream.applied
            accepted_total += len(stream.accepted)
            results, issues = _verify(design, reqs.requirements, emit)

        rounds = look_rounds() if accepted_total and design.has_geometry() else 0
        if rounds and not getattr(llm, "vision", False):
            emit("look", f"{llm.name} is not set up to see images (LLM_VISION); skipping the visual check", {"skipped": True})
            rounds = 0
        def save(shot: Shot) -> str:
            return f"/projects/{project_id}/shots/{store.save_shot(project_id, shot.png)}"

        for _ in range(rounds):
            review = look_round(llm, prompt, design, checklist, guids, emit, save)
            if not review.problems:
                break
            fixing = follow_up(llm, prompt, design, checklist, emit, guids=guids, first_index=steps_total,
                               feedback=Feedback(seen=review.problems), editing=editing, toolbox=toolbox,
                               attached=attached)
            if fixing is None:
                break
            stream = fixing
            design, guids = stream.design, stream.guids
            steps_total += stream.applied
            accepted_total += len(stream.accepted)
            results, issues = _verify(design, reqs.requirements, emit)

        for _ in range(code_rounds() if accepted_total else 0):
            failing, fixes = _code_screen(design, emit)
            if not failing:
                break
            fixing = follow_up(llm, prompt, design, checklist, emit, guids=guids, first_index=steps_total,
                               feedback=Feedback(code=failing, remedies=fixes), editing=editing, toolbox=toolbox,
                               attached=attached)
            if fixing is None:
                break
            stream = fixing
            design, guids = stream.design, stream.guids
            steps_total += stream.applied
            accepted_total += len(stream.accepted)
            results, issues = _verify(design, reqs.requirements, emit)

        if accepted_total == 0:
            raise PipelineError("the model produced no applicable steps" + (": " + stream.rejected[0][2] if stream.rejected else ""))
        if not design.has_geometry():
            raise PipelineError("the design has nothing to build")

        emit("compile", "drawing the construction: walls, slabs, openings and roof, then writing the IFC")
        spec, derive_notes = derive(design)
        model, guids = compile_ifc(spec, guids, design.model_dump_json())
        notes = design.notes + derive_notes + notes + [r.line() for r in results if r.status != "met"] + [i.line() for i in issues]
        met, total = score(results)
        if total:
            notes.append(f"requirements met: {met}/{total}")
        return _persist(store, project_id, spec, guids, mode="edit" if editing else "design", prompt=prompt, llm=llm.name,
                        ops=[{"step": s} for s in []], notes=notes, design=design, emit=emit, model=model,
                        checks=[{"text": r.requirement.text, "status": r.status, "detail": r.detail} for r in results],
                        images=stored_images, approach=approach, usage=tally.total())
    except LLMError as exc:
        raise PipelineError(f"language model unavailable: {exc}") from exc
    except (DesignError, GeometryError) as exc:
        raise PipelineError(f"the design could not be built: {exc}") from exc


def _code_screen(design: Design, emit: Emit) -> tuple[list[str], list[dict]]:
    """Screen the design against the code before it is issued: the failing clauses, as lines a fix round can
    act on, and the design steps that would clear them."""
    try:
        spec, _ = derive(design)
        screen = review(spec, design)
    except Exception as exc:  # noqa: BLE001 — a review bug must not stop the building being issued
        log.warning("pre-issue code screen failed: %s", exc)
        return [], []
    failing = [c for c in screen["checks"] if c["status"] == "fail"]
    try:
        fixes = remedies(failing, spec, design)
    except Exception as exc:  # noqa: BLE001 — the clauses still go back to the model without suggested steps
        log.warning("code remedies failed: %s", exc)
        fixes = {}
    score = screen["score"]
    emit("precheck", f"pre-issue code screen: {score['pass']} of {score['total']} clauses pass"
                     + (f", {len(failing)} failing — handing them back to the model" if failing else ", nothing failing"),
         {"phase": "code", "code": screen["code"], "score": score,
          "checks": [{**{k: c[k] for k in ("title", "reference", "status", "value", "target", "detail", "advice")},
                      "fix": len(fixes.get(c["id"], []))} for c in failing]})
    lines = [f"{c['reference']} — {c['title']}: measured {c['value']}, required {c['target']}. {c['detail']}"
             + (f" Fix: {c['advice']}" if c["advice"] else "") + (f" (elements: {', '.join(c['elements'][:6])})" if c["elements"] else "")
             + (" Suggested steps: " + json.dumps([{k: v for k, v in s.items() if k != "why"} for s in fixes[c["id"]]])
                if c["id"] in fixes else "")
             for c in failing]
    return lines, [s for c in failing for s in fixes.get(c["id"], [])]


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
    results = check(design, derived, reqs)
    met, total = score(results)
    unmet = [r for r in results if r.status == "unmet"]
    emit("verify", f"checking the model against the brief: {met}/{total} met" + (f", {len(unmet)} outstanding" if unmet else ""),
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
