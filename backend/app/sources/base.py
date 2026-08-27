"""
base.py -- The contract every content source must meet.

The product's copyright promise lives here, not in a policy document. A source
adapter cannot return a clip without stating its licence, and the registry
refuses to enable any adapter that is not marked commercially reusable unless
the operator has explicitly opted in.

That makes the safe path the default path: an operator who changes nothing gets
only footage that is licensed for reuse or supplied by the user themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Protocol


@dataclass
class SourceClip:
    """A candidate clip, with the licence it arrives under."""

    source: str
    external_id: str
    title: str
    url: str                      # page the clip came from
    download_url: str = ""        # direct media URL, if any
    author: str = ""
    author_url: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0

    # Licence facts. `reusable` is the gate; everything else is bookkeeping.
    licence: str = ""             # e.g. "Pexels License", "CC BY 4.0"
    reusable: bool = False        # cleared for commercial reuse
    attribution_required: bool = False

    local_path: Optional[Path] = None
    tags: List[str] = field(default_factory=list)
    extra: Dict = field(default_factory=dict)

    def credit(self) -> str:
        if not self.attribution_required:
            return ""
        return f"{self.title or 'Clip'} by {self.author or 'unknown'} " \
               f"({self.licence}) - {self.url}"


class Source(Protocol):
    """What every adapter implements."""

    name: str
    label: str
    licence_summary: str
    reusable: bool          # False marks an adapter as legally risky
    needs_key: bool

    def available(self) -> bool:
        """True when this adapter is configured and usable."""

    def search(self, terms: List[str], limit: int) -> List[SourceClip]:
        """Find candidate clips."""

    def fetch(self, clip: SourceClip, destination: Path) -> Optional[Path]:
        """Download one clip; return its local path."""


class SourceError(RuntimeError):
    """Raised when a source fails in a way worth surfacing to the user."""
