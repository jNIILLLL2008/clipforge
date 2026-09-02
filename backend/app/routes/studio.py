"""
studio.py -- The endpoints the Home and Settings screens use.

The shape mirrors the desktop app: one configuration per account, one button
that runs the whole pipeline, and a switch for the daily schedule. Everything
the Home screen shows comes from ``/api/studio``, so the status panel cannot
disagree with what a publish would actually do.
"""

from __future__ import annotations

import secrets
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import youtube
from ..auth import current_user, read_token
from ..config import settings
from ..db import get_db
from ..logging_setup import get_logger
from ..models import Job, JobStatus, Niche, User, utcnow
from ..scheduler import automation_allowed, due
from ..settings_schema import defaults, sanitise, schema
from ..sources import catalogue
from ..worker import enqueue

log = get_logger("studio")
router = APIRouter(prefix="/api")


class SettingsIn(BaseModel):
    settings: Dict = {}


class AutomationIn(BaseModel):
    enabled: bool
    time: str = "09:00"
    timezone: str = ""


class RunIn(BaseModel):
    dry_run: bool = False


def _user_settings(user: User) -> Dict:
    """The account's configuration, always complete and in range."""
    return sanitise(dict(user.settings or {}))


def _readiness(user: User, cfg: Dict) -> List[Dict]:
    """The Home screen's status rows: what would stop a publish right now."""
    rows = [{
        "id": "engine",
        "label": "Video engine",
        "detail": "",
        "state": "ready",
    }]

    wants_upload = bool(cfg.get("auto_upload"))
    if not youtube.configured(user):
        # "off" reads as a feature nobody asked for, and that is right until
        # the account has asked for it. With "Publish after rendering" on, a
        # run that cannot possibly upload is a promise the screen is making
        # and the pipeline cannot keep, so it becomes something to act on.
        rows.append({"id": "youtube", "label": "YouTube account",
                     "detail": "Publishing is not set up yet"
                     + (" — videos will render but go nowhere"
                        if wants_upload else ""),
                     "state": "action" if wants_upload else "off",
                     # Which walkthrough to open: the Google project has to
                     # exist before there is anything to sign in to.
                     "action": "setup-publishing"})
    elif user.youtube_connected:
        rows.append({"id": "youtube", "label": "YouTube account",
                     "detail": user.youtube_channel_title or "Signed in",
                     "state": "ready"})
    else:
        # "Not connected" is true but misleading for somebody who connected
        # last week and whose token has since expired: it reads as though
        # they never finished, and the fix looks like setup rather than one
        # click. Say which of the two it is.
        rows.append({"id": "youtube", "label": "YouTube account",
                     "detail": user.youtube_disconnected_reason
                     or "Not connected",
                     "state": "action", "action": "connect"})

    rows.append({
        "id": "ai",
        "label": "AI metadata",
        "detail": settings.ai_model if settings.anthropic_api_key
        else "Template titles",
        "state": "ready" if settings.anthropic_api_key else "off",
    })

    sources = [s for s in catalogue(user.id)
               if s["name"] in (cfg.get("sources") or [])]
    usable = [s for s in sources if s["enabled"] and s["configured"]]
    rows.append({
        "id": "sources",
        "label": "Footage",
        "detail": ", ".join(s["label"] for s in usable) if usable
        else "No usable source",
        "state": "ready" if usable else "action",
    })
    return rows


@router.get("/studio")
def studio(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Everything the Home screen renders."""
    cfg = _user_settings(user)
    user.refresh_period()

    published = (db.query(Job)
                 .filter(Job.owner_id == user.id, Job.upload_state == "uploaded")
                 .count())
    rendered = (db.query(Job)
                .filter(Job.owner_id == user.id, Job.status == JobStatus.DONE)
                .count())
    running = (db.query(Job)
               .filter(Job.owner_id == user.id,
                       Job.status.in_([JobStatus.QUEUED, JobStatus.SOURCING,
                                       JobStatus.CURATING, JobStatus.RENDERING]))
               .order_by(Job.id.desc())
               .first())

    readiness = _readiness(user, cfg)
    blocking = [r for r in readiness if r["state"] == "action"]

    return {
        "ready": not blocking and running is None,
        "busy": running.to_dict() if running else None,
        "blocked_by": [r["label"] for r in blocking],
        "status": readiness,
        "automation": {
            "enabled": bool(user.automate_daily),
            "time": user.automate_time,
            "timezone": user.automate_timezone,
            "allowed": automation_allowed(user),
            "plan_needed": "starter",
            "last_run": user.automate_last_run.isoformat()
            if user.automate_last_run else None,
            "due_now": due(user) if user.automate_daily else False,
        },
        "overview": {
            "sources": len(cfg.get("sources") or []),
            "source_names": cfg.get("sources") or [],
            "visibility": cfg.get("privacy_status", "private"),
            "auto_upload": bool(cfg.get("auto_upload")),
            "clips_per_run": cfg.get("clips", 5),
            "length": cfg.get("target_seconds", 105),
            "published": published,
            "rendered": rendered,
        },
        "plan": {
            "id": user.plan.value,
            "renders_left": user.renders_left(),
            "renders_total": user.limits["renders_per_month"],
            "watermark": user.limits["watermark"],
        },
        "youtube": {
            "configured": youtube.configured(),
            "connected": user.youtube_connected,
            "channel": user.youtube_channel_title,
        },
        "onboarded": bool(user.onboarded),
    }


@router.post("/studio/onboarded")
def set_onboarded(seen: bool = True, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Remember that the first-run tour has been seen (or replay it)."""
    user.onboarded = bool(seen)
    db.commit()
    return {"onboarded": user.onboarded}


@router.get("/studio/settings")
def get_settings(user: User = Depends(current_user)):
    return {"settings": _user_settings(user), "schema": schema()}


@router.put("/studio/settings")
def put_settings(body: SettingsIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    cfg = sanitise(body.settings, base=user.settings or {})

    # Plan ceilings are enforced here, not just in the UI.
    #
    # And they are reported. Clamping in silence is how somebody sets a
    # two-minute target on the free plan, watches it save, gets a sixty-second
    # video every single time, and has no way to find out why -- the box reads
    # 60 afterwards, so it looks like the setting was never applied rather than
    # capped. Two people spent a while blaming the clip length for this.
    capped = []
    if cfg["clips"] > user.limits["max_clips"]:
        capped.append(
            f"clip count reduced from {cfg['clips']} to "
            f"{user.limits['max_clips']}")
        cfg["clips"] = user.limits["max_clips"]
    if cfg["target_seconds"] > user.limits["max_seconds"]:
        capped.append(
            f"length reduced from {cfg['target_seconds']}s to "
            f"{user.limits['max_seconds']}s")
        cfg["target_seconds"] = user.limits["max_seconds"]

    user.settings = cfg
    db.commit()
    notice = ""
    if capped:
        notice = (f"Your {user.plan.value} plan caps these: "
                  + "; ".join(capped)
                  + ". Upgrade to lift the limit.")
    return {"settings": cfg, "capped": capped, "notice": notice}


class PreviewIn(BaseModel):
    settings: Dict = {}
    at_clip: int = 2


@router.post("/studio/preview")
def preview(body: PreviewIn, user: User = Depends(current_user)):
    """One frame of the layout, rendered the same way the video will be.

    Takes unsaved settings so the preview can update while someone is still
    editing, rather than forcing them to save first.
    """
    from fastapi.responses import Response

    from ..render import preview as preview_render
    from ..sources.upload import VIDEO_SUFFIXES, user_dir

    cfg = sanitise(body.settings, base=user.settings or {})
    cfg["clips"] = min(cfg["clips"], user.limits["max_clips"])

    # Preview against the user's own footage when they have some -- seeing the
    # overlay on a grey card tells you much less than seeing it on your clip.
    sample = None
    if "upload" in (cfg.get("sources") or []):
        directory = user_dir(user.id)
        clips = sorted(
            (p for p in directory.iterdir()
             if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES),
            key=lambda p: -p.stat().st_mtime,
        )
        sample = clips[0] if clips else None

    try:
        image = preview_render.build(
            cfg,
            at_clip=body.at_clip,
            user_upload=sample,
            watermark="clipforge.app" if user.limits["watermark"] else "",
        )
    except Exception as exc:  # noqa: BLE001 - a preview must never 500 the app
        log.warning("Preview failed for user %s: %s", user.id, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Could not build a preview just now.",
        ) from exc

    return Response(content=image, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.post("/studio/review")
def review_settings(body: PreviewIn, user: User = Depends(current_user)):
    """What is wrong with this configuration, before a render is spent on it."""
    from ..render.advice import review
    from ..sources.upload import VIDEO_SUFFIXES, user_dir

    cfg = sanitise(body.settings, base=user.settings or {})
    directory = user_dir(user.id)
    uploads = sum(1 for p in directory.iterdir()
                  if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES)

    available = [s["name"] for s in catalogue(user.id)
                 if s["enabled"] and s["configured"] and s["permitted"]]
    return review(cfg, upload_count=uploads,
                  available_sources=available).to_dict()


@router.get("/presets")
def presets(db: Session = Depends(get_db)):
    """Starting points a user can load over their settings."""
    rows = db.query(Niche).filter(Niche.owner_id.is_(None)).all()
    return {"presets": [
        {"id": n.id, "slug": n.slug, "name": n.name,
         "description": n.description,
         "highlights": {
             "clips": (n.settings or {}).get("clips"),
             "seconds": (n.settings or {}).get("target_seconds"),
             "list": (n.settings or {}).get("checklist_enabled"),
             "show_filter": (n.settings or {}).get("require_show_match"),
         }}
        for n in sorted(rows, key=lambda r: r.name.lower())
    ]}


@router.post("/presets/{preset_id}/apply")
def apply_preset(preset_id: int, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """Copy a preset over the account's settings, keeping upload preferences."""
    preset = db.get(Niche, preset_id)
    if preset is None or preset.owner_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such preset.")

    current = _user_settings(user)
    incoming = dict(preset.settings or {})
    # A preset describes the video, not where it goes. Keep the user's channel
    # choices so applying one never silently makes their uploads public.
    for keep in ("auto_upload", "privacy_status", "category_id",
                 "made_for_kids", "publish_delay_minutes", "title_suffix"):
        incoming[keep] = current.get(keep)

    user.settings = sanitise(incoming)
    db.commit()
    return {"settings": user.settings, "applied": preset.name}


@router.post("/studio/run")
def run(body: RunIn, user: User = Depends(current_user),
        db: Session = Depends(get_db)):
    """The one button: source, cut, check, render and publish."""
    cfg = _user_settings(user)

    if user.renders_left() <= 0:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"You have used all {user.limits['renders_per_month']} runs this "
            "month. Upgrade for more.",
        )

    busy = (db.query(Job)
            .filter(Job.owner_id == user.id,
                    Job.status.in_([JobStatus.QUEUED, JobStatus.SOURCING,
                                    JobStatus.CURATING, JobStatus.RENDERING]))
            .count())
    if busy:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "A run is already in progress.")

    # The same check /studio/review runs, enforced rather than displayed.
    #
    # advice.py was written to stop a run -- "so the guided setup can stop them
    # before they run it" -- but nothing ever called it on this path, so a
    # blocker was only ever text in a side panel. A configuration that cannot
    # work still queued, still spent a render, and still produced something
    # wrong several minutes later: a target of 120s with five clips capped at
    # 12s each renders exactly 60s, and the panel saying so is not much use to
    # somebody who pressed the button on the other screen.
    #
    # Deliberately above the renders_this_period increment below, so being
    # refused here costs nothing.
    from ..render.advice import review as review_cfg
    from ..sources.upload import VIDEO_SUFFIXES as _SUFFIXES, user_dir as _dir

    _uploads = 0
    _directory = _dir(user.id)
    if _directory.exists():
        _uploads = sum(1 for p in _directory.iterdir()
                       if p.is_file() and p.suffix.lower() in _SUFFIXES)
    _available = [s["name"] for s in catalogue(user.id)
                  if s["enabled"] and s["configured"] and s["permitted"]]
    _blockers = review_cfg(cfg, upload_count=_uploads,
                           available_sources=_available).blockers
    if _blockers:
        # Every one of them, with the fix. One at a time would mean pressing
        # the button once per problem to discover the next.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            " ".join(f"{b.title}: {b.detail}"
                     + (f" {b.fix}" if b.fix else "")
                     for b in _blockers),
        )

    job = Job(
        owner_id=user.id,
        title="",
        options={"format": {}},
        status=JobStatus.QUEUED,
        stage_detail="Waiting for a worker",
        dry_run=bool(body.dry_run),
    )
    db.add(job)
    user.refresh_period()
    user.renders_this_period += 1
    db.commit()
    db.refresh(job)

    enqueue(job.id)
    log.info("Run queued for user %s (job %s, dry_run=%s).",
             user.id, job.public_id, body.dry_run)
    return job.to_dict()


@router.put("/studio/automation")
def set_automation(body: AutomationIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    if body.enabled and not automation_allowed(user):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            "Daily automation is included with Starter and Pro.",
        )
    try:
        hour, minute = (int(p) for p in body.time.split(":"))
        assert 0 <= hour < 24 and 0 <= minute < 60
    except (ValueError, AssertionError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Time must be HH:MM in 24-hour form.")

    user.automate_daily = bool(body.enabled)
    user.automate_time = f"{hour:02d}:{minute:02d}"
    user.automate_timezone = body.timezone.strip()[:64]
    db.commit()
    return {"enabled": user.automate_daily, "time": user.automate_time,
            "timezone": user.automate_timezone}


# --------------------------------------------------------------------------- #
# YouTube connection
# --------------------------------------------------------------------------- #
@router.get("/youtube/connect")
def youtube_connect(user: User = Depends(current_user)):
    if not youtube.configured(user):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No Google project is set up for publishing yet. Follow the "
            "publishing setup to create one — it takes a few minutes and only "
            "has to be done once.")
    # The state carries the account so the callback knows who came back, and a
    # nonce so a stray callback cannot be replayed.
    state = f"{user.id}:{secrets.token_urlsafe(16)}"
    _PENDING[state] = user.id
    return {"url": youtube.consent_url(state, user)}


# Short-lived map of outstanding consent requests.
_PENDING: Dict[str, int] = {}


@router.get("/youtube/callback")
def youtube_callback(request: Request, db: Session = Depends(get_db)):
    """Where Google sends the user back after they approve."""
    params = request.query_params
    error = params.get("error")
    if error:
        return _closing_page(f"YouTube connection cancelled ({error}).")

    code, state = params.get("code"), params.get("state", "")
    user_id = _PENDING.pop(state, None)
    if not code or user_id is None:
        return _closing_page("That connection link has expired. Try again.")

    user = db.get(User, user_id)
    if user is None:
        return _closing_page("Account not found.")

    try:
        # The user, not the server: the code was issued by their own OAuth
        # client and only that client can exchange it.
        refresh_token, title, channel_id = youtube.exchange_code(code, user)
    except Exception as exc:  # noqa: BLE001
        log.warning("YouTube exchange failed for user %s: %s", user_id, exc)
        return _closing_page(f"Could not connect: {exc}")

    user.youtube_refresh_token = refresh_token
    user.youtube_channel_title = (title or "")[:160]
    user.youtube_channel_id = (channel_id or "")[:64]
    user.youtube_connected_at = utcnow()
    # Whatever went wrong before has just been fixed by this.
    user.youtube_disconnected_reason = ""
    db.commit()
    log.info("User %s connected channel %r.", user_id, title)
    return _closing_page(f"Connected to {title or 'your channel'}.", ok=True)


class GoogleAppIn(BaseModel):
    client_id: str = ""
    client_secret: str = ""


@router.get("/youtube/app")
def google_app(user: User = Depends(current_user)):
    """What is stored, never the secret itself.

    The client id is shown because somebody has to be able to check they
    pasted the right one; the secret is only ever reported as present or
    absent. There is no reason for this API to hand a credential back, and
    every reason not to.
    """
    return {
        "client_id": user.google_client_id or "",
        "has_secret": bool(user.google_client_secret),
        "redirect_uri": settings.google_redirect_uri,
        "scopes": list(youtube.SCOPES),
        "configured": youtube.configured(user),
        "connected": bool(user.youtube_refresh_token),
        "channel_title": user.youtube_channel_title or "",
    }


@router.put("/youtube/app")
def save_google_app(body: GoogleAppIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Store the subscriber's own OAuth client."""
    client_id = body.client_id.strip()
    client_secret = body.client_secret.strip()

    if client_id and not client_id.endswith(".apps.googleusercontent.com"):
        # Every Google web client id ends this way. Saying so here beats a
        # failed consent redirect with an error page from Google that does
        # not mention which field was wrong.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That does not look like a Google client ID — they end in "
            "'.apps.googleusercontent.com'. Copy it from the OAuth client "
            "you created, not the API key or the project number.")

    user.google_client_id = client_id[:255]
    # An empty secret leaves the stored one alone, so re-saving the form
    # without retyping it does not silently wipe it.
    if client_secret:
        user.google_client_secret = client_secret
    if not client_id:
        user.google_client_secret = ""

    # The channel was authorised by the old client and its refresh token
    # cannot be renewed by a new one -- Google answers invalid_client. Better
    # to ask for one more click now than to fail on the next upload.
    if user.youtube_refresh_token:
        user.youtube_refresh_token = None
        user.youtube_channel_title = ""
        user.youtube_channel_id = ""
        user.youtube_connected_at = None
        user.youtube_disconnected_reason = (
            "New credentials were saved, so the channel needs connecting "
            "again — a sign-in belongs to the client that issued it.")

    db.commit()
    return {"configured": youtube.configured(user),
            "client_id": user.google_client_id,
            "has_secret": bool(user.google_client_secret),
            "reconnect_needed": True}


@router.post("/youtube/disconnect")
def youtube_disconnect(user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    user.youtube_refresh_token = None
    user.youtube_channel_title = ""
    user.youtube_channel_id = ""
    user.youtube_connected_at = None
    # Chosen, not lost. Leaving an expiry notice up after somebody
    # deliberately disconnected would explain a thing that did not happen.
    user.youtube_disconnected_reason = ""
    db.commit()
    return {"connected": False}


def _closing_page(message: str, ok: bool = False) -> HTMLResponse:
    """A tiny page that tells the opener and closes itself."""
    colour = "#17803d" if ok else "#c0392b"
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8">
<title>ClipForge</title>
<body style="font:15px system-ui;background:#0e1014;color:#e8eaee;
display:grid;place-items:center;height:100vh;margin:0;text-align:center">
<div><p style="color:{colour};font-weight:600">{message}</p>
<p style="opacity:.7">You can close this window.</p></div>
<script>
  try {{ window.opener && window.opener.postMessage('clipforge-youtube', '*'); }} catch (e) {{}}
  setTimeout(function () {{ window.close(); }}, 1200);
</script></body>""")
