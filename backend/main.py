"""Generative BIM backend. Run: python main.py  (or: uvicorn main:app --port 8765)"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import config
from api.routes import OUTPUT_DIR, router, store
from core import replay
from logsetup import log

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
log.info("config: provider=%s model=%r base_url=%r output=%s", config.LLM_PROVIDER, config.LLM_MODEL or None,
         config.LLM_BASE_URL or None, OUTPUT_DIR)
replay.seed(store, config.DEMO_DIR)

app = FastAPI(title="NoCoast generative BIM")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.mount("/models", StaticFiles(directory=OUTPUT_DIR), name="models")

if __name__ == "__main__":
    log.info("listening on http://127.0.0.1:%d", config.PORT)
    uvicorn.run(app, host="127.0.0.1", port=config.PORT, log_level=config.LOG_LEVEL.lower())
