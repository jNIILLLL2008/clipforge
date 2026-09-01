"""
curator.py -- Ask Claude which of the candidate moments fit the niche.

The settings screen has told subscribers this since it was written:

    What this niche is
    Written for the AI that picks clips. Be specific: 'funny studio banter
    between the four pundits on a football panel show' beats 'football'.

Nothing picked clips with it. The description went to metadata.py, which
writes the title and the tags, and the choice of *which twenty seconds* was
made entirely by the heuristic in moments.py. Somebody could write a careful
paragraph about their programme and it changed nothing about the video.

That is also exactly the gap the heuristic leaves. It scores dialogue density,
reaction markers and loudness, which together are a good proxy for "a scene is
happening here" and say nothing at all about *which* scene anybody wanted.
Three niches pointed at one playlist -- funniest moments, best fights, every
time the landlord shows up -- get identical cuts, because nothing in the
scoring can tell them apart.

So the candidates the heuristic finds are shortlisted rather than final, and
their spoken lines go to Claude with the subscriber's own description of the
niche. One call for the whole job: the shortlist is small, and ranking every
candidate together is what lets moments from different episodes be compared.

Everything here is optional and silent. No key, no network, a refusal, bad
JSON, an empty answer -- each one leaves the heuristic ordering exactly as it
was. Rendering a slightly worse video is a much better failure than not
rendering one, and it is the same bargain metadata.py already makes.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Sequence

from ..config import settings
from ..logging_setup import get_logger

log = get_logger("render.curator")

SYSTEM = (
    "You choose which moments from a TV show or video belong in a short-form "
    "compilation. You are given what the channel is about and a numbered list "
    "of candidate moments with the lines spoken in each. Score how well each "
    "one fits what the channel is about. Reply with JSON only."
)

#: Beyond this the prompt stops being worth its cost: the shortlist is already
#: the heuristic's best guesses, and a hundred of them is not a better set of
#: guesses than thirty.
MAX_CANDIDATES = 30

#: Spoken text per candidate. Enough to tell what the scene is, short enough
#: that thirty of them stay well inside one cheap request.
EXCERPT_LIMIT = 420

_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def available() -> bool:
    """Whether ranking can even be attempted."""
    return bool(settings.anthropic_api_key)


def _loads(text: str) -> Optional[Dict]:
    for attempt in (text, _TRAILING_COMMA.sub(r"\1", text)):
        try:
            parsed = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract(raw: str) -> Optional[Dict]:
    """Parse the model's reply, tolerating a code fence around it."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text,
                      flags=re.MULTILINE).strip()
    parsed = _loads(text)
    if parsed is not None:
        return parsed
    start, end = text.find("{"), text.rfind("}")
    return _loads(text[start:end + 1]) if start != -1 and end > start else None


def _clock(seconds: float) -> str:
    minutes, secs = divmod(int(max(0.0, seconds)), 60)
    return f"{minutes}:{secs:02d}"


def _prompt(candidates: Sequence[Dict], description: str,
            niche_name: str) -> str:
    lines = [
        f"Channel: {niche_name or 'a short-form compilation channel'}",
        f"What it is about: {description.strip()[:600]}",
        "",
        f"{len(candidates)} candidate moments:",
    ]
    for index, candidate in enumerate(candidates, start=1):
        lines.append(
            f"{index}. [{candidate.get('source', 'source')} at "
            f"{_clock(candidate.get('start', 0))}] "
            f"{(candidate.get('excerpt') or '(no dialogue)')[:EXCERPT_LIMIT]}"
        )
    lines += [
        "",
        'Return {"scores": [{"n": 1, "score": 0.0-1.0, "why": "a few words"}, '
        "...]} with one entry per candidate.",
        "Score how well the moment fits what the channel is about. A moment "
        "with no dialogue may still be a good one; judge it on what you can "
        "tell. Use the full range -- if half of them do not fit, say so.",
    ]
    return "\n".join(lines)


def rank(candidates: Sequence[Dict], *, description: str,
         niche_name: str = "") -> Dict[int, Dict]:
    """Score the shortlist against the niche. Empty when unavailable.

    Keyed by the candidate's position in the list it was given, because that
    is the only identifier the model is asked to echo back -- and a model
    inventing an id is a failure mode worth not having.
    """
    if not available():
        return {}
    if not description.strip():
        # Nothing to rank *against*. Guessing at the niche from its name would
        # be worse than the heuristic, which at least measures the footage.
        log.info("No niche description; leaving the moment order alone.")
        return {}
    shortlist = list(candidates)[:MAX_CANDIDATES]
    if len(shortlist) < 2:
        return {}

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=settings.ai_model,
            max_tokens=2000,
            system=SYSTEM,
            messages=[{"role": "user",
                       "content": _prompt(shortlist, description, niche_name)}],
        )
        raw = "".join(block.text for block in message.content
                      if getattr(block, "type", "") == "text")
        payload = _extract(raw)
        if not payload:
            raise ValueError(f"no usable JSON in {raw[:160]!r}")

        out: Dict[int, Dict] = {}
        for row in payload.get("scores") or []:
            if not isinstance(row, dict):
                continue
            try:
                position = int(row.get("n"))
                score = float(row.get("score"))
            except (TypeError, ValueError):
                continue
            if not 1 <= position <= len(shortlist):
                continue
            out[position - 1] = {
                "score": max(0.0, min(1.0, score)),
                "why": str(row.get("why") or "")[:60],
            }
        if not out:
            raise ValueError("no scores in the reply")
        log.info("%s ranked %d of %d candidate moment(s).",
                 settings.ai_model, len(out), len(shortlist))
        return out
    except Exception as exc:  # noqa: BLE001 - never fail a render over this
        log.warning("AI moment ranking failed (%s); keeping the measured "
                    "order.", exc)
        return {}


def blend(measured: float, judged: Optional[float]) -> float:
    """Combine what the footage measures with what the niche asked for.

    Not a replacement. The heuristic knows things the transcript cannot show
    -- that a stretch is wall-to-wall music, or silent, or the credits -- and
    a model reading only the lines will happily pick a moment that plays over
    a black screen. Weighted to the judgement because relevance is the thing
    the subscriber actually asked about, but never to the exclusion of what is
    measurably there.
    """
    if judged is None:
        return measured
    return 0.35 * measured + 0.65 * judged
