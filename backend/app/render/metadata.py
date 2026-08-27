"""
metadata.py -- Title, description and tags for a finished video.

Claude writes them when a key is configured; otherwise a template stands in, so
publishing never blocks on the AI being available. Required attribution is
appended to the description either way, because that is a licence obligation
rather than a nicety.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..config import settings
from ..logging_setup import get_logger

log = get_logger("render.metadata")

TITLE_LIMIT = 100
_BAD_ESCAPE = re.compile(r"\\'")
_TRAILING_COMMA = re.compile(r",\s*([}\]])")

SYSTEM = (
    "You write YouTube Shorts metadata. Reply with JSON only. Titles must be "
    "under 90 characters, front-load the hook, and never use clickbait that the "
    "video does not deliver."
)


@dataclass
class Metadata:
    title: str
    description: str = ""
    tags: List[str] = field(default_factory=list)


def _loads(text: str) -> Optional[Dict]:
    """Parse model JSON, repairing the two slips models actually make."""
    for attempt in (text, _TRAILING_COMMA.sub(r"\1", _BAD_ESCAPE.sub("'", text))):
        try:
            parsed = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract(raw: str) -> Optional[Dict]:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    parsed = _loads(text)
    if parsed is not None:
        return parsed
    start, end = text.find("{"), text.rfind("}")
    return _loads(text[start:end + 1]) if start != -1 and end > start else None


def _fallback(niche_name: str, labels: List[str], count: int) -> Metadata:
    subject = niche_name or "Compilation"
    title = f"Top {count} {subject}" if count > 1 else subject
    body = "\n".join(f"{i}. {label}" for i, label in enumerate(labels, 1))
    words = re.findall(r"[a-zA-Z]{3,}", " ".join([subject] + labels).lower())
    tags = list(dict.fromkeys(words))[:15] + ["shorts", "viral"]
    return Metadata(title=title[:TITLE_LIMIT], description=body, tags=tags)


def generate(*, niche_name: str, description: str, labels: List[str],
             transcript: str = "") -> Metadata:
    """Write metadata for one finished compilation."""
    count = len(labels)
    if not settings.anthropic_api_key:
        log.info("No AI key; using template metadata.")
        return _fallback(niche_name, labels, count)

    prompt = (
        f"A {count}-clip short-form compilation.\n"
        f"Niche: {niche_name}\n"
        f"About: {description[:400]}\n"
        f"The clips, in order:\n"
        + "\n".join(f"  {i}. {label}" for i, label in enumerate(labels, 1))
        + (f"\nSpoken content: {transcript[:900]}\n" if transcript else "\n")
        + '\nReturn: {"title": "...", "description": "...", "tags": ["..."]}\n'
          "The description should be 2-3 lines, then a blank line, then "
          "hashtags. Give 12-20 tags."
    )

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=settings.ai_model,
            max_tokens=1200,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(block.text for block in message.content
                      if getattr(block, "type", "") == "text")
        payload = _extract(raw)
        if not payload or not payload.get("title"):
            raise ValueError(f"no usable JSON in {raw[:160]!r}")

        tags = [str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()]
        meta = Metadata(
            title=str(payload["title"]).strip()[:TITLE_LIMIT],
            description=str(payload.get("description", "")).strip(),
            tags=tags[:40],
        )
        log.info("Metadata written by %s.", settings.ai_model)
        return meta
    except Exception as exc:  # noqa: BLE001 - never block publishing on this
        log.warning("AI metadata failed (%s); using template.", exc)
        return _fallback(niche_name, labels, count)


def finalise(meta: Metadata, *, suffix: str, credits: List[str]) -> Metadata:
    """Apply the user's title suffix and append any required attribution."""
    title = meta.title
    if suffix and suffix.strip() not in title:
        room = TITLE_LIMIT - len(suffix) - 1
        title = f"{title[:room].rstrip()} {suffix.strip()}"

    description = meta.description
    if credits:
        description = (description.rstrip() + "\n\nClips used:\n"
                       + "\n".join(f"- {c}" for c in credits))
    return Metadata(title=title[:TITLE_LIMIT], description=description,
                    tags=meta.tags)
