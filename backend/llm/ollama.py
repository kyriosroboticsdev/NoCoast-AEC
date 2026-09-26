"""Ollama adapter: local models through /api/chat with a JSON-schema `format`."""

from __future__ import annotations

import json

import httpx

from llm.base import LLMError, LLMRequest
from llm.schema import strict_schema


class OllamaLLM:
    name = "ollama"

    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434", timeout: float = 600):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(self, request: LLMRequest) -> dict:
        body = {
            "model": self.model,
            "stream": False,
            "format": strict_schema(request.schema),  # constrained decoding: the reply is guaranteed to parse
            "options": {"temperature": 0, "num_ctx": 16384},
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": request.user}],
        }
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama request failed: {exc}") from exc
        content = r.json().get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"ollama returned non-JSON: {content[:200]!r}") from exc
