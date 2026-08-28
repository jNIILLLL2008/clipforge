"""
pipeline.py -- One job, start to finish.

Order matters here. Clips are gathered, a plan is built, and the plan is scored
for retention *before* anything is encoded. A weak video is rejected while it
costs nothing, and the user's monthly allowance is only spent on a render that
actually happened.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..config import settings
from ..logging_setup import get_logger
from .. import sources as source_registry
from ..sources.base import SourceClip
from . import selection
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


def _noop(stage: str, detail: str) -> None:
    log.info("[%s] %s", stage, detail)


def gather(niche_settings: Dict, wanted: int,
           user_id: Optional[int]) -> List[SourceClip]:
    """Collect candidates across every permitted source, then filter them."""
    adapters = source_registry.for_job(niche_settings.get("sources") or [],
                                       user_id, niche_settings)
    if not adapters:
        raise RenderError(
            "No usable content sources. Add your own clips, or ask the operator "
            "to configure a stock library."
        )

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
    """Fetch clips until enough usable ones exist locally."""
    ready: List[SourceClip] = []
    for index, clip in enumerate(pool):
        if len(ready) >= wanted:
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
    return ready


def _plan_segments(clips: List[SourceClip], fmt: Dict) -> List[Segment]:
    """Give every clip an even share of the target, inside the niche's bounds."""
    target = float(fmt.get("target_seconds", 105))
    min_len = float(fmt.get("min_clip_seconds", 8))
    max_len = float(fmt.get("max_clip_seconds", 26))
    strategy = str(fmt.get("clip_trim_strategy", "center")).lower()
    share = target / max(len(clips), 1)

    segments: List[Segment] = []
    remaining = target
    for clip in clips:
        if remaining <= 0.5:
            break
        available = clip.duration or 0.0
        length = min(share, max_len, available, remaining)
        if length < min(min_len, available):
            length = min(min_len, available, remaining)
        if length < 1.0:
            continue

        # Where inside the source the excerpt comes from. Centre is the default
        # because the opening second of a stock clip is often a fade-in.
        slack = available - length
        if slack <= 1.0:
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
            label=clip.title[:60],
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
    pool = gather(fmt, wanted, user_id)
    if not pool:
        raise RenderError(
            "No clips matched this niche. Try broader search terms, or upload "
            "your own footage."
        )

    progress("sourcing", f"Downloading {min(wanted, len(pool))} clip(s)")
    clips = _download_all(pool, workspace, wanted, user_id, fmt)
    if len(clips) < 2:
        raise RenderError(
            f"Only {len(clips)} clip(s) could be downloaded; at least 2 are "
            "needed to build a video."
        )

    progress("curating", "Planning the cut")
    segments = _plan_segments(clips, fmt)
    if len(segments) < 2:
        raise RenderError("The clips were too short to build a video from.")
    clips = clips[:len(segments)]

    labels = [c.title[:34] for c in clips]
    if fmt.get("countdown"):
        # Countdown shows the payoff last, so reverse into the timeline.
        clips = list(reversed(clips))
        segments = list(reversed(segments))
        labels = [c.title[:34] for c in clips]

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
        )

    progress("rendering", f"Encoding {len(segments)} clip(s)")
    result = render(segments, plan, fmt, output, watermark)

    credits = [c.credit() for c in clips if c.credit()]
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
