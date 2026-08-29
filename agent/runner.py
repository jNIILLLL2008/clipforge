"""
runner.py -- Running one claimed job on this machine.

This is deliberately thin. The pipeline it calls is the same
``backend.app.render.pipeline`` the server runs, imported rather than copied,
so a change to how a video is cut cannot drift between the two. What the agent
adds is only what differs locally: where footage comes from, where the work
happens, and reporting the outcome back over HTTP.

The retention gate still applies here, and a rejection is reported as a
rejection rather than a failure, so the server refunds the run exactly as it
would have done on its own worker.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .client import Server
from .config import AgentConfig

#: The agent works for one account, so the shared upload source is always
#: pointed at the same local folder. The real account id lives on the server.
LOCAL_USER = 1


def _describe(clip) -> dict:
    """One clip, as the server's JobClip rows expect it."""
    return {
        "source": clip.source,
        "external_id": clip.external_id,
        "title": clip.title,
        "author": clip.author,
        "url": clip.url,
        "licence": clip.licence,
        "attribution_required": bool(clip.attribution_required),
        "duration": float(clip.duration or 0.0),
        "label": (clip.title or "")[:120],
    }


def run(job: dict, config: AgentConfig, server: Server) -> str:
    """Render one claimed job. Returns a short outcome for the log."""
    # Imported here, not at module scope: config.apply_paths must set
    # STORAGE_DIR before backend.app.config reads it.
    from backend.app.config import settings
    from backend.app.render.engine import RenderError
    from backend.app.render.pipeline import cleanup, run_job

    public_id = job["job"]
    job_settings = job.get("settings") or {}
    workspace = settings.cache_dir / f"agent-{public_id}"
    output = settings.render_dir / f"agent-{public_id}.mp4"

    def progress(stage: str, detail: str) -> None:
        server.progress(public_id, stage, detail)

    try:
        result = run_job(
            niche={
                "name": job.get("title") or "Compilation",
                "description": str(job_settings.get("description", "")),
                "settings": job_settings,
            },
            options={
                **(job.get("options") or {}),
                # Back into tuples: the server sent pairs as lists.
                "already_used": {
                    (str(pair[0]), str(pair[1]))
                    for pair in (job.get("already_used") or [])
                    if isinstance(pair, (list, tuple)) and len(pair) == 2
                },
            },
            user_id=LOCAL_USER,
            workspace=workspace,
            output=output,
            watermark=job.get("watermark") or "",
            progress=progress,
        )
    except RenderError as exc:
        cleanup(workspace)
        server.failed(public_id, str(exc))
        return f"failed: {exc}"
    except Exception as exc:  # noqa: BLE001 - the loop must survive anything
        cleanup(workspace)
        server.failed(public_id, f"The render agent crashed: {exc}")
        raise

    cleanup(workspace)

    # A rejection is not a failure. Nothing was encoded, so the server gives
    # the run back rather than charging for it.
    if result.retention.rejected:
        server.failed(
            public_id,
            "Rejected before rendering: " + " ".join(result.retention.reasons),
            rejected=True,
        )
        return f"rejected on retention ({result.retention.score:.1f})"

    thumbnail: Optional[Path] = (Path(result.thumbnail)
                                 if result.thumbnail else None)
    server.complete(
        public_id,
        {
            "title": result.title,
            "duration": float(result.duration or 0.0),
            "size_bytes": int(result.size_bytes or 0),
            "score": float(result.retention.score),
            "retention": result.retention.to_dict(),
            "labels": [item.label for item in result.plan.items],
            "credits": list(result.credits or []),
            "settings": job_settings,
            "clips": [_describe(clip) for clip in result.clips],
        },
        Path(result.output),
        thumbnail,
    )

    # The server owns the copy now, and this machine is not a library.
    for leftover in (Path(result.output), thumbnail):
        if leftover and leftover.exists():
            try:
                leftover.unlink()
            except OSError:
                pass

    return f"done ({result.duration:.0f}s, retention {result.retention.score:.1f})"
