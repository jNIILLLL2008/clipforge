"""
niches.py -- What a user is making, and how it should be cut.

A niche now carries the *complete* settings set from ``settings_schema`` --
subject, show filter, clip filters, cut, retention, banner, list, captions,
badge, video and copyright guard. Users fork a built-in and can change any of
it, which is what makes a niche like "one specific TV panel show" possible for
somebody who is not the person who wrote the code.

The built-ins differ mainly by *shape* -- pacing, clip count, whether a
numbered list is shown -- because shape is what decides retention. Topic is
just search terms.

The exception is "One TV Show", which differs in *where it looks*. Searching
for short videos about a programme returns other people's edits, other
series and people talking to camera about it, and no amount of filtering
fixes a pool that is mostly the wrong thing. Pointing it at a playlist of
full episodes and cutting the moments out of those does.
"""

from __future__ import annotations

from typing import Dict, List

from sqlalchemy.orm import Session

from .models import Niche
from .settings_schema import defaults, sanitise


def _settings(**overrides) -> Dict:
    """A full settings block with a few fields changed."""
    return sanitise(overrides)


BUILTIN_NICHES: List[Dict] = [
    {
        "slug": "top5",
        "name": "Top 5 Countdown",
        "description": "A ranked countdown that holds the best clip until last. "
                       "The numbered list is what keeps people watching.",
        "settings": _settings(
            banner_line1="TOP {count}", checklist_enabled=True, countdown=True,
            # Two minutes, and a longest-segment with room above the 24s
            # share so one short source cannot drag the whole video under.
            clips=5, target_seconds=120, max_clip_seconds=32,
            sources=["upload"],
        ),
    },
    {
        "slug": "funny",
        "name": "Funny Moments",
        "description": "Loose comedy cuts. No ranking, so the hook has to do the "
                       "work: the funniest beat goes first, not last.",
        "settings": _settings(
            banner_line1="FUNNY MOMENTS", checklist_enabled=False,
            countdown=False, clips=6, target_seconds=90, max_clip_seconds=18,
            hook_seconds=1.5, search_terms=["funny", "fail", "bloopers"],
            exclude_terms=["tutorial", "review"],
            sources=["upload"],
        ),
    },
    {
        "slug": "memes",
        "name": "Meme Cuts",
        "description": "Very fast cuts with big captions. Built for rewatching, "
                       "so it stays short and never lingers on one shot.",
        "settings": _settings(
            banner_enabled=False, checklist_enabled=False, countdown=False,
            clips=8, target_seconds=45, min_clip_seconds=3, max_clip_seconds=7,
            caption_uppercase=True, hook_seconds=1.0, max_shot_seconds=7.0,
            search_terms=["meme", "reaction"], sources=["upload"],
        ),
    },
    {
        "slug": "satisfying",
        "name": "Oddly Satisfying",
        "description": "Calm, loopable visuals. Retention comes from flow, so "
                       "clips run longer and captions stay out of the way.",
        "settings": _settings(
            banner_enabled=False, checklist_enabled=False,
            captions_enabled=False, countdown=False, clips=6,
            target_seconds=100, min_clip_seconds=10, max_clip_seconds=20,
            background="crop", max_shot_seconds=22.0,
            search_terms=["satisfying", "slow motion", "kinetic"],
            exclude_terms=["talking", "interview"],
            sources=["upload"],
        ),
    },
    {
        "slug": "facts",
        "name": "Did You Know",
        "description": "One fact per clip with an on-screen list. The text carries "
                       "it, so the footage under it can be simple.",
        "settings": _settings(
            banner_line1="{count} FACTS", checklist_enabled=True, countdown=True,
            clips=5, target_seconds=95, caption_uppercase=True,
            search_terms=["nature", "space", "city", "ocean"],
            sources=["upload"],
        ),
    },
    {
        "slug": "howto",
        "name": "Quick How-To",
        "description": "Numbered steps. The list doubles as a progress bar, which "
                       "is why people stay to the final step.",
        "settings": _settings(
            banner_line1="{count} STEPS", checklist_enabled=True,
            countdown=False, clips=5, target_seconds=110, max_clip_seconds=24,
            sources=["upload"],
        ),
    },
    {
        "slug": "show",
        "name": "One TV Show",
        "description": "Built for a single programme rather than a topic. "
                       "Paste a playlist of full episodes and it cuts the "
                       "moments out of them, which is the only way to be sure "
                       "every clip is really from your show.",
        "settings": _settings(
            banner_line1="TOP {count} FROM", banner_line2="YOUR SHOW",
            checklist_enabled=True, countdown=True, clips=5,
            target_seconds=120, max_clip_seconds=32, require_show_match=True,
            background="pad", checklist_y=1303, caption_margin_v=700,
            # Anything past a minute or so is an episode to be searched
            # rather than a clip to be used whole. See render/moments.py.
            long_clip_seconds=75, moments_per_video=2,
            moment_min_gap_seconds=120, skip_intro_seconds=45,
            skip_outro_seconds=45,
            # A curated playlist is exempt from both of these, but they still
            # apply to anything a channel scan turns up alongside it.
            max_duration_seconds=1800, min_view_count=0,
            # This preset only makes sense with broadcast footage, so it names
            # the YouTube source. The registry still refuses it unless the
            # operator has enabled unlicensed sources, in which case only
            # uploads are used.
            sources=["youtube", "upload"],
            channel_tabs=["videos"],
        ),
    },
]


def starter_settings() -> Dict:
    """The configuration a brand-new account begins with.

    The Top 5 preset, because it is the format the on-screen furniture was
    designed around, with uploads defaulting to private so nobody's first run
    goes public before they have watched it.
    """
    top5 = next(n for n in BUILTIN_NICHES if n["slug"] == "top5")
    return sanitise({**top5["settings"], "privacy_status": "private",
                     "auto_upload": True})


def seed_builtin_niches(db: Session) -> int:
    """Insert or refresh the shared built-in niches."""
    changed = 0
    for spec in BUILTIN_NICHES:
        existing = (
            db.query(Niche)
            .filter(Niche.owner_id.is_(None), Niche.slug == spec["slug"])
            .one_or_none()
        )
        if existing is None:
            db.add(Niche(owner_id=None, is_builtin=True, slug=spec["slug"],
                         name=spec["name"], description=spec["description"],
                         settings=spec["settings"]))
            changed += 1
            continue
        # Keep built-ins in step with the code without touching user copies.
        if existing.name != spec["name"]:
            existing.name = spec["name"]
            changed += 1
        if existing.description != spec["description"]:
            existing.description = spec["description"]
            changed += 1
        if existing.settings != spec["settings"]:
            existing.settings = spec["settings"]
            changed += 1
    return changed


def fork_for_user(db: Session, source: Niche, owner_id: int,
                  name: str = "", slug: str = "") -> Niche:
    """Copy a niche into a user's account so they can edit every setting."""
    base_slug = slug or f"{source.slug}-copy"
    candidate, suffix = base_slug, 2
    while (db.query(Niche)
             .filter(Niche.owner_id == owner_id, Niche.slug == candidate)
             .count()):
        candidate = f"{base_slug}-{suffix}"
        suffix += 1

    clone = Niche(
        owner_id=owner_id,
        slug=candidate,
        name=name or f"{source.name} (mine)",
        description=source.description,
        settings=sanitise(dict(source.settings or {})),
        is_builtin=False,
    )
    db.add(clone)
    db.flush()
    return clone


def blank_for_user(db: Session, owner_id: int, name: str) -> Niche:
    """A niche starting from defaults rather than a built-in."""
    base_slug = "".join(c.lower() if c.isalnum() else "-" for c in name)[:40]
    base_slug = base_slug.strip("-") or "niche"
    candidate, suffix = base_slug, 2
    while (db.query(Niche)
             .filter(Niche.owner_id == owner_id, Niche.slug == candidate)
             .count()):
        candidate = f"{base_slug}-{suffix}"
        suffix += 1

    niche = Niche(owner_id=owner_id, slug=candidate, name=name,
                  description="", settings=defaults(), is_builtin=False)
    db.add(niche)
    db.flush()
    return niche


def visible_to(db: Session, user_id: int) -> List[Niche]:
    """Built-ins plus this user's own, built-ins first."""
    rows = (
        db.query(Niche)
        .filter((Niche.owner_id.is_(None)) | (Niche.owner_id == user_id))
        .all()
    )
    return sorted(rows, key=lambda n: (not n.is_builtin, n.name.lower()))
