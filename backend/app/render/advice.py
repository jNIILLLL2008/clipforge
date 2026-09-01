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

import re

#: Whole-word match, so "edit" in a search term is not found
#: inside "credits". Named because an inline r"" is one
#: escaping mistake away from a literal backspace.
BOUNDARY = r"\b"

from dataclasses import dataclass, field
from typing import Dict, List


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

    # --- pasted playlist links -------------------------------------------- #
    # A link that carries no playlist is the easy mistake: the address bar
    # shows a plain video URL unless you opened the playlist itself. Left
    # unsaid, the run just quietly has one fewer place to look.
    pasted = [str(p).strip() for p in (cfg.get("source_playlists") or [])
              if str(p).strip()]
    channels = [str(c).strip() for c in (cfg.get("source_channels") or [])
                if str(c).strip()]
    if not pasted and "youtube" in sources and not channels:
        # A blocker, not a warning, and this is the one place in the product
        # where a capability is removed rather than guarded.
        #
        # YouTube keyword search cannot deliver clips from one specific show.
        # Not with better filters -- three rounds of them were tried. The
        # derivative list grew to sixty terms, the show filter learned to
        # count regulars, video-essay openers were added by name, and the
        # same three clips kept coming back: a schoolwork video about the
        # scientific method, a scene from the Andrew Garfield film, and
        # somebody's edit with their watermark burned into it. Every one is
        # an honest match for the words typed. The pool is the problem, and
        # no filter recovers from a pool that is mostly the wrong thing.
        #
        # Warning it was not enough either: a warning is read once and
        # skipped, and the scheduler never sees one at all. So the run is
        # refused. Failing with an instruction is a better product than
        # succeeding with a video nobody can publish.
        add(Finding(
            "blocker", "Nothing says which videos to use",
            "Clips would be found by searching YouTube for your terms, and a "
            "search returns whatever matches the words: fan edits, reaction "
            "videos, clips from the films and other series, as readily as "
            "your show. That pool cannot be filtered into a good video, so "
            "the run is refused rather than spent on it.",
            "Paste a playlist of full episodes under Playlists, or name a "
            "channel under Source channels.", "source_playlists"))
    if pasted:
        from ..sources.youtube_source import playlist_problem

        # The reason comes from the parser, so the wording matches why it
        # actually refused rather than guessing.
        bad = [(link, playlist_problem(link)) for link in pasted]
        bad = [(link, why) for link, why in bad if why]

        if bad and len(bad) == len(pasted):
            reasons = "; ".join(sorted({why for _, why in bad}))
            add(Finding(
                "blocker", "No usable playlist in what you pasted",
                f"Nothing can be taken from "
                f"{'that link' if len(bad) == 1 else 'those links'}: {reasons}.",
                "Open the playlist itself on YouTube and copy the address from "
                "there -- a usable one contains 'list=' followed by an id.",
                "source_playlists"))
        elif bad:
            add(Finding(
                "warning",
                f"{len(bad)} playlist link(s) skipped",
                "; ".join(f"{link[:44]!r}: {why}" for link, why in bad[:3]),
                "The rest are fine, so the run still has somewhere to look.",
                "source_playlists"))
        elif "youtube" not in sources:
            # The links are fine, but nothing will ever read them.
            add(Finding(
                "warning", "Playlists are set but YouTube is not a source",
                "Clips come from the sources you tick, and the playlist links "
                "are only read by the YouTube source.",
                "Add YouTube under Sources, or the playlists do nothing.",
                "sources"))
        else:
            # A usable playlist takes over YouTube discovery entirely, which is
            # the point -- but it silently stops other settings on the same
            # screen from doing anything, so say so rather than let somebody
            # wonder why their channel list is being ignored.
            displaced = []
            if [c for c in (cfg.get("source_channels") or []) if str(c).strip()]:
                displaced.append("source channels")
            if terms:
                displaced.append("search terms")
            if displaced:
                add(Finding(
                    "tip", "The playlist is the only place it will look",
                    f"Your {' and '.join(displaced)} will not be searched for "
                    "more footage while a playlist is set -- the clips come "
                    "from the playlist and nothing else."
                    + (" Search terms are still used to rank and filter what "
                       "the playlist gives back." if terms else ""),
                    "Clear the playlist to go back to searching.",
                    "source_playlists"))

            # A playlist is a fixed pool, so it runs out -- but far more
            # slowly than it used to, because a long video is no longer worth
            # one clip. A twenty-minute episode is searched and several
            # moments are cut out of it, and the reuse history records the
            # moment rather than the video, so the same episode can be
            # returned to for a different scene. The arithmetic below counts
            # videos per run on that basis.
            per_video = max(1, int(cfg.get("moments_per_video", 2) or 1))
            if int(cfg.get("reuse_after_days", 60) or 0) > 0:
                needed = -(-clips // per_video)      # ceiling division
                add(Finding(
                    "tip", "A playlist runs out",
                    f"Each run uses about {needed} video(s) -- {clips} clip(s) "
                    f"at up to {per_video} moment(s) cut from each -- and "
                    "avoids repeating a moment for a while, so a playlist "
                    "needs several times that many videos to keep producing "
                    "fresh cuts. When it runs dry the run reuses whatever was "
                    "published longest ago rather than failing.",
                    "Add more videos to the playlist, or paste a second one.",
                    "source_playlists"))

            # Five moments from one episode is a video that plays as a single
            # scene, which is the thing the round-robin across sources exists
            # to prevent -- and setting this at or above the clip count opts
            # straight back into it.
            if per_video >= clips:
                add(Finding(
                    "warning", "Every clip could come from one episode",
                    f"{per_video} moment(s) are allowed from each video and "
                    f"the video has {clips} clip(s), so one episode can fill "
                    "the whole thing. It will play as one long scene rather "
                    "than a countdown.",
                    f"Set the per-video limit to about "
                    f"{max(1, clips // 2)}.", "moments_per_video"))

    # --- searching for the thing you just told it to refuse --------------- #
    # "funny moments compilation" is the obvious search to write, and with the
    # derivative filter on it returns a pool that is then thrown away whole.
    if cfg.get("reject_derivative", True) and terms:
        from .selection import _DERIVATIVE_PHRASES, _DERIVATIVE_TERMS

        clash = sorted({
            word
            for term in terms
            for word in tuple(_DERIVATIVE_TERMS) + tuple(_DERIVATIVE_PHRASES)
            if re.search(BOUNDARY + re.escape(word) + BOUNDARY, term)
        })
        if clash:
            add(Finding(
                "warning", "You are searching for edits and refusing them",
                f"{', '.join(repr(c) for c in clash)} appears in your search "
                "terms, but \"Skip other people's edits\" throws those results "
                "away. The run will look busy and find nothing.",
                "Drop that word from the search, or turn the filter off.",
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

    if max_clip * clips < target * 1.15 and share <= max_clip + 0.01:
        # Reachable, but only if every source is long enough. The planner
        # spreads what is left over the clips that are left, so a short clip
        # is covered by the others -- and with no headroom there is nothing
        # to cover it with.
        # "tip", not "note": the app sorts on blocker/warning/tip and colours
        # those three; an unknown level sorts nowhere and renders plain.
        add(Finding(
            "tip", "No slack on the length",
            f"{clips} clips at most {max_clip:g}s each is "
            f"{max_clip * clips:.0f}s against a {target:.0f}s target. If any "
            "source clip is short, nothing can make up the difference.",
            f"Raise the longest segment to about {target / clips * 1.3:.0f}s "
            "for some headroom.", "max_clip_seconds"))

    if share > max_clip + 0.01:
        reachable = max_clip * clips
        # clips x max_clip is a hard ceiling on the whole video, because the
        # planner caps every segment at max_clip_seconds. How much that matters
        # depends entirely on the size of the gap, so this is two findings and
        # not one.
        #
        # Missing 105s by a second is arithmetic nobody needs stopping for --
        # and the shipped defaults do exactly that, 4 clips at 26s being 104s.
        # Asking for 120s and getting 60s is a different thing: that is half a
        # video, it happens every single run, and warned about in a side panel
        # it reads as the length setting being ignored, discovered only after
        # the render has been spent.
        #
        # Nothing is auto-corrected either way. All three numbers were set
        # deliberately, and the clip count drives the numbered list, so quietly
        # raising it to reach the target would rewrite the format.
        needed = target / max(clips, 1)
        if reachable < target * 0.85:
            add(Finding(
                "blocker", "It cannot reach your target length",
                f"{clips} clips at most {max_clip:g}s each is {reachable:.0f}s, "
                f"and that is the whole video -- {target:.0f}s is not "
                f"reachable, so the result would come out {reachable:.0f}s.",
                f"Raise the longest segment to at least {needed:.0f}s, or use "
                f"{-(-target // max_clip):.0f} clips, or lower the target to "
                f"{reachable:.0f}s.",
                "max_clip_seconds"))
        else:
            add(Finding(
                "warning", "It will come up a little short",
                f"{clips} clips at most {max_clip:g}s each is {reachable:.0f}s, "
                f"just under the {target:.0f}s you asked for.",
                f"Raise the longest segment to {needed:.0f}s to hit it exactly.",
                "max_clip_seconds"))
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
