"""Token accounting for one run.

Every LLM call reports what it used: the provider's own count when it gives one (llm/base.py `Usage`),
an estimate from the text otherwise. `Tally` sits in front of a run's `emit`, adds up the calls as
their `llm` events pass through, and puts the running total on each of them, so the UI can show the
count while the model is still working. The total is stored with the version the run produced.
"""

from __future__ import annotations

from typing import Callable

from llm.base import LLMRequest, Usage, estimate_tokens

Emit = Callable[[str, str, dict | None], None]


def usage_of(request: LLMRequest, reply: str) -> Usage:
    """What a call used: the provider's count, or an estimate from the prompt and the reply.
    The estimate does not count attached images."""
    if request.usage is not None:
        return request.usage
    return Usage(input_tokens=estimate_tokens(request.system) + estimate_tokens(request.user),
                 output_tokens=estimate_tokens(reply), estimated=True)


class Tally:
    """An `emit` that counts. Use it in place of the run's emit; read `total()` at the end."""

    def __init__(self, emit: Emit, provider: str | None = None, model: str | None = None):
        self.emit = emit
        self.provider, self.model = provider, model
        self.used = Usage()
        self.calls = 0

    def __call__(self, stage: str, message: str, data: dict | None = None) -> None:
        if stage == "llm" and data and isinstance(data.get("usage"), dict):
            self.used = self.used + Usage.from_dict(data["usage"])
            self.calls += 1
            data = data | {"usage_total": self.total()}
        self.emit(stage, message, data)

    def total(self) -> dict | None:
        if not self.calls:
            return None
        return self.used.as_dict() | {"calls": self.calls, "provider": self.provider, "model": self.model}
