"""
moments.py -- Find the moment inside a long source video.

Until this existed, one source video became exactly one clip, and the excerpt
was whatever happened to be in the middle of it. That single fact is what made
the output bad, and it made it bad in three separate ways at once:

* **Reuse.** One video could only ever yield one clip, so a niche with eight
  usable videos ran out after eight. The ninth run repeated itself.
* **The wrong show.** Because a whole video had to *be* the clip, discovery
  had to look for videos that were already short -- and short Spider-Man
  videos are mostly other people's edits, other series, and scenes from the
  films. A finished "Spectacular Spider-Man" render contained a scene from
  the Andrew Garfield film and a schoolwork video about the scientific
  method, and both are perfectly good matches for a metadata search.
* **Commentary.** Same cause. The short-video pool is full of people talking
  *about* the show, and no keyword list catches all of them, because the only
  honest difference between "Spider-Man scene" and "Spider-Man video essay"
  is what is on the screen.

Sourcing a playlist of full episodes and cutting the moments out of them
removes all three at the root. An episode is twenty minutes of the actual
programme: there is no question of whether it is the right show, nobody is
talking over it, and it holds a dozen different moments rather than one.

So this module answers the question that then becomes the whole product:
given twenty minutes of footage, *which twenty seconds*?

It answers from the material rather than from metadata:

* **Dialogue density**, from the subtitle track the downloader already
  fetches. In an animated comedy the dense-dialogue stretches are the scenes;
  the sparse ones are the fights and the establishing shots.
* **Reaction markers** -- [laughter], [applause], [gasps] -- which caption
  tracks mark and which point straight at the beat.
* **Loudness**, from one audio-only pass, so a physical gag with no dialogue
  is still found.
* **Niche keywords**, when the subscriber has named the catchphrases.
* **Minus music**, because a stretch that is nothing but the score is the
  montage, and it is also the stretch most likely to draw a claim.

Everything degrades rather than fails: no subtitles falls back to loudness,
no audio scan falls back to dialogue, and neither falls back to evenly spaced
windows -- which still beats the centre, because at least the five clips
differ from each other.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..config import settings
from ..logging_setup import get_logger
from ..sources.base import SourceClip
from . import curator
from .overlay import _NON_SPEECH, parse_vtt

log = get_logger("render.moments")

#: How often a candidate window is tried, in seconds. Two is fine-grained
#: enough to land on a scene and coarse enough that a 40-minute source is a
#: few hundred windows rather than a few thousand.
_STEP = 2.0

#: Words a second that counts as full-tilt dialogue. Measured off animated
#: comedy, where three is a busy two-hander and one is someone narrating over
#: a wide shot.
_BUSY_WORDS_PER_SECOND = 3.0

#: Cues that mark a reaction rather than speech. Deliberately narrower than
#: overlay's non-speech set: music is a penalty here, not a signal.
_REACTION = re.compile(
    r"(laugh|chuckl|giggl|applause|cheer|clap|gasp|scream|yell|shout|"
    r"groan|grunt|whoop)", re.IGNORECASE)

#: The other half of the non-speech set: the score playing.
_MUSIC = re.compile(r"(music|instrumental|theme|singing|♪|♫|♩|♬)",
                    re.IGNORECASE)

#: Auto-captions are mostly these. A candidate label made only of them says
#: nothing about the moment.
_FILLER = {
    "a", "the", "and", "but", "so", "or", "of", "to", "in", "on", "at", "it",
    "is", "was", "are", "were", "be", "been", "am", "i", "you", "he", "she",
    "we", "they", "this", "that", "there", "here", "just", "like", "well",
    "yeah", "yes", "no", "oh", "uh", "um", "er", "hey", "okay", "ok", "hmm",
    "gonna", "wanna", "got", "get", "know", "think", "right", "now", "then",
    "what", "why", "how", "do", "did", "does", "not", "my", "me", "your",
}

#: Small words a title-cased label leaves alone, so a quote does not read
#: like a headline from 1890.
_LOWER_IN_TITLE = {
    "a", "an", "and", "at", "but", "by", "for", "in", "of", "on", "or",
    "the", "to", "vs", "with",
}

#: ebur128 prints one of these per audio frame. The format has been stable
#: for a decade, and anything unparseable simply means no loudness signal.
_EBUR128 = re.compile(
    r"\bt:\s*(\d+(?:\.\d+)?)\b.*?\bM:\s*(-?\d+(?:\.\d+)?|-?inf)",
    re.IGNORECASE)

#: Below this, ebur128 is reporting silence rather than a quiet passage.
_SILENCE_LUFS = -70.0


@dataclass
class Cut:
    """One excerpt, and where inside its source it comes from.

    A ``start`` of None means "wherever the trim strategy puts it": a short
    source is a clip rather than a haystack, and nothing is gained by
    searching a twelve-second video for the best eight seconds of it.
    """

    clip: SourceClip
    start: Optional[float] = None
    duration: float = 0.0
    source_duration: float = 0.0
    score: float = 0.0
    label: str = ""
    why: str = ""
    #: What is said inside the window. The label is one line chosen to read
    #: well in the list; this is the whole excerpt, and it is what the curator
    #: judges against the niche.
    excerpt: str = ""

    @property
    def mined(self) -> bool:
        return self.start is not None

    def moment_id(self) -> str:
        """The history key: this moment, not the whole video.

        Burning a whole episode because one scene from it went out is what
        made a niche run dry after a handful of runs. The episode is a
        haystack and can be returned to; the scene cannot.
        """
        if self.start is None:
            return self.clip.external_id
        return f"{self.clip.external_id}@{int(round(self.start))}"


@dataclass
class _Cue:
    start: float
    end: float
    text: str
    words: int = 0
    music: bool = False
    reaction: bool = False


@dataclass
class _Window:
    start: float
    score: float
    parts: Dict[str, float] = field(default_factory=dict)

    def why(self) -> str:
        best = sorted(self.parts.items(), key=lambda kv: -kv[1])
        named = [name for name, value in best if value > 0.05][:2]
        return ", ".join(named) or "evenly spaced"


# --------------------------------------------------------------------- #
# Reading the source
# --------------------------------------------------------------------- #
def _cues(clip: SourceClip) -> List[_Cue]:
    """The source's subtitle track, classified. Empty when it has none."""
    path = (clip.extra or {}).get("subtitle_path")
    if not path or not Path(path).exists():
        return []
    try:
        raw = parse_vtt(Path(path), include_non_speech=True)
    except Exception as exc:  # noqa: BLE001 - a bad caption file is not a failure
        log.debug("Could not read captions for %s: %s", clip.external_id, exc)
        return []

    out: List[_Cue] = []
    for cue in raw:
        if cue.end <= cue.start:
            continue
        text = cue.text.strip()
        if _NON_SPEECH.fullmatch(text):
            out.append(_Cue(cue.start, cue.end, text, words=0,
                            music=bool(_MUSIC.search(text)),
                            reaction=bool(_REACTION.search(text))))
            continue
        # A cue can carry both: "[Laughter] you have got to be kidding".
        out.append(_Cue(cue.start, cue.end, text, words=len(text.split()),
                        music=False,
                        reaction=bool(_REACTION.search(text))))
    return out


def _loudness(path: Path, timeout: float = 240.0) -> List[Tuple[float, float]]:
    """Momentary loudness over the whole file, as (seconds, LUFS).

    One audio-only pass. Video is never decoded, which is what keeps this
    affordable on a twenty-minute episode.
    """
    command = [
        settings.ffmpeg, "-nostdin", "-hide_banner", "-nostats",
        "-i", str(path), "-vn", "-filter_complex", "ebur128=peak=none",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout)
    except (subprocess.SubprocessError, OSError) as exc:
        log.debug("Loudness scan failed for %s: %s", path.name, exc)
        return []

    curve: List[Tuple[float, float]] = []
    for line in (proc.stderr or "").splitlines():
        match = _EBUR128.search(line)
        if not match:
            continue
        when = float(match.group(1))
        raw = match.group(2).lower()
        level = _SILENCE_LUFS if "inf" in raw else float(raw)
        curve.append((when, max(level, _SILENCE_LUFS)))
    return curve


def _band(values: Sequence[float]) -> Tuple[float, float]:
    """The 10th and 90th percentile, so one explosion is not the whole scale."""
    if not values:
        return 0.0, 1.0
    ordered = sorted(values)
    low = ordered[int(len(ordered) * 0.10)]
    high = ordered[min(len(ordered) - 1, int(len(ordered) * 0.90))]
    if high - low < 1.0:
        return low, low + 1.0
    return low, high


# --------------------------------------------------------------------- #
# Scoring one window
# --------------------------------------------------------------------- #
def _overlap(a_start: float, a_end: float,
             b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _keywords(fmt: Dict) -> List[str]:
    """What the subscriber says marks a moment, lowercased."""
    return [str(k).strip().lower()
            for k in (fmt.get("moment_keywords") or []) if str(k).strip()]


def _score_window(start: float, length: float, cues: Sequence[_Cue],
                  curve: Sequence[Tuple[float, float]],
                  loud_band: Tuple[float, float],
                  keywords: Sequence[str]) -> _Window:
    end = start + length
    spoken = 0.0
    music_seconds = 0.0
    reactions = 0
    hits = 0

    for cue in cues:
        share = _overlap(start, end, cue.start, cue.end)
        if share <= 0:
            continue
        span = max(0.05, cue.end - cue.start)
        fraction = share / span
        if cue.music:
            music_seconds += share
        if cue.reaction:
            reactions += 1
        if cue.words:
            spoken += cue.words * fraction
            if keywords:
                lowered = cue.text.lower()
                hits += sum(1 for word in keywords if word in lowered)

    parts: Dict[str, float] = {
        "dialogue": _clamp(spoken / length / _BUSY_WORDS_PER_SECOND),
        "reactions": _clamp(reactions / 2.0),
        "keywords": _clamp(hits / 2.0),
    }
    weights = {"dialogue": 0.40, "reactions": 0.15, "keywords": 0.20}

    if curve:
        levels = [level for when, level in curve if start <= when < end]
        if levels:
            low, high = loud_band
            mean = sum(levels) / len(levels)
            parts["audio"] = _clamp((mean - low) / (high - low))
            weights["audio"] = 0.25

    # Only the signals actually available divide the score, so a source with
    # no captions is not scored as though every window in it were silent.
    # Without this a video with subtitles always beat one without, whatever
    # was in either of them.
    total = sum(weights.values()) or 1.0
    score = sum(parts[name] * weight
                for name, weight in weights.items()) / total

    # Music is a penalty rather than a signal: a stretch that is nothing but
    # the score is the montage, and it is what a claim is filed against.
    music_share = _clamp(music_seconds / length)
    score -= 0.5 * music_share
    if music_share:
        parts["music"] = -music_share

    return _Window(start=start, score=max(0.0, score), parts=parts)


# --------------------------------------------------------------------- #
# Labels
# --------------------------------------------------------------------- #
def _titleish(text: str) -> str:
    """Capitalise an auto-caption line without shouting it.

    Auto-captions arrive lowercase and unpunctuated, and a numbered list of
    lowercase fragments reads as a mistake rather than a style.
    """
    if any(c.isupper() for c in text):
        return text
    out: List[str] = []
    for index, word in enumerate(text.split()):
        if word == "i" or word.startswith("i'"):
            out.append("I" + word[1:])
        elif index and word.lower() in _LOWER_IN_TITLE:
            out.append(word.lower())
        else:
            out.append(word[:1].upper() + word[1:])
    return " ".join(out)


def _trim_words(text: str, limit: int) -> str:
    """Cut on a word boundary, or return nothing rather than half a word."""
    if len(text) <= limit:
        return text
    kept: List[str] = []
    for word in text.split():
        if len(" ".join(kept + [word])) > limit:
            break
        kept.append(word)
    # Two words of a sentence names nothing; the title is better than that.
    return " ".join(kept) if len(kept) >= 3 else ""


def _excerpt(cues: Sequence[_Cue], start: float, end: float,
             limit: int = 420) -> str:
    """Everything spoken inside the window, as one run of text."""
    said: List[str] = []
    for cue in cues:
        if not cue.words or cue.end <= start or cue.start >= end:
            continue
        said.append(cue.text.strip())
    text = " ".join(" ".join(said).split())
    return text[:limit]


def _quote(cues: Sequence[_Cue], start: float, end: float,
           limit: int = 38) -> str:
    """A line said inside the window, to name the moment in the list.

    A quote beats the video's title here, and by a distance: every moment cut
    from one episode carries the same title, so a five-entry list read as the
    same episode name five times over.
    """
    best = ""
    best_weight = 0
    # Kept separately, and only used if nothing fits. A scene where every
    # line runs long otherwise produced no label at all, and the entry fell
    # back to the episode's title -- which is the failure this exists to
    # avoid, arrived at from the other direction.
    overlong = ""
    overlong_weight = 0

    for cue in cues:
        if not cue.words or cue.start < start or cue.end > end:
            continue
        text = re.sub(r"\[[^\]]*\]|\([^\)]*\)", " ", cue.text)
        words = [w for w in text.split() if w.strip(".,!?'\"")]
        if not 3 <= len(words) <= 12:
            continue
        meaty = [w for w in words if w.strip(".,!?'\"").lower() not in _FILLER]
        if len(meaty) < 2:
            continue
        candidate = " ".join(words)
        # Substance before length, so "you have got to be kidding me" beats
        # "and then the thing that we were going to do".
        weight = len(meaty) * 2 + len(words)
        if len(candidate) <= limit:
            if weight > best_weight:
                best_weight, best = weight, candidate
        elif weight > overlong_weight:
            overlong_weight, overlong = weight, candidate

    chosen = best or _trim_words(overlong, limit)
    if not chosen:
        return ""
    return _titleish(chosen.strip(" ,.-"))


# --------------------------------------------------------------------- #
# Mining one source
# --------------------------------------------------------------------- #
def slot_seconds(fmt: Dict) -> float:
    """How long one entry in the finished video gets.

    The same arithmetic the segment planner uses, so the window that was
    scored is the window that gets cut.
    """
    target = float(fmt.get("target_seconds", 105) or 105)
    count = max(1, int(fmt.get("clips", 5) or 5))
    low = float(fmt.get("min_clip_seconds", 8) or 8)
    high = float(fmt.get("max_clip_seconds", 26) or 26)
    return max(low, min(high, target / count))


def _used_windows(clip: SourceClip, already_used: Optional[Dict],
                  slot: float) -> List[Tuple[float, float]]:
    """Stretches of this source that a finished video has already shown."""
    if not already_used:
        return []
    windows: List[Tuple[float, float]] = []
    for source, external_id in already_used:
        if source != clip.source:
            continue
        head, _, tail = str(external_id).rpartition("@")
        if head == clip.external_id and tail.isdigit():
            start = float(tail)
            windows.append((start, start + slot))
        elif external_id == clip.external_id:
            # Published before moments existed, when the excerpt was always
            # the middle. The rest of the episode was never used and must not
            # be treated as though it had been.
            centre = max(0.0, (clip.duration or 0.0) / 2 - slot / 2)
            windows.append((centre - slot, centre + 2 * slot))
    return windows


def _snap(start: float, cues: Sequence[_Cue], reach: float = 4.0) -> float:
    """Move the start into the nearest pause, so a cut is not mid-sentence."""
    speech = [c for c in cues if c.words]
    if not speech:
        return start
    best, best_gap = start, 0.0
    for index in range(len(speech) - 1):
        gap_start, gap_end = speech[index].end, speech[index + 1].start
        gap = gap_end - gap_start
        if gap <= 0.25 or abs(gap_start - start) > reach:
            continue
        if gap > best_gap:
            best_gap, best = gap, gap_start + min(0.25, gap / 3)
    return max(0.0, best)


def mine(clip: SourceClip, fmt: Dict, wanted: int,
         already_used: Optional[Dict] = None) -> List[Cut]:
    """The best `wanted` moments inside one long source, best first."""
    return mine_candidates(clip, fmt, wanted, already_used)


def mine_candidates(clip: SourceClip, fmt: Dict, wanted: int,
                    already_used: Optional[Dict] = None) -> List[Cut]:
    """Up to `wanted` non-overlapping moments, best-measured first.

    Asked for more than the video needs when a curator is available: the
    heuristic decides what is worth *considering* and the shortlist is then
    judged against the niche. Asked for exactly what is needed otherwise, in
    which case this is the whole decision.
    """
    duration = float(clip.duration or 0.0)
    slot = slot_seconds(fmt)
    head = float(fmt.get("skip_intro_seconds", 20) or 0)
    tail = float(fmt.get("skip_outro_seconds", 30) or 0)

    first = min(head, max(0.0, duration - slot))
    last = duration - tail - slot
    if last <= first:
        # A short source, or one where the skips swallow the whole thing.
        # Search all of it rather than returning nothing.
        first, last = 0.0, max(0.0, duration - slot)
    if last <= 0:
        return []

    cues = _cues(clip)
    curve: List[Tuple[float, float]] = []
    if fmt.get("moment_audio_scan", True) and clip.local_path:
        curve = _loudness(Path(clip.local_path))
    loud_band = _band([level for _, level in curve])
    keywords = _keywords(fmt)

    gap = max(float(fmt.get("moment_min_gap_seconds", 90) or 0), slot)
    blocked = _used_windows(clip, already_used, slot)

    if cues or curve:
        windows: List[_Window] = []
        position = first
        while position <= last + 0.001:
            windows.append(_score_window(position, slot, cues, curve,
                                         loud_band, keywords))
            position += _STEP
    else:
        # Nothing to go on. Every window would score identically and the sort
        # below would take the first `wanted` of them -- five consecutive
        # windows from the top of the episode. Spacing them is the honest
        # fallback, and still better than the centre, which gave one.
        log.info("No captions or audio for %r; spacing %d moment(s) evenly.",
                 (clip.title or "")[:40], wanted)
        span = max(0.0, last - first)
        windows = [_Window(start=first + span * index / max(1, wanted),
                           score=0.5, parts={})
                   for index in range(max(1, wanted))]
        gap = min(gap, span / max(1, wanted) if span else gap)

    chosen: List[_Window] = []
    for window in sorted(windows, key=lambda w: (-w.score, w.start)):
        if any(abs(window.start - taken.start) < gap for taken in chosen):
            continue
        if any(_overlap(window.start, window.start + slot, low, high)
               > slot * 0.4 for low, high in blocked):
            continue
        chosen.append(window)
        if len(chosen) >= wanted:
            break

    cuts: List[Cut] = []
    for window in chosen:
        start = _snap(window.start, cues)
        start = max(0.0, min(start, max(0.0, duration - slot)))
        cuts.append(Cut(
            clip=clip,
            start=round(start, 3),
            duration=round(min(slot, duration - start), 3),
            source_duration=duration,
            score=window.score,
            label=_quote(cues, start, start + slot),
            why=window.why(),
            excerpt=_excerpt(cues, start, start + slot),
        ))
    return cuts


# --------------------------------------------------------------------- #
# Across the whole job
# --------------------------------------------------------------------- #
def _interleave(per_video: Sequence[Sequence[Cut]], wanted: int) -> List[Cut]:
    """Take everyone's best before anyone's second best.

    Five moments from one episode is a video that feels like one scene, and
    that is the failure a subscriber reports as "it reuses the same clips".
    The round-robin is what spreads the cut across the playlist.
    """
    ranked = sorted((list(cuts) for cuts in per_video if cuts),
                    key=lambda cuts: -cuts[0].score)
    out: List[Cut] = []
    depth = 0
    while len(out) < wanted:
        added = False
        for cuts in ranked:
            if depth < len(cuts):
                out.append(cuts[depth])
                added = True
                if len(out) >= wanted:
                    break
        if not added:
            break
        depth += 1
    return out


def _curate(per_source: List[List[Cut]], fmt: Dict, niche_name: str) -> None:
    """Re-score the shortlists against what the subscriber said they want.

    In place, and across every source at once, so a moment from episode four
    can beat one from episode one on relevance rather than only on how loud it
    was. Does nothing at all when there is no key, no description, or the call
    fails -- see curator.py.
    """
    if not fmt.get("ai_moment_ranking", True) or not curator.available():
        return
    description = str(fmt.get("description") or "")
    flat = [cut for cuts in per_source for cut in cuts if cut.mined]
    if len(flat) < 2:
        return

    judged = curator.rank(
        [{"source": (c.clip.title or "")[:60], "start": c.start or 0.0,
          "excerpt": c.excerpt} for c in flat],
        description=description, niche_name=niche_name)
    if not judged:
        return

    for index, cut in enumerate(flat):
        verdict = judged.get(index)
        if verdict is None:
            continue
        cut.score = curator.blend(cut.score, verdict["score"])
        if verdict["why"]:
            cut.why = verdict["why"]

    # Each source's own shortlist is re-ordered, so the "best from every
    # video first" rule below hands over what the niche asked for rather than
    # what merely measured loudest.
    for cuts in per_source:
        cuts.sort(key=lambda c: -c.score)


def plan(clips: Sequence[SourceClip], fmt: Dict, wanted: int,
         already_used: Optional[Dict] = None,
         niche_name: str = "") -> List[Cut]:
    """Turn downloaded sources into the excerpts the video is made of.

    A long source contributes several moments and a short one contributes
    itself, so a mixed pool -- two full episodes and three clips somebody
    uploaded -- works without the caller knowing which is which.

    With a curator available the heuristic shortlists rather than decides: it
    is good at finding where something is happening and blind to whether that
    something is what the channel is about.
    """
    long_at = float(fmt.get("long_clip_seconds", 75) or 75)
    per_video = max(1, int(fmt.get("moments_per_video", 2) or 1))
    shortlisting = (bool(fmt.get("ai_moment_ranking", True))
                    and curator.available()
                    and bool(str(fmt.get("description") or "").strip()))
    #: Three per slot is enough for the ranking to have a real choice without
    #: the prompt growing past what MAX_CANDIDATES will take anyway.
    per_source_limit = min(per_video * 3, 8) if shortlisting else per_video

    per_source: List[List[Cut]] = []
    for clip in clips:
        duration = float(clip.duration or 0.0)
        if duration > long_at:
            found = mine_candidates(clip, fmt, max(per_video, per_source_limit),
                                    already_used)
            if found:
                log.info("%r: %d candidate moment(s) at %s.",
                         (clip.title or "")[:40], len(found),
                         ", ".join(f"{c.start:.0f}s" for c in found))
                per_source.append(found)
                continue
        per_source.append([Cut(clip=clip, start=None, duration=0.0,
                               source_duration=duration, score=0.0)])

    _curate(per_source, fmt, niche_name)

    # Only now cut each source back to its share, so the ranking got to see
    # everything before anything was thrown away.
    per_source = [cuts[:per_video] if any(c.mined for c in cuts) else cuts
                  for cuts in per_source]

    cuts = _interleave(per_source, wanted)
    # Best first. The countdown reverses the timeline, so this is what puts
    # the strongest moment at number one, instead of whichever video happened
    # to download last.
    cuts.sort(key=lambda c: -c.score)
    for cut in cuts:
        log.info("  chose %r at %ss -- %s",
                 (cut.clip.title or "")[:32],
                 f"{cut.start:.0f}" if cut.start is not None else "whole",
                 cut.why or "no reason recorded")
    return cuts
