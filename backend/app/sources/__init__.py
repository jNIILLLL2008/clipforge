"""
sources -- Registry of content adapters.

The registry is where the copyright promise is enforced mechanically: an
adapter whose ``reusable`` flag is False cannot be handed to a job unless the
operator sets ``ALLOW_UNLICENSED_SOURCES``. Forgetting to configure something
results in *fewer* sources, never a riskier one.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..config import settings
from ..logging_setup import get_logger
from .base import SourceClip, SourceError  # noqa: F401 - re-exported
from .commons import ArchiveSource, OpenverseSource
from .stock import PexelsSource, PixabaySource
from .upload import UploadSource
from .youtube_source import YouTubeSource

log = get_logger("sources")

# Adapters that need per-request context rather than a shared instance:
# "upload" is scoped to one user, "youtube" to one job's settings.
_PER_USER = {"upload", "youtube"}

_SHARED = {
    "pexels": PexelsSource(),
    "pixabay": PixabaySource(),
    "openverse": OpenverseSource(),
    "archive": ArchiveSource(),
}


def build(name: str, user_id: Optional[int] = None,
          job_settings: Optional[Dict] = None):
    """Instantiate one adapter by name, or None if unknown."""
    if name == "upload":
        return UploadSource(user_id)
    if name == "youtube":
        return YouTubeSource(job_settings or {})
    return _SHARED.get(name)


def _permitted(adapter) -> bool:
    """Licensed adapters always; risky ones only on an explicit opt-in."""
    if adapter.reusable:
        return True
    if settings.allow_unlicensed_sources:
        log.warning(
            "Source %r is enabled but is NOT cleared for reuse. The operator "
            "has accepted the liability via ALLOW_UNLICENSED_SOURCES.",
            adapter.name,
        )
        return True
    return False


def for_job(names: List[str], user_id: Optional[int] = None,
            job_settings: Optional[Dict] = None) -> List:
    """Adapters a job may use: enabled, permitted, configured, in order."""
    chosen = []
    for name in names or []:
        if name not in settings.enabled_sources:
            continue
        adapter = build(name, user_id, job_settings)
        if adapter is None:
            log.debug("Unknown source %r ignored.", name)
            continue
        if not _permitted(adapter):
            log.info("Source %r blocked: not cleared for commercial reuse.", name)
            continue
        if not adapter.available():
            log.info("Source %r skipped: not configured.", name)
            continue
        chosen.append(adapter)
    return chosen


def catalogue(user_id: Optional[int] = None) -> List[Dict]:
    """Every adapter and its current state, for the settings screen."""
    rows: List[Dict] = []
    for name in sorted(set(list(_SHARED) + list(_PER_USER))):
        adapter = build(name, user_id, {})
        if adapter is None:
            continue
        rows.append({
            "name": adapter.name,
            "label": adapter.label,
            "licence": adapter.licence_summary,
            "reusable": adapter.reusable,
            "enabled": name in settings.enabled_sources,
            "configured": adapter.available(),
            "needs_key": adapter.needs_key,
            # A source can be enabled and installed yet still blocked, because
            # it is not cleared for reuse. Say so rather than showing "ready".
            "permitted": _permitted(adapter),
        })
    return rows
