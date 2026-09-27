"""Ollama adapter: local models through /api/chat with a JSON-schema `format`, streamed as NDJSON."""

from __future__ import annotations

import json

import httpx

from llm.base import LLMError, LLMRequest, OnNote, OnText, parse_reply
from llm.schema import strict_schema


def user_message(request: LLMRequest) -> dict:
    """Ollama attaches images to the message as base64 strings; their captions go in the text."""
    if not request.images:
        return {"role": "user", "content": request.user}
    return {"role": "user", "content": request.captioned_text(), "images": [im.b64() for im in request.images]}


class OllamaLLM:
    name = "ollama"

    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434", timeout: float = 600, vision: bool = False):
        self.model = model
        self.vision = vision  # a multimodal model (llava, llama3.2-vision, qwen2.5vl …); set LLM_VISION=1
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(self, request: LLMRequest, on_text: OnText | None = None, on_note: OnNote | None = None) -> dict:
        body = {
            "model": self.model,
            "stream": True,
            "format": strict_schema(request.schema),  # constrained decoding: the reply is guaranteed to parse
            "options": {"temperature": 0, "num_ctx": 16384},
            "messages": [{"role": "system", "content": request.system}, user_message(request)],
        }
        text = ""
        try:
            with httpx.stream("POST", f"{self.base_url}/api/chat", json=body, timeout=httpx.Timeout(self.timeout, connect=30)) as r:
                if r.status_code >= 400:
                    r.read()
                    raise LLMError(f"ollama returned {r.status_code}: {r.text[:400]}")
                for line in r.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = (chunk.get("message") or {}).get("content")
                    if piece:
                        text += piece
                        if on_text:
                            on_text(text)
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama request failed: {type(exc).__name__}: {exc}") from exc
        return parse_reply(text)
