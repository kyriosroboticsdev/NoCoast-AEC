"""llama.cpp adapter: serve a local .gguf with `llama-server` and talk to it as OpenAI-compatible.

    LLM_PROVIDER=llamacpp
    LLM_MODEL=qwen3-4b-instruct-2507-q4_k_m.gguf   # file name in LLM_MODELS_DIR, or an absolute path
    LLM_MODELS_DIR=D:\\Models
    LLAMA_SERVER=<path to llama-server.exe>          # default: backend/.llama/llama-server.exe (see tools/get_llama.py)
    LLM_BASE_URL=http://127.0.0.1:8080/v1            # default; if a server already answers here it is reused

The server is started on first use and stopped when the backend exits. JSON output is
enforced by llama.cpp's grammar sampling from the request's JSON schema.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import time
from pathlib import Path

import httpx

from llm.base import LLMError, LLMRequest, OnNote, OnText
from llm.openai_compat import OpenAICompatibleLLM
from logsetup import log

DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_SERVER = Path(__file__).resolve().parent.parent / ".llama" / "llama-server.exe"
STARTUP_TIMEOUT = 180  # seconds to load the model


class LlamaCppLLM(OpenAICompatibleLLM):
    name = "llamacpp"

    def __init__(self, model: str, models_dir: str = "", server: str = "", base_url: str = "", timeout: float = 600,
                 n_gpu_layers: int = 99, ctx: int = 16384):
        super().__init__(model=model, base_url=base_url or DEFAULT_BASE_URL, timeout=timeout)
        self.gguf = Path(model) if Path(model).is_absolute() else Path(models_dir or ".") / model
        self.server = Path(server) if server else DEFAULT_SERVER
        self.n_gpu_layers = n_gpu_layers
        self.ctx = ctx
        self.process: subprocess.Popen | None = None
        self.logfile = self.server.parent / "server.log"

    # --- server lifecycle ------------------------------------------------

    def _root(self) -> str:
        return self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url

    def _healthy(self) -> bool:
        try:
            return httpx.get(f"{self._root()}/health", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def ensure_server(self) -> None:
        if self._healthy():
            return
        if self.process and self.process.poll() is None:
            self._wait()
            return
        if not self.gguf.is_file():
            raise LLMError(f"model file not found: {self.gguf} (set LLM_MODEL and LLM_MODELS_DIR)")
        if not self.server.is_file():
            raise LLMError(f"llama-server not found at {self.server}; run `python tools/get_llama.py` or set LLAMA_SERVER")
        port = self.base_url.split(":")[-1].split("/")[0]
        cmd = [str(self.server), "-m", str(self.gguf), "--port", port, "--host", "127.0.0.1",
               "-ngl", str(self.n_gpu_layers), "-c", str(self.ctx), "--jinja", "--log-colors", "off"]
        self.logfile = self.server.parent / "server.log"
        log.info("starting llama-server (log: %s): %s", self.logfile, " ".join(cmd))
        self.process = subprocess.Popen(cmd, cwd=self.server.parent, stdout=open(self.logfile, "wb"), stderr=subprocess.STDOUT,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        atexit.register(self.stop)
        self._wait()

    def _wait(self) -> None:
        t0 = time.time()
        while time.time() - t0 < STARTUP_TIMEOUT:
            if self._healthy():
                log.info("llama-server ready (%s) after %.0fs", self.gguf.name, time.time() - t0)
                return
            if self.process and self.process.poll() is not None:
                tail = ""
                try:
                    tail = self.logfile.read_text(errors="replace").strip().splitlines()[-1]
                except (OSError, IndexError):
                    pass
                raise LLMError(f"llama-server exited with code {self.process.returncode} while loading {self.gguf.name}: {tail}"
                               f" (full log: {self.logfile})")
            time.sleep(1)
        raise LLMError(f"llama-server did not become healthy within {STARTUP_TIMEOUT}s")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()

    # --- LLM ---------------------------------------------------------------

    def complete(self, request: LLMRequest, on_text: OnText | None = None, on_note: OnNote | None = None) -> dict:
        self.ensure_server()
        return super().complete(request, on_text, on_note)


def env_defaults() -> dict:
    """Extra environment knobs read here so config.py stays small."""
    return {"n_gpu_layers": int(os.environ.get("LLAMA_GPU_LAYERS", 99)), "ctx": int(os.environ.get("LLAMA_CTX", 16384))}
