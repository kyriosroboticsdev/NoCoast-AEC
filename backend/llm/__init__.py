"""LLM adapter registry. The rest of the backend only sees the `LLM` protocol.

    LLM_PROVIDER=mock     rule-based stand-in, no network (default; what the tests use)
    LLM_PROVIDER=ollama   local model via Ollama's /api/chat with JSON-schema output
    LLM_PROVIDER=openai   any OpenAI-compatible /chat/completions endpoint (vLLM, LM Studio,
                          llama.cpp server, a hosted provider, a future fine-tuned model…)
"""

from __future__ import annotations

import config
from llm.base import LLM, LLMError, LLMRequest
from llm.mock import MockLLM
from llm.ollama import OllamaLLM
from llm.openai_compat import OpenAICompatibleLLM

PROVIDERS = {"mock": MockLLM, "ollama": OllamaLLM, "openai": OpenAICompatibleLLM}


def get_llm(provider: str | None = None) -> LLM:
    name = provider or config.LLM_PROVIDER
    if name not in PROVIDERS:
        raise LLMError(f"unknown LLM provider '{name}' (available: {', '.join(PROVIDERS)})")
    if name == "mock":
        return MockLLM()
    if name == "ollama":
        return OllamaLLM(model=config.LLM_MODEL or "llama3.1", base_url=config.LLM_BASE_URL or "http://127.0.0.1:11434",
                         timeout=config.LLM_TIMEOUT)
    return OpenAICompatibleLLM(model=config.LLM_MODEL, base_url=config.LLM_BASE_URL or "http://127.0.0.1:8080/v1",
                               api_key=config.LLM_API_KEY, timeout=config.LLM_TIMEOUT)


__all__ = ["LLM", "LLMError", "LLMRequest", "get_llm", "PROVIDERS"]
