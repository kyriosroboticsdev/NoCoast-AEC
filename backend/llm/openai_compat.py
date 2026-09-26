"""OpenAI-compatible adapter: any server that speaks POST /chat/completions with SSE streaming.

Covers Anthropic's OpenAI-compatible endpoint, Fireworks, vLLM, LM Studio, llama.cpp's server,
LocalAI and hosted providers, so a specifically trained model can be dropped in by changing
three env vars.

JSON is requested with a JSON-schema `response_format`. Servers whose grammar compiler rejects a
schema as too large (Anthropic does this for the edit schema) get the same request again without
constrained decoding, once; the schema is then remembered as unconstrained for this process, the
prompt's "return only the JSON object" and the validate/repair loop take over, and the decision is
reported through `on_note` so it shows in the step log.
"""

from __future__ import annotations

import json

import httpx

from llm.base import LLMError, LLMRequest, OnNote, OnText, parse_reply
from llm.schema import strict_schema
from logsetup import log

TOO_LARGE_MARKERS = ("grammar is too large", "too large", "too complex")


class OpenAICompatibleLLM:
    name = "openai"

    def __init__(self, model: str, base_url: str, api_key: str = "", timeout: float = 600, extra_headers: dict | None = None,
                 temperature: float | None = 0.0, schema_bounds: bool = True):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        self.temperature = temperature  # None = omit (Claude 5 models reject the field)
        self.schema_bounds = schema_bounds  # False for Anthropic's endpoint, which rejects minimum/maximum/…
        self.unconstrained: set[str] = set()  # schema names this server refused to compile

    def _body(self, request: LLMRequest, constrained: bool) -> dict:
        body = {
            "model": self.model,
            "stream": True,
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": request.user}],
        }
        if constrained:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": request.schema_name, "strict": True,
                                "schema": strict_schema(request.schema, keep_bounds=self.schema_bounds)},
            }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        return body

    def complete(self, request: LLMRequest, on_text: OnText | None = None, on_note: OnNote | None = None) -> dict:
        constrained = request.schema_name not in self.unconstrained
        try:
            return self._stream(request, constrained, on_text)
        except SchemaTooLarge as exc:
            self.unconstrained.add(request.schema_name)
            msg = (f"this endpoint cannot compile the '{request.schema_name}' JSON schema into a grammar "
                   f"({exc}); retrying without constrained decoding — validation happens on our side")
            log.warning(msg)
            if on_note:
                on_note(msg)
            return self._stream(request, False, on_text)

    def _stream(self, request: LLMRequest, constrained: bool, on_text: OnText | None) -> dict:
        headers = dict(self.extra_headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        text = ""
        try:
            with httpx.stream("POST", f"{self.base_url}/chat/completions", json=self._body(request, constrained),
                              headers=headers, timeout=httpx.Timeout(self.timeout, connect=30)) as r:
                if r.status_code >= 400:
                    r.read()
                    detail = r.text[:400]
                    if constrained and r.status_code == 400 and any(m in detail.lower() for m in TOO_LARGE_MARKERS):
                        raise SchemaTooLarge(detail)
                    raise LLMError(f"chat/completions returned {r.status_code}: {detail}")
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    piece = (choices[0].get("delta") or {}).get("content")  # reasoning_content, if any, is ignored
                    if piece:
                        text += piece
                        if on_text:
                            on_text(text)
        except httpx.HTTPError as exc:
            raise LLMError(f"chat/completions request failed: {exc}") from exc
        return parse_reply(text)


class SchemaTooLarge(LLMError):
    """The server refused to compile the schema; the caller retries unconstrained."""
