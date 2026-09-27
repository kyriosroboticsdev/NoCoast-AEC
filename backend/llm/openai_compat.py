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

from llm.base import LLMError, LLMRequest, OnNote, OnText, Usage, parse_reply
from llm.schema import strict_schema
from logsetup import log

TOO_LARGE_MARKERS = ("grammar is too large", "too large", "too complex")
USAGE_MARKERS = ("stream_options", "include_usage")


def usage_of(chunk: dict) -> Usage | None:
    """Token counts from a streamed chunk that carries them (the last one, when `include_usage` is on)."""
    u = chunk.get("usage")
    if not isinstance(u, dict) or u.get("prompt_tokens") is None:
        return None
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    return Usage(input_tokens=int(u["prompt_tokens"]), output_tokens=int(u.get("completion_tokens") or 0), cached_tokens=int(cached))


def user_content(request: LLMRequest) -> str | list[dict]:
    """The user message: plain text, or text followed by each image (as a data URL) after its caption."""
    if not request.images:
        return request.user
    parts: list[dict] = [{"type": "text", "text": request.user}]
    for i, image in enumerate(request.images, 1):
        parts.append({"type": "text", "text": f"Image {i}: {image.caption}"})
        parts.append({"type": "image_url", "image_url": {"url": f"data:{image.media_type};base64,{image.b64()}"}})
    return parts


class OpenAICompatibleLLM:
    name = "openai"

    def __init__(self, model: str, base_url: str, api_key: str = "", timeout: float = 600, extra_headers: dict | None = None,
                 temperature: float | None = 0.0, schema_bounds: bool = True, vision: bool = False):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        self.temperature = temperature  # None = omit (Claude 5 models reject the field)
        self.schema_bounds = schema_bounds  # False for Anthropic's endpoint, which rejects minimum/maximum/…
        self.unconstrained: set[str] = set()  # schema names this server refused to compile
        self.ask_usage = True  # ask for token counts in the stream; turned off if the server refuses the option
        self.vision = vision  # the server's model accepts image parts (LLM_VISION)

    def _body(self, request: LLMRequest, constrained: bool) -> dict:
        body = {
            "model": self.model,
            "stream": True,
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": user_content(request)}],
        }
        if constrained:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": request.schema_name, "strict": True,
                                "schema": strict_schema(request.schema, keep_bounds=self.schema_bounds)},
            }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.ask_usage:
            body["stream_options"] = {"include_usage": True}
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
                    if self.ask_usage and r.status_code in (400, 422) and any(m in detail.lower() for m in USAGE_MARKERS):
                        # A server that does not know the option: go without counts (they are estimated instead).
                        log.warning("this endpoint rejects stream_options; token counts will be estimated")
                        self.ask_usage = False
                        return self._stream(request, constrained, on_text)
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
                    request.usage = usage_of(chunk) or request.usage   # arrives on a chunk of its own, without choices
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
