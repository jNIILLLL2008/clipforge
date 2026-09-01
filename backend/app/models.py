"""
models.py -- Database schema.

Five tables carry the product: who the user is, what they are allowed to do,
what a "niche" means to them, the render jobs they queue, and the clips those
jobs used. Every clip row keeps its licence and attribution, so a finished
video can always explain where each second of it came from.
"""

from __future__ import annotations

import enum
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, JSON, String,
    Text, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def token() -> str:
    return secrets.token_urlsafe(24)


class Plan(str, enum.Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"


# Monthly render allowance and feature gates per plan.
PLAN_LIMITS = {
    Plan.FREE: {
        "renders_per_month": 3,
        "max_clips": 5,
        "watermark": True,
        "max_seconds": 60,
        "custom_niches": 0,
        "price": "Free",
    },
    Plan.STARTER: {
        "renders_per_month": 40,
        "max_clips": 8,
        "watermark": False,
        "max_seconds": 180,
        "custom_niches": 3,
        "price": "$12/mo",
    },
    Plan.PRO: {
        "renders_per_month": 300,
        "max_clips": 12,
        "watermark": False,
        "max_seconds": 300,
        "custom_niches": 50,
        "price": "$39/mo",
    },
}


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    SOURCING = "sourcing"
    CURATING = "curating"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"
    REJECTED = "rejected"   # failed the retention bar, nothing was charged


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(320), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    plan = Column(Enum(Plan), default=Plan.FREE, nullable=False)
    stripe_customer_id = Column(String(64), nullable=True)
    stripe_subscription_id = Column(String(64), nullable=True)
    plan_renews_at = Column(DateTime(timezone=True), nullable=True)

    # Usage window, reset lazily on first job of a new month.
    period_started_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    renders_this_period = Column(Integer, default=0, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)

    # Whether the first-run tour has been completed. Kept on the account
    # rather than in the browser, so it does not reappear on a second device
    # and does not vanish when someone clears their site data.
    onboarded = Column(Boolean, default=False, nullable=False)

    # The studio configuration. One per account, like the desktop app: the
    # Settings screen edits this, and Publish uses it. Presets seed it.
    settings = Column(JSON, default=dict, nullable=False)

    # Lets a render agent on the user's own machine claim their jobs. Separate
    # from the session token on purpose: it is long-lived, it sits in a config
    # file on a desktop, and it has to be revocable without signing the person
    # out everywhere. Null until they ask for one.
    agent_token = Column(String(64), unique=True, nullable=True, index=True)
    agent_last_seen = Column(DateTime(timezone=True), nullable=True)

    # YouTube connection. Only the refresh token is kept; access tokens are
    # short-lived and fetched as needed.
    youtube_refresh_token = Column(Text, nullable=True)
    youtube_channel_title = Column(String(160), default="", nullable=False)
    youtube_channel_id = Column(String(64), default="", nullable=False)
    youtube_connected_at = Column(DateTime(timezone=True), nullable=True)

    # Daily automation (paid plans only).
    automate_daily = Column(Boolean, default=False, nullable=False)
    automate_time = Column(String(5), default="09:00", nullable=False)  # HH:MM
    automate_timezone = Column(String(64), default="", nullable=False)
    automate_last_run = Column(DateTime(timezone=True), nullable=True)

    jobs = relationship("Job", back_populates="owner",
                        cascade="all, delete-orphan")

    @property
    def youtube_connected(self) -> bool:
        return bool(self.youtube_refresh_token)

    @property
    def limits(self) -> dict:
        return PLAN_LIMITS[self.plan]

    def refresh_period(self) -> None:
        """Roll the usage window forward if the month has turned."""
        started = self.period_started_at
        if started and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if not started or utcnow() - started >= timedelta(days=30):
            self.period_started_at = utcnow()
            self.renders_this_period = 0

    def renders_left(self) -> int:
        self.refresh_period()
        return max(0, self.limits["renders_per_month"] - self.renders_this_period)


class Niche(Base):
    """A starting point for a user's settings.

    These are templates only: applying one copies its settings onto the user's
    own configuration, which they then edit in Settings. Nothing here is
    per-user, so there is one row per preset.
    """

    __tablename__ = "niches"
    __table_args__ = (UniqueConstraint("owner_id", "slug", name="uq_niche_owner_slug"),)

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    slug = Column(String(64), nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text, default="", nullable=False)

    # The complete settings block, validated against settings_schema. Held as
    # one JSON document so adding an option needs no migration.
    settings = Column(JSON, default=dict, nullable=False)

    is_builtin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def to_dict(self) -> dict:
        from .settings_schema import sanitise

        # Sanitise on read as well as write, so a niche stored before a field
        # existed still comes back complete.
        settings = sanitise(dict(self.settings or {}))
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "settings": settings,
            "is_builtin": self.is_builtin,
            "editable": not self.is_builtin,
        }


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    public_id = Column(String(40), default=token, unique=True, nullable=False,
                       index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    niche_id = Column(Integer, ForeignKey("niches.id"), nullable=True)

    status = Column(Enum(JobStatus), default=JobStatus.QUEUED, nullable=False)
    stage_detail = Column(String(255), default="", nullable=False)
    error = Column(Text, default="", nullable=False)

    title = Column(String(255), default="", nullable=False)
    options = Column(JSON, default=dict, nullable=False)

    output_path = Column(String(512), default="", nullable=False)
    thumbnail_path = Column(String(512), default="", nullable=False)
    duration_seconds = Column(Float, default=0.0, nullable=False)
    size_bytes = Column(Integer, default=0, nullable=False)

    # Retention scoring: why this video should hold a viewer, or why we refused.
    retention_score = Column(Float, default=0.0, nullable=False)
    retention_report = Column(JSON, default=dict, nullable=False)

    # Where the clips came from and what was thrown away getting them. Kept
    # because "the same clips keep coming back" and "my playlist is being
    # ignored" look identical from the finished video, and the difference --
    # a pool of six candidates against a run that needs four -- was only ever
    # written to a log.
    sourcing_report = Column(JSON, default=dict, nullable=False)

    # Publishing
    upload_state = Column(String(20), default="none", nullable=False)
    # none | skipped | uploading | uploaded | failed
    youtube_video_id = Column(String(32), default="", nullable=False)
    youtube_url = Column(String(255), default="", nullable=False)
    upload_error = Column(Text, default="", nullable=False)
    description = Column(Text, default="", nullable=False)
    tags = Column(JSON, default=list, nullable=False)

    # True when this run came from the daily schedule rather than a button.
    automated = Column(Boolean, default=False, nullable=False)
    dry_run = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", back_populates="jobs")
    niche = relationship("Niche")
    clips = relationship("JobClip", back_populates="job",
                         cascade="all, delete-orphan")

    def to_dict(self, include_clips: bool = False) -> dict:
        data = {
            "id": self.public_id,
            "status": self.status.value,
            "stage": self.stage_detail,
            "error": self.error,
            "title": self.title,
            "duration": round(self.duration_seconds, 1),
            "size_bytes": self.size_bytes,
            "retention_score": round(self.retention_score, 1),
            "retention": self.retention_report or {},
            "sourcing": self.sourcing_report or {},
            "niche": self.niche.name if self.niche else "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "download_url": f"/api/jobs/{self.public_id}/download"
            if self.status == JobStatus.DONE else None,
            "upload_state": self.upload_state,
            "youtube_url": self.youtube_url,
            "upload_error": self.upload_error,
            "automated": self.automated,
            "dry_run": self.dry_run,
            "description": self.description,
            "tags": self.tags or [],
        }
        if include_clips:
            data["clips"] = [clip.to_dict() for clip in self.clips]
        return data


class JobClip(Base):
    """One source clip used by a job, with the licence it came under."""

    __tablename__ = "job_clips"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)

    position = Column(Integer, default=0, nullable=False)
    source = Column(String(40), default="", nullable=False)     # adapter name
    external_id = Column(String(128), default="", nullable=False)
    title = Column(String(255), default="", nullable=False)
    author = Column(String(160), default="", nullable=False)
    source_url = Column(String(512), default="", nullable=False)

    licence = Column(String(80), default="", nullable=False)
    attribution_required = Column(Boolean, default=False, nullable=False)

    start_seconds = Column(Float, default=0.0, nullable=False)
    duration_seconds = Column(Float, default=0.0, nullable=False)
    label = Column(String(120), default="", nullable=False)

    job = relationship("Job", back_populates="clips")

    def to_dict(self) -> dict:
        return {
            "position": self.position,
            "source": self.source,
            "title": self.title,
            "author": self.author,
            "url": self.source_url,
            "licence": self.licence,
            "attribution_required": self.attribution_required,
            "start": round(self.start_seconds, 2),
            "duration": round(self.duration_seconds, 2),
            "label": self.label,
        }

    def credit_line(self) -> str:
        if not self.attribution_required:
            return ""
        who = self.author or "unknown"
        return f"{self.title or 'Clip'} by {who} ({self.licence}) - {self.source_url}"


class AgentPairing(Base):
    """One in-progress "pair this computer" request.

    The agent cannot ask the person to paste a token, because the person is a
    subscriber and not a developer. So it starts one of these instead: it gets
    a short code, opens the browser at a page carrying that code, and polls
    until someone signed in has approved it. The token then travels straight
    into the agent's own config file and is never shown to anybody.

    Two separate secrets, because they protect different things. ``code`` is
    short and goes on screen, so it only ever identifies a request waiting for
    approval -- knowing one is useless without a signed-in session to approve
    it with. ``device_secret`` is long, never displayed, and is the only thing
    that can collect the token afterwards, so a guessed code cannot steal it.
    """

    __tablename__ = "agent_pairings"

    id = Column(Integer, primary_key=True)

    # Shown to the person so they can confirm the agent in front of them is
    # the one they are approving. Short, and therefore rate-limited and
    # short-lived rather than relied on for secrecy.
    code = Column(String(16), unique=True, index=True, nullable=False)
    device_secret = Column(String(64), unique=True, index=True, nullable=False)

    # The machine's own name, so the approval page can say which computer is
    # asking rather than asking for blind trust.
    label = Column(String(120), default="", nullable=False)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # Held only between approval and the agent's next poll, then cleared. A
    # pairing row that has done its job stops being worth stealing.
    token = Column(Text, nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User")

    #: Long enough to find the browser window, short enough that an abandoned
    #: code is not sitting there tomorrow.
    LIFETIME = timedelta(minutes=15)

    @staticmethod
    def new_code() -> str:
        """A code someone can read off one screen and recognise on another.

        No I, L, O, U, 0 or 1: the first four are misread as each other and as
        digits, and U is dropped so the alphabet cannot spell anything unkind.
        Grouped in fours because that is how people read them back.
        """
        alphabet = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
        raw = "".join(secrets.choice(alphabet) for _ in range(8))
        return f"{raw[:4]}-{raw[4:]}"

    @property
    def expired(self) -> bool:
        deadline = self.expires_at
        if deadline is not None and deadline.tzinfo is None:
            # SQLite hands back naive datetimes; Postgres does not.
            deadline = deadline.replace(tzinfo=timezone.utc)
        return deadline is None or deadline <= utcnow()
