"""
youtube_source.py -- Pull candidate clips from YouTube.

**This source is not licensed for reuse.** It is registered like any other
adapter but declares ``reusable = False``, so the registry refuses to hand it
to a job unless the operator sets ``ALLOW_UNLICENSED_SOURCES=true`` and
accepts what that means. Read the note in ``sources/__init__.py`` before
switching it on: YouTube's Terms of Service prohibit downloading, Content ID
matches the underlying content regardless of who re-uploaded it, and as a paid
service the liability sits with the operator rather than the subscriber.

It exists because the alternative -- pretending the capability is impossible --
is worse than stating the trade-off plainly and letting the operator decide.

Discovery is the two-stage scan from the desktop tool, which is what makes it
cheap: a flat listing gets many candidates with headline fields only, and just
the survivors are fully resolved.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from ..config import settings
from ..logging_setup import get_logger
from .base import SourceClip

log = get_logger("sources.youtube")

_HANDLE = re.compile(r"^@[\w.\-]+$")
_VIDEO_ID = re.compile(r"^[\w\-]{11}$")


def _slug(term: str) -> str:
    """A hashtag tab wants 'premierleague', not 'premier league'."""
    return re.sub(r"[^a-z0-9]+", "", term.lower())


class YouTubeSource:
    name = "youtube"
    label = "YouTube (NOT licensed for reuse)"
    licence_summary = (
        "NOT licensed for reuse. This is other people's copyrighted video: "
        "downloading it breaks YouTube's Terms of Service, and Content ID "
        "matches the content whoever re-uploaded it. Stays off unless the "
        "operator explicitly enables unlicensed sources and accepts the risk."
    )
    reusable = False
    needs_key = False

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        # Per-job settings, so each subscriber's channels and filters apply.
        self.config: Dict[str, Any] = config or {}

    def with_settings(self, config: Dict[str, Any]) -> "YouTubeSource":
        return YouTubeSource(config)

    def available(self) -> bool:
        try:
            import yt_dlp  # noqa: F401
        except ImportError:
            return False
        return True

    # ------------------------------------------------------------------ #
    # yt-dlp plumbing
    # ------------------------------------------------------------------ #
    def _opts(self, **extra: Any) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "ignoreerrors": True,
            "socket_timeout": 30,
            "retries": 3,
        }
        if settings.ytdlp_cookies_file:
            opts["cookiefile"] = settings.ytdlp_cookies_file
        opts.update(extra)
        return opts

    # ------------------------------------------------------------------ #
    # Where to look
    # ------------------------------------------------------------------ #
    def _channel_base(self, value: str) -> str:
        value = (value or "").strip().rstrip("/")
        if not value:
            return ""
        if _HANDLE.match(value):
            return f"https://www.youtube.com/{value}"
        if not value.startswith("http"):
            return f"https://www.youtube.com/@{value.lstrip('@')}"
        return value

    def build_sources(self, terms: List[str]) -> List[str]:
        """Every discovery URL for this job, most specific first."""
        cfg = self.config
        urls: List[str] = []

        channels = [c for c in (cfg.get("source_channels") or []) if c.strip()]
        tabs = [t for t in (cfg.get("channel_tabs") or ["videos", "shorts"]) if t]
        searches = [s for s in (cfg.get("channel_search_terms") or []) if s.strip()]

        for channel in channels:
            base = self._channel_base(channel)
            if not base:
                continue
            # Archive searches first: a channel's recent uploads are rarely its
            # best material, and a seasonal show may be off air entirely.
            for term in searches:
                urls.append(f"{base}/search?query={quote_plus(term)}")
            for tab in tabs:
                urls.append(f"{base}/{tab}")

        # Hashtag Shorts tabs actually return Shorts, where ytsearch returns
        # full-length videos that all die on the duration filter.
        for term in terms:
            slug = _slug(term)
            if slug:
                urls.append(f"https://www.youtube.com/hashtag/{slug}/shorts")

        return urls

    # ------------------------------------------------------------------ #
    # Stage 1 -- flat scan
    # ------------------------------------------------------------------ #
    def _flat_scan(self, url: str, limit: int) -> List[SourceClip]:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError, ExtractorError

        opts = self._opts(extract_flat="in_playlist", skip_download=True,
                          playlistend=limit)
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except (DownloadError, ExtractorError) as exc:
            log.warning("Scan failed for %s: %s", url[:70], str(exc)[:120])
            return []
        if not info:
            return []

        found: List[SourceClip] = []
        for entry in (info.get("entries") or []):
            if not entry:
                continue
            video_id = entry.get("id") or ""
            if not _VIDEO_ID.match(video_id):
                continue
            clip = SourceClip(
                source=self.name,
                external_id=video_id,
                title=(entry.get("title") or "")[:200],
                url=f"https://www.youtube.com/watch?v={video_id}",
                author=entry.get("channel") or entry.get("uploader") or "",
                duration=float(entry.get("duration") or 0),
                licence="Not licensed for reuse",
                reusable=False,
                attribution_required=True,
            )
            clip.extra = {
                "view_count": entry.get("view_count"),
                "description": "",
                "age_days": None,
            }
            found.append(clip)
        log.info("Scanned %s -> %d candidate(s).", url[:70], len(found))
        return found

    # ------------------------------------------------------------------ #
    # Stage 2 -- enrichment
    # ------------------------------------------------------------------ #
    def enrich(self, clip: SourceClip) -> bool:
        """Fill in description, tags and age. Returns False if unavailable."""
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError, ExtractorError

        try:
            with YoutubeDL(self._opts(skip_download=True, noplaylist=True)) as ydl:
                info = ydl.extract_info(clip.url, download=False)
        except (DownloadError, ExtractorError) as exc:
            log.debug("Enrich failed for %s: %s", clip.external_id, str(exc)[:90])
            return False
        if not info:
            return False

        clip.title = (info.get("title") or clip.title)[:200]
        clip.author = info.get("channel") or info.get("uploader") or clip.author
        clip.duration = float(info.get("duration") or clip.duration or 0)
        clip.width = int(info.get("width") or 0)
        clip.height = int(info.get("height") or 0)
        clip.tags = [str(t) for t in (info.get("tags") or [])][:20]

        age_days = None
        stamp = info.get("upload_date")
        if stamp and len(str(stamp)) == 8:
            try:
                when = datetime.strptime(str(stamp), "%Y%m%d").replace(
                    tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - when).days
            except ValueError:
                pass

        clip.extra = {
            "view_count": info.get("view_count"),
            "description": (info.get("description") or "")[:2000],
            "age_days": age_days,
        }
        return True

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #
    def search(self, terms: List[str], limit: int) -> List[SourceClip]:
        if not self.available():
            log.warning("yt-dlp is not installed; the YouTube source is idle.")
            return []

        urls = self.build_sources(terms)
        if not urls:
            log.info("No channels or search terms configured for YouTube.")
            return []

        pool_size = int(self.config.get("candidate_pool_size", 40))
        seen: Dict[str, SourceClip] = {}
        for url in urls:
            for clip in self._flat_scan(url, pool_size):
                seen.setdefault(clip.external_id, clip)
            if len(seen) >= pool_size:
                break

        # Best first, then resolve only as many as the job can use. Enrichment
        # is one network round-trip per clip, so this is the expensive part.
        ordered = sorted(seen.values(),
                         key=lambda c: c.extra.get("view_count") or 0,
                         reverse=True)
        enriched: List[SourceClip] = []
        for clip in ordered:
            if len(enriched) >= limit:
                break
            if self.enrich(clip):
                enriched.append(clip)

        log.info("YouTube offered %d clip(s) from %d source URL(s).",
                 len(enriched), len(urls))
        return enriched

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #
    def fetch(self, clip: SourceClip, destination: Path) -> Optional[Path]:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError, ExtractorError

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        stem = destination.with_suffix("")

        opts = self._opts(
            format=("bestvideo[height<=1920][ext=mp4]+bestaudio[ext=m4a]/"
                    "best[ext=mp4]/best"),
            merge_output_format="mp4",
            outtmpl=f"{stem}.%(ext)s",
            noplaylist=True,
            ignoreerrors=False,   # a download failure must surface here
            overwrites=True,
            # Auto-captions drive the burned-in subtitles and the music scan.
            writesubtitles=True,
            writeautomaticsub=True,
            subtitleslangs=["en.*"],
            subtitlesformat="vtt",
        )
        # ffmpeg lives outside PATH on some machines; yt-dlp does its own lookup.
        ffmpeg_dir = str(Path(settings.ffmpeg).parent)
        if ffmpeg_dir and ffmpeg_dir != ".":
            opts["ffmpeg_location"] = ffmpeg_dir

        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([clip.url])
        except (DownloadError, ExtractorError) as exc:
            log.warning("Download failed for %s: %s", clip.external_id,
                        str(exc)[:140])
            return None

        produced = destination if destination.exists() else None
        if produced is None:
            for candidate in sorted(stem.parent.glob(f"{stem.name}.*")):
                if candidate.suffix.lower() in {".mp4", ".mkv", ".webm"}:
                    produced = candidate
                    break
        if produced is None:
            return None

        # Hand the caption file to the pipeline for captions and music scanning.
        for vtt in sorted(stem.parent.glob(f"{stem.name}*.vtt")):
            clip.extra["subtitle_path"] = str(vtt)
            break
        return produced
