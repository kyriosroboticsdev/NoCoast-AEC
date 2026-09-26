"""Generative BIM backend. Run: python main.py  (or: uvicorn main:app --port 8765)"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import config
from api.routes import OUTPUT_DIR, router

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="NoCoast generative BIM")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.mount("/models", StaticFiles(directory=OUTPUT_DIR), name="models")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config.PORT)
