"""The one contract every language model must satisfy: JSON in, schema-valid JSON out.

Keeping it this narrow is what makes the model swappable. Nothing else in the
backend knows whether it is talking to a rule-based mock, llama.cpp, Fireworks,
or Anthropic. Providers stream: `on_text` receives the accumulated reply text
after every chunk so the pipeline can render partial results while the model is
still generating.
"""

from __future__ import annotations

import base64
import json
import math
import re
from dataclasses import dataclass, field
from typing import Callable, Protocol

OnText = Callable[[str], None]
OnNote = Callable[[str], None]  # provider remarks worth surfacing to the user ("retrying without grammar…")
OnThinking = Callable[[str], None]  # the model's accumulated reasoning, for providers that expose it

_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class LLMError(RuntimeError):
    """The model could not be reached or returned something that is not JSON."""


class EmptyReply(LLMError):
    """The model returned nothing at all. On a build round that means "no changes"; on a
    checklist it is a failure, so the two are distinguished rather than both being errors."""


@dataclass(frozen=True)
class Image:
    """An image shown to the model after the user text, introduced by its caption. A screenshot of
    the model's own work is a PNG (render/); an image the user attached to the prompt may be any
    format the providers take (schemas/attachments.py)."""
    data: bytes
    caption: str
    media_type: str = "image/png"

    def b64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


@dataclass(frozen=True)
class Usage:
    """Tokens one call used. `input_tokens` is everything the model read, cached or not;
    `cached_tokens` is the part of it that came from the provider's prompt cache."""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    estimated: bool = False     # counted from the text (about 4 characters a token), not by the provider

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens,
                     self.cached_tokens + other.cached_tokens, self.estimated or other.estimated)

    def as_dict(self) -> dict:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "cached_tokens": self.cached_tokens,
                "total_tokens": self.input_tokens + self.output_tokens, "estimated": self.estimated}

    @classmethod
    def from_dict(cls, d: dict) -> "Usage":
        return cls(int(d.get("input_tokens") or 0), int(d.get("output_tokens") or 0), int(d.get("cached_tokens") or 0),
                   bool(d.get("estimated")))


def estimate_tokens(text: str) -> int:
    """A rough count for providers that report none: about four characters a token."""
    return math.ceil(len(text) / 4)


@dataclass
class LLMRequest:
    system: str
    user: str
    schema: dict            # JSON schema the reply must satisfy
    schema_name: str        # "program" | "edit" — lets adapters pick a grammar or route
    meta: dict = field(default_factory=dict)  # side channel (raw prompt, current state) for the mock adapter
    images: list[Image] = field(default_factory=list)   # only sent to adapters with `vision`
    usage: Usage | None = None   # filled in by the adapter when the provider reports token counts

    def captioned_text(self) -> str:
        """The user text with the image captions listed, for adapters that attach images without text parts."""
        return self.user + "".join(f"\n\nImage {i}: {im.caption}" for i, im in enumerate(self.images, 1))


class LLM(Protocol):
    name: str
    vision: bool    # accepts images; the look loop is skipped for models that do not

    def complete(self, request: LLMRequest, on_text: OnText | None = None, on_note: OnNote | None = None) -> dict: ...


def clean_reply(text: str) -> str:
    """Drop reasoning blocks and code fences some models wrap around the JSON."""
    text = _THINK.sub("", text)
    if "<think>" in text and "</think>" not in text:  # still thinking: nothing usable yet
        return ""
    return _FENCE.sub("", text.strip())


def thinking_of(text: str) -> str:
    """The reasoning inside `<think>` blocks of a (possibly still streaming) reply, for the
    open-weight models that think inline rather than in a separate channel."""
    start = text.find("<think>")
    if start < 0:
        return ""
    end = text.find("</think>", start)
    return text[start + 7:end if end >= 0 else None].strip()


def body(text: str) -> str:
    """The JSON object inside a (possibly still streaming) reply.

    Unconstrained models introduce themselves before the object — "Here's the design:" — and a
    leading sentence makes the whole prefix unparseable, so the live parser would see no steps at
    all until the reply ended. Cutting to the first brace costs nothing when there is no prose."""
    cleaned = clean_reply(text)
    start = cleaned.find("{")
    return cleaned[start:] if start > 0 else cleaned


def parse_reply(text: str) -> dict:
    """Final reply → dict. Tolerates prose around the object (unconstrained models) and falls back
    to closing an unfinished JSON (max_tokens cut) so the validate/repair loop gets a concrete
    complaint instead of a parse error."""
    from core.partial_json import parse_partial  # local import: core depends on llm, not the reverse

    cleaned = clean_reply(text)
    if not cleaned.strip():
        raise EmptyReply("the model returned an empty reply")
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
