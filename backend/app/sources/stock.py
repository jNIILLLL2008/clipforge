"""
stock.py -- Licensed stock libraries (Pexels, Pixabay).

Both licence their footage for commercial use without attribution. That is what
makes them safe defaults for a paid product: a subscriber can publish and
monetise the output without a claim arriving.

Neither carries broadcast footage, which is the honest limit of this approach --
sports and TV niches have to come from the user's own uploads.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List, Optional

import requests

from ..config import settings
from ..logging_setup import get_logger
from .base import SourceClip

log = get_logger("sources.stock")
TIMEOUT = 25


def _download(url: str, destination: Path, headers: Optional[Dict] = None) -> Optional[Path]:
    """Stream a media file to disk."""
    try:
        with requests.get(url, stream=True, timeout=TIMEOUT,
                          headers=headers or {}) as response:
            response.raise_for_status()
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as handle:
                shutil.copyfileobj(response.raw, handle)
    except (requests.RequestException, OSError) as exc:
        log.warning("Download failed for %s: %s", url[:80], exc)
        return None
    return destination if destination.exists() and destination.stat().st_size else None


class PexelsSource:
    name = "pexels"
    label = "Pexels (stock video)"
    licence_summary = "Pexels License - free for commercial use, no attribution."
    reusable = True
    needs_key = True

    def available(self) -> bool:
        return bool(settings.pexels_api_key)

    def search(self, terms: List[str], limit: int) -> List[SourceClip]:
        if not self.available():
            return []
        query = " ".join(terms[:4]) or "cinematic"
        try:
            response = requests.get(
                "https://api.pexels.com/videos/search",
                params={"query": query, "per_page": min(limit, 40),
                        "orientation": "portrait", "size": "medium"},
                headers={"Authorization": settings.pexels_api_key},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("Pexels search failed: %s", exc)
            return []

        clips: List[SourceClip] = []
        for video in payload.get("videos", []):
            files = sorted(
                (f for f in video.get("video_files", []) if f.get("link")),
                key=lambda f: abs((f.get("height") or 0) - 1920),
            )
            if not files:
                continue
            best = files[0]
            clips.append(SourceClip(
                source=self.name,
                external_id=str(video.get("id")),
                title=(video.get("alt") or query)[:200],
                url=video.get("url", ""),
                download_url=best["link"],
                author=(video.get("user") or {}).get("name", ""),
                author_url=(video.get("user") or {}).get("url", ""),
                duration=float(video.get("duration") or 0),
                width=int(best.get("width") or 0),
                height=int(best.get("height") or 0),
                licence="Pexels License",
                reusable=True,
                attribution_required=False,
            ))
        log.info("Pexels returned %d clip(s) for %r.", len(clips), query)
        return clips

    def fetch(self, clip: SourceClip, destination: Path) -> Optional[Path]:
        return _download(clip.download_url, destination)


class PixabaySource:
    name = "pixabay"
    label = "Pixabay (stock video)"
    licence_summary = "Pixabay Content License - free for commercial use."
    reusable = True
    needs_key = True

    def available(self) -> bool:
        return bool(settings.pixabay_api_key)

    def search(self, terms: List[str], limit: int) -> List[SourceClip]:
        if not self.available():
            return []
        query = " ".join(terms[:4]) or "cinematic"
        try:
            response = requests.get(
                "https://pixabay.com/api/videos/",
                params={"key": settings.pixabay_api_key, "q": query,
                        "per_page": min(max(limit, 3), 50), "safesearch": "true"},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("Pixabay search failed: %s", exc)
            return []

        clips: List[SourceClip] = []
        for hit in payload.get("hits", []):
            streams = hit.get("videos") or {}
            best = streams.get("large") or streams.get("medium") or streams.get("small")
            if not best or not best.get("url"):
                continue
            clips.append(SourceClip(
                source=self.name,
                external_id=str(hit.get("id")),
                title=(hit.get("tags") or query)[:200],
                url=hit.get("pageURL", ""),
                download_url=best["url"],
                author=hit.get("user", ""),
                duration=float(hit.get("duration") or 0),
                width=int(best.get("width") or 0),
                height=int(best.get("height") or 0),
                licence="Pixabay Content License",
                reusable=True,
                attribution_required=False,
                tags=[t.strip() for t in (hit.get("tags") or "").split(",") if t.strip()],
            ))
        log.info("Pixabay returned %d clip(s) for %r.", len(clips), query)
        return clips

    def fetch(self, clip: SourceClip, destination: Path) -> Optional[Path]:
        return _download(clip.download_url, destination)
