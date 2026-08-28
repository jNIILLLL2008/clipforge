"""
config.py -- One settings object, read from the environment.

Deployment-specific values live in ``.env``; nothing here hardcodes a secret.
The defaults are safe for local development and refuse to start in production
with a development signing key.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import List

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DEV_SECRET = "dev-only-not-for-production"


def _str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, "") or default)
    except ValueError:
        return default


def _bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _list(key: str, default: str = "") -> List[str]:
    return [part.strip() for part in _str(key, default).split(",") if part.strip()]


def _normalise_public_url(url: str) -> str:
    """Guarantee PUBLIC_URL carries a scheme.

    Stripe and Google both reject a bare host, so a value like
    ``example.com`` turns every checkout into a 500 at the exact moment a
    customer is trying to pay. Hosting dashboards show domains without the
    scheme, so pasting one in is the obvious mistake to make.

    Anything that is not clearly local gets https, because a production
    redirect over http would leak the session cookie.
    """
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    local = url.startswith(("localhost", "127.0.0.1", "0.0.0.0", "[::1]"))
    return f"{'http' if local else 'https'}://{url}"


def _normalise_db_url(url: str) -> str:
    """Accept the connection string a host hands you, unchanged.

    Railway, Render and Fly all expose ``postgresql://…``; Heroku still emits
    the older ``postgres://``, which SQLAlchemy refuses outright. Neither names
    a driver, so SQLAlchemy reaches for psycopg2 and fails on an install that
    only has psycopg 3.

    Rewriting it here means an operator can paste the platform's variable
    straight in -- ``${{Postgres.DATABASE_URL}}`` on Railway -- instead of
    hand-editing a URL and getting it subtly wrong.
    """
    url = (url or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Settings:
    def __init__(self) -> None:
        self.env: str = _str("ENV", "development")
        self.debug: bool = _bool("DEBUG", self.env != "production")

        # --- security ---------------------------------------------------- #
        self.secret_key: str = _str("SECRET_KEY", DEV_SECRET)
        self.token_hours: int = _int("TOKEN_HOURS", 24 * 14)
        self.cors_origins: List[str] = _list(
            "CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
        )

        # --- storage ----------------------------------------------------- #
        self.storage_dir: Path = Path(_str("STORAGE_DIR", str(ROOT / "storage")))
        self.upload_dir: Path = self.storage_dir / "uploads"
        self.render_dir: Path = self.storage_dir / "renders"
        self.cache_dir: Path = self.storage_dir / "cache"
        self.database_url: str = _normalise_db_url(
            _str("DATABASE_URL", f"sqlite:///{(ROOT / 'clipforge.db').as_posix()}")
        )

        # --- media ------------------------------------------------------- #
        self.ffmpeg: str = _str("FFMPEG_BINARY", "ffmpeg")
        self.ffprobe: str = _str("FFPROBE_BINARY", "ffprobe")
        self.max_upload_mb: int = _int("MAX_UPLOAD_MB", 512)
        self.render_workers: int = _int("RENDER_WORKERS", 2)

        # The daily scheduler lives inside the web process. Running more than
        # one web process therefore means more than one scheduler, and an
        # account could be published twice in a day. Set this false on every
        # instance except one when scaling out.
        self.run_scheduler: bool = _bool("RUN_SCHEDULER", True)

        # --- content sources --------------------------------------------- #
        # Only sources licensed for commercial reuse are on by default. The
        # scraping adapter exists but stays off unless an operator turns it on
        # and accepts what that means for their own liability.
        self.enabled_sources: List[str] = _list(
            "ENABLED_SOURCES", "upload"
        )
        self.allow_unlicensed_sources: bool = _bool("ALLOW_UNLICENSED_SOURCES", False)

        # yt-dlp, used only by the unlicensed YouTube adapter. A cookies file
        # exported from a signed-in browser gets past age gates and the
        # "confirm you're not a bot" interstitial that hits datacentre IPs.
        self.ytdlp_cookies_file: str = _str("YTDLP_COOKIES_FILE")
        # YouTube answers different "player clients" differently, and which
        # ones work shifts week to week. Tried in order until one returns
        # something, so a client going bad degrades instead of breaking.
        self.ytdlp_player_clients: List[str] = _list(
            "YTDLP_PLAYER_CLIENTS", "default,android,web_safari,tv")
        # The industrial answer to datacentre blocking. An operator points this
        # at a residential proxy once and no subscriber ever hears about it.
        self.ytdlp_proxy: str = _str("YTDLP_PROXY")
        # yt-dlp needs a JS runtime for YouTube's player challenges. The image
        # installs deno; this lets an operator point at another one.
        self.ytdlp_js_runtime: str = _str("YTDLP_JS_RUNTIME")
        # A container has nowhere to put a cookies.txt and no browser to
        # read one from, so the jar can be pasted straight into an env var.
        self.ytdlp_cookies_content: str = _str("YTDLP_COOKIES_CONTENT")
        # Desktop only: chrome, firefox, edge, brave...
        self.ytdlp_cookies_from_browser: str = _str("YTDLP_COOKIES_FROM_BROWSER")

        # --- AI ---------------------------------------------------------- #
        self.anthropic_api_key: str = _str("ANTHROPIC_API_KEY")
        self.ai_model: str = _str("AI_MODEL", "claude-sonnet-5")

        # Where this instance is reachable. Defined before the OAuth and
        # billing blocks, because both derive redirect URLs from it.
        self.public_url: str = _normalise_public_url(
            _str("PUBLIC_URL", "http://localhost:8000")
        )

        # --- YouTube publishing ------------------------------------------ #
        # A web OAuth client from Google Cloud. Without it the app runs with
        # publishing switched off and renders are download-only.
        self.google_client_id: str = _str("GOOGLE_CLIENT_ID")
        self.google_client_secret: str = _str("GOOGLE_CLIENT_SECRET")
        # Derived from the already-normalised public_url, so it inherits the
        # scheme rather than repeating the same mistake.
        self.google_redirect_uri: str = _normalise_public_url(
            _str("GOOGLE_REDIRECT_URI",
                 f"{self.public_url}/api/youtube/callback")
        )

        # --- billing ----------------------------------------------------- #
        self.stripe_secret_key: str = _str("STRIPE_SECRET_KEY")
        self.stripe_webhook_secret: str = _str("STRIPE_WEBHOOK_SECRET")
        self.stripe_price_starter: str = _str("STRIPE_PRICE_STARTER")
        self.stripe_price_pro: str = _str("STRIPE_PRICE_PRO")
        # What the pricing screen shows. These are labels only -- the amount
        # actually charged is whatever the Stripe Price says, so keep them in
        # step with it or customers see one number and pay another.
        self.price_label_starter: str = _str("PRICE_LABEL_STARTER", "$12/mo")
        self.price_label_pro: str = _str("PRICE_LABEL_PRO", "$39/mo")
        self.billing_enabled: bool = bool(self.stripe_secret_key)

        for directory in (self.upload_dir, self.render_dir, self.cache_dir):
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except PermissionError as exc:
                # Almost always a volume mounted as root under a container that
                # runs unprivileged. The raw traceback points at pathlib and
                # tells you nothing, so say what to actually do.
                raise PermissionError(
                    f"Cannot write to {directory}. If this is a container with "
                    f"a mounted volume, the volume is owned by root while the "
                    f"app runs as another user -- the image's entrypoint should "
                    f"chown {self.storage_dir} before dropping privileges. "
                    f"Otherwise set STORAGE_DIR to a writable path."
                ) from exc

    def validate(self) -> List[str]:
        """Problems that should stop a production boot."""
        problems: List[str] = []
        if self.env == "production":
            if self.secret_key in ("", DEV_SECRET):
                problems.append("SECRET_KEY must be set in production.")
            if not self.billing_enabled:
                problems.append("STRIPE_SECRET_KEY is required to charge for plans.")
            if self.debug:
                problems.append("DEBUG must be off in production.")
        if not self.secret_key:
            self.secret_key = secrets.token_urlsafe(32)
        return problems


settings = Settings()
