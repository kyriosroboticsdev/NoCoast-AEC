"""The one contract every language model must satisfy: JSON in, schema-valid JSON out.

Keeping it this narrow is what makes the model swappable. Nothing else in the
backend knows whether it is talking to a rule-based mock, Ollama, or a hosted API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class LLMError(RuntimeError):
    """The model could not be reached or returned something that is not JSON."""


@dataclass
class LLMRequest:
    system: str
    user: str
    schema: dict            # JSON schema the reply must satisfy
    schema_name: str        # "program" | "edit" — lets adapters pick a grammar or route
    meta: dict = field(default_factory=dict)  # side channel (raw prompt, current state) for the mock adapter


class LLM(Protocol):
    name: str

    def complete(self, request: LLMRequest) -> dict: ...
