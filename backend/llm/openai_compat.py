"""OpenAI-compatible adapter: any server that speaks POST /chat/completions.

Covers vLLM, LM Studio, llama.cpp's server, LocalAI and hosted providers, so a
specifically trained model can be dropped in by changing three env vars.
"""

from __future__ import annotations

import json
import re

import httpx

from llm.base import LLMError, LLMRequest
from llm.schema import strict_schema


class OpenAICompatibleLLM:
    name = "openai"

    def __init__(self, model: str, base_url: str, api_key: str = "", timeout: float = 600):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def complete(self, request: LLMRequest) -> dict:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": request.user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": request.schema_name, "schema": strict_schema(request.schema)},
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"chat/completions request failed: {exc}") from exc
        try:
            content = r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"unexpected chat/completions response: {r.text[:200]!r}") from exc
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())  # servers without grammar support may fence it
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"model returned non-JSON: {content[:200]!r}") from exc
