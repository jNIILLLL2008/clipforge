"""
main.py -- The ASGI application.

    uvicorn backend.app.main:app --reload

Serves the API and the static frontend from one process, so a small deployment
is a single service behind one domain.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT, settings
from .db import init_db
from .logging_setup import get_logger, setup_logging
from .routes.api import router as api_router
from .routes.billing import router as billing_router
from .routes.studio import router as studio_router
from .scheduler import start_scheduler
from .worker import start_workers

setup_logging("DEBUG" if settings.debug else "INFO")
log = get_logger("main")

FRONTEND = ROOT / "frontend"

app = FastAPI(title="ClipForge", version="1.0.0", docs_url="/api/docs",
              redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(studio_router)
app.include_router(api_router)
app.include_router(billing_router)


@app.on_event("startup")
def on_startup() -> None:
    problems = settings.validate()
    if problems:
        for problem in problems:
            log.error("Config: %s", problem)
        if settings.env == "production":
            log.error("Refusing to start in production with these problems.")
            sys.exit(1)

    init_db()
    start_workers()
    start_scheduler()
    log.info("ClipForge ready on %s (env=%s)", settings.public_url, settings.env)


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse({
        "ok": True,
        "env": settings.env,
        "billing": settings.billing_enabled,
        "sources": settings.enabled_sources,
    })


#: Paths whose content changes during development and must never be cached.
_PAGE_PATHS = {"/", "/app"}


#: Assets that change on every deploy and whose filenames are not fingerprinted.
_REVALIDATE_SUFFIXES = (".css", ".js", ".html")


@app.middleware("http")
async def cache_frontend(request, call_next):
    """Tell the browser how long it may trust the frontend.

    In development nothing is cached at all. In production this used to send no
    Cache-Control header whatsoever, which is worse than it sounds: with only an
    ETag and a Last-Modified to go on, browsers fall back to *heuristic* caching
    and invent their own freshness window. A stylesheet could then outlive the
    deploy that changed it, and the new markup would render against the old CSS.

    Filenames here are not fingerprinted, so the fix is to make the browser
    revalidate. "no-cache" still lets it store the file; it just has to ask
    first, and the ETag turns that into a 304 with no body.
    """
    response = await call_next(request)
    path = request.url.path
    if not (path.startswith("/static") or path in _PAGE_PATHS):
        return response

    if settings.debug:
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    elif path in _PAGE_PATHS or path.endswith(_REVALIDATE_SUFFIXES):
        response.headers["Cache-Control"] = "no-cache"
    else:
        # Images and fonts change rarely. Rename the file to force a swap
        # sooner than this.
        response.headers["Cache-Control"] = "public, max-age=3600"
    return response


# Pages are served last so /api routes always win.
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

    @app.get("/")
    def landing() -> FileResponse:
        """The marketing page. Signing in happens at /app."""
        return FileResponse(FRONTEND / "landing.html")

    @app.get("/app")
    def studio_app() -> FileResponse:
        """The product itself, which shows its own sign-in when logged out."""
        return FileResponse(FRONTEND / "index.html")
