"""
commons.py -- Openly licensed material (Openverse, Internet Archive).

Both carry Creative Commons and public-domain media. CC licences are real
licences with conditions, so anything requiring credit is flagged
``attribution_required`` and the renderer puts it in the description. Openly
licensed is not the same as "free to do anything with", and the difference is
what keeps a paying user out of trouble.

Non-commercial and no-derivatives variants are refused outright: a subscriber
is by definition using this commercially, and every output is a derivative.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import requests

from ..logging_setup import get_logger
from .base import SourceClip

log = get_logger("sources.commons")
TIMEOUT = 25

# Licence codes that permit commercial derivative use.
COMMERCIAL_OK = {"cc0", "pdm", "by", "by-sa"}
NEEDS_CREDIT = {"by", "by-sa"}


def _licence_ok(code: str) -> bool:
    code = (code or "").strip().lower()
    # "by-nc", "by-nd", "by-nc-sa" and friends are all out.
    return code in COMMERCIAL_OK


def _download(url: str, destination: Path) -> Optional[Path]:
    try:
        with requests.get(url, stream=True, timeout=TIMEOUT,
                          headers={"User-Agent": "ClipForge/1.0"}) as response:
            response.raise_for_status()
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as handle:
                for chunk in response.iter_content(1 << 16):
                    handle.write(chunk)
    except (requests.RequestException, OSError) as exc:
        log.warning("Download failed for %s: %s", url[:80], exc)
        return None
    return destination if destination.exists() and destination.stat().st_size else None


class OpenverseSource:
    name = "openverse"
    label = "Openverse (Creative Commons)"
    licence_summary = ("CC0, Public Domain and CC BY / BY-SA only. Credit is "
                       "added automatically where the licence requires it.")
    reusable = True
    needs_key = False

    def available(self) -> bool:
        return True

    def search(self, terms: List[str], limit: int) -> List[SourceClip]:
        query = " ".join(terms[:4])
        if not query:
            return []
        try:
            response = requests.get(
                "https://api.openverse.org/v1/audio/",  # video API is not public
                params={"q": query, "page_size": min(limit, 20),
                        "license": ",".join(sorted(COMMERCIAL_OK))},
                headers={"User-Agent": "ClipForge/1.0"},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            log.info("Openverse unavailable: %s", exc)
            return []

        clips: List[SourceClip] = []
        for item in payload.get("results", []):
            code = item.get("license", "")
            if not _licence_ok(code):
                continue
            clips.append(SourceClip(
                source=self.name,
                external_id=str(item.get("id")),
                title=(item.get("title") or query)[:200],
                url=item.get("foreign_landing_url", ""),
                download_url=item.get("url", ""),
                author=item.get("creator", ""),
                licence=f"CC {code.upper()}",
                reusable=True,
                attribution_required=code.lower() in NEEDS_CREDIT,
            ))
        return clips

    def fetch(self, clip: SourceClip, destination: Path) -> Optional[Path]:
        return _download(clip.download_url, destination)


class ArchiveSource:
    name = "archive"
    label = "Internet Archive (public domain)"
    licence_summary = "Public-domain and openly licensed film from archive.org."
    reusable = True
    needs_key = False

    def available(self) -> bool:
        return True

    def search(self, terms: List[str], limit: int) -> List[SourceClip]:
        query = " ".join(terms[:4])
        if not query:
            return []
        params = {
            "q": f'({query}) AND mediatype:(movies) AND licenseurl:(*publicdomain*)',
            "fl[]": ["identifier", "title", "creator", "downloads"],
            "rows": min(limit, 20),
            "output": "json",
        }
        try:
            response = requests.get(
                "https://archive.org/advancedsearch.php", params=params,
                headers={"User-Agent": "ClipForge/1.0"}, timeout=TIMEOUT,
            )
            response.raise_for_status()
            docs = response.json().get("response", {}).get("docs", [])
        except (requests.RequestException, ValueError) as exc:
            log.info("Archive.org unavailable: %s", exc)
            return []

        clips: List[SourceClip] = []
        for doc in docs:
            identifier = doc.get("identifier")
            if not identifier:
                continue
            clips.append(SourceClip(
                source=self.name,
                external_id=identifier,
                title=(doc.get("title") or identifier)[:200],
                url=f"https://archive.org/details/{identifier}",
                author=doc.get("creator") or "",
                licence="Public Domain",
                reusable=True,
                attribution_required=False,
            ))
        return clips

    def fetch(self, clip: SourceClip, destination: Path) -> Optional[Path]:
        """Resolve the item's file list, then pull the smallest usable video."""
        try:
            meta = requests.get(
                f"https://archive.org/metadata/{clip.external_id}",
                headers={"User-Agent": "ClipForge/1.0"}, timeout=TIMEOUT,
            ).json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("Archive metadata failed for %s: %s", clip.external_id, exc)
            return None

        videos = [
            f for f in meta.get("files", [])
            if str(f.get("name", "")).lower().endswith((".mp4", ".m4v", ".webm"))
        ]
        if not videos:
            return None
        videos.sort(key=lambda f: int(f.get("size") or 1 << 40))
        server = meta.get("server") or "archive.org"
        directory = meta.get("dir", "")
        url = f"https://{server}{directory}/{videos[0]['name']}"
        return _download(url, destination)
