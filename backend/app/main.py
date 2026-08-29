"""
main.py -- The ASGI application.

    uvicorn backend.app.main:app --reload

Serves the API and the static frontend from one process, so a small deployment
is a single service behind one domain.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import security
from .config import ROOT, settings
from .db import init_db
from .logging_setup import get_logger, setup_logging
from .routes.agent import router as agent_router
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

# No wildcard fallback. "*" together with allow_credentials makes Starlette
# echo whichever Origin asked, which hands any site on the internet an
# authenticated cross-origin request. An empty list means same-origin only,
# which is all this app needs: the frontend is served from here, and the render
# agent is a Python client that CORS does not apply to.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

security.install(app)

app.include_router(studio_router)
app.include_router(api_router)
app.include_router(agent_router)
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


@app.exception_handler(404)
async def not_found(request, exc):
    """A styled page for people, JSON for anything under /api.

    A framework's default {"detail":"Not Found"} in the browser is one of the
    clearest signs nobody looked at the site from outside.
    """
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": "Not found."}, status_code=404)
    page = FRONTEND / "404.html"
    if page.is_file():
        return FileResponse(page, status_code=404)
    return JSONResponse({"detail": "Not found."}, status_code=404)


#: Rendered once. PUBLIC_URL is fixed for the life of the process.
_LANDING_CACHE: Optional[str] = None


def _landing_html() -> str:
    """landing.html with __ORIGIN__ replaced by the real public URL."""
    global _LANDING_CACHE
    if _LANDING_CACHE is None or settings.debug:
        raw = (FRONTEND / "landing.html").read_text(encoding="utf-8")
        _LANDING_CACHE = raw.replace("__ORIGIN__", settings.public_url)
    return _LANDING_CACHE


# Pages are served last so /api routes always win.
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

    @app.get("/")
    def landing() -> HTMLResponse:
        """The marketing page. Signing in happens at /app.

        Served through a one-token substitution rather than as a static file:
        canonical, og:url and og:image all have to be absolute, and a file on
        disk cannot know what domain it is being served from. Rendered once and
        kept, because the answer only changes when PUBLIC_URL does.
        """
        return HTMLResponse(_landing_html())

    @app.get("/robots.txt", include_in_schema=False)
    def robots() -> Response:
        """Crawlers, including the AI ones.

        They are allowed on purpose. This is a product that wants to be found,
        and blocking the assistants people now ask for recommendations is
        giving up a channel to avoid a cost that is not being charged.
        """
        body = (
            "User-agent: *\n"
            "Allow: /\n"
            # Nothing behind the sign-in is useful to a crawler, and the API
            # returns JSON that would only pollute an index.
            "Disallow: /app\n"
            "Disallow: /api/\n"
            "\n"
            f"Sitemap: {settings.public_url}/sitemap.xml\n"
        )
        return Response(body, media_type="text/plain")

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap() -> Response:
        """One public page, listed properly rather than not at all."""
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"  <url><loc>{settings.public_url}/</loc>"
            "<changefreq>weekly</changefreq><priority>1.0</priority></url>\n"
            "</urlset>\n"
        )
        return Response(body, media_type="application/xml")

    @app.get("/llms.txt", include_in_schema=False)
    def llms() -> Response:
        """What this is, for an assistant reading the site rather than a person.

        The convention is a short, factual description at a fixed path. Written
        plainly and without marketing, because the failure mode is an assistant
        repeating a claim that is not true.
        """
        body = f"""# ClipForge

> Finds and ranks source clips on YouTube, cuts them into short-form vertical
> video, scores the result against a retention model before rendering, and
> publishes it to your YouTube channel on a schedule.

## What it does

- Footage arrives one of two ways: clips you upload, or YouTube, where it
  collects the candidates for a show, channel or search and ranks them itself.
  Sourcing from YouTube is off unless the operator has turned it on.
- It cuts them to a chosen format: countdown, meme cut, calm loop, or one
  specific TV show.
- Every video is scored before a frame is encoded. Below 55 the run is
  rejected, the reason is reported, and the run is refunded.
- Finished videos are uploaded to a connected YouTube channel, private by
  default.

## What it does not do

- It does not make someone else's footage safe to re-upload. Re-cutting does
  not move the rights, and Content ID matches the content itself regardless of
  who posted it.
- It does not include stock or public-domain libraries. Those carry no
  broadcast, sport or gaming footage, which is what it is used for.

## Plans

- Free: 3 videos a month, watermarked, no scheduling.
- Starter: {settings.price_label_starter}, 40 videos a month, daily automation.
- Pro: {settings.price_label_pro}, 300 videos a month, priority rendering.

## Links

- Home: {settings.public_url}/
- App: {settings.public_url}/app
"""
        return Response(body, media_type="text/plain")

    @app.get("/app")
    def studio_app() -> FileResponse:
        """The product itself, which shows its own sign-in when logged out."""
        return FileResponse(FRONTEND / "index.html")
