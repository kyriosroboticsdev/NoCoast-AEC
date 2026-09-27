"""The research loop: tool calls into the brick library and the skills before building.

    checklist ─► LLM: research turn {calls, done} ─► run tools ─► results ─► next turn (≤ BIM_TOOL_ROUNDS)
              ─► toolbox: brick cards, search hits and skills it read, plus skills matched to the request
              ─► appended to every build prompt as LIBRARY

The tools are plain functions over the library, the skill book and the current design, so they are
cheap, deterministic and identical for every model. A model that never calls a tool still gets the
skills whose triggers match the request.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable, get_args

from bricks import Brick, library
from core import structure
from core.coordinate import coordinate
from core.derive import DesignError, Derived, analyze
from core.issues import Issue
from schemas.design import Design
from schemas.research import ResearchTurn, ToolCall, ToolName
from skills import skillbook

Emit = Callable[[str, str, dict | None], None]
Complete = Callable[[list[str]], dict]      # the tool log so far -> one research turn's JSON

TOOLBOX_CAP = 14000      # chars of research carried into the build prompt
RESULT_CAP = 3000        # chars of one tool result shown back to the model
SEARCH_LIMIT = 8


def tool_rounds() -> int:
    return int(os.environ.get("BIM_TOOL_ROUNDS", 3))


@dataclass
class Toolbox:
    """What research found, in the order it was found; texts are deduplicated by key."""

    entries: dict[str, str] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)       # "tool(args) -> result" lines shown on the next turn

    def add(self, key: str, text: str) -> None:
        self.entries.setdefault(key, text)

    @property
    def bricks(self) -> list[str]:
        return [k.split(":", 1)[1] for k in self.entries if k.startswith("brick:")]

    @property
    def skills(self) -> list[str]:
        return [k.split(":", 1)[1] for k in self.entries if k.startswith("skill:")]

    def text(self) -> str:
        """Skills first (how to assemble), then brick cards, then search hits; capped."""
        order = sorted(self.entries.items(), key=lambda kv: ("skill:", "brick:", "search:").index(kv[0].split(":", 1)[0] + ":"))
        out, size = [], 0
        for _, text in order:
            if size + len(text) > TOOLBOX_CAP:
                break
            out.append(text)
            size += len(text) + 2
        return "\n\n".join(out)


Tool = Callable[[ToolCall, Design, Toolbox], str]


def _search_bricks(call: ToolCall, design: Design, box: Toolbox) -> str:
    hits = library().search(call.query or "", call.tag, SEARCH_LIMIT)
    if not hits:
        return f"no bricks match '{call.query}'" + (f" tagged {call.tag}" if call.tag else "") + "; you can write an asset instead"
    text = "\n".join(b.line() for b, _ in hits)
    box.add(f"search:{call.query}|{call.tag}", f"search_bricks({call.query!r}):\n{text}")
    return text


def _get_brick(call: ToolCall, design: Design, box: Toolbox) -> str:
    brick = design.find_brick(call.id)
    if brick is None:
        return f"no brick '{call.id}'; closest: {', '.join(library().suggest((call.id or '').replace('_', ' '))) or 'none'}"
    box.add(f"brick:{brick.id}", brick.card())
    return brick.card()


def _check_asset(call: ToolCall, design: Design, box: Toolbox) -> str:
    if not call.definition:
        return "check_asset needs `definition`: the asset JSON"
    try:
        brick = Brick.model_validate(json.loads(call.definition))
        solids = brick.solids(brick.resolve())
    except json.JSONDecodeError as exc:
        return f"not valid JSON: {exc.msg} at char {exc.pos}"
    except ValueError as exc:
        return f"invalid: {exc}"
    return f"valid ({len(solids)} solid(s) at its defaults):\n{brick.card()}"


def _list_skills(call: ToolCall, design: Design, box: Toolbox) -> str:
    return skillbook().index_text()


def _get_skill(call: ToolCall, design: Design, box: Toolbox) -> str:
    skill = skillbook().get(call.id or "")
    if skill is None:
        return f"no skill '{call.id}'; skills: {', '.join(s.name for s in skillbook().all())}"
    box.add(f"skill:{skill.name}", skill.text())
    return skill.text()


def _checked(report: Callable[[Design, Derived], list[Issue]]) -> Tool:
    def run(call: ToolCall, design: Design, box: Toolbox) -> str:
        if not design.rooms:
            return "the design is empty; nothing to check yet"
        try:
            derived = analyze(design)
        except DesignError as exc:
            return f"the design is not buildable: {exc}"
        return "\n".join(i.line() for i in report(design, derived)) or "no issues"
    return run


TOOLS: dict[ToolName, Tool] = {
    "search_bricks": _search_bricks,
    "get_brick": _get_brick,
    "check_asset": _check_asset,
    "list_skills": _list_skills,
    "get_skill": _get_skill,
    "check_design": _checked(coordinate),
    "structure_report": _checked(structure.report),
}
assert set(TOOLS) == set(get_args(ToolName)), "every tool needs a handler"


def run_tool(call: ToolCall, design: Design, box: Toolbox) -> str:
    return TOOLS[call.tool](call, design, box)


def _describe(call: ToolCall) -> str:
    args = call.model_dump(exclude_none=True, exclude={"tool"})
    return f"{call.tool}(" + ", ".join(f"{k}={v!r}" for k, v in args.items()) + ")"


def research(complete: Complete, request: str, design: Design, emit: Emit, rounds: int | None = None) -> Toolbox:
    """Run up to `rounds` research turns; `complete(log)` makes one LLM call and returns its JSON. `request`
    (the prompt and checklist) picks the skills every build gets even without a tool call."""
    box = Toolbox()
    for skill in skillbook().match(request):
        box.add(f"skill:{skill.name}", skill.text())
    if box.skills:
        emit("research", f"skills matched to the request: {', '.join(box.skills)}", {"skills": box.skills})
    rounds = tool_rounds() if rounds is None else rounds
    for turn in range(rounds):
        emit("research", f"research turn {turn + 1}: asking the model which tools to call", {"turn": turn + 1})
        try:
            reply = ResearchTurn.model_validate(complete(box.log))
        except ValueError as exc:
            emit("research", f"research turn {turn + 1} was not valid ({exc}); building with what was found", {"error": str(exc)})
            break
        for call in reply.calls:
            try:
                result = run_tool(call, design, box)
            except ValueError as exc:
                result = f"error: {exc}"
            label = _describe(call)
            box.log.append(f"{label} ->\n{result[:RESULT_CAP]}")
            emit("tool", f"{label}: {result.splitlines()[0][:160] if result else ''}",
                 {"tool": call.tool, "args": call.model_dump(exclude_none=True), "result": result[:RESULT_CAP]})
        if reply.done or not reply.calls:
            break
    emit("research", f"research done: {len(box.bricks)} brick card(s), {len(box.skills)} skill(s)",
         {"bricks": box.bricks, "skills": box.skills, "chars": len(box.text())})
    return box
