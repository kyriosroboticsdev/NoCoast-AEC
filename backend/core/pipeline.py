"""The prompt → version pipeline.

    new project:  prompt ─► LLM: Program ─► validate ─► solver ─► spec ─► compile IFC ─► version
    existing:     prompt + current spec ─► LLM: EditResponse ─► ops → apply | program → solver
                                           ─► validate ─► compile IFC ─► version (GlobalIds kept)

Every LLM answer goes through a validate/repair loop: schema errors, semantic
errors (opening past the end of its wall, unknown ids …) and geometry failures are
turned into text and sent back, at most MAX_REPAIRS times. `emit` receives progress
stages so the API can stream them.
"""

from __future__ import annotations

from typing import Callable

import json
import time

import ifcopenshell
from pydantic import ValidationError

import config
from logsetup import log
from core.context import describe_spec
from core.guids import GuidMap, prune_guids
from core.ops import OpError, apply_ops
from core.preview import Build, Preview
from ifc.builder import GeometryError, compile_ifc, summarize
from llm import LLM, LLMError, LLMRequest
from llm.prompts import EDIT_SYSTEM, PROGRAM_SYSTEM, edit_user_message, program_user_message
from schemas.bim import BuildingSpec
from schemas.ops import EditResponse, FlatOp
from schemas.program import Program
from solver.layout import solve
from store.db import Store, VersionData

Emit = Callable[[str, str, dict | None], None]

PROGRAM_SCHEMA = Program.model_json_schema()
EDIT_SCHEMA = EditResponse.model_json_schema()


class PipelineError(Exception):
    """User-facing failure (the LLM never produced a valid answer, nothing to change, …)."""


class ConflictError(PipelineError):
    """The client edited against a version that is no longer the head."""


def _fmt_validation(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"] for e in exc.errors()]


def _noop(stage: str, message: str, data: dict | None = None) -> None:
    pass


def _call(llm: LLM, request: LLMRequest, emit: Emit = _noop, build: Build | None = None) -> dict:
    """One streamed LLM call with timing, (at DEBUG) the full prompt and reply, and live previews
    when `build` can turn a partial reply into a spec."""
    model = getattr(llm, "model", None)
    log.info("LLM %s: %s request, system %d chars, user %d chars", llm.name, request.schema_name, len(request.system), len(request.user))
    log.debug("LLM user message:\n%s", request.user)
    emit("llm", f"sending {request.schema_name} request to {llm.name}{' ' + model if model else ''}",
         {"provider": llm.name, "model": model, "schema": request.schema_name, "system_chars": len(request.system),
          "user_chars": len(request.user), "user": request.user[-4000:]})
    t = time.perf_counter()
    preview = Preview(emit, build) if build else None
    try:
        raw = llm.complete(request, preview.feed if preview else None, lambda note: emit("llm", note, None))
    except LLMError as exc:
        log.error("LLM %s failed after %.1fs: %s", llm.name, time.perf_counter() - t, exc)
        raise
    finally:
        if preview:
            preview.close()
            log.info("LLM %s: %d preview(s) rendered while streaming", llm.name, preview.count)
    text = json.dumps(raw)
    log.info("LLM %s replied in %.1fs (%d chars)", llm.name, time.perf_counter() - t, len(text))
    log.debug("LLM reply:\n%s", json.dumps(raw, indent=1)[:20000])
    emit("llm", f"reply complete: {len(text)} chars in {time.perf_counter() - t:.1f}s"
         + (f", {preview.count} preview(s) rendered, {preview.skipped} snapshot(s) not yet valid" if preview else ""),
         {"seconds": round(time.perf_counter() - t, 2), "chars": len(text), "previews": preview.count if preview else 0,
          "reply": json.dumps(raw, indent=1)[:30000]})
    return raw


def _op_summary(op) -> str:
    d = op.model_dump(mode="json")
    if d["op"] in ("add_element", "add_level"):
        item = d.get("element") or d.get("level")
        return f"{d['op']} {item.get('type', 'level')} {item.get('id')}"
    if d["op"] in ("modify_element", "modify_level"):
        return f"{d['op']} {d['id']}: " + ", ".join(f"{k}={v}" for k, v in d["set"].items() if v is not None)
    if d["op"] == "set_building":
        return "set_building: " + ", ".join(f"{k}={v}" for k, v in d["set"].items() if v is not None)
    return f"{d['op']} {d.get('id', '')}"


def build_program_preview(data: dict) -> BuildingSpec | None:
    try:
        return solve(Program.model_validate(data))
    except (ValidationError, ValueError):
        return None


def build_edit_preview(head: VersionData) -> Build:
    """Ops applied so far (skipping ones that are still incomplete), or the partial redesign program."""

    def build(data: dict) -> BuildingSpec | None:
        try:
            if data.get("mode") == "redesign":
                return solve(Program.model_validate(data["program"])) if data.get("program") else None
            ops = []
            for raw in data.get("ops") or []:
                try:
                    ops.append(FlatOp.model_validate(raw).typed())
                except (ValidationError, OpError):
                    pass  # still being generated
            if not ops:
                return None
            spec, _ = apply_ops(head.spec, ops)
            return spec
        except (ValidationError, ValueError, KeyError, TypeError):
            return None

    return build


# --- LLM calls with repair -------------------------------------------------

def request_program(llm: LLM, prompt: str, emit: Emit = _noop) -> Program:
    errors: list[str] = []
    for attempt in range(config.MAX_REPAIRS + 1):
        emit("program", "asking the model for a building program" if not attempt else f"repair attempt {attempt}", {"errors": errors})
        raw = _call(llm, LLMRequest(system=PROGRAM_SYSTEM, user=program_user_message(prompt, errors), schema=PROGRAM_SCHEMA,
                                    schema_name="program", meta={"prompt": prompt}), emit, build_program_preview)
        try:
            program = Program.model_validate(raw)
            emit("validate", f"valid program: {program.storeys} storey(s), {len(program.rooms)} rooms",
                 {"rooms": [f"{r.name} ({r.level})" for r in program.rooms], "features": [k for k in ("garage", "porch", "bright") if getattr(program, k)]})
            return program
        except ValidationError as exc:
            errors = _fmt_validation(exc)
            log.warning("program rejected (attempt %d): %s", attempt + 1, "; ".join(errors))
            emit("validate", f"program rejected: {len(errors)} problem(s) sent back to the model", {"errors": errors})
    raise PipelineError("the model did not produce a valid program: " + "; ".join(errors))


def request_edit(llm: LLM, prompt: str, head: VersionData, emit: Emit = _noop) -> tuple[BuildingSpec, EditResponse, list, list[str], GuidMap, ifcopenshell.file]:
    """Ask for an edit, apply it, compile it. Returns (spec, response, typed ops, cascade notes, guids, ifc model)."""
    context = describe_spec(head.spec)
    errors: list[str] = []
    program_json = head.program.model_dump_json(exclude={"notes"}) if head.program else None
    meta = {"prompt": prompt, "spec": head.spec.model_dump(mode="json"), "program": head.program.model_dump(mode="json") if head.program else None}
    build = build_edit_preview(head)
    for attempt in range(config.MAX_REPAIRS + 1):
        emit("edit", "asking the model for edit operations" if not attempt else f"repair attempt {attempt}", {"errors": errors})
        raw = _call(llm, LLMRequest(system=EDIT_SYSTEM, user=edit_user_message(prompt, context, errors, program_json), schema=EDIT_SCHEMA,
                                    schema_name="edit", meta=meta), emit, build)
        try:
            if isinstance(raw, dict) and raw.get("mode") == "ops":
                raw["program"] = None  # strict schemas make the model fill it anyway; it is meaningless in ops mode
            resp = EditResponse.model_validate(raw)
            typed: list = []
            if resp.mode == "ops":
                if not resp.ops:
                    raise OpError("no operations were returned; if nothing should change say so in notes and return mode=redesign with the current program")
                typed = resp.typed_ops()
                emit("validate", f"valid edit: {len(typed)} operation(s)", {"ops": [_op_summary(op) for op in typed]})
                emit("apply", f"applying {len(typed)} operation(s)")
                spec, cascade = apply_ops(head.spec, typed)
                if cascade:
                    emit("apply", f"{len(cascade)} cascaded change(s)", {"cascade": cascade})
            else:
                if resp.program is None:
                    raise OpError("mode=redesign requires a program")
                resp.ops = []  # models sometimes fill both; only the program counts in redesign mode
                emit("validate", f"valid redesign: {resp.program.storeys} storey(s), {len(resp.program.rooms)} rooms",
                     {"rooms": [f"{r.name} ({r.level})" for r in resp.program.rooms]})
                emit("solve", "solving the layout")
                spec, cascade = solve(resp.program), []
            emit("compile", f"compiling IFC ({len(spec.elements)} elements)")
            model, guids = compile_ifc(spec, head.guids)
            return spec, resp, typed, cascade, guids, model
        except ValidationError as exc:
            errors = _fmt_validation(exc)
            log.warning("edit rejected (attempt %d): %s", attempt + 1, "; ".join(errors))
            emit("validate", f"edit rejected: {len(errors)} problem(s) sent back to the model", {"errors": errors})
        except (OpError, GeometryError) as exc:
            errors = [str(exc)]
            log.warning("edit rejected (attempt %d): %s", attempt + 1, exc)
            emit("validate", "edit rejected: problem sent back to the model", {"errors": errors})
    raise PipelineError("the model did not produce a valid edit: " + "; ".join(errors))


# --- versions ---------------------------------------------------------------

def _persist(store: Store, project_id: str, spec: BuildingSpec, guids: GuidMap, *, mode: str, prompt: str | None,
             llm: str | None, ops: list[dict], notes: list[str], program: Program | None, emit: Emit,
             model: ifcopenshell.file | None = None) -> VersionData:
    if model is None:
        model, guids = compile_ifc(spec, guids)
    guids = prune_guids(spec, guids)
    head = store.head(project_id)
    number = head.number + 1 if head else 1
    path = store.ifc_path(project_id, number)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    log.info("project %s: wrote %s (%d elements, mode=%s)", project_id, path.name, len(spec.elements), mode)
    version = store.add_version(project_id, spec=spec, guids=guids, mode=mode, summary=summarize(model), ifc_path=path,
                                prompt=prompt, llm=llm, ops=ops, notes=notes, program=program)
    emit("done", f"version {version.number} ready", version.as_version().model_dump() | {"ifc_url": version.ifc_url})
    return version


def run_prompt(store: Store, llm: LLM, project_id: str, prompt: str, base_version: int | None = None,
               emit: Emit = _noop) -> VersionData:
    if not prompt.strip():
        raise PipelineError("prompt is empty")
    head = store.head(project_id)
    log.info("project %s: prompt %r (head=%s, base=%s, llm=%s)", project_id, prompt[:120], head.number if head else None, base_version, llm.name)
    if base_version is not None and head is not None and head.number != base_version:
        raise ConflictError(f"project is at version {head.number}, you edited version {base_version}")
    try:
        if head is None:
            program = request_program(llm, prompt, emit)
            emit("solve", "solving the layout")
            spec = solve(program)
            emit("compile", f"compiling IFC ({len(spec.elements)} elements)")
            return _persist(store, project_id, spec, {}, mode="design", prompt=prompt, llm=llm.name, ops=[],
                            notes=program.notes, program=program, emit=emit)
        spec, resp, typed, cascade, guids, model = request_edit(llm, prompt, head, emit)
        program = resp.program if resp.mode == "redesign" else head.program
        return _persist(store, project_id, spec, guids, mode=resp.mode, prompt=prompt, llm=llm.name,
                        ops=[op.model_dump(mode="json") for op in typed], notes=resp.notes + cascade,
                        program=program, emit=emit, model=model)
    except LLMError as exc:
        raise PipelineError(f"language model unavailable: {exc}") from exc


def run_ops(store: Store, project_id: str, ops: list, base_version: int | None = None, emit: Emit = _noop) -> VersionData:
    """Apply ops without an LLM (the UI, a script, or a future agent tool)."""
    head = store.head(project_id)
    if head is None:
        raise PipelineError("project has no design yet; send a prompt first")
    if base_version is not None and head.number != base_version:
        raise ConflictError(f"project is at version {head.number}, you edited version {base_version}")
    try:
        spec, cascade = apply_ops(head.spec, ops)
        return _persist(store, project_id, spec, head.guids, mode="ops", prompt=None, llm=None,
                        ops=[op.model_dump(mode="json") for op in ops], notes=cascade, program=head.program, emit=emit)
    except (OpError, GeometryError) as exc:
        raise PipelineError(str(exc)) from exc


def revert(store: Store, project_id: str, to_number: int, emit: Emit = _noop) -> VersionData:
    target = store.get_version(project_id, to_number)
    if target is None:
        raise PipelineError(f"version {to_number} does not exist")
    return _persist(store, project_id, target.spec, target.guids, mode="revert", prompt=None, llm=None, ops=[],
                    notes=[f"reverted to version {to_number}"], program=target.program, emit=emit)


def import_spec(store: Store, project_id: str, spec: BuildingSpec, guids: GuidMap, notes: list[str], emit: Emit = _noop) -> VersionData:
    return _persist(store, project_id, spec, guids, mode="import", prompt=None, llm=None, ops=[], notes=notes, program=None, emit=emit)
