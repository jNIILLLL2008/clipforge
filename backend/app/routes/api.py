"""
api.py -- Every HTTP endpoint the frontend calls.

Grouped in one module because the surface is small and the flow reads better in
order: sign in, pick a niche, upload footage, queue a job, poll it, download.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, File, HTTPException, Response, UploadFile, status,
)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import sources as source_registry
from ..auth import create_token, current_user, register, verify_password
from ..config import settings
from ..db import get_db
from ..logging_setup import get_logger
from ..models import (
    PLAN_LIMITS, AgentPairing, Job, JobStatus, Niche, User, utcnow,
)
from ..sources.upload import VIDEO_SUFFIXES, user_dir
from ..worker import enqueue

log = get_logger("api")
router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class Credentials(BaseModel):
    email: str
    password: str


class JobIn(BaseModel):
    """Kept for the API, though the app uses /api/studio/run."""

    title: str = ""
    clips: Optional[int] = None
    search_terms: List[str] = []
    format: dict = {}


def _user_payload(user: User) -> dict:
    user.refresh_period()
    limits = dict(user.limits)
    return {
        "email": user.email,
        "plan": user.plan.value,
        "limits": limits,
        "renders_left": user.renders_left(),
        "renders_used": user.renders_this_period,
        "billing_enabled": settings.billing_enabled,
    }


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@router.post("/auth/signup")
def signup(body: Credentials, response: Response, db: Session = Depends(get_db)):
    user, error = register(db, body.email, body.password)
    if error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, error)
    db.commit()
    token = create_token(user.id)
    response.set_cookie("cf_token", token, httponly=True, samesite="lax",
                        secure=settings.secure_cookies,
                        max_age=settings.token_hours * 3600)
    return {"token": token, "user": _user_payload(user)}


@router.post("/auth/login")
def login(body: Credentials, response: Response, db: Session = Depends(get_db)):
    email = (body.email or "").strip().lower()
    user = db.query(User).filter(User.email == email).one_or_none()
    if not user or not verify_password(body.password or "", user.password_hash):
        # Same message either way, so the endpoint cannot be used to enumerate.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Email or password is incorrect.")
    token = create_token(user.id)
    response.set_cookie("cf_token", token, httponly=True, samesite="lax",
                        secure=settings.secure_cookies,
                        max_age=settings.token_hours * 3600)
    return {"token": token, "user": _user_payload(user)}


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie("cf_token")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _user_payload(user)


@router.get("/plans")
def plans():
    """The plan table, plus whether anyone can actually subscribe right now."""
    labels = {"starter": settings.price_label_starter,
              "pro": settings.price_label_pro}

    rows = []
    for plan, limits in PLAN_LIMITS.items():
        row = {"id": plan.value, **limits}
        row["price"] = labels.get(plan.value, limits["price"])
        # A plan can only be bought if Stripe is configured AND that specific
        # price exists, so the button never leads to a dead checkout.
        price_id = {"starter": settings.stripe_price_starter,
                    "pro": settings.stripe_price_pro}.get(plan.value)
        row["purchasable"] = bool(settings.billing_enabled and price_id)
        rows.append(row)

    return {
        "plans": rows,
        "billing_enabled": settings.billing_enabled,
        "billing_note": "" if settings.billing_enabled else
        "Payments are not switched on for this deployment yet. Add your Stripe "
        "keys to accept subscriptions.",
    }


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Sources and uploads
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Render agent
# --------------------------------------------------------------------------- #
@router.get("/agent/status")
def agent_status(user: User = Depends(current_user)) -> dict:
    """Whether an agent is paired, without revealing the token again."""
    return {
        "paired": bool(user.agent_token),
        "last_seen": user.agent_last_seen.isoformat() if user.agent_last_seen else "",
        "local_rendering": settings.render_workers <= 0,
        "download_url": settings.agent_download_url,
    }


@router.post("/agent/token")
def agent_token(user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> dict:
    """Mint a new agent token, invalidating any previous one.

    Returned in full exactly once. It is stored as-is so an agent can present
    it, so treat it the way you would an API key.
    """
    from .agent import new_agent_token

    user.agent_token = new_agent_token()
    user.agent_last_seen = None
    db.commit()
    log.info("Issued a render agent token for %s.", user.email)
    return {"token": user.agent_token, "server": settings.public_url}


@router.delete("/agent/token")
def revoke_agent_token(user: User = Depends(current_user),
                       db: Session = Depends(get_db)) -> dict:
    """Unpair the agent. Any copy of the old token stops working at once."""
    user.agent_token = None
    user.agent_last_seen = None
    db.commit()
    return {"paired": False}


@router.get("/sources")
def list_sources(user: User = Depends(current_user)):
    return {"sources": source_registry.catalogue(user.id)}


@router.get("/uploads")
def list_uploads(user: User = Depends(current_user)):
    directory = user_dir(user.id)
    files = [
        {"name": p.name, "size": p.stat().st_size,
         "modified": p.stat().st_mtime}
        for p in sorted(directory.iterdir(), key=lambda p: -p.stat().st_mtime)
        if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES
    ]
    return {"uploads": files}


@router.post("/uploads")
async def upload(file: UploadFile = File(...), user: User = Depends(current_user)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported file type {suffix or '?'}. Use "
            + ", ".join(sorted(VIDEO_SUFFIXES)),
        )

    safe = "".join(c for c in Path(file.filename).stem if c.isalnum() or c in " -_")[:60]
    target = user_dir(user.id) / f"{safe or 'clip'}{suffix}"
    counter = 2
    while target.exists():
        target = user_dir(user.id) / f"{safe or 'clip'}-{counter}{suffix}"
        counter += 1

    limit = settings.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(1 << 20):
                written += len(chunk)
                if written > limit:
                    handle.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        f"File is larger than {settings.max_upload_mb} MB.",
                    )
                handle.write(chunk)
    finally:
        await file.close()

    return {"name": target.name, "size": written}


@router.delete("/uploads/{name}")
def delete_upload(name: str, user: User = Depends(current_user)):
    target = user_dir(user.id) / Path(name).name
    if not target.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such upload.")
    target.unlink()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Your data
# --------------------------------------------------------------------------- #
# A privacy policy that promises access and erasure without shipping either is
# a worse position than having no policy, because the promise is now written
# down. These two endpoints are what make section 6 of /privacy true.
class DeleteAccount(BaseModel):
    """Deleting an account asks for the password again.

    A signed-in session is enough to change most things, but not to destroy
    everything irreversibly: a borrowed laptop should not be able to do it, and
    neither should a link somebody was tricked into clicking.
    """

    password: str
    # Typed out in full, so the request cannot be made by accident and cannot
    # be forged by a form post that guessed the shape of the body.
    confirm: str = ""


@router.get("/me/export")
def export_my_data(user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Everything held about this account, as JSON.

    Covers the right of access and the right to portability in one file:
    machine-readable, and complete enough to be worth having.

    Two things are deliberately absent. The password hash, because handing back
    a hash helps nobody and helps an attacker who has the file. And the YouTube
    refresh token, because it is a live credential -- exporting it would turn a
    download into a way to walk off with the ability to post to somebody's
    channel. Both are described rather than dumped.
    """
    jobs = (db.query(Job).filter(Job.owner_id == user.id)
            .order_by(Job.id.asc()).all())

    uploads = []
    directory = user_dir(user.id)
    if directory.exists():
        uploads = [
            {"name": path.name, "size_bytes": path.stat().st_size,
             "modified": path.stat().st_mtime}
            for path in sorted(directory.iterdir())
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
        ]

    niches = (db.query(Niche).filter(Niche.owner_id == user.id)
              .order_by(Niche.id.asc()).all())

    payload = {
        "exported_at": utcnow().isoformat(),
        "account": {
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "plan": user.plan.value,
            "plan_renews_at": (user.plan_renews_at.isoformat()
                               if user.plan_renews_at else None),
            "renders_this_period": user.renders_this_period,
            "period_started_at": (user.period_started_at.isoformat()
                                  if user.period_started_at else None),
            "onboarded": user.onboarded,
            "is_active": user.is_active,
            "password": "Stored only as a salted PBKDF2-HMAC-SHA256 hash, "
                        "which is not included here and cannot be reversed.",
        },
        "settings": user.settings or {},
        "billing": {
            "stripe_customer_id": user.stripe_customer_id,
            "stripe_subscription_id": user.stripe_subscription_id,
            "note": "Card details are held by Stripe and never reach "
                    "ClipForge. Ask Stripe for those directly.",
        },
        "youtube": {
            "connected": bool(user.youtube_refresh_token),
            "disconnected_reason": user.youtube_disconnected_reason or "",
            "channel_title": user.youtube_channel_title,
            "channel_id": user.youtube_channel_id,
            "connected_at": (user.youtube_connected_at.isoformat()
                             if user.youtube_connected_at else None),
            "refresh_token": "Held, but withheld from this export: it is a "
                             "live credential for your channel. Disconnecting "
                             "in Settings deletes it.",
        },
        "automation": {
            "daily": user.automate_daily,
            "time": user.automate_time,
            "timezone": user.automate_timezone,
            "last_run": (user.automate_last_run.isoformat()
                         if user.automate_last_run else None),
        },
        "render_agent": {
            "paired": bool(user.agent_token),
            "last_seen": (user.agent_last_seen.isoformat()
                          if user.agent_last_seen else None),
        },
        "niches": [niche.to_dict() for niche in niches],
        "jobs": [job.to_dict(include_clips=True) for job in jobs],
        "uploads": uploads,
    }

    stamp = utcnow().strftime("%Y-%m-%d")
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition":
                f'attachment; filename="clipforge-my-data-{stamp}.json"',
        },
    )


@router.post("/me/delete")
def delete_my_account(body: DeleteAccount,
                      response: Response,
                      user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Erasure. Irreversible, and it happens now rather than in 30 days.

    Order matters here. Files go first, because a row deleted before its files
    are removed leaves footage on disk that nothing points at any more -- an
    orphan nobody will ever find to delete. The database rows go last, in one
    transaction, so a failure halfway leaves the account intact rather than
    half-erased.
    """
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "That password is not right.")
    if body.confirm.strip().upper() != "DELETE":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            'Type DELETE to confirm.')

    user_id = user.id
    email = user.email

    # 1. Rendered videos and thumbnails.
    jobs = db.query(Job).filter(Job.owner_id == user_id).all()
    for job in jobs:
        for candidate in (job.output_path, job.thumbnail_path):
            if candidate:
                try:
                    Path(candidate).unlink(missing_ok=True)
                except OSError as exc:  # noqa: PERF203
                    log.warning("Could not remove %s: %s", candidate, exc)

    # 2. Uploaded footage, the whole per-user directory.
    directory = user_dir(user_id)
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)

    # 3. The rows. Clips cascade from their job; pairings are cleared by hand
    #    because they carry a nullable owner and would otherwise be left
    #    pointing at a user that no longer exists.
    for job in jobs:
        db.delete(job)
    db.query(Niche).filter(Niche.owner_id == user_id).delete(
        synchronize_session=False)
    db.query(AgentPairing).filter(AgentPairing.user_id == user_id).delete(
        synchronize_session=False)
    db.delete(user)
    db.commit()

    # The session cookie is now a token for an account that is gone. Clearing
    # it means the browser is not left holding a credential to nothing.
    response.delete_cookie("cf_token")
    log.info("Deleted account %s (id=%s) at the owner's request.", email, user_id)
    return {"ok": True, "deleted": True}


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
@router.post("/jobs")
def create_job(body: JobIn, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    """Queue a run with one-off overrides.

    The app's Publish button uses ``/api/studio/run``; this exists for API
    callers who want to vary a setting for a single run without saving it.
    """
    if user.renders_left() <= 0:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"You have used all {user.limits['renders_per_month']} renders this "
            "month. Upgrade for more.",
        )

    fmt = dict(body.format or {})
    if body.clips:
        fmt["clips"] = min(int(body.clips), user.limits["max_clips"])
    if body.search_terms:
        fmt["search_terms"] = body.search_terms
    if fmt.get("target_seconds"):
        fmt["target_seconds"] = min(int(fmt["target_seconds"]),
                                    user.limits["max_seconds"])

    job = Job(
        owner_id=user.id,
        title=body.title[:255],
        options={"format": fmt, "title": body.title},
        status=JobStatus.QUEUED,
        stage_detail="Waiting for a worker",
    )
    db.add(job)

    # Reserve the render now, not when it finishes. Counting on completion
    # would let someone queue their whole month at once and outrun the check.
    # The worker refunds this if the job fails or is rejected on retention.
    user.refresh_period()
    user.renders_this_period += 1

    db.commit()
    db.refresh(job)

    enqueue(job.id)
    log.info("Queued job %s for user %s.", job.public_id, user.id)
    return job.to_dict()


@router.get("/jobs")
def list_jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(Job).filter(Job.owner_id == user.id)
            .order_by(Job.id.desc()).limit(50).all())
    return {"jobs": [job.to_dict() for job in rows]}


@router.get("/jobs/{public_id}")
def get_job(public_id: str, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    job = (db.query(Job)
           .filter(Job.public_id == public_id, Job.owner_id == user.id)
           .one_or_none())
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return job.to_dict(include_clips=True)


@router.get("/jobs/{public_id}/download")
def download(public_id: str, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    job = (db.query(Job)
           .filter(Job.public_id == public_id, Job.owner_id == user.id)
           .one_or_none())
    if job is None or job.status != JobStatus.DONE or not job.output_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No finished video here.")
    path = Path(job.output_path)
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "The file has been cleaned up.")
    name = (job.title or "clipforge").replace(" ", "_")[:60]
    return FileResponse(path, media_type="video/mp4", filename=f"{name}.mp4")


@router.delete("/jobs/{public_id}")
def delete_job(public_id: str, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    job = (db.query(Job)
           .filter(Job.public_id == public_id, Job.owner_id == user.id)
           .one_or_none())
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    for candidate in (job.output_path, job.thumbnail_path):
        if candidate:
            Path(candidate).unlink(missing_ok=True)
    db.delete(job)
    db.commit()
    return {"ok": True}
