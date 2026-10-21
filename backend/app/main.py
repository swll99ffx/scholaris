"""
Scholaris API entry point.

Run with:  uvicorn app.main:app --reload   (from the backend/ folder)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import ROOT_DIR, get_settings
from app.core.access import (
    AccessMiddleware,
    cookie_secure,
    issue_session,
    password_matches,
    session_valid,
)
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
    version="1.0.0",
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
# Rate limits + optional shared-password gate (no-op when SITE_PASSWORD is empty).
app.add_middleware(AccessMiddleware, settings=settings)

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


# --------------------------------------------------------------- access gate


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class AccessStatus(BaseModel):
    required: bool
    authenticated: bool


@app.get("/api/auth/status", response_model=AccessStatus, tags=["auth"])
async def auth_status(request: Request) -> AccessStatus:
    required = bool(settings.site_password)
    authenticated = not required or session_valid(
        settings.site_password,
        request.cookies.get(settings.session_cookie_name),
    )
    return AccessStatus(required=required, authenticated=authenticated)


@app.post("/api/auth/login", tags=["auth"])
async def auth_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> dict[str, bool]:
    if not settings.site_password:
        return {"ok": True}
    if not password_matches(settings.site_password, payload.password):
        raise HTTPException(status_code=401, detail="Incorrect access code.")
    response.set_cookie(
        settings.session_cookie_name,
        issue_session(settings.site_password, settings.session_ttl_seconds),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(settings, request),
        path="/",
    )
    return {"ok": True}


@app.post("/api/auth/logout", tags=["auth"])
async def auth_logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"ok": True}


# ------------------------------------------------------------ built frontend
# In production a single process serves both the API and the built React app,
# so there is no CORS setup and no second URL to configure.

FRONTEND_DIST = (
    Path(settings.frontend_dist).expanduser()
    if settings.frontend_dist
    else ROOT_DIR / "frontend" / "dist"
)

if FRONTEND_DIST.is_dir():
    _assets = FRONTEND_DIST / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (FRONTEND_DIST / full_path).resolve()
        if FRONTEND_DIST.resolve() in candidate.parents and candidate.is_file():
            response = FileResponse(candidate)
            # The app shell and service worker must revalidate so updates land.
            if candidate.name in {"index.html", "sw.js", "manifest.webmanifest"}:
                response.headers["Cache-Control"] = "no-cache"
            return response
        response = FileResponse(FRONTEND_DIST / "index.html")
        response.headers["Cache-Control"] = "no-cache"
        return response
