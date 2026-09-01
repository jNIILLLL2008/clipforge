"""
pipeline.py -- One job, start to finish.

Order matters here. Clips are gathered, a plan is built, and the plan is scored
for retention *before* anything is encoded. A weak video is rejected while it
costs nothing, and the user's monthly allowance is only spent on a render that
actually happened.
"""

from __future__ import annotations

import copy
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..config import settings
from ..logging_setup import get_logger
from .labels import clean as _clean_label, for_cuts as build_cut_labels
from .. import sources as source_registry
from ..sources.base import SourceClip
from . import moments, selection
from .moments import Cut
from .engine import RenderError, Segment, media_summary, render
from .overlay import Caption, OverlayItem, OverlayPlan, chunk, parse_vtt
from .retention import PlannedClip, RetentionReport, score_plan

log = get_logger("render.pipeline")

Progress = Callable[[str, str], None]     # (stage, detail)


@dataclass
class PipelineResult:
    output: Path
    thumbnail: Optional[Path]
    duration: float
    size_bytes: int
    clips: List[SourceClip]
    plan: OverlayPlan
    retention: RetentionReport
    title: str
    credits: List[str]
    #: What sourcing actually did -- how many candidates were found, how many
    #: the filters threw away, and how many clips are repeats. Without this a
    #: video full of clips you have seen before is indistinguishable from a
    #: broken playlist, and the only place the difference was recorded was a
    #: log line nobody reads.
    sourcing: Dict = field(default_factory=dict)


def _noop(stage: str, detail: str) -> None:
    log.info("[%s] %s", stage, detail)


def _refuse_blind_search(niche_settings: Dict, adapters) -> None:
    """Refuse a run that would search YouTube for whatever matches the words.

    Enforced here rather than only in the advice, because the advice is
    checked by one route. The API creates jobs without consulting it and the
    daily scheduler never sees it at all, so a subscriber who set automation
    up once would go on producing these videos every morning with nothing
    anywhere telling them why.

    What it refuses is narrow: YouTube switched on with no playlist and no
    channel, which is the only configuration where discovery falls back to a
    keyword search. Naming either one is a decision about what to use, and
    both are honoured. This is the only capability the product removes
    outright, and it is removed because three rounds of filtering could not
    make its output publishable -- see advice.py for the full reasoning.
    """
    if not any(getattr(a, "name", "") == "youtube" for a in adapters):
        return
    playlists = [p for p in (niche_settings.get("source_playlists") or [])
                 if str(p).strip()]
    channels = [c for c in (niche_settings.get("source_channels") or [])
                if str(c).strip()]
    if playlists or channels:
        return
    raise RenderError(
        "Nothing says which videos to use. Clips would be found by searching "
        "YouTube for your terms, and a search returns fan edits, reaction "
        "videos and clips from other series as readily as the show you want "
        "-- so the run is refused rather than spent on it. Paste a playlist "
        "of full episodes under Playlists, or name a channel under Source "
        "channels."
    )


def _times_mined(clip: SourceClip, already_used) -> int:
    """How many moments this account has already published from one source."""
    total = 0
    for source, external_id in already_used or ():
        if source != clip.source:
            continue
        head, _, tail = str(external_id).rpartition("@")
        if external_id == clip.external_id or (
                head == clip.external_id and tail.isdigit()):
            total += 1
    return total


def gather(niche_settings: Dict, wanted: int,
           user_id: Optional[int],
           already_used: Optional[set] = None,
           report: Optional[Dict] = None) -> List[SourceClip]:
    """Collect candidates across every permitted source, then filter them.

    ``report``, when given, is filled in with what happened: the counts a
    person needs to tell "my playlist is being ignored" apart from "my
    playlist only has six videos in it".
    """
    stats = report if report is not None else {}
    adapters = source_registry.for_job(niche_settings.get("sources") or [],
                                       user_id, niche_settings)
    if not adapters:
        raise RenderError(
            "No usable content sources. Add your own clips, or ask the operator "
            "to configure a stock library."
        )

    _refuse_blind_search(niche_settings, adapters)

    terms = list(niche_settings.get("search_terms") or [])
    pool_size = int(niche_settings.get("candidate_pool_size", 40))
    per_source = max(4, min(pool_size, wanted * 4))

    raw: List[SourceClip] = []
    for adapter in adapters:
        try:
            found = adapter.search(terms, per_source)
        except Exception as exc:  # noqa: BLE001 - one bad source must not stop a job
            log.warning("Source %s failed: %s", adapter.name, exc)
            continue

        for clip in found:
            # The licence gate, enforced per clip and not just per adapter.
            if not clip.reusable and not settings.allow_unlicensed_sources:
                log.info("Dropped %r: licence does not permit reuse.",
                         clip.title[:40])
                continue
            raw.append(clip)

    pool = selection.apply(raw, niche_settings)
    stats["candidates"] = len(raw)
    stats["rejected_by_filters"] = len(raw) - len(pool)
    stats["sources"] = sorted({a.name for a in adapters})

    # Everything above ranks the same way every time, so without this the
    # same five clips win every run. Drop what this account has already
    # published and the next run is pushed further down its own ranking.
    if already_used:
        # A long source is a haystack, not a clip. Taking one scene out of an
        # episode is no reason to skip the other nineteen minutes of it, and
        # treating it as spent is what emptied a niche's pool after a handful
        # of runs. Which scenes are off limits is decided per moment, once the
        # episode is downloaded and can actually be searched.
        long_at = float(niche_settings.get("long_clip_seconds", 75) or 75)
        haystacks = [c for c in pool if (c.duration or 0.0) > long_at]
        clips_only = [c for c in pool if (c.duration or 0.0) <= long_at]

        # Least-mined episode first, so successive runs walk the playlist
        # rather than returning to the same two files for the next scene
        # along. Ties keep discovery order, which for a playlist is the order
        # the subscriber put it in.
        order = {id(c): index for index, c in enumerate(haystacks)}
        haystacks.sort(key=lambda c: (_times_mined(c, already_used),
                                      order[id(c)]))

        # Returning to an episode for a different scene is not a repeat, but
        # it is not nothing either, and the run has to say which happened.
        # Without this the counters read "reused: 0" for a video built
        # entirely out of episodes it had already been through -- which is
        # exactly the silence the sourcing report exists to break.
        stats["remined"] = sum(1 for c in haystacks
                               if _times_mined(c, already_used))

        fresh = haystacks + [c for c in clips_only
                             if (c.source, c.external_id) not in already_used]
        stale = [c for c in clips_only
                 if (c.source, c.external_id) in already_used]

        if len(fresh) >= wanted:
            log.info("Skipped %d clip(s) already published.", len(stale))
            pool = fresh
        else:
            # Enough to not repeat is `wanted`, not two. The first version of
            # this checked for two and happily handed a five-clip job a pool
            # of two, because two is what was left after the history came out.
            #
            # So top back up rather than starve. Oldest use first, so a repeat
            # is the clip seen longest ago instead of the one that keeps
            # winning -- which is the whole complaint this was fixing.
            when = already_used if hasattr(already_used, "get") else {}
            stale.sort(key=lambda c: str(when.get((c.source, c.external_id))
                                         or ""))
            topped = stale[:max(0, wanted - len(fresh))]
            if topped:
                log.info(
                    "Only %d unused clip(s) for a %d-clip video; reusing %d "
                    "of the oldest.", len(fresh), wanted, len(topped))
                stats["reused"] = len(topped)
                stats["reused_titles"] = [c.title for c in topped][:6]
                stats["unused_available"] = len(fresh)
            pool = fresh + topped

    stats.setdefault("reused", 0)
    stats.setdefault("remined", 0)
    stats["usable"] = len(pool)
    log.info("Gathered %d candidate clip(s) from %d source(s).",
             len(pool), len(adapters))

    if not pool:
        # Every source coming back empty looks the same from here, but the
        # causes are very different: no uploads, nothing configured to look
        # at, or YouTube refusing a datacentre IP. Each adapter records why,
        # so the job can say which rather than "no clips matched".
        notes = [note for note in
                 (getattr(a, "last_problem", "") for a in adapters) if note]
        if raw and not notes:
            notes.append(
                f"Found {len(raw)} clip(s), but every one was rejected by the "
                "niche filters. Loosen the duration, view count or show filter."
            )
        if notes:
            raise RenderError(" ".join(notes))

    return pool


def _download_all(pool: List[SourceClip], workspace: Path, wanted: int,
                  user_id: Optional[int],
                  job_settings: Optional[Dict] = None) -> List[SourceClip]:
    """Fetch sources until they can supply `wanted` excerpts between them.

    Counted in excerpts rather than in files, because a full episode is worth
    several and a twelve-second clip is worth one. Downloading five episodes
    for a five-clip video wastes four of them, and stopping at two files when
    only short clips turned up leaves the video three short.
    """
    fmt = job_settings or {}
    long_at = float(fmt.get("long_clip_seconds", 75) or 75)
    per_video = max(1, int(fmt.get("moments_per_video", 2) or 1))

    ready: List[SourceClip] = []
    yield_so_far = 0
    for index, clip in enumerate(pool):
        if yield_so_far >= wanted:
            break
        adapter = source_registry.build(clip.source, user_id, job_settings)
        if adapter is None:
            continue
        target = workspace / f"src{index:02d}.mp4"
        try:
            path = adapter.fetch(clip, target)
        except Exception as exc:  # noqa: BLE001
            log.warning("Fetch failed for %r: %s", clip.title[:40], exc)
            continue
        if not path or not Path(path).exists():
            continue
        try:
            duration, _, width, height = media_summary(Path(path))
        except RenderError:
            continue
        if duration < 1.0:
            continue
        clip.local_path = Path(path)
        clip.duration = duration
        clip.width, clip.height = width, height
        ready.append(clip)
        # What a source is worth is known only now: discovery reports a
        # duration, but a listing that lies or a download that stopped early
        # would otherwise be counted as a whole episode.
        yield_so_far += per_video if duration > long_at else 1
    return ready


def _timecode(seconds: float) -> str:
    """12:41, so somebody can open the episode and check."""
    minutes, secs = divmod(int(max(0.0, seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return (f"{hours}:{minutes:02d}:{secs:02d}" if hours
            else f"{minutes}:{secs:02d}")


def _as_excerpt(cut: Cut) -> SourceClip:
    """One excerpt as its own clip, so two moments are two rows in history.

    Several cuts can share a source video. Handing the same SourceClip back
    twice would write two identical job_clips rows, and the reuse history
    would then read them as "this episode is spent" rather than "these two
    scenes are". The copy is shallow on purpose: the subtitle path and the
    licence facts belong to the source and are the same for every moment
    taken out of it.
    """
    excerpt = copy.copy(cut.clip)
    excerpt.external_id = cut.moment_id()
    excerpt.tags = list(cut.clip.tags or [])
    return excerpt


def label_for(clip, fmt) -> str:
    """One clip's label, for the places that have no batch to compare with."""
    return _clean_label(getattr(clip, "title", "") or "", fmt, limit=60) or "Clip"


def _plan_segments(clips: List[SourceClip], fmt: Dict,
                   cuts: Optional[List[Cut]] = None) -> List[Segment]:
    """Give every clip an even share of the target, inside the niche's bounds.

    ``cuts`` carries the moment finder's answer for where inside each source
    the excerpt begins. Without it -- an upload, or a source already short
    enough to be the clip -- the trim strategy decides, as it always has.
    """
    target = float(fmt.get("target_seconds", 105))
    min_len = float(fmt.get("min_clip_seconds", 8))
    max_len = float(fmt.get("max_clip_seconds", 26))
    strategy = str(fmt.get("clip_trim_strategy", "center")).lower()

    segments: List[Segment] = []
    remaining = target
    for index, clip in enumerate(clips):
        if remaining <= 0.5:
            break
        cut = cuts[index] if cuts and index < len(cuts) else None
        # A mined moment can only run to the end of its source, not to the
        # end of the file: measuring from zero would let a segment starting at
        # 19:40 of a twenty-minute episode ask for twenty-four seconds.
        if cut is not None and cut.start is not None:
            available = max(0.0, cut.source_duration - cut.start)
        else:
            available = clip.duration or 0.0

        # Recomputed each time, not fixed at target/len(clips) up front. With
        # a fixed share a single short source just made the whole video
        # shorter and nothing took up the slack: asking for 120s with one
        # 12-second clip in the set produced 108s, and the setting read as a
        # ceiling rather than a target. Spreading what is left over the clips
        # that are left lets the longer ones cover for the short one, still
        # inside max_clip_seconds.
        left = len(clips) - index
        share = remaining / left if left else remaining
        length = min(share, max_len, available, remaining)
        if length < min(min_len, available):
            length = min(min_len, available, remaining)
        if length < 1.0:
            continue

        # Where inside the source the excerpt comes from. Centre is the default
        # because the opening second of a stock clip is often a fade-in.
        slack = available - length
        if cut is not None and cut.start is not None:
            start = cut.start
        elif slack <= 1.0:
            start = 0.0
        elif strategy == "start":
            start = 0.0
        elif strategy == "end":
            start = max(0.0, slack)
        else:
            start = max(0.0, slack / 2)
        segments.append(Segment(
            path=clip.local_path,
            start=round(start, 3),
            duration=round(length, 3),
            label=label_for(clip, fmt),
        ))
        remaining -= length
    return segments


def _captions_for(clip: SourceClip, segment: Segment, fmt: Dict) -> List[Caption]:
    """Captions for one excerpt, re-timed from the source clip's own subtitles.

    Only sources that supply a subtitle file produce any -- stock footage has
    no speech to caption, so an empty list here is normal rather than a fault.
    """
    if not fmt.get("captions_enabled"):
        return []
    path = (clip.extra or {}).get("subtitle_path")
    if not path or not Path(path).exists():
        return []

    window_start = segment.start
    window_end = segment.start + segment.duration
    max_words = int(fmt.get("caption_max_words", 4))

    out: List[Caption] = []
    for cue in parse_vtt(Path(path)):
        if cue.end <= window_start or cue.start >= window_end:
            continue
        clipped = Caption(max(cue.start, window_start),
                          min(cue.end, window_end), cue.text)
        for piece in chunk(clipped, max_words):
            # Times are relative to the segment, which is where the overlay
            # places them on the finished timeline.
            out.append(Caption(piece.start - window_start,
                               piece.end - window_start, piece.text))
    return out


def _build_overlay_plan(clips: List[SourceClip], segments: List[Segment],
                        fmt: Dict, labels: List[str]) -> OverlayPlan:
    plan = OverlayPlan()
    cursor = 0.0
    for position, (clip, segment) in enumerate(zip(clips, segments), start=1):
        label = labels[position - 1] if position <= len(labels) else clip.title[:34]
        plan.items.append(OverlayItem(
            number=position,
            label=label or f"Clip {position}",
            timeline_start=cursor,
            duration=segment.duration,
            captions=_captions_for(clip, segment, fmt),
        ))
        cursor += segment.duration
    return plan


def run_job(*, niche: Dict, options: Dict, user_id: Optional[int],
            workspace: Path, output: Path, watermark: str = "",
            progress: Progress = _noop) -> PipelineResult:
    """Execute one render end to end."""
    # The niche carries the full settings block; per-job options override it.
    from ..settings_schema import sanitise

    fmt = sanitise(options.get("format") or {}, base=niche.get("settings") or {})
    if options.get("search_terms"):
        fmt["search_terms"] = list(options["search_terms"])

    wanted = int(options.get("clips") or fmt.get("clips", 5))
    terms = list(fmt.get("search_terms") or [])
    workspace.mkdir(parents=True, exist_ok=True)

    progress("sourcing", "Looking for clips")
    already_used = options.get("already_used") or set()
    sourcing: Dict = {}
    pool = gather(fmt, wanted, user_id, already_used, report=sourcing)
    if not pool:
        raise RenderError(
            "No clips matched this niche. Try broader search terms, or upload "
            "your own footage."
        )

    progress("sourcing", "Downloading footage")
    sources = _download_all(pool, workspace, wanted, user_id, fmt)
    if not sources:
        raise RenderError(
            "Nothing could be downloaded. The sources may be unavailable, or "
            "YouTube may be refusing this server."
        )

    # A source video is a haystack, not a clip: a full episode holds several
    # moments and this is where they are found. See moments.py for why that
    # is the difference between a compilation of the show and a compilation
    # of videos that mention it.
    progress("curating", "Finding the moments")
    cuts = moments.plan(sources, fmt, wanted, already_used,
                        niche_name=str(niche.get("name") or ""))
    if len(cuts) < 2:
        raise RenderError(
            f"Only {len(cuts)} usable moment(s) were found; at least 2 are "
            "needed to build a video."
        )
    sourcing["moments"] = len(cuts)
    sourcing["mined_from"] = len({c.clip.external_id for c in cuts})

    progress("curating", "Planning the cut")
    clips = [_as_excerpt(cut) for cut in cuts]
    segments = _plan_segments(clips, fmt, cuts)
    if len(segments) < 2:
        raise RenderError("The clips were too short to build a video from.")
    cuts = cuts[:len(segments)]
    clips = clips[:len(segments)]
    for clip, segment in zip(clips, segments):
        # The excerpt's own length, so the library and the reuse history
        # record the moment rather than the episode it came out of.
        clip.duration = segment.duration

    # Not clip.title[:34]. A YouTube title carries the channel name after a
    # separator, the series in brackets and emoji as bait, and cutting it at
    # 34 characters leaves the viewer reading "The Spectacular Spider-Man
    # (2008-2". See labels.py.
    labels = build_cut_labels(cuts, fmt)
    if fmt.get("countdown"):
        # Countdown shows the payoff last, so reverse into the timeline.
        # moments.plan returns best first, so this is what actually puts the
        # strongest moment at number one rather than whichever video happened
        # to download last.
        cuts = list(reversed(cuts))
        clips = list(reversed(clips))
        segments = list(reversed(segments))
        labels = build_cut_labels(cuts, fmt)

    # What it decided, in the order it will play. Until this existed the first
    # sight anybody got of a misread niche was a finished video, with no way
    # to tell a bad choice of moment from a bad playlist -- so "it does not
    # understand what I want" had no evidence behind it either way.
    sourcing["moments_chosen"] = [
        {
            "position": position,
            "source": (cut.clip.title or "")[:80],
            "at": _timecode(cut.start) if cut.start is not None else "whole clip",
            "seconds": round(cut.start, 1) if cut.start is not None else None,
            "label": label,
            "why": cut.why,
            "score": round(cut.score, 3),
        }
        for position, (cut, label) in enumerate(zip(cuts, labels), start=1)
    ]

    plan = _build_overlay_plan(clips, segments, fmt, labels)

    # --- the retention gate, before any encoding happens ------------------ #
    progress("curating", "Checking retention")
    # has_captions must reflect what will actually be burned in. Trusting the
    # setting alone inflated the score for footage that has no speech at all.
    planned = [
        PlannedClip(
            duration=segment.duration,
            label=item.label,
            has_captions=bool(fmt.get("captions_enabled")) and bool(item.captions),
            hook_at=0.0,
        )
        for segment, item in zip(segments, plan.items)
    ]
    report = score_plan(planned, fmt)
    log.info("Retention score %.1f (%s)", report.score, report.verdict)
    if report.rejected:
        return PipelineResult(
            output=Path(), thumbnail=None, duration=0.0, size_bytes=0,
            clips=clips, plan=plan, retention=report, title="", credits=[],
            sourcing=sourcing,
        )

    progress("rendering", f"Encoding {len(segments)} clip(s)")
    result = render(segments, plan, fmt, output, watermark)

    # De-duplicated: two moments cut from one episode are one source to
    # credit, and listing it twice reads as a mistake in the description.
    credits = list(dict.fromkeys(c.credit() for c in clips if c.credit()))
    title = options.get("title") or _default_title(niche, len(segments), terms)

    return PipelineResult(
        output=result.path,
        thumbnail=result.thumbnail,
        duration=result.duration,
        size_bytes=result.size_bytes,
        clips=clips,
        plan=plan,
        retention=report,
        title=title,
        credits=credits,
        sourcing=sourcing,
    )


def _default_title(niche: Dict, count: int, terms: List[str]) -> str:
    """A readable fallback title.

    The subject comes from the search terms the user actually typed. The niche
    *description* is prose written for the picker screen and reads as nonsense
    in a title, so it is never used here.
    """
    name = (niche.get("name") or "Compilation").strip()
    subject = " ".join(t.strip() for t in terms[:2] if t.strip()).title()

    if niche.get("format", {}).get("countdown") or name.lower().startswith("top"):
        return f"Top {count} {subject}".strip() if subject else f"Top {count}"
    return f"{name}: {subject}" if subject else name


def cleanup(workspace: Path) -> None:
    shutil.rmtree(workspace, ignore_errors=True)
