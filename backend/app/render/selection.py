"""
selection.py -- Decide which candidate clips qualify.

Ported from the single-channel tool, where these rules were learned the hard
way, and generalised so any subscriber can express them for their own subject.

Three independent gates:

* **Clip filters** -- duration, views, age, blocked channels. Cheap, and they
  run before anything is downloaded.
* **The derivative filter** -- is this somebody else's edit? Sourcing from a
  fan edit or a compilation is the worst outcome available: their music, their
  captions and their watermark come with it, the moment is usually already
  speed-ramped, and the copyright position is worse than the original because
  now two people have a claim.
* **The show filter** -- optional, and the interesting one. It insists a clip
  is from *one specific programme* rather than merely featuring the same
  people. A clip qualifies on an explicit show keyword, or on naming two or
  more of the show's regulars together.

The alias handling matters: "thierry henry" is two words naming one person, and
counting it as two regulars would let a clip about him alone pass a filter
meant to catch panel moments. Aliases are grouped per person with "|".
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

from ..logging_setup import get_logger
from ..sources.base import SourceClip

log = get_logger("render.selection")

#: What a re-edit calls itself. Two families, and both are disqualifying for
#: the same reason: the footage has already been cut by somebody else.
#:
#: These are matched as whole words. A substring test is unusable here --
#: "edit" is inside "credits", "editor" and "meditation", and a naive check
#: throws away most of the pool for no reason.
_DERIVATIVE_TERMS = (
    # Music-video style edits.
    "amv", "edit", "edits", "editz", "fanedit", "twixtor", "capcut",
    "velocity", "phonk", "shitpost", "sigma",
    # Somebody else's assembly of the same footage.
    "compilation", "supercut", "montage", "mashup", "tribute",
    "allscenes", "marathon",
    # Re-uploads that carry another layer of somebody else on top.
    "reupload", "screenrecord", "screenrecording",
    # Somebody talking *about* the show rather than footage *from* it. A
    # ranking video called "The Top 5 Spider-Man Series" reached a finished
    # render: half of it is a man at a desk, and it passed the show filter
    # because it names the show in its description -- which is exactly what a
    # video discussing the show would do.
    "reaction", "reactions", "reacts", "reacting", "react",
    "review", "reviews", "reviewing", "reviewed",
    "explained", "explaining", "breakdown", "recap", "recaps",
    "ranked", "ranking", "rankings", "tierlist", "retrospective",
    "analysis", "analyzed", "analysed", "essay", "podcast", "interview",
    "commentary", "reviewer", "critique",
)

#: Phrases, kept separate because they need the space matched literally.
_DERIVATIVE_PHRASES = (
    "fan edit", "all scenes", "every scene", "whatsapp status",
    "status video", "edit audio", "after effects",
    # Ranking formats. Someone else's list is someone else's edit, and it is
    # the same reason a compilation is refused.
    "tier list", "top 5", "top 10", "top ten", "top five",
    "worst to best", "best to worst", "ranking every", "every episode",
    "video essay", "first time watching", "i watched",
    # Video-essay openers. The single word list above catches anything that
    # calls itself a review or a breakdown, but the essay format usually does
    # not: "What If...? The Spectacular Spider-Man" and "THIS Is Why
    # Spectacular Spider-man Was Cancelled" are both a person at a desk
    # talking over stills, and both reached a finished render because neither
    # title contains one of those words. These are the openers that format
    # actually uses.
    #
    # Phrases rather than words on purpose: "why" and "truth" and "story" are
    # ordinary English that appear in real episode titles, and banning them
    # would throw away the footage this is meant to find.
    "what if", "this is why", "here's why", "heres why",
    "the reason why", "the truth about", "what happened to",
    "the problem with", "everything wrong with", "we need to talk about",
    "the rise and fall", "the story behind", "how they made",
    "was cancelled", "was canceled", "got cancelled", "got canceled",
    "deep dive", "revisited", "iceberg",
)


def _split_camel(text: str) -> str:
    """"SpideyEdits" -> "Spidey Edits".

    Channel names run words together far more often than titles do, and a
    word-boundary match cannot see inside them.
    """
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text or "")


def _haystack(clip: SourceClip) -> str:
    return " ".join(part.lower() for part in (
        clip.title or "",
        (clip.extra.get("description") or "")[:800],
        " ".join(clip.tags or []),
        _split_camel(clip.author or ""),
    ))


def is_derivative(clip: SourceClip, settings: Dict) -> Tuple[bool, str]:
    """Is this someone's edit rather than the footage? (yes, which_term)."""
    if not settings.get("reject_derivative", True):
        return False, ""

    # A channel the subscriber has vouched for posts originals by definition,
    # which is what the Trusted channels box has always said it meant.
    trusted = [t.lower() for t in settings.get("trusted_uploaders", []) if t]
    if trusted and any(t in (clip.author or "").lower() for t in trusted):
        return False, ""

    text = _haystack(clip)
    extra = [str(t).strip().lower() for t in
             settings.get("derivative_terms", []) if str(t).strip()]

    for phrase in _DERIVATIVE_PHRASES:
        if phrase in text:
            return True, phrase
    for word in tuple(_DERIVATIVE_TERMS) + tuple(extra):
        # \b on both ends: "edit" must be the whole word, never the tail of
        # "credits" or the head of "editorial".
        if re.search(r"\b" + re.escape(word) + r"\b", text):
            return True, word
    return False, ""


def passes_filters(clip: SourceClip, settings: Dict) -> Tuple[bool, str]:
    """Cheap metadata checks. Returns (ok, reason_if_not)."""
    duration = clip.duration or 0.0
    if duration:
        low = float(settings.get("min_duration_seconds", 0) or 0)
        high = float(settings.get("max_duration_seconds", 0) or 0)
        if low and duration < low:
            return False, f"{duration:.0f}s is shorter than {low:.0f}s"
        if high and duration > high:
            return False, f"{duration:.0f}s is longer than {high:.0f}s"

    views = clip.extra.get("view_count")
    floor = int(settings.get("min_view_count", 0) or 0)
    if floor and isinstance(views, int) and views < floor:
        return False, f"{views:,} views is under {floor:,}"

    age = clip.extra.get("age_days")
    max_age = int(settings.get("max_video_age_days", 0) or 0)
    if max_age and isinstance(age, (int, float)) and age > max_age:
        return False, f"{age:.0f} days old"

    author = (clip.author or "").lower()
    blocked = [b.lower() for b in settings.get("blocked_uploaders", []) if b]
    if author and any(b in author for b in blocked):
        return False, f"channel {clip.author!r} is blocked"

    excluded = [e.lower() for e in settings.get("exclude_terms", []) if e]
    if excluded:
        text = _haystack(clip)
        hit = next((e for e in excluded if e in text), None)
        if hit:
            # An explicit show keyword outranks a generic exclusion, so a real
            # show clip is not thrown away for mentioning a banned word.
            show_terms = [s.lower() for s in settings.get("show_terms", []) if s]
            if not any(term in text for term in show_terms):
                return False, f"matched excluded term {hit!r}"

    return True, ""


def derived_show_terms(settings: Dict) -> List[str]:
    """What the search terms agree on, which is the subject.

    Used only when the show filter is on and nothing was typed into it. The
    alternative is rejecting every clip, which fails the run and teaches
    people to turn the filter off -- and a niche with the filter off is how
    clips from two other Spider-Man series end up in a Spectacular
    Spider-Man video.
    """
    terms = [str(t).strip().lower() for t in
             (settings.get("search_terms") or []) if str(t).strip()]
    if len(terms) < 2:
        return []

    # Every 2-to-4 word phrase in every search term, counted across terms.
    counts: Dict[str, int] = {}
    for term in terms:
        words = re.findall(r"[\w'-]+", term)
        seen = set()
        for size in (4, 3, 2):
            for start in range(len(words) - size + 1):
                phrase = " ".join(words[start:start + size])
                if phrase not in seen:
                    seen.add(phrase)
                    counts[phrase] = counts.get(phrase, 0) + 1

    threshold = max(2, int(len(terms) * 0.6))
    shared = [p for p, n in counts.items() if n >= threshold]
    if not shared:
        return []

    # Prefer the longest, and drop any phrase contained in a longer one, so
    # "spectacular spider-man" wins over "spider-man".
    shared.sort(key=lambda p: (-len(p.split()), -len(p)))
    kept: List[str] = []
    for phrase in shared:
        if not any(phrase in longer for longer in kept):
            kept.append(phrase)
    return kept[:4]


def matches_show(clip: SourceClip, settings: Dict) -> Tuple[bool, str]:
    """The show filter. Returns (ok, reason_if_not)."""
    if not settings.get("require_show_match"):
        return True, ""

    text = _haystack(clip)
    show_terms = [t.lower() for t in settings.get("show_terms", []) if t]
    people = [p for p in settings.get("show_people", []) if str(p).strip()]
    if not show_terms and not people:
        # Nothing configured. Rather than refuse everything, work out what the
        # niche is about from what it searches for.
        show_terms = derived_show_terms(settings)
        if show_terms:
            log.info("Show filter had no keywords; using %s from the search "
                     "terms.", show_terms)
        else:
            # Genuinely nothing to go on -- one vague search term and no
            # names. Refusing the whole run helps nobody.
            log.warning("Show filter is on but nothing identifies the show, "
                        "and the search terms are too thin to guess from. "
                        "Letting clips through; add Show keywords.")
            return True, ""
    if any(term in text for term in show_terms):
        return True, ""

    # Count distinct people, not distinct words: one person's aliases must
    # never look like two different regulars.
    found = set()
    for entry in settings.get("show_people", []):
        aliases = [a.strip().lower() for a in str(entry).split("|") if a.strip()]
        if aliases and any(alias in text for alias in aliases):
            found.add(aliases[0])
    if len(found) >= 2:
        return True, ""

    trusted = [t.lower() for t in settings.get("trusted_uploaders", []) if t]
    if trusted and any(t in (clip.author or "").lower() for t in trusted):
        return True, ""

    return False, "no evidence it is from this show"


def apply(clips: Sequence[SourceClip], settings: Dict) -> List[SourceClip]:
    """Run all three gates, logging why anything was dropped."""
    kept: List[SourceClip] = []
    dropped = 0
    for clip in clips:
        ok, reason = passes_filters(clip, settings)
        if ok:
            derivative, term = is_derivative(clip, settings)
            if derivative:
                ok, reason = False, f"looks like an edit ({term!r})"
        if ok:
            ok, reason = matches_show(clip, settings)
        if not ok:
            dropped += 1
            log.debug("Dropped %r: %s", (clip.title or "")[:44], reason)
            continue
        kept.append(clip)

    if dropped:
        log.info("Selection kept %d of %d clip(s).", len(kept), len(clips))
    return kept
