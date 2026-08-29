"""
agent.py -- The render agent protocol.

A render agent is the same pipeline, running on the subscriber's own machine
instead of this server. It exists because of where the two are: YouTube serves
datacentre IPs a bot interstitial, so a cloud instance is refused for requests
that a home connection answers fine. Moving the work to the person's own
machine removes that problem instead of paying a residential proxy to disguise
it, and takes the ffmpeg encode off the server's bill at the same time.

What stays here is everything that decides *whether* a job may run: accounts,
plan limits, the monthly allowance, the retention verdict, metadata and the
YouTube upload. The agent is handed one job at a time and hands back a file. It
cannot mint work for itself, so it is useless without a live subscription.

The finished video is uploaded back rather than published by the agent. It is a
few MB, once, against the tens of GB of source footage the agent no longer
makes this server pull, and it keeps the channel's refresh token on the server
where it belongs.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Request, Response,
    UploadFile, status,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import settings
from ..db import get_db, session_scope
from ..logging_setup import get_logger
from ..models import (
    AgentPairing, Job, JobClip, JobStatus, User, utcnow,
)

log = get_logger("agent")
router = APIRouter(prefix="/api/agent")

#: What this server's render pipeline expects an agent to be built from. An
#: agent reports its own; anything lower is rendering with code we have since
#: fixed, and it is told so on every hello.
#:
#: Bump it together with agent/__init__.py PIPELINE_VERSION.
PIPELINE_VERSION = 2

#: Stages an agent may report, mapped to the status the job takes. Anything
#: else is ignored rather than trusted: the agent does not get to declare a job
#: finished by naming a status.
_STAGES = {
    "sourcing": JobStatus.SOURCING,
    "curating": JobStatus.CURATING,
    "rendering": JobStatus.RENDERING,
}


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
def agent_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the agent token on the request to its owner."""
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Send the agent token as a bearer token.")
    user = db.query(User).filter(User.agent_token == token).first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "That agent token is not valid. Generate a new one "
                            "in Settings.")
    user.agent_last_seen = utcnow()
    return user


def new_agent_token() -> str:
    return secrets.token_urlsafe(36)


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class Progress(BaseModel):
    stage: str = ""
    detail: str = ""


class Failure(BaseModel):
    error: str = ""
    rejected: bool = False


# --------------------------------------------------------------------------- #
# Pairing
#
# The old flow showed the token on a web page and asked the subscriber to paste
# it into a file called agent.env. That is a developer's install, and these are
# not developers: it asked them to find a folder, create a file with no
# extension, paste a 48-character secret without mangling it, and then open a
# terminal. Every one of those is a place to give up.
#
# So the agent asks instead. It starts a pairing, opens the browser at a page
# carrying the code, and polls. The person clicks one button on a site they are
# already signed in to. The token goes from the server into the agent's own
# config file and is never displayed, never copied and never typed.
#
# This is the device-authorisation shape a television uses, and it has the same
# weak point: nothing stops someone sending a victim a link to *their* code and
# borrowing the approval. The defences are that the approval page names the
# machine asking, says plainly what to do if you did not start it, and expires
# in fifteen minutes -- and that approving grants rendering for your own
# account, not access to it.
# --------------------------------------------------------------------------- #
class PairStart(BaseModel):
    label: str = ""


class PairPoll(BaseModel):
    device_secret: str = ""


class PairApprove(BaseModel):
    code: str = ""


def _sweep(db: Session) -> None:
    """Drop pairings nobody finished. Cheap, and keeps codes reusable."""
    db.query(AgentPairing).filter(AgentPairing.expires_at <= utcnow()).delete(
        synchronize_session=False)


def _find(db: Session, code: str) -> Optional[AgentPairing]:
    """Look up a code the way a person would type it: loosely."""
    cleaned = (code or "").strip().upper().replace(" ", "")
    if len(cleaned) == 8 and "-" not in cleaned:
        cleaned = f"{cleaned[:4]}-{cleaned[4:]}"
    if not cleaned:
        return None
    return db.query(AgentPairing).filter(AgentPairing.code == cleaned).first()


@router.post("/pair/start")
def pair_start(body: PairStart, db: Session = Depends(get_db)) -> dict:
    """Begin pairing. Unauthenticated: the agent has no credentials yet.

    Handing out a code costs nothing and grants nothing. Only the approval
    step, which needs a signed-in session, attaches it to an account.
    """
    _sweep(db)

    # A collision is a lost pairing rather than a security problem, but it is
    # trivial to avoid, so avoid it.
    for _ in range(6):
        code = AgentPairing.new_code()
        if not db.query(AgentPairing.id).filter(
                AgentPairing.code == code).first():
            break
    else:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Could not allocate a pairing code. Try again.")

    pairing = AgentPairing(
        code=code,
        device_secret=secrets.token_urlsafe(36),
        label=(body.label or "")[:120],
        expires_at=utcnow() + AgentPairing.LIFETIME,
    )
    db.add(pairing)
    db.commit()

    log.info("Pairing %s started for %r.", pairing.code, pairing.label)
    return {
        "code": pairing.code,
        "device_secret": pairing.device_secret,
        # Built from PUBLIC_URL because the agent has no browser context to
        # borrow an origin from, unlike the settings page.
        "verify_url": f"{settings.public_url.rstrip('/')}/pair?code={pairing.code}",
        "interval": 3,
        "expires_in": int(AgentPairing.LIFETIME.total_seconds()),
    }


@router.post("/pair/poll")
def pair_poll(body: PairPoll, db: Session = Depends(get_db)) -> dict:
    """Has anyone approved us yet? Answered only to the agent that asked.

    The token is handed over exactly once and then wiped from the row, so a
    database dump taken later holds nothing usable.
    """
    secret = (body.device_secret or "").strip()
    pairing = (db.query(AgentPairing)
                 .filter(AgentPairing.device_secret == secret).first()
               if secret else None)
    if pairing is None:
        # Deleted by the sweep, or never existed. Same answer either way: the
        # agent should start over rather than poll forever.
        return {"status": "expired"}
    if pairing.expired:
        return {"status": "expired"}
    if pairing.approved_at is None:
        return {"status": "pending"}

    token = pairing.token
    if not token:
        # Approved, and already collected. Somebody is polling with a copy.
        return {"status": "expired"}

    pairing.token = None
    pairing.delivered_at = utcnow()
    db.commit()

    log.info("Pairing %s collected by the agent.", pairing.code)
    return {
        "status": "approved",
        "token": token,
        "server": settings.public_url,
        "email": pairing.user.email if pairing.user else "",
    }


@router.get("/pair/lookup")
def pair_lookup(code: str = "", user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> dict:
    """What the approval page shows before anyone clicks anything."""
    pairing = _find(db, code)
    if pairing is None or pairing.expired:
        return {"found": False}
    return {
        "found": True,
        "code": pairing.code,
        "label": pairing.label,
        "approved": pairing.approved_at is not None,
        "already_paired": bool(user.agent_token),
    }


@router.post("/pair/approve")
def pair_approve(body: PairApprove, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict:
    """Attach a waiting pairing to this account and mint its token.

    Approving replaces any existing agent token, exactly as "Replace token"
    does, because one account renders on one machine at a time and the
    alternative is two agents fighting over the same queue.
    """
    pairing = _find(db, body.code)
    if pairing is None or pairing.expired:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "That pairing code has expired. Start the agent "
                            "again to get a new one.")
    if pairing.approved_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "That code has already been used.")

    user.agent_token = new_agent_token()
    user.agent_last_seen = None

    pairing.user_id = user.id
    pairing.approved_at = utcnow()
    pairing.token = user.agent_token
    db.commit()

    log.info("Pairing %s approved by %s for %r.",
             pairing.code, user.email, pairing.label)
    return {"ok": True, "label": pairing.label}


# --------------------------------------------------------------------------- #
# Claiming work
# --------------------------------------------------------------------------- #
@router.get("/hello")
def hello(request: Request, user: User = Depends(agent_user),
          db: Session = Depends(get_db)) -> dict:
    """Confirm a token works, before an agent starts polling with it.

    Also the version handshake. The agent carries its own copy of the render
    pipeline, so an old build keeps producing old output no matter what has
    been fixed here -- and it has no way to know. It reports what it was built
    from and is told plainly when that is behind.
    """
    db.commit()

    try:
        reported = int(request.headers.get("x-clipforge-pipeline") or 0)
    except ValueError:
        reported = 0
    stale = 0 < reported < PIPELINE_VERSION or reported == 0

    if stale:
        log.info("Agent for %s reports pipeline %s; this server is %s.",
                 user.email, reported or "unknown", PIPELINE_VERSION)

    return {
        "email": user.email,
        "plan": user.plan.value,
        "renders_left": user.renders_left(),
        "server": settings.public_url,
        "pipeline_version": PIPELINE_VERSION,
        "your_pipeline_version": reported,
        "update_available": stale,
        "update_note": (
            "This agent was built before the current render pipeline, so it "
            "will keep producing the old output -- old clip labels, and none "
            "of the newer source filtering. Download the current agent and "
            "replace the .exe."
        ) if stale else "",
    }


@router.post("/claim")
def claim(response: Response, user: User = Depends(agent_user),
          db: Session = Depends(get_db)) -> Optional[dict]:
    """Take the oldest queued job for this account, or answer 204.

    The status flip to SOURCING is the claim: a second agent polling the same
    account sees no queued job rather than racing for the same one.
    """
    job = (db.query(Job)
             .filter(Job.owner_id == user.id, Job.status == JobStatus.QUEUED)
             .order_by(Job.created_at.asc())
             .first())
    if job is None:
        # agent_user() stamped agent_last_seen, and nothing else on this path
        # writes, so without this the stamp is rolled back. An idle agent polls
        # every 20 seconds and would still look like it had never connected --
        # which is wrong on the Activity screen, and wrong for the worker
        # below, which uses that timestamp to decide whether to stay out of
        # the way.
        db.commit()
        response.status_code = status.HTTP_204_NO_CONTENT
        return None

    from ..settings_schema import sanitise

    job_settings = sanitise(dict(job.options or {}).get("format") or {},
                            base=user.settings or {})
    job.status = JobStatus.SOURCING
    job.stage_detail = "Claimed by your render agent"

    # The agent renders on somebody's laptop and has no database, so the list
    # of clips this account has already published has to travel with the job.
    # Without it the agent picks the same five every run, which is exactly
    # what it was doing.
    from ..render.history import recently_used

    used = recently_used(db, user.id,
                         int(job_settings.get("reuse_after_days", 60) or 0))

    db.commit()
    log.info("Job %s claimed by the agent for %s.", job.public_id, user.email)
    return {
        "job": job.public_id,
        "title": job.title or "Compilation",
        "settings": job_settings,
        "options": dict(job.options or {}),
        "dry_run": job.dry_run,
        # The agent burns the watermark in, so it has to be told to.
        "watermark": "clipforge.app" if user.limits["watermark"] else "",
        # Tuples do not survive JSON, so pairs go over as two-item lists.
        "already_used": [[source, external] for source, external in sorted(used)],
    }


def _owned(db: Session, user: User, public_id: str) -> Job:
    job = (db.query(Job)
             .filter(Job.public_id == public_id, Job.owner_id == user.id)
             .first())
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job.")
    return job


# --------------------------------------------------------------------------- #
# Reporting back
# --------------------------------------------------------------------------- #
@router.post("/jobs/{public_id}/progress")
def progress(public_id: str, body: Progress,
             user: User = Depends(agent_user),
             db: Session = Depends(get_db)) -> dict:
    job = _owned(db, user, public_id)
    if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.REJECTED):
        return {"ok": False, "reason": "This job has already finished."}
    job.status = _STAGES.get(body.stage, job.status)
    job.stage_detail = (body.detail or "")[:255]
    db.commit()
    return {"ok": True}


@router.post("/jobs/{public_id}/failed")
def failed(public_id: str, body: Failure,
           user: User = Depends(agent_user),
           db: Session = Depends(get_db)) -> dict:
    """Record a failure and give the reserved render back.

    A retention rejection is a separate outcome from a crash: nothing was
    encoded, so it is not the subscriber's fault and not their allowance.
    """
    job = _owned(db, user, public_id)
    if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.REJECTED):
        return {"ok": False, "reason": "This job has already finished."}

    job.status = JobStatus.REJECTED if body.rejected else JobStatus.FAILED
    job.error = (body.error or "The render agent reported a failure.")[:2000]
    job.stage_detail = ""
    job.finished_at = utcnow()
    if user.renders_this_period > 0:
        user.renders_this_period -= 1
    db.commit()
    log.info("Job %s reported %s by the agent.", public_id, job.status.value)
    return {"ok": True}


@router.post("/jobs/{public_id}/complete")
async def complete(public_id: str,
                   result: str = Form(...),
                   video: UploadFile = File(...),
                   thumbnail: Optional[UploadFile] = File(None),
                   user: User = Depends(agent_user),
                   db: Session = Depends(get_db)) -> dict:
    """Accept a finished render, then take over metadata and publishing.

    The agent sends what it produced. It does not send a status: whether this
    job counts, publishes or is thrown away stays a server decision.
    """
    job = _owned(db, user, public_id)
    if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.REJECTED):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This job has already finished.")
    try:
        payload = json.loads(result)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"The result field is not valid JSON: {exc}")

    settings.render_dir.mkdir(parents=True, exist_ok=True)
    output = settings.render_dir / f"job{job.id}.mp4"
    size = 0
    with output.open("wb") as handle:
        while chunk := await video.read(1 << 20):
            size += handle.write(chunk)

    thumb_path = ""
    if thumbnail is not None and thumbnail.filename:
        target = settings.render_dir / f"job{job.id}.jpg"
        with target.open("wb") as handle:
            while chunk := await thumbnail.read(1 << 20):
                handle.write(chunk)
        thumb_path = str(target)

    job.output_path = str(output)
    job.thumbnail_path = thumb_path
    job.size_bytes = size
    job.duration_seconds = float(payload.get("duration") or 0.0)
    job.retention_score = float(payload.get("score") or 0.0)
    job.retention_report = payload.get("retention") or {}
    job.title = str(payload.get("title") or job.title or "Compilation")[:255]

    for position, clip in enumerate(payload.get("clips") or [], start=1):
        db.add(JobClip(
            job_id=job.id, position=position,
            source=str(clip.get("source", ""))[:40],
            external_id=str(clip.get("external_id", ""))[:128],
            title=str(clip.get("title", ""))[:255],
            author=str(clip.get("author", ""))[:160],
            source_url=str(clip.get("url", ""))[:512],
            licence=str(clip.get("licence", ""))[:80],
            attribution_required=bool(clip.get("attribution_required")),
            duration_seconds=float(clip.get("duration") or 0.0),
            label=str(clip.get("label", ""))[:120],
        ))

    job.status = JobStatus.RENDERING
    job.stage_detail = "Writing title and description"
    job_id = job.id
    db.commit()
    log.info("Job %s completed by the agent, %.1f MB.", public_id,
             size / 1048576)

    # Metadata and publishing stay here: the AI key and the channel's refresh
    # token are the server's, and neither belongs on a subscriber's desktop.
    _finish(job_id, payload, dict(payload.get("settings") or {}))
    return {"ok": True}


def _finish(job_id: int, payload: dict, job_settings: dict) -> None:
    """Write metadata, publish if wanted, and close the job out."""
    from ..render.metadata import finalise, generate
    from ..worker import _publish

    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        user = db.get(User, job.owner_id)
        settings_block = job_settings or (user.settings if user else {}) or {}
        refresh_token = (user.youtube_refresh_token or "") if user else ""
        wants_upload = (bool(settings_block.get("auto_upload"))
                        and not job.dry_run and bool(refresh_token))
        niche_name = job.title or "Compilation"

    meta = generate(
        niche_name=niche_name,
        description=str(settings_block.get("description", "")),
        labels=[str(label) for label in (payload.get("labels") or [])],
    )
    credits = payload.get("credits") or []
    if isinstance(credits, str):          # tolerate an agent sending one line
        credits = [credits] if credits else []
    meta = finalise(meta, suffix=str(settings_block.get("title_suffix", "")),
                    credits=[str(line) for line in credits])

    with session_scope() as db:
        job = db.get(Job, job_id)
        if job:
            job.title = meta.title[:255]
            job.description = meta.description
            job.tags = meta.tags

    if wants_upload:
        _publish(job_id, refresh_token, settings_block)
    else:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job:
                job.upload_state = "skipped"

    with session_scope() as db:
        job = db.get(Job, job_id)
        if job:
            job.status = JobStatus.DONE
            job.stage_detail = ""
            job.finished_at = utcnow()
