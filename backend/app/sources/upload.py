"""
upload.py -- The user's own footage.

The only source with no copyright question at all, and the one that makes
niches like sport or gaming possible: the user brings the material, the product
does the editing. Uploads are scoped to their owner and never shared.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

from ..config import settings
from ..logging_setup import get_logger
from .base import SourceClip

log = get_logger("sources.upload")

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


def user_dir(user_id: int) -> Path:
    path = settings.upload_dir / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


class UploadSource:
    name = "upload"
    label = "Your own uploads"
    licence_summary = "Your footage. You hold the rights; nothing is claimed."
    reusable = True
    needs_key = False

    def __init__(self, user_id: Optional[int] = None) -> None:
        self.user_id = user_id
        # Why the last search came back empty. Read by render/pipeline.py.
        self.last_problem: str = ""

    def available(self) -> bool:
        return self.user_id is not None

    def search(self, terms: List[str], limit: int) -> List[SourceClip]:
        """List the user's uploads, newest first.

        Terms filter by filename when given, but an empty term list returns
        everything -- a user with ten clips expects to use all ten.
        """
        self.last_problem = ""
        if not self.available():
            return []
        directory = user_dir(self.user_id)
        wanted = [t.lower() for t in terms if t]

        files = [
            path for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
        ]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        # This adapter is "available" whenever somebody is signed in, so an
        # empty folder is the single most common reason a run finds nothing.
        if not files:
            self.last_problem = (
                "You have not uploaded any footage yet, and uploads are the "
                "only source this niche is using."
            )
            return []

        clips: List[SourceClip] = []
        for path in files:
            name = path.stem.replace("_", " ").replace("-", " ")
            if wanted and not any(term in name.lower() for term in wanted):
                continue
            clips.append(SourceClip(
                source=self.name,
                external_id=path.name,
                title=name[:200],
                url="",
                download_url=str(path),
                author="you",
                licence="Your own footage",
                reusable=True,
                attribution_required=False,
                local_path=path,
            ))
            if len(clips) >= limit:
                break
        log.info("Upload source offered %d clip(s) for user %s.",
                 len(clips), self.user_id)
        return clips

    def fetch(self, clip: SourceClip, destination: Path) -> Optional[Path]:
        """Copy into the job workspace so the original is never touched."""
        source = clip.local_path or Path(clip.download_url)
        if not source.exists():
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination
