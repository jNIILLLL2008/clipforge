"""
youtube.py -- Connect a user's channel and publish to it.

The desktop tool used the installed-app OAuth flow, which opens a local browser
and writes token.json next to the exe. A hosted service cannot do that: each
subscriber authorises through the normal web consent screen, and we keep only
their refresh token.

Nothing here runs unless the operator has configured a Google OAuth client, so
the app boots and renders fine with YouTube switched off entirely.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import settings
from .logging_setup import get_logger

log = get_logger("youtube")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

RETRIABLE_STATUS = {500, 502, 503, 504}
MAX_ATTEMPTS = 5


class YouTubeError(RuntimeError):
    """Anything that stops a publish, phrased for the user."""


@dataclass
class UploadOutcome:
    video_id: str
    url: str
    privacy: str


def configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _require_libs():
    try:
        from google.auth.transport.requests import Request  # noqa: F401
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import Flow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise YouTubeError(
            "The Google API libraries are not installed on this server."
        ) from exc
    return Credentials, Flow, build, HttpError, MediaFileUpload


def _client_config() -> Dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def consent_url(state: str) -> str:
    """Where to send the user to authorise their channel."""
    if not configured():
        raise YouTubeError("YouTube publishing is not configured on this server.")
    _, Flow, _, _, _ = _require_libs()

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.google_redirect_uri
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        # Force a refresh token even if they have authorised before.
        prompt="consent",
        state=state,
    )
    return url


def exchange_code(code: str) -> Tuple[str, str, str]:
    """Swap the callback code for (refresh_token, channel_title, channel_id)."""
    Credentials, Flow, build, _, _ = _require_libs()

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.google_redirect_uri
    flow.fetch_token(code=code)
    creds = flow.credentials

    if not creds.refresh_token:
        raise YouTubeError(
            "Google did not return a refresh token. Remove this app from your "
            "Google account permissions and connect again."
        )

    title, channel_id = "", ""
    try:
        service = build("youtube", "v3", credentials=creds, cache_discovery=False)
        response = service.channels().list(part="snippet", mine=True).execute()
        items = response.get("items") or []
        if items:
            title = items[0]["snippet"]["title"]
            channel_id = items[0]["id"]
    except Exception as exc:  # noqa: BLE001 - the token is still valid without this
        log.warning("Could not read channel details: %s", exc)

    return creds.refresh_token, title, channel_id


def _credentials(refresh_token: str):
    Credentials, _, _, _, _ = _require_libs()
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES,
    )


def upload(
    *,
    refresh_token: str,
    path: Path,
    title: str,
    description: str,
    tags: List[str],
    privacy: str = "private",
    category_id: str = "24",
    made_for_kids: bool = False,
    publish_at: Optional[str] = None,
    on_progress=None,
) -> UploadOutcome:
    """Publish one video, resuming through transient failures."""
    if not configured():
        raise YouTubeError("YouTube publishing is not configured on this server.")
    if not refresh_token:
        raise YouTubeError("This account has no YouTube channel connected.")
    path = Path(path)
    if not path.exists():
        raise YouTubeError("The rendered file is missing.")

    _, _, build, HttpError, MediaFileUpload = _require_libs()
    service = build("youtube", "v3", credentials=_credentials(refresh_token),
                    cache_discovery=False)

    status: Dict = {
        "privacyStatus": privacy,
        # Required on every upload since 2020.
        "selfDeclaredMadeForKids": bool(made_for_kids),
    }
    if publish_at:
        # Scheduling only works on a private video.
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": [t[:60] for t in tags][:40],
            "categoryId": str(category_id),
        },
        "status": status,
    }

    media = MediaFileUpload(str(path), chunksize=4 * 1024 * 1024, resumable=True,
                            mimetype="video/mp4")
    request = service.videos().insert(part="snippet,status", body=body,
                                      media_body=media)

    response, attempt = None, 0
    while response is None:
        try:
            progress, response = request.next_chunk()
            if progress and on_progress:
                on_progress(int(progress.progress() * 100))
        except HttpError as exc:
            if exc.resp.status in RETRIABLE_STATUS and attempt < MAX_ATTEMPTS:
                attempt += 1
                wait = 2 ** attempt
                log.warning("YouTube returned %s; retrying in %ss (%d/%d).",
                            exc.resp.status, wait, attempt, MAX_ATTEMPTS)
                time.sleep(wait)
                continue
            raise YouTubeError(_explain(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            if attempt < MAX_ATTEMPTS:
                attempt += 1
                time.sleep(2 ** attempt)
                continue
            raise YouTubeError(f"Upload failed: {exc}") from exc

    video_id = response.get("id", "")
    log.info("Published %s (%s).", video_id, status["privacyStatus"])
    return UploadOutcome(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        privacy=status["privacyStatus"],
    )


def _explain(exc) -> str:
    """Turn a Google API error into something a user can act on."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    text = str(exc)
    if status == 403 and "quotaExceeded" in text:
        return ("YouTube's daily upload quota for this app has been used up. "
                "Try again tomorrow.")
    if status == 403 and "uploadLimitExceeded" in text:
        return "This channel has hit its own upload limit for today."
    if status == 401:
        return "YouTube rejected the connection. Reconnect the channel."
    if status == 400 and "invalidCategoryId" in text:
        return "That YouTube category ID is not valid."
    return f"YouTube refused the upload ({status}): {text[:180]}"
