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


@app.middleware("http")
async def no_cache_frontend(request, call_next):
    """Serve the frontend uncached in development.

    This covers the HTML pages as well as /static. Without it the browser keeps
    an old styles.css after an edit -- or worse, keeps serving a cached "/" from
    before that route changed, so the new page appears not to exist at all.
    """
    response = await call_next(request)
    path = request.url.path
    if settings.debug and (path.startswith("/static") or path in _PAGE_PATHS):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
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
