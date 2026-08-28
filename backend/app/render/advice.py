"""
advice.py -- Tell someone why their niche will not produce the video they want.

Most failed first runs are not bugs. They are a configuration that cannot
work: stock-only sources with search terms about a TV show, a show filter with
no keywords, a target length the chosen clips can never fill. The pipeline
would discover each of these several minutes in, having already spent a render.

This checks the same settings up front and says what is wrong in the user's
terms, so the guided setup can stop them before they run it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

# Sources that carry no broadcast, sport or celebrity footage. Someone whose
# niche is a TV show will find nothing in them however good their search terms.
STOCK_ONLY = {"pexels", "pixabay", "openverse", "archive"}

# Words that say "I want footage of a specific programme or person", which is
# exactly what stock libraries do not have.
BROADCAST_HINTS = (
    "show", "tv", "episode", "series", "podcast", "interview", "panel",
    "highlights", "match", "game", "league", "football", "soccer", "nba",
    "nfl", "ufc", "boxing", "celebrity", "reaction", "stream", "twitch",
)


@dataclass
class Finding:
    level: str          # blocker | warning | tip
    title: str
    detail: str
    fix: str = ""
    field: str = ""     # the setting to jump to, when there is one


@dataclass
class Advice:
    findings: List[Finding] = field(default_factory=list)

    @property
    def blockers(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "blocker"]

    @property
    def can_run(self) -> bool:
        return not self.blockers

    def to_dict(self) -> Dict:
        return {
            "can_run": self.can_run,
            "findings": [
                {"level": f.level, "title": f.title, "detail": f.detail,
                 "fix": f.fix, "field": f.field}
                for f in self.findings
            ],
        }


def review(cfg: Dict, *, upload_count: int = 0,
           available_sources: List[str] | None = None) -> Advice:
    """Assess a configuration against what it can actually produce."""
    advice = Advice()
    add = advice.findings.append

    sources = [s for s in (cfg.get("sources") or [])]
    usable = [s for s in sources if not available_sources or s in available_sources]
    terms = [str(t).strip().lower() for t in (cfg.get("search_terms") or []) if str(t).strip()]
    clips = int(cfg.get("clips", 5))

    # --- can it find anything at all? ------------------------------------ #
    if not sources:
        add(Finding("blocker", "No footage source chosen",
                    "Nothing has been selected for it to pull clips from.",
                    "Pick at least one source, or upload your own clips.",
                    "sources"))
    elif not usable:
        add(Finding("blocker", "None of your sources are available",
                    f"You chose {', '.join(sources)}, but none is switched on "
                    "and configured on this server.",
                    "Choose a different source, or upload your own footage.",
                    "sources"))

    if sources == ["upload"] and upload_count == 0:
        add(Finding("blocker", "Your only source is uploads, and you have none",
                    "The run will find nothing to cut.",
                    "Upload clips on the Activity screen, or add another source.",
                    "sources"))
    elif "upload" in sources and upload_count and upload_count < clips:
        add(Finding("warning", f"Only {upload_count} clip(s) uploaded",
                    f"You have asked for {clips} clips per video, so it will "
                    "either repeat itself or come out short.",
                    f"Upload at least {clips}, or lower the clip count.",
                    "clips"))

    # --- is the subject reachable from these sources? --------------------- #
    stock_only = bool(sources) and set(sources) <= STOCK_ONLY
    hinted = [word for word in BROADCAST_HINTS
              if any(word in term for term in terms)]
    if stock_only and hinted:
        add(Finding(
            "blocker", "Stock libraries cannot cover this subject",
            f"Your search terms mention {hinted[0]!r}, but stock footage "
            "libraries hold generic clips, not broadcast, sport or celebrity "
            "footage.",
            "Add your own clips as a source and upload the footage you have "
            "the rights to.",
            "sources"))

    if stock_only and not terms:
        add(Finding("warning", "No search terms with stock sources",
                    "Stock libraries need something to search for; without "
                    "terms the results will be arbitrary.",
                    "Add a few words describing the footage you want.",
                    "search_terms"))

    # --- the show filter -------------------------------------------------- #
    if cfg.get("require_show_match"):
        show_terms = [t for t in (cfg.get("show_terms") or []) if str(t).strip()]
        people = [p for p in (cfg.get("show_people") or []) if str(p).strip()]
        if not show_terms and not people:
            add(Finding(
                "blocker", "The show filter is on but empty",
                "It will reject every clip, because nothing can prove a clip "
                "belongs to your show.",
                "Add show keywords, the regulars' names, or turn the filter "
                "off.", "show_terms"))
        elif not show_terms and len(people) < 2:
            add(Finding(
                "warning", "Only one person named in the show filter",
                "A clip qualifies on a show keyword, or on two different "
                "regulars appearing together. One name alone will reject "
                "almost everything.",
                "Add show keywords, or a second regular.", "show_people"))
        if people and not any("|" in str(p) for p in people):
            add(Finding(
                "tip", "Add name variations",
                "Separate each person's aliases with | so nicknames match too "
                "-- 'thierry henry|thierry|henry'. It also stops one person's "
                "full name being miscounted as two people.",
                "", "show_people"))

    # --- will the maths produce a video? ---------------------------------- #
    target = float(cfg.get("target_seconds", 105))
    min_clip = float(cfg.get("min_clip_seconds", 8))
    max_clip = float(cfg.get("max_clip_seconds", 26))
    share = target / max(clips, 1)

    if share > max_clip + 0.01:
        reachable = max_clip * clips
        add(Finding(
            "warning", "It cannot reach your target length",
            f"{clips} clips at most {max_clip:.0f}s each is {reachable:.0f}s, "
            f"short of the {target:.0f}s you asked for.",
            f"Raise the longest segment, or use more clips.", "max_clip_seconds"))
    if share < min_clip - 0.01:
        # One decimal, or 7.5 rounds to 8 and the sentence reads as a
        # contradiction: "8s each, below your 8s minimum".
        add(Finding(
            "warning", "Segments will be shorter than your minimum",
            f"{target:.0f}s over {clips} clips is {share:.1f}s each, below "
            f"your {min_clip:g}s minimum.",
            "Lower the minimum, use fewer clips, or make the video longer.",
            "min_clip_seconds"))

    # --- will it pass its own retention gate? ----------------------------- #
    cuts_per_min = (clips / target * 60.0) if target else 0
    if cuts_per_min < 8:
        add(Finding(
            "warning", "This will score badly on pace",
            f"{cuts_per_min:.1f} cuts a minute reads as static, and the "
            "retention gate may reject the video before it renders.",
            "Use more clips, or make the video shorter.", "clips"))

    has_text = (cfg.get("captions_enabled") or cfg.get("checklist_enabled")
                or cfg.get("banner_enabled"))
    if not has_text:
        add(Finding(
            "warning", "Nothing on screen to read",
            "Most short-form is watched muted. With no banner, list or "
            "captions the retention gate will mark it down.",
            "Turn on at least the banner or the numbered list.",
            "checklist_enabled"))

    # --- publishing ------------------------------------------------------- #
    if cfg.get("auto_upload") and cfg.get("privacy_status") == "public":
        add(Finding(
            "tip", "Uploads will go straight to public",
            "You will not get to watch one before your subscribers do.",
            "Consider private or unlisted until you have seen a few.",
            "privacy_status"))

    return advice
