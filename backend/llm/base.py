"""The one contract every language model must satisfy: JSON in, schema-valid JSON out.

Keeping it this narrow is what makes the model swappable. Nothing else in the
backend knows whether it is talking to a rule-based mock, llama.cpp, Fireworks,
or Anthropic. Providers stream: `on_text` receives the accumulated reply text
after every chunk so the pipeline can render partial results while the model is
still generating.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Protocol

OnText = Callable[[str], None]
OnNote = Callable[[str], None]  # provider remarks worth surfacing to the user ("retrying without grammar…")

_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


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

    def complete(self, request: LLMRequest, on_text: OnText | None = None, on_note: OnNote | None = None) -> dict: ...


def clean_reply(text: str) -> str:
    """Drop reasoning blocks and code fences some models wrap around the JSON."""
    text = _THINK.sub("", text)
    if "<think>" in text and "</think>" not in text:  # still thinking: nothing usable yet
        return ""
    return _FENCE.sub("", text.strip())


def parse_reply(text: str) -> dict:
    """Final reply → dict. Tolerates prose around the object (unconstrained models) and falls back
    to closing an unfinished JSON (max_tokens cut) so the validate/repair loop gets a concrete
    complaint instead of a parse error."""
    from core.partial_json import parse_partial  # local import: core depends on llm, not the reverse

    cleaned = clean_reply(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    if start >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])  # first complete object, trailing prose ignored
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        partial = parse_partial(cleaned[start:])
        if isinstance(partial, dict):
            return partial
    raise LLMError(f"model returned non-JSON: {cleaned[:200]!r}")
