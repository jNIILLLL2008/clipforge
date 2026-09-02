"""
main.py -- The ASGI application.

    uvicorn backend.app.main:app --reload

Serves the API and the static frontend from one process, so a small deployment
is a single service behind one domain.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import security
from . import youtube as _youtube
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
        "build": settings.build_ref,
        "billing": settings.billing_enabled,
        # Whether this server *could* publish at all, which is a fact about
        # its configuration rather than about anybody's account. Without it,
        # "Publish did nothing" cannot be told apart from "this deploy has no
        # Google credentials" without logging in as somebody.
        "publishing": _youtube.configured(),
        "sources": settings.enabled_sources,
    })


#: Paths whose content changes during development and must never be cached.
_PAGE_PATHS = {"/", "/app", "/pair", "/privacy", "/terms", "/cookies"}


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


#: Rendered once each. Everything substituted below is fixed for the life of
#: the process, so the work is done on first request and then kept.
_PAGE_CACHE: Dict[str, str] = {}


def _optional_section() -> str:
    """The "Optional" block of the cookie policy.

    Two different pages depending on whether this deployment actually runs a
    tracker, because the honest answer differs and a policy that describes
    cookies the site does not set is as wrong as one that omits cookies it
    does.
    """
    if not settings.optional_trackers:
        return (
            "<p>\n"
            "  <strong>There are currently none.</strong> This deployment runs no\n"
            "  analytics, so nothing is set beyond the two entries above and there\n"
            "  is nothing to accept or decline. That is why you have not been shown\n"
            "  a cookie banner: a notice with no choice behind it is theatre.\n"
            "</p>\n"
            "<p>\n"
            "  If that changes, this table fills in, the banner appears, and nothing\n"
            "  optional loads until you have answered it.\n"
            "</p>"
        )

    return (
        "<p>\n"
        "  Off until you accept. Nothing below is loaded, and no request is made\n"
        "  to the domains involved, until you have said yes -- declining is not a\n"
        "  setting applied after the fact, it stops the script being fetched at\n"
        "  all. You can change your answer at any time.\n"
        "</p>\n"
        '<div class="legal-table-wrap">\n'
        '  <table class="legal-table">\n'
        "    <thead>\n"
        "      <tr><th>Name</th><th>Set by</th><th>What it does</th><th>Expires</th></tr>\n"
        "    </thead>\n"
        "    <tbody>\n"
        "      <tr>\n"
        "        <td>_ga</td>\n"
        "        <td>Google Analytics</td>\n"
        "        <td>Tells repeat visits apart so a page view is not counted as a new\n"
        "            person each time. We ask Google to truncate your IP address and\n"
        "            we switch off its advertising signals.</td>\n"
        "        <td>2 years</td>\n"
        "      </tr>\n"
        "      <tr>\n"
        "        <td>_ga_*</td>\n"
        "        <td>Google Analytics</td>\n"
        "        <td>Holds the state of the current visit for the specific property.</td>\n"
        "        <td>2 years</td>\n"
        "      </tr>\n"
        "    </tbody>\n"
        "  </table>\n"
        "</div>\n"
        "<p>\n"
        "  We use this to see which pages get read and where people give up. We do\n"
        "  not use it for advertising, and we have not enabled the settings that\n"
        "  would let Google build an advertising profile from it. Declining changes\n"
        "  nothing about how the product works.\n"
        "</p>"
    )


#: Token -> value, applied to every page served through _page_html. Kept in one
#: place so a policy page cannot drift from the config the app actually runs on
#: -- printing a company name or a contact address that nobody reads is how a
#: privacy notice ends up naming a controller who does not exist.
def _substitutions() -> Dict[str, str]:
    address = settings.legal_address.strip()
    trackers = settings.optional_trackers
    return {
        "__ORIGIN__": settings.public_url,
        "__LEGAL_ENTITY__": settings.legal_entity,
        "__LEGAL_EMAIL__": settings.legal_contact_email,
        "__LEGAL_JURISDICTION__": settings.legal_jurisdiction,
        "__LEGAL_UPDATED__": settings.legal_updated,
        # Written as a whole sentence, or omitted entirely. A policy with a
        # dangling "Registered at ." reads as unmaintained.
        "__LEGAL_ADDRESS_LINE__": f"We are at {address}." if address else "",
        "__PRICE_STARTER__": settings.price_label_starter,
        "__PRICE_PRO__": settings.price_label_pro,
        "__CONSENT_OPTIONAL__": ",".join(trackers),
        "__GA_ID__": settings.ga_measurement_id,
        "__TRACKER_COUNT__": str(len(trackers)) if trackers else "none",
        "__OPTIONAL_SECTION__": _optional_section(),
    }


def _page_html(name: str) -> str:
    """A frontend page with its tokens filled in.

    Served through substitution rather than as a static file because canonical
    and og:url have to be absolute, and a file on disk cannot know what domain
    it is being served from. The policy pages need it for a second reason: the
    contact address and the governing law belong in config, not in markup that
    a fork would forget to change.
    """
    cached = _PAGE_CACHE.get(name)
    if cached is not None and not settings.debug:
        return cached

    html = (FRONTEND / name).read_text(encoding="utf-8")
    for token, value in _substitutions().items():
        html = html.replace(token, value)
    _PAGE_CACHE[name] = html
    return html


def _landing_html() -> str:
    """Kept as a name because it reads better at the call site."""
    return _page_html("landing.html")


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

    @app.get("/privacy")
    def privacy() -> HTMLResponse:
        """What we collect and what you can make us do about it."""
        return HTMLResponse(_page_html("privacy.html"))

    @app.get("/terms")
    def terms() -> HTMLResponse:
        """The agreement somebody accepts by creating an account."""
        return HTMLResponse(_page_html("terms.html"))

    @app.get("/cookies")
    def cookies() -> HTMLResponse:
        """Every cookie by name, and the consent control for the optional ones."""
        return HTMLResponse(_page_html("cookies.html"))

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
            "Disallow: /pair\n"
            "Disallow: /api/\n"
            "\n"
            f"Sitemap: {settings.public_url}/sitemap.xml\n"
        )
        return Response(body, media_type="text/plain")

    #: Public pages, with how often each is worth recrawling. The policies
    #: change rarely but must be indexable: a privacy notice nobody can find
    #: is not much better than one that does not exist.
    _SITEMAP = (
        ("/", "weekly", "1.0"),
        ("/privacy", "yearly", "0.4"),
        ("/terms", "yearly", "0.4"),
        ("/cookies", "yearly", "0.3"),
    )

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap() -> Response:
        """The public pages, listed properly rather than not at all."""
        urls = "".join(
            f"  <url><loc>{settings.public_url}{path}</loc>"
            f"<changefreq>{freq}</changefreq>"
            f"<priority>{priority}</priority></url>\n"
            for path, freq, priority in _SITEMAP
        )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}"
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
- Privacy: {settings.public_url}/privacy
- Terms: {settings.public_url}/terms
- Cookies: {settings.public_url}/cookies
"""
        return Response(body, media_type="text/plain")

    @app.get("/app")
    def studio_app() -> HTMLResponse:
        """The product itself, which shows its own sign-in when logged out.

        Rendered rather than sent from disk because the cookie notice is
        configured through the same token substitution as the marketing pages.
        Serving this as a static file would ship the tokens unreplaced, and the
        consent script would treat the placeholder as the name of a tracker to
        ask about.
        """
        return HTMLResponse(_page_html("index.html"))

    @app.get("/pair")
    def pair_page() -> HTMLResponse:
        """Where a render agent sends the browser to be approved.

        The same file as /app: it already knows how to show a sign-in when
        logged out, which matters here because arriving signed out is the
        common case. Somebody who has just installed the agent is, more often
        than not, on a machine where they have not signed in yet.
        """
        return HTMLResponse(_page_html("index.html"))
