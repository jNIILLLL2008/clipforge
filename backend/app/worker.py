"""
worker.py -- Background render queue.

A small in-process thread pool, deliberately: it keeps the deployment to one
service, and rendering is ffmpeg-bound rather than Python-bound. The job table
is the queue, so a restart resumes anything left QUEUED instead of losing it.

Swap this for Celery/RQ when one machine stops being enough; ``enqueue`` is the
only function callers use, so the change stays local.
"""

from __future__ import annotations

import queue
import threading
from datetime import timedelta, timezone
from pathlib import Path
from typing import Optional

from .config import settings
from .db import session_scope
from .logging_setup import get_logger
from .models import Job, JobClip, JobStatus, Niche, User, utcnow
from .render.engine import RenderError
from .render.pipeline import cleanup, run_job

log = get_logger("worker")

_queue: "queue.Queue[int]" = queue.Queue()
_threads: list = []
_started = threading.Event()

#: How long to wait before looking at a deferred job again. Shorter than the
#: agent's 20-second idle poll, so the handover costs the subscriber nothing.
_DEFER_SECONDS = 15.0


def enqueue(job_id: int) -> None:
    _queue.put(job_id)


def agent_is_live(user: User) -> bool:
    """Is a render agent for this account polling right now?

    Paired is not the same as running. Somebody who paired an agent months ago
    and has not opened it since must still get their videos, so this asks when
    it last spoke rather than whether a token exists.
    """
    if not user.agent_token or user.agent_last_seen is None:
        return False
    seen = user.agent_last_seen
    if seen.tzinfo is None:
        # SQLite hands back naive datetimes; Postgres does not.
        seen = seen.replace(tzinfo=timezone.utc)
    return (utcnow() - seen) < timedelta(seconds=settings.agent_online_seconds)


def _defer(job_id: int, seconds: float) -> None:
    """Put a job back in the queue shortly, without blocking a worker on it."""
    timer = threading.Timer(seconds, enqueue, args=(job_id,))
    timer.daemon = True
    timer.start()


def start_workers() -> None:
    """Start the pool once, and requeue anything stranded by a restart."""
    if _started.is_set():
        return
    _started.set()

    with session_scope() as db:
        stranded = db.query(Job).filter(
            Job.status.in_([JobStatus.QUEUED, JobStatus.SOURCING,
                            JobStatus.CURATING, JobStatus.RENDERING])
        ).all()
        for job in stranded:
            job.status = JobStatus.QUEUED
            job.stage_detail = "Requeued after restart"
            enqueue(job.id)
        if stranded:
            log.info("Requeued %d job(s) after restart.", len(stranded))

    # RENDER_WORKERS=0 means this instance renders nothing itself and waits for
    # a render agent to claim the queue instead. Jobs still queue normally, so
    # they simply wait rather than fail while the agent is offline.
    if settings.render_workers <= 0:
        log.info("No local render workers; jobs will wait for a render agent.")
        return

    for index in range(settings.render_workers):
        thread = threading.Thread(target=_loop, name=f"render-{index}", daemon=True)
        thread.start()
        _threads.append(thread)
    log.info("Started %d render worker(s).", len(_threads))


def _loop() -> None:
    while True:
        job_id = _queue.get()
        try:
            _process(job_id)
        except Exception as exc:  # noqa: BLE001 - a worker must never die
            log.exception("Job %s crashed: %s", job_id, exc)
            _fail(job_id, str(exc))
        finally:
            _queue.task_done()


def _set_stage(job_id: int, status: JobStatus, detail: str) -> None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job:
            job.status = status
            job.stage_detail = detail[:255]


def _detail(job_id: int, detail: str) -> None:
    """Update the progress line without touching the status."""
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job:
            job.stage_detail = detail[:255]


def _fail(job_id: int, message: str, status: JobStatus = JobStatus.FAILED) -> None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if not job:
            return
        job.status = status
        job.error = message[:2000]
        job.stage_detail = ""
        job.finished_at = utcnow()
        _refund(db, job)


def _refund(db, job: Job) -> None:
    """Give back the render reserved at queue time.

    Nothing was delivered, so it should not count against the month. Guarded
    against going negative if a job is somehow finished twice.
    """
    user = db.get(User, job.owner_id)
    if user and user.renders_this_period > 0:
        user.renders_this_period -= 1


def _upload_decision(job_settings: dict, *, dry_run: bool,
                     refresh_token: str, google_app: tuple = ("", "")) -> tuple:
    """Whether to publish, and in plain words why not. (wants, reason)

    Ordered from the subscriber's own choices outwards, so the reason names
    the thing they can actually change: their setting first, their channel
    next, and the server's configuration last.
    """
    from . import youtube

    if dry_run:
        return False, "Dry run: the video was rendered but not uploaded."
    if not job_settings.get("auto_upload"):
        return False, ("Not uploaded: \"Publish after rendering\" is turned "
                       "off in your settings.")
    if not (all(google_app) or youtube.configured()):
        return False, ("Not uploaded: publishing is not set up yet. Follow "
                       "the publishing setup to create your Google project "
                       "— it only has to be done once.")
    if not refresh_token:
        return False, ("Not uploaded: no YouTube account is connected. "
                       "Connect one from the Home screen.")
    return True, ""


def _process(job_id: int) -> None:
    """Run one job, recording progress as it goes."""
    with session_scope() as db:
        job = db.get(Job, job_id)
        if not job or job.status not in (JobStatus.QUEUED,):
            return
        user = db.get(User, job.owner_id)
        if user is None:
            job.status = JobStatus.FAILED
            job.error = "The account for this job no longer exists."
            return

        # Both this pool and the agent claim from the same QUEUED pool, and
        # this one is in the same process as the queue, so it wins the race
        # essentially always. That is the wrong outcome: the agent exists
        # because YouTube refuses this machine's datacentre address and
        # answers the subscriber's home connection, so a job rendered here is
        # the one likely to fail.
        #
        # So stand down while an agent is actually polling. This is not a
        # standoff -- agent_is_live goes false a couple of minutes after the
        # agent stops asking, and the job is picked up here on the next pass.
        if agent_is_live(user):
            job.stage_detail = "Waiting for your render agent"
            _defer(job_id, _DEFER_SECONDS)
            return

        # The user's own configuration is the source of truth; the job's
        # options are per-run overrides on top of it.
        from .settings_schema import sanitise

        job_settings = sanitise(dict(job.options or {}).get("format") or {},
                                base=user.settings or {})

        # Which clips this account has already published, so the same five do
        # not win every run. Read here, inside the session that already has
        # the user open.
        from .render.history import recently_used

        # user.id, not user_id: that local is assigned a few lines below and
        # reading it here is an UnboundLocalError.
        used_clips = recently_used(
            db, user.id, int(job_settings.get("reuse_after_days", 60) or 0))
        niche_data = {"name": job.title or "Compilation",
                      "description": job_settings.get("description", ""),
                      "settings": job_settings}
        options = dict(job.options or {})
        user_id = user.id
        watermark = "clipforge.app" if user.limits["watermark"] else ""
        refresh_token = user.youtube_refresh_token or ""
        google_app = (user.google_client_id or "", user.google_client_secret or "")
        wants_upload, skip_reason = _upload_decision(
            job_settings, dry_run=bool(job.dry_run), refresh_token=refresh_token,
            google_app=google_app)
        job.status = JobStatus.SOURCING
        job.stage_detail = "Starting"

    workspace = settings.cache_dir / f"job{job_id}"
    output = settings.render_dir / f"job{job_id}.mp4"

    def progress(stage: str, detail: str) -> None:
        mapping = {
            "sourcing": JobStatus.SOURCING,
            "curating": JobStatus.CURATING,
            "rendering": JobStatus.RENDERING,
        }
        _set_stage(job_id, mapping.get(stage, JobStatus.SOURCING), detail)

    try:
        result = run_job(
            niche=niche_data, options={**options, "already_used": used_clips},
            user_id=user_id,
            workspace=workspace, output=output, watermark=watermark,
            progress=progress,
        )
    except RenderError as exc:
        log.warning("Job %s failed: %s", job_id, exc)
        _fail(job_id, str(exc))
        cleanup(workspace)
        return

    cleanup(workspace)

    # Retention rejection happens before any encode, so there is nothing to
    # publish and the reserved render is given back.
    if result.retention.rejected:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            job.retention_score = result.retention.score
            job.retention_report = result.retention.to_dict()
            job.status = JobStatus.REJECTED
            job.error = ("Rejected before rendering: "
                         + " ".join(result.retention.reasons))[:800]
            job.finished_at = utcnow()
            _refund(db, job)
        log.info("Job %s rejected on retention (%.1f).", job_id,
                 result.retention.score)
        return

    # Record the render, then write metadata and publish. The job is only
    # marked DONE at the very end: anything that sets a status in between
    # would be overwritten, and a half-published job must not look finished.
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.retention_score = result.retention.score
        job.retention_report = result.retention.to_dict()
        job.sourcing_report = result.sourcing or {}
        job.title = result.title[:255]
        job.output_path = str(result.output)
        job.thumbnail_path = str(result.thumbnail or "")
        job.duration_seconds = result.duration
        job.size_bytes = result.size_bytes
        for position, clip in enumerate(result.clips, start=1):
            db.add(JobClip(
                job_id=job.id, position=position, source=clip.source,
                external_id=clip.external_id[:128], title=clip.title[:255],
                author=clip.author[:160], source_url=clip.url[:512],
                licence=clip.licence[:80],
                attribution_required=clip.attribution_required,
                duration_seconds=clip.duration,
                label=(clip.title or "")[:120],
            ))
        # The render itself was reserved when the job was queued.

    _write_metadata(job_id, result, job_settings)

    if wants_upload:
        _publish(job_id, refresh_token, job_settings, google_app)
    else:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job:
                job.upload_state = "skipped"
                # Never a bare "skipped". Three separate conditions have to
                # hold for a video to reach a channel, and when one did not
                # the only record was this word -- so pressing Publish and
                # getting a file that went nowhere was indistinguishable from
                # a dry run, from publishing being switched off, and from the
                # server having no Google credentials at all.
                job.upload_error = skip_reason

    with session_scope() as db:
        job = db.get(Job, job_id)
        if job:
            job.status = JobStatus.DONE
            job.stage_detail = ""
            job.finished_at = utcnow()


def _write_metadata(job_id: int, result, job_settings: dict) -> None:
    """Generate the title, description and tags, then store them."""
    from .render.metadata import finalise, generate

    _detail(job_id, "Writing title and description")
    labels = [item.label for item in result.plan.items]
    meta = generate(
        niche_name=result.title or "Compilation",
        description=str(job_settings.get("description", "")),
        labels=labels,
    )
    meta = finalise(meta, suffix=str(job_settings.get("title_suffix", "")),
                    credits=result.credits)

    with session_scope() as db:
        job = db.get(Job, job_id)
        if job:
            job.title = meta.title[:255]
            job.description = meta.description
            job.tags = meta.tags


def _publish(job_id: int, refresh_token: str, job_settings: dict,
             google_app: tuple = ("", "")) -> None:
    """Upload the finished render to the user's channel."""
    from datetime import timedelta

    from . import youtube

    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None or not job.output_path:
            return
        path = Path(job.output_path)
        title, description, tags = job.title, job.description, list(job.tags or [])
        job.upload_state = "uploading"
        job.stage_detail = "Uploading to YouTube"

    delay = int(job_settings.get("publish_delay_minutes", 0) or 0)
    publish_at = None
    if delay > 0:
        when = utcnow() + timedelta(minutes=delay)
        publish_at = when.strftime("%Y-%m-%dT%H:%M:%SZ")

    def progress(percent: int) -> None:
        _detail(job_id, f"Uploading — {percent}%")

    try:
        outcome = youtube.upload(
            refresh_token=refresh_token,
            path=path,
            title=title,
            description=description,
            tags=tags,
            privacy=str(job_settings.get("privacy_status", "private")),
            category_id=str(job_settings.get("category_id", "24")),
            made_for_kids=bool(job_settings.get("made_for_kids")),
            publish_at=publish_at,
            on_progress=progress,
            client_id=google_app[0],
            client_secret=google_app[1],
        )
    except youtube.YouTubeAuthError as exc:
        # The permission is gone, so the stored token is worthless and every
        # later run would fail the same way. Clearing it turns an endless
        # stream of failed uploads into one thing to do: connect again.
        log.warning("Upload for job %s hit a dead connection: %s", job_id, exc)
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job:
                job.upload_state = "failed"
                job.upload_error = str(exc)[:1000]
                job.stage_detail = ""
                user = db.get(User, job.owner_id)
                if user:
                    user.youtube_refresh_token = None
                    user.youtube_channel_title = ""
                    user.youtube_channel_id = ""
                    user.youtube_connected_at = None
                    user.youtube_disconnected_reason = str(exc)[:255]
        return
    except Exception as exc:  # noqa: BLE001 - the render still succeeded
        log.warning("Upload failed for job %s: %s", job_id, exc)
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job:
                job.upload_state = "failed"
                job.upload_error = str(exc)[:1000]
                job.stage_detail = ""
        return

    with session_scope() as db:
        job = db.get(Job, job_id)
        if job:
            job.upload_state = "uploaded"
            job.youtube_video_id = outcome.video_id
            job.youtube_url = outcome.url
            job.stage_detail = ""
    log.info("Job %s published: %s", job_id, outcome.url)
