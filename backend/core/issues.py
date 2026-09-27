"""A coordination issue: something about how the pieces fit together (a clash, a missing service, an
unsupported span) rather than whether a requirement is met. Issues come with concrete suggested steps
so a fix round, or the mock, can resolve them without guessing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

IssueKind = Literal["clash", "clearance", "service", "structure", "intersection", "insertion"]


@dataclass
class Issue:
    kind: IssueKind
    severity: Literal["error", "warning"]
    message: str
    ids: list[str] = field(default_factory=list)
    suggestions: list[dict] = field(default_factory=list)   # build steps that would resolve it

    def line(self) -> str:
        return f"[{self.kind}] {self.message}"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "severity": self.severity, "message": self.message, "ids": self.ids,
                "suggestions": self.suggestions}
