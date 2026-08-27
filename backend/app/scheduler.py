"""
scheduler.py -- Daily automated runs for paid accounts.

One background thread wakes every minute, finds accounts whose local run time
has arrived, and queues a job for each. Unlike the desktop app this does not
need anything left open: the server is already running.

Two guards matter. An account is only run once per calendar day in its own
timezone, so a restart or a clock change cannot double-post. And the plan is
re-checked at fire time rather than trusted from when the switch was flipped,
so a lapsed subscription stops publishing.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .db import session_scope
from .logging_setup import get_logger
from .models import Job, JobStatus, Plan, User, utcnow

log = get_logger("scheduler")

_started = threading.Event()
TICK_SECONDS = 60


def automation_allowed(user: User) -> bool:
    """Daily publishing is a paid feature."""
    return user.plan in (Plan.STARTER, Plan.PRO)


def _zone(name: str):
    if not name:
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - a bad name must not stop the loop
        return timezone.utc


def _local_now(user: User) -> datetime:
    return datetime.now(_zone(user.automate_timezone))


def due(user: User, now: Optional[datetime] = None) -> bool:
    """Has this account's run time passed today, without having run yet?"""
    if not user.automate_daily or not automation_allowed(user):
        return False

    local = now or _local_now(user)
    try:
        hour, minute = (int(part) for part in user.automate_time.split(":"))
    except (ValueError, AttributeError):
        return False

    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local < target:
        return False

    last = user.automate_last_run
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        # Compare in the user's own day, so a run at 23:50 and one at 00:10 are
        # different days rather than "within 24 hours".
        if last.astimezone(local.tzinfo).date() >= local.date():
            return False

    # Do not fire for a window missed by hours -- a server that was down all
    # day should not publish at 4am when it comes back.
    return local - target < timedelta(hours=2)


def start_scheduler() -> None:
    from .config import settings

    if not settings.run_scheduler:
        log.info("Daily scheduler disabled here (RUN_SCHEDULER=false).")
        return
    if _started.is_set():
        return
    _started.set()
    threading.Thread(target=_loop, name="scheduler", daemon=True).start()
    log.info("Daily scheduler running (checks every %ds).", TICK_SECONDS)


def _loop() -> None:
    while True:
        try:
            run_due_jobs()
        except Exception as exc:  # noqa: BLE001 - the loop must survive anything
            log.exception("Scheduler tick failed: %s", exc)
        time.sleep(TICK_SECONDS)


def run_due_jobs() -> List[int]:
    """Queue a job for every account whose time has come. Returns job ids."""
    from .worker import enqueue

    queued: List[int] = []
    with session_scope() as db:
        candidates = (db.query(User)
                      .filter(User.automate_daily.is_(True),
                              User.is_active.is_(True))
                      .all())
        for user in candidates:
            if not due(user):
                continue
            if user.renders_left() <= 0:
                log.info("Skipping daily run for user %s: no renders left.",
                         user.id)
                # Still stamp it, or every tick retries for the rest of the day.
                user.automate_last_run = utcnow()
                continue

            job = Job(
                owner_id=user.id,
                title="",
                options={"format": {}},
                status=JobStatus.QUEUED,
                stage_detail="Queued by the daily schedule",
                automated=True,
            )
            db.add(job)
            user.refresh_period()
            user.renders_this_period += 1
            user.automate_last_run = utcnow()
            db.flush()
            queued.append(job.id)
            log.info("Daily run queued for user %s (job %s).", user.id, job.id)

    for job_id in queued:
        enqueue(job_id)
    return queued
