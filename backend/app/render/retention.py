"""
retention.py -- Refuse to ship a video that nobody will watch.

"No videos with no retention" only means something if it is checked. This
module scores a *planned* video before it renders, so a weak one is rejected
while it is still cheap to fix -- and the user is not charged a render for it.

The rules encode what actually drives short-form retention, and each one is
here because it is measurable from the plan, not because it sounds good:

* **A hook inside the first ~2 seconds.** The first clip has to open on
  something, not on a title card or a slow fade.
* **No long unbroken shot.** A single shot running past the niche's limit is
  where viewers leave.
* **Enough cuts for the runtime.** Pace is cuts per minute, not total length.
* **A reason to stay to the end.** A countdown, a numbered list, or a payoff
  clip held back. Without one, the video has no promise to keep.
* **On-screen text.** Most short-form is watched muted.
* **Sane total length.** Too short cannot hold a story, too long bleeds.

Scores are 0-100. Below ``REJECT_BELOW`` the job is refused with the specific
reasons, so the failure is actionable rather than a shrug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

REJECT_BELOW = 55.0
WARN_BELOW = 72.0


@dataclass
class PlannedClip:
    """One segment as it will appear in the finished video."""

    duration: float
    label: str = ""
    has_captions: bool = False
    hook_at: float | None = None     # seconds into the clip where action starts


@dataclass
class RetentionReport:
    score: float = 0.0
    verdict: str = "pass"            # pass | warn | reject
    reasons: List[str] = field(default_factory=list)
    wins: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)

    @property
    def rejected(self) -> bool:
        return self.verdict == "reject"

    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 1),
            "verdict": self.verdict,
            "reasons": self.reasons,
            "wins": self.wins,
            "metrics": {k: round(v, 2) for k, v in self.metrics.items()},
        }


def _band(value: float, low: float, high: float) -> float:
    """1.0 inside [low, high], tapering to 0 outside it."""
    if low <= value <= high:
        return 1.0
    if value < low:
        return max(0.0, value / low) if low else 0.0
    overshoot = (value - high) / high
    return max(0.0, 1.0 - overshoot)


def score_plan(clips: Sequence[PlannedClip], fmt: Dict) -> RetentionReport:
    """Score a planned video and decide whether it may be rendered."""
    report = RetentionReport()
    if not clips:
        report.verdict = "reject"
        report.reasons.append("No clips were found for this niche.")
        return report

    total = sum(c.duration for c in clips)
    longest = max(c.duration for c in clips)
    cuts_per_minute = (len(clips) / total * 60.0) if total else 0.0
    captioned = sum(1 for c in clips if c.has_captions) / len(clips)

    report.metrics.update({
        "total_seconds": total,
        "clips": float(len(clips)),
        "longest_clip": longest,
        "cuts_per_minute": cuts_per_minute,
        "captioned_share": captioned,
    })

    points, possible = 0.0, 0.0

    # --- 1. Hook (25) --------------------------------------------------- #
    possible += 25
    hook_limit = float(fmt.get("hook_seconds", 2.0))
    opening = clips[0]
    hook_at = opening.hook_at if opening.hook_at is not None else 0.0
    if hook_at <= hook_limit:
        points += 25
        report.wins.append(f"Opens on the action within {hook_limit:.0f}s.")
    else:
        deficit = min(1.0, (hook_at - hook_limit) / max(hook_limit, 1.0))
        points += 25 * (1.0 - deficit)
        report.reasons.append(
            f"The first clip takes {hook_at:.1f}s to get going; a viewer decides "
            f"inside {hook_limit:.0f}s."
        )

    # --- 2. No dead-air shot (20) --------------------------------------- #
    possible += 20
    shot_limit = float(fmt.get("max_shot_seconds", 30.0))
    if longest <= shot_limit:
        points += 20
        report.wins.append(f"No shot runs longer than {shot_limit:.0f}s.")
    else:
        over = (longest - shot_limit) / shot_limit
        points += 20 * max(0.0, 1.0 - over)
        report.reasons.append(
            f"One clip runs {longest:.0f}s unbroken (limit {shot_limit:.0f}s) -- "
            "that is where viewers drop."
        )

    # --- 3. Pace (20) ---------------------------------------------------- #
    possible += 20
    # Below ~8 cuts/min short-form feels static; above ~30 it is unreadable.
    pace = _band(cuts_per_minute, 8.0, 30.0)
    points += 20 * pace
    if pace >= 0.99:
        report.wins.append(f"Cuts every {60 / cuts_per_minute:.0f}s on average.")
    elif cuts_per_minute < 8.0:
        report.reasons.append(
            f"Only {cuts_per_minute:.1f} cuts a minute; the edit feels static."
        )
    else:
        report.reasons.append(
            f"{cuts_per_minute:.0f} cuts a minute is too frantic to follow."
        )

    # --- 4. A reason to stay (20) ---------------------------------------- #
    possible += 20
    has_promise = bool(fmt.get("checklist_enabled")) or bool(fmt.get("countdown"))
    if has_promise:
        points += 20
        report.wins.append("A countdown or numbered list gives a reason to stay.")
    else:
        # Not fatal: a fast meme cut earns retention through pace instead.
        if cuts_per_minute >= 20:
            points += 14
            report.wins.append("Fast cutting carries it without a countdown.")
        else:
            report.reasons.append(
                "Nothing promises a payoff -- add a countdown or numbered list, "
                "or cut faster."
            )

    # --- 5. Readable muted (10) ------------------------------------------ #
    # Captions are the best on-screen text, but they are not the only kind: a
    # numbered list or a banner also gives a muted viewer something to read,
    # and stock footage has no speech to caption in the first place.
    possible += 10
    other_text = bool(fmt.get("checklist_enabled")) or bool(fmt.get("banner_enabled"))
    if captioned >= 0.5:
        points += 10
        report.wins.append("Captions on most clips, so it works muted.")
    elif other_text and captioned > 0:
        points += 9
        report.wins.append("On-screen text throughout, with captions on some clips.")
    elif other_text:
        points += 7
        report.wins.append("A banner and list carry it for muted viewers.")
    elif fmt.get("captions_enabled"):
        report.reasons.append(
            "No on-screen text: these clips carry no captions and neither a "
            "banner nor a list is switched on."
        )
    else:
        report.reasons.append(
            "Nothing to read: most short-form is watched muted, so turn on "
            "captions, the banner or the numbered list."
        )

    # --- 6. Length (5) ---------------------------------------------------- #
    possible += 5
    target = float(fmt.get("target_seconds", 105))
    points += 5 * _band(total, min(20.0, target * 0.4), max(target * 1.4, 60.0))
    if total < 15:
        report.reasons.append(f"At {total:.0f}s there is not enough to hold anyone.")

    report.score = round(100.0 * points / possible, 1) if possible else 0.0
    if report.score < REJECT_BELOW:
        report.verdict = "reject"
    elif report.score < WARN_BELOW:
        report.verdict = "warn"
    else:
        report.verdict = "pass"
    return report
