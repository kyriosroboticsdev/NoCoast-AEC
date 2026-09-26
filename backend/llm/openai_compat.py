"""OpenAI-compatible adapter: any server that speaks POST /chat/completions with SSE streaming.

Covers Fireworks, vLLM, LM Studio, llama.cpp's server, LocalAI and hosted providers, so a
specifically trained model can be dropped in by changing three env vars.
"""

from __future__ import annotations

import json

import httpx

from llm.base import LLMError, LLMRequest, OnText, parse_reply
from llm.schema import strict_schema


class OpenAICompatibleLLM:
    name = "openai"

    def __init__(self, model: str, base_url: str, api_key: str = "", timeout: float = 600):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _body(self, request: LLMRequest) -> dict:
        return {
            "model": self.model,
            "temperature": 0,
            "stream": True,
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": request.user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": request.schema_name, "schema": strict_schema(request.schema)},
            },
        }

    def complete(self, request: LLMRequest, on_text: OnText | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        text = ""
        try:
            with httpx.stream("POST", f"{self.base_url}/chat/completions", json=self._body(request), headers=headers,
                              timeout=httpx.Timeout(self.timeout, connect=30)) as r:
                if r.status_code >= 400:
                    r.read()
                    raise LLMError(f"chat/completions returned {r.status_code}: {r.text[:400]}")
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
