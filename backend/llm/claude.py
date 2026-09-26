"""Claude adapter: the official Anthropic SDK with structured outputs.

Credentials come from the environment (ANTHROPIC_API_KEY in backend/.env, or an
`ant auth login` profile). The reply is constrained to the request's JSON schema
with `output_config.format`, so it always parses.
"""

from __future__ import annotations

import copy
import json

import anthropic

from llm.base import LLMError, LLMRequest

DEFAULT_MODEL = "claude-opus-5"


def strict_schema(schema: dict) -> dict:
    """Rewrite a Pydantic JSON schema into the subset structured outputs accept:
    closed objects, tuples as fixed-length arrays, no defaults/titles."""
    s = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
            return
        if not isinstance(node, dict):
            return
        node.pop("default", None)
        node.pop("title", None)
        if "prefixItems" in node:  # tuple[float, float] → array of numbers, length 2
            items = node.pop("prefixItems")
            node["items"] = items[0] if all(i == items[0] for i in items) else {"anyOf": items}
            node.setdefault("minItems", len(items))
            node.setdefault("maxItems", len(items))
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])  # every field present; optional ones are nullable
        for v in node.values():
            walk(v)

    walk(s)
    return s


class ClaudeLLM:
    name = "claude"

    def __init__(self, model: str = DEFAULT_MODEL, timeout: float = 600):
        self.model = model or DEFAULT_MODEL
        self.client = anthropic.Anthropic(timeout=timeout)

    def complete(self, request: LLMRequest) -> dict:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=request.system,
                messages=[{"role": "user", "content": request.user}],
                output_config={"format": {"type": "json_schema", "schema": strict_schema(request.schema)}},
            )
        except anthropic.AuthenticationError as exc:
            raise LLMError("Anthropic authentication failed: set ANTHROPIC_API_KEY or run `ant auth login`") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError(f"Anthropic rate limit: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"cannot reach the Anthropic API: {exc}") from exc
        if response.stop_reason == "refusal":
            raise LLMError("the model declined this request")
        if response.stop_reason == "max_tokens":
            raise LLMError("the model's answer was cut off (max_tokens)")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"model returned non-JSON: {text[:200]!r}") from exc
