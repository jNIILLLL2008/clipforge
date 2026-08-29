"""
labels.py -- Turn a source video's title into a numbered-list entry.

The list is the single biggest retention device in the format, and it used to
be ``clip.title[:34]``: the uploader's title, hard-truncated at 34 characters
wherever that landed. Real output read

    1. Real power loading (lock emoji) .The Spectacu
    2. Flash Confronts Peter (emoji)| The Specta
    3. The Spectacular Spider-Man (2008-2
    4. How Did I Ever Live Without You? |
    5. Origin 2 | Marvel's Spider-Man | D

Every one of those problems is in that one line. YouTube titles are written
for search, not for reading: they carry the channel name after a separator,
the series and its years in brackets, emoji as attention bait, and quality
tags. Truncating mid-word then leaves a dangling separator.

What the viewer needs instead is a short phrase naming the moment. This is
deterministic on purpose -- most installs have no AI key, so the fallback has
to be the thing that is actually good rather than a placeholder.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

#: Channel and series names hang off the end of a title behind one of these.
_SEPARATORS = re.compile(r"\s*[|·•‣>»~/]+\s*|\s+[-–—]\s+")

#: Bracketed asides are almost always metadata: (2008-2009), [HD], {FULL HD}.
_BRACKETED = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")

#: Emoji and pictographs. Ranges rather than a library, because this runs
#: inside a render worker and one more dependency is not worth it.
_PICTOGRAPHS = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # emoji, symbols, pictographs, supplements
    "\U00002600-\U000027BF"   # misc symbols and dingbats
    "\U0001F1E6-\U0001F1FF"   # regional indicators
    "\U00002190-\U000021FF"   # arrows
    "\U00002B00-\U00002BFF"   # misc symbols and arrows
    "️‍⃣"      # variation selectors, ZWJ, keycap
    "]+"
)

_HASHTAG = re.compile(r"#\w+")
_URL = re.compile(r"https?://\S+|www\.\S+")

#: Words that describe the file rather than the moment.
_NOISE = {
    "hd", "hq", "fhd", "uhd", "4k", "8k", "1080p", "720p", "480p", "60fps",
    "full", "official", "video", "clip", "scene", "moment", "shorts", "short",
    "remastered", "reupload", "part", "episode", "ep", "season", "s01", "hdtv",
}

#: Left after the surgery, these are punctuation with nothing attached.
_EDGE_JUNK = re.compile(r"^[\s\-–—:;,.|·•~/\\]+|[\s\-–—:;,.|·•~/\\]+$")


def _looks_like_a_name(part: str, show_terms: List[str],
                       boilerplate: Optional[Set[str]] = None) -> bool:
    """Is this segment the channel or series rather than the moment?

    Only two signals are trusted, and neither guesses from shape. An earlier
    version also flagged any segment of three-or-fewer capitalised words,
    which sounds reasonable and is wrong: it ate "Flash Confronts Peter" and
    "Origin 2", which are exactly the labels worth keeping.
    """
    lowered = part.lower().strip()
    if any(term and term in lowered for term in show_terms):
        return True
    if boilerplate and lowered in boilerplate:
        return True
    return False


def _boilerplate(titles: List[str]) -> Set[str]:
    """Segments that recur across the batch, which makes them the channel.

    A moment is unique to its clip; a channel or series name is on every one.
    Counting is what show_terms does by configuration, without needing any.
    """
    counts: Dict[str, int] = {}
    for title in titles:
        seen = set()
        for part in _segments(title):
            key = part.lower().strip()
            if key and key not in seen:
                seen.add(key)
                counts[key] = counts.get(key, 0) + 1
    if len(titles) < 3:
        # Too few to tell a repeat from a coincidence.
        return set()
    threshold = max(2, int(len(titles) * 0.6))
    return {key for key, n in counts.items() if n >= threshold}


def _segments(title: str) -> List[str]:
    """The title, cleaned of decoration and split on its separators."""
    text = _URL.sub(" ", title or "")
    text = _PICTOGRAPHS.sub(" ", text)
    text = _HASHTAG.sub(" ", text)
    text = _BRACKETED.sub(" ", text)
    parts = [p.strip() for p in _SEPARATORS.split(text) if p and p.strip()]
    parts = [_EDGE_JUNK.sub("", p) for p in parts]
    return [p for p in parts if p]


def _strip_noise(text: str) -> str:
    kept = [w for w in text.split()
            if w.strip(".,!?'\"").lower() not in _NOISE]
    return " ".join(kept)


def _truncate(text: str, limit: int) -> str:
    """Cut on a word boundary. A label ending mid-word reads as broken."""
    if len(text) <= limit:
        return text
    cut = text[:limit + 1]
    space = cut.rfind(" ")
    if space >= limit * 0.6:          # a sensible break exists
        cut = cut[:space]
    else:                              # one very long word; hard cut is honest
        cut = text[:limit]
    return _EDGE_JUNK.sub("", cut)


def clean(title: str, settings: Optional[Dict] = None, limit: int = 38,
          boilerplate: Optional[Set[str]] = None) -> str:
    """A short phrase naming the moment, or "" if nothing usable survives."""
    settings = settings or {}
    show_terms = [str(t).strip().lower()
                  for t in (settings.get("show_terms") or []) if str(t).strip()]

    # Split on separators and drop the parts that name the channel or series.
    parts = _segments(title)
    if not parts:
        return ""

    candidates = [p for p in parts
                  if not _looks_like_a_name(p, show_terms, boilerplate)]
    # Everything looked like a name: the title is only a series name, so use
    # the longest piece of it rather than returning nothing at all.
    chosen = candidates[0] if candidates else max(parts, key=len)

    chosen = _strip_noise(chosen)
    chosen = " ".join(chosen.split())
    chosen = _EDGE_JUNK.sub("", chosen)
    if not chosen:
        return ""

    # SHOUTED TITLES are common and unreadable in a list.
    letters = [c for c in chosen if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(letters) > 4:
        chosen = chosen.title()

    return _truncate(chosen, limit)


def for_clips(clips, settings: Optional[Dict] = None,
              limit: int = 38) -> List[str]:
    """One label per clip, numbered as a fallback so none is ever blank.

    Goes through the batch rather than one title at a time, because what
    identifies the channel is that it appears on all of them.
    """
    titles = [getattr(c, "title", "") or "" for c in clips]
    shared = _boilerplate(titles)
    out: List[str] = []
    for index, title in enumerate(titles, start=1):
        label = clean(title, settings, limit, shared)
        out.append(label or f"Moment {index}")
    return out
