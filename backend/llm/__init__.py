"""LLM adapter registry. The rest of the backend only sees the `LLM` protocol.

    LLM_PROVIDER=mock     rule-based stand-in, no network (default; what the tests use)
    LLM_PROVIDER=ollama   local model via Ollama's /api/chat with JSON-schema output
    LLM_PROVIDER=openai   any OpenAI-compatible /chat/completions endpoint (vLLM, LM Studio,
                          llama.cpp server, a hosted provider, a future fine-tuned model…)
    LLM_PROVIDER=claude   Anthropic API via the official SDK (ANTHROPIC_API_KEY), structured outputs
    LLM_PROVIDER=llamacpp a local .gguf served by llama-server, started on demand (LLM_MODEL, LLM_MODELS_DIR)
"""

from __future__ import annotations

import config
from llm.base import LLM, LLMError, LLMRequest
from llm.claude import ClaudeLLM
from llm.llamacpp import LlamaCppLLM, env_defaults
from llm.mock import MockLLM
from llm.ollama import OllamaLLM
from llm.openai_compat import OpenAICompatibleLLM

PROVIDERS = {"mock": MockLLM, "ollama": OllamaLLM, "openai": OpenAICompatibleLLM, "claude": ClaudeLLM, "llamacpp": LlamaCppLLM}
_singletons: dict[str, LLM] = {}  # llamacpp owns a server process; keep one instance


def get_llm(provider: str | None = None) -> LLM:
    config.reload()  # pick up .env edits (provider, model, key) without a restart
    name = provider or config.LLM_PROVIDER
    if name not in PROVIDERS:
        raise LLMError(f"unknown LLM provider '{name}' (available: {', '.join(PROVIDERS)})")
    if name == "mock":
        return MockLLM()
    if name == "claude":
        return ClaudeLLM(model=config.LLM_MODEL, timeout=config.LLM_TIMEOUT, workspace_id=config.ANTHROPIC_WORKSPACE_ID)
    if name == "llamacpp":
        if not config.LLM_MODEL:
            raise LLMError("LLM_MODEL must name a .gguf file for the llamacpp provider")
        current = _singletons.get("llamacpp")
        if current is not None and current.model != config.LLM_MODEL:
            current.stop()  # model changed in .env: drop the old server
            current = None
        if current is None:
            current = _singletons["llamacpp"] = LlamaCppLLM(
                model=config.LLM_MODEL, models_dir=config.LLM_MODELS_DIR, server=config.LLAMA_SERVER,
                base_url=config.LLM_BASE_URL, timeout=config.LLM_TIMEOUT, **env_defaults())
        return current
    if name == "ollama":
        return OllamaLLM(model=config.LLM_MODEL or "llama3.1", base_url=config.LLM_BASE_URL or "http://127.0.0.1:11434",
                         timeout=config.LLM_TIMEOUT)
    return OpenAICompatibleLLM(model=config.LLM_MODEL, base_url=config.LLM_BASE_URL or "http://127.0.0.1:8080/v1",
                               api_key=config.LLM_API_KEY, timeout=config.LLM_TIMEOUT)


__all__ = ["LLM", "LLMError", "LLMRequest", "get_llm", "PROVIDERS"]
