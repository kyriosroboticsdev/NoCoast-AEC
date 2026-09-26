"""Claude adapter: the official Anthropic SDK with structured outputs.

Credentials come from the environment (ANTHROPIC_API_KEY in backend/.env, or an
`ant auth login` profile). The reply is constrained to the request's JSON schema
with `output_config.format`, so it always parses.
"""

from __future__ import annotations

import json

import anthropic

from llm.base import LLMError, LLMRequest
from llm.schema import strict_schema

DEFAULT_MODEL = "claude-opus-5"


class ClaudeLLM:
    name = "claude"

    def __init__(self, model: str = DEFAULT_MODEL, timeout: float = 600, workspace_id: str = ""):
        self.model = model or DEFAULT_MODEL
        # Keys created at organisation level (not inside a workspace) must name the workspace per request.
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self.client = anthropic.Anthropic(timeout=timeout, default_headers=headers)

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
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"model returned non-JSON: {text[:200]!r}") from exc
