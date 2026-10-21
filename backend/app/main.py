"""
Scholaris API entry point.

Run with:  uvicorn app.main:app --reload   (from the backend/ folder)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.llm import LLMClient
from app.modules.research.router import router as research_router
from app.modules.research.services import library
from app.modules.summarize.router import router as summarize_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    library.init_db(settings.database_path)
    logging.getLogger(__name__).info("Database ready at %s", settings.database_path)
    yield


app = FastAPI(
    title="Scholaris API",
    version="0.2.1",
    description="Study smarter, not harder. Modules: Research Source Finder, Source Summarizer.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Allows the Vite dev server to be reached from a phone on the same Wi-Fi.
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(research_router)
app.include_router(summarize_router)


@app.get("/api/health", tags=["system"])
async def health() -> dict[str, str]:
    # "key"  -> the user's own AI endpoint (fast, parallel)
    # "free" -> the built-in keyless AI
    # "off"  -> offline only (heuristic notes + raw queries)
    if settings.llm_enabled:
        ai = "key"
    elif LLMClient(settings).available:
        ai = "free"
    else:
        ai = "off"
    return {"status": "ok", "app": settings.app_name, "version": app.version, "ai": ai}
