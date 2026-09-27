"""Claude adapter: the official Anthropic SDK with structured outputs, streamed.

Credentials come from the environment (ANTHROPIC_API_KEY in backend/.env, or an
`ant auth login` profile). The reply is constrained to the request's JSON schema with
`output_config.format`, so it always parses.

Anthropic's grammar compiler has a size limit that the build schema exceeds (a flat step
with ~40 optional fields compiles large). Such a request is retried once without
constrained decoding — the prompt's "return only the JSON object", the streaming parser
and the validate/repair loop take over — and the schema is remembered as unconstrained for
the rest of the process, so the cost is paid once. The decision is reported through
`on_note` so it shows up in the step log rather than silently changing behaviour.
"""

from __future__ import annotations

import os

import anthropic

from llm.base import LLMError, LLMRequest, OnNote, OnText, Usage, parse_reply
from llm.schema import strict_schema
from logsetup import log

DEFAULT_MODEL = "claude-opus-5"
TOO_LARGE_MARKERS = ("grammar is too large", "too large", "too complex")
# A whole building is a long reply: two storeys of rooms, openings, fit-out and a rationale per move
# runs well past 16k tokens. Override with LLM_MAX_TOKENS when a model's ceiling is lower.
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", 32000))


class SchemaTooLarge(LLMError):
    """Anthropic refused to compile the schema; the caller retries unconstrained."""


def user_content(request: LLMRequest) -> str | list[dict]:
    """The user turn: plain text, or text followed by each image after its caption."""
    if not request.images:
        return request.user
    parts: list[dict] = [{"type": "text", "text": request.user}]
    for i, image in enumerate(request.images, 1):
        parts.append({"type": "text", "text": f"Image {i}: {image.caption}"})
        parts.append({"type": "image", "source": {"type": "base64", "media_type": image.media_type, "data": image.b64()}})
    return parts


def usage_of(response) -> Usage:
    """Anthropic counts uncached input, cache writes and cache reads separately; together they are what was read."""
    u = response.usage
    written, read = u.cache_creation_input_tokens or 0, u.cache_read_input_tokens or 0
    return Usage(input_tokens=u.input_tokens + written + read, output_tokens=u.output_tokens, cached_tokens=read)


class ClaudeLLM:
    name = "claude"
    vision = True

    def __init__(self, model: str = DEFAULT_MODEL, timeout: float = 600, workspace_id: str = ""):
        self.model = model or DEFAULT_MODEL
        # Keys created at organisation level (not inside a workspace) must name the workspace per request.
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self.client = anthropic.Anthropic(timeout=timeout, default_headers=headers)
        self.unconstrained: set[str] = set()  # schema names this account's grammar compiler refused

    def complete(self, request: LLMRequest, on_text: OnText | None = None, on_note: OnNote | None = None) -> dict:
        constrained = request.schema_name not in self.unconstrained
        try:
            return self._stream(request, constrained, on_text)
        except SchemaTooLarge as exc:
            self.unconstrained.add(request.schema_name)
            note = (f"Anthropic cannot compile the '{request.schema_name}' schema into a grammar ({exc}); "
                    f"asking again without constrained decoding — the reply is validated on our side")
            log.warning(note)
            if on_note:
                on_note(note)
            return self._stream(request, False, on_text)

    def _stream(self, request: LLMRequest, constrained: bool, on_text: OnText | None) -> dict:
        text = ""
        extra = {}
        if constrained:
            extra["output_config"] = {"format": {"type": "json_schema", "schema": strict_schema(request.schema, keep_bounds=False)}}
        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=request.system,
                messages=[{"role": "user", "content": user_content(request)}],
                **extra,
            ) as stream:
                for piece in stream.text_stream:
                    text += piece
                    if on_text:
                        on_text(text)
                response = stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise LLMError("Anthropic authentication failed: set ANTHROPIC_API_KEY or run `ant auth login`") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError(f"Anthropic rate limit: {exc.message}") from exc
        except anthropic.BadRequestError as exc:
            if constrained and any(m in exc.message.lower() for m in TOO_LARGE_MARKERS):
                raise SchemaTooLarge(exc.message) from exc
            hint = ""
            if "anthropic-workspace-id" in exc.message:
                hint = " — set ANTHROPIC_WORKSPACE_ID in backend/.env (Console → Settings → Workspaces), or create the key inside a workspace"
            raise LLMError(f"Anthropic rejected the request: {exc.message}{hint}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"cannot reach the Anthropic API: {exc}") from exc
        request.usage = (request.usage or Usage()) + usage_of(response)   # a retry without a grammar adds to the first try
        if response.stop_reason == "refusal":
            raise LLMError("the model declined this request")
        if response.stop_reason == "max_tokens":
            raise LLMError("the model's answer was cut off (max_tokens)")
        return parse_reply(text)
