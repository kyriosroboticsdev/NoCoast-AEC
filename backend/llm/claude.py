"""Claude adapter: the official Anthropic SDK with structured outputs, streamed.

Credentials come from the environment (ANTHROPIC_API_KEY in backend/.env, or an
`ant auth login` profile). The reply is constrained to the request's JSON schema
with `output_config.format`, so it always parses.
"""

from __future__ import annotations

import anthropic

from llm.base import LLMError, LLMRequest, OnNote, OnText, parse_reply
from llm.schema import strict_schema

DEFAULT_MODEL = "claude-opus-5"


def user_content(request: LLMRequest) -> str | list[dict]:
    """The user turn: plain text, or text followed by each image after its caption."""
    if not request.images:
        return request.user
    parts: list[dict] = [{"type": "text", "text": request.user}]
    for i, image in enumerate(request.images, 1):
        parts.append({"type": "text", "text": f"Image {i}: {image.caption}"})
        parts.append({"type": "image", "source": {"type": "base64", "media_type": image.media_type, "data": image.b64()}})
    return parts


class ClaudeLLM:
    name = "claude"
    vision = True

    def __init__(self, model: str = DEFAULT_MODEL, timeout: float = 600, workspace_id: str = ""):
        self.model = model or DEFAULT_MODEL
        # Keys created at organisation level (not inside a workspace) must name the workspace per request.
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self.client = anthropic.Anthropic(timeout=timeout, default_headers=headers)

    def complete(self, request: LLMRequest, on_text: OnText | None = None, on_note: OnNote | None = None) -> dict:
        text = ""
        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=16000,
                system=request.system,
                messages=[{"role": "user", "content": user_content(request)}],
                output_config={"format": {"type": "json_schema", "schema": strict_schema(request.schema, keep_bounds=False)}},
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
            hint = ""
            if "anthropic-workspace-id" in exc.message:
                hint = " — set ANTHROPIC_WORKSPACE_ID in backend/.env (Console → Settings → Workspaces), or create the key inside a workspace"
            raise LLMError(f"Anthropic rejected the request: {exc.message}{hint}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"cannot reach the Anthropic API: {exc}") from exc
        if response.stop_reason == "refusal":
            raise LLMError("the model declined this request")
        if response.stop_reason == "max_tokens":
            raise LLMError("the model's answer was cut off (max_tokens)")
        return parse_reply(text)
