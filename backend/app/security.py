"""
security.py -- Response hardening and abuse limits.

Two middlewares and a small limiter, kept together because they answer the same
question: what should this server refuse to do for a stranger.

Nothing here needs a dependency. The rate limiter is an in-process dictionary,
which is the honest fit for a single-container deployment. If this ever runs on
more than one instance the buckets stop being shared and the effective limit
multiplies by the instance count, so move it to Redis before scaling out rather
than after.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import settings
from .logging_setup import get_logger

log = get_logger("security")

#: Everything the frontend actually loads, and nothing else. Google Fonts
#: serves its stylesheet from one host and the font files from another, so both
#: are needed. Simple Icons is the YouTube mark under the hero.
_CSP = "; ".join([
    "default-src 'self'",
    # The two inline scripts on the marketing page are the reason for
    # 'unsafe-inline'. Removing it means moving them into files and paying an
    # extra request for the class flag that has to run before first paint.
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    # blob: is not optional: /api/studio/preview returns a PNG body that
    # app.js turns into an object URL, on the settings screen and again in the
    # guided walkthrough. Without it both previews render their alt text, which
    # is exactly what they did between this header shipping and this line.
    "img-src 'self' data: blob: https://cdn.simpleicons.org",
    "connect-src 'self'",
    "media-src 'self'",
    # None of these are used, so none of them should be possible.
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
])


class SecurityHeaders(BaseHTTPMiddleware):
    """Add the headers a browser uses to limit the damage of a mistake."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        headers = response.headers

        headers.setdefault("Content-Security-Policy", _CSP)
        # Clickjacking. frame-ancestors above is the modern control; this is
        # the one older browsers understand.
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Nothing here uses a camera, a microphone or a location.
        headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")

        # HSTS only over a real HTTPS request. Sending it over plain HTTP is
        # ignored by browsers, and sending it in local development would pin
        # localhost to HTTPS in the developer's browser for a year.
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        if proto == "https":
            headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains")
        return response


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #
class _Buckets:
    """Sliding windows keyed by whatever the caller decides identifies a client."""

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()
        self._swept = 0.0

    def hit(self, key: str, limit: int, window: float) -> Tuple[bool, int]:
        """Record one request. Returns (allowed, seconds until it frees up)."""
        now = time.monotonic()
        with self._lock:
            self._sweep(now, window)
            seen = self._hits.setdefault(key, deque())
            while seen and now - seen[0] > window:
                seen.popleft()
            if len(seen) >= limit:
                return False, max(1, int(window - (now - seen[0])) + 1)
            seen.append(now)
            return True, 0

    def _sweep(self, now: float, window: float) -> None:
        """Drop empty buckets occasionally so this cannot grow without bound."""
        if now - self._swept < 60:
            return
        self._swept = now
        for key in [k for k, v in self._hits.items()
                    if not v or now - v[-1] > window * 2]:
            self._hits.pop(key, None)


_buckets = _Buckets()


def client_ip(request) -> str:
    """Best guess at who is calling.

    Behind Railway the socket address is the proxy, so the first entry of
    X-Forwarded-For is the client. That header is caller-supplied and trivially
    spoofed, which is fine for rate limiting (a spoofer only splits their own
    budget) but must never be used for anything that grants access.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


#: Path prefix -> (requests, seconds). Longest match wins, so the auth limits
#: below sit under the broader /api one.
_LIMITS: Dict[str, Tuple[int, float]] = {
    # Guessing a password should be slow. Six tries a minute from one address
    # is generous for a person and useless for a script.
    "/api/auth/login": (6, 60.0),
    "/api/auth/signup": (4, 300.0),
    # An agent polls this on a timer; the ceiling is only here to stop a
    # runaway loop hammering the database.
    "/api/agent/claim": (60, 60.0),
    "/api/uploads": (30, 300.0),
    "/api/studio/run": (20, 300.0),
    "/api": (240, 60.0),
}


def _limit_for(path: str):
    match, rule = "", None
    for prefix, spec in _LIMITS.items():
        if path.startswith(prefix) and len(prefix) > len(match):
            match, rule = prefix, spec
    return match, rule


class RateLimit(BaseHTTPMiddleware):
    """Refuse too many requests from one address, per route family."""

    async def dispatch(self, request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        prefix, rule = _limit_for(request.url.path)
        if rule is None:
            return await call_next(request)

        limit, window = rule
        allowed, retry = _buckets.hit(
            f"{client_ip(request)}|{prefix}", limit, window)
        if not allowed:
            log.warning("Rate limited %s on %s.", client_ip(request), prefix)
            return JSONResponse(
                {"detail": "Too many requests. Wait a moment and try again."},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
        return await call_next(request)


def install(app) -> None:
    """Attach both middlewares. Order does not matter; neither reads the other."""
    app.add_middleware(SecurityHeaders)
    if settings.rate_limit_enabled:
        app.add_middleware(RateLimit)
    else:
        log.warning("Rate limiting is OFF (RATE_LIMIT_ENABLED=false).")
