"""
history.py -- What this account has already published.

Every clip a job used is written to job_clips with its source and external id.
Nothing ever read that back, so each run scored the same candidate pool with
the same model and picked the same top five. Subscribers watched the same
moments come out again and again, which reads as the product being broken
rather than being consistent.

Reading it back is the whole fix. A clip that has been in a finished video is
skipped until it has aged out, so the second run is forced further down its
own ranking and finds something else.

Only finished jobs count. A failed or rejected run published nothing, and
burning its clips would punish somebody for a run that never went out.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional, Set, Tuple

from ..logging_setup import get_logger
from ..models import Job, JobClip, JobStatus, utcnow

log = get_logger("render.history")


def recently_used(db, user_id: Optional[int], days: int) -> Set[Tuple[str, str]]:
    """(source, external_id) pairs this account published inside `days`.

    Returns an empty set when there is no user, no window, or no database --
    the caller treats that as "nothing to exclude" rather than an error, so a
    history lookup can never be the reason a render fails.
    """
    if not user_id or days <= 0 or db is None:
        return set()

    since = utcnow() - timedelta(days=days)
    try:
        rows = (db.query(JobClip.source, JobClip.external_id)
                  .join(Job, JobClip.job_id == Job.id)
                  .filter(Job.owner_id == user_id,
                          Job.status == JobStatus.DONE,
                          Job.finished_at.isnot(None),
                          Job.finished_at >= since)
                  .all())
    except Exception as exc:  # noqa: BLE001 - never fail a render over history
        log.warning("Could not read clip history: %s", exc)
        return set()

    used = {(source or "", external_id or "")
            for source, external_id in rows if external_id}
    if used:
        log.info("%d clip(s) used in the last %d days will be skipped.",
                 len(used), days)
    return used
