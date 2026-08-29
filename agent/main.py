"""
main.py -- The render agent.

Polls the server for work, renders it here, sends the result back. That is the
whole program. It runs on a subscriber's own machine because YouTube answers a
home connection and refuses a datacentre, and because their computer can do the
ffmpeg encode that the server would otherwise be billed for.

    python -m agent.main --check     confirm the token and settings
    python -m agent.main             work until stopped

Nothing here decides whether a job may run. The server hands out work against a
live subscription and counts it; this asks, renders and reports.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from typing import Optional

import requests

from . import config as agent_config
from .client import Server, ServerError

log = logging.getLogger("agent")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)-16s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # The shared pipeline is chatty at debug; its info lines are the useful part.
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def preflight(cfg, server: Server) -> bool:
    """Check everything a run needs before claiming work with it.

    Failing here costs nothing. Failing after claiming a job means the
    subscriber watches a run die for a reason they cannot see.
    """
    ok = True

    if not shutil.which("ffmpeg"):
        log.error("ffmpeg is not on PATH. The agent cannot cut video without "
                  "it: install it and reopen this terminal.")
        ok = False

    try:
        who = server.hello()
        log.info("Paired with %s as %s (%s plan, %s runs left this month).",
                 cfg.server, who.get("email"), who.get("plan"),
                 who.get("renders_left"))
    except ServerError as exc:
        log.error("%s", exc)
        ok = False
    except requests.RequestException as exc:
        log.error("Could not reach %s: %s", cfg.server, exc)
        ok = False

    clips = [p for p in cfg.footage_dir.glob("*")
             if p.is_file() and p.suffix.lower() in
             {".mp4", ".mov", ".mkv", ".webm", ".m4v"}]
    if clips:
        log.info("%d clip(s) of your own footage in %s.",
                 len(clips), cfg.footage_dir)
    else:
        log.warning("No footage in %s. Niches that use your own uploads will "
                    "find nothing until you put clips there.", cfg.footage_dir)
    return ok


def _sync_footage(cfg) -> None:
    """Present the footage folder to the pipeline as user 1's uploads.

    The shared upload source reads a fixed layout under STORAGE_DIR. Rather
    than teach it about the agent, the agent puts the files where it looks.
    Hard links where the filesystem allows it, so a 4GB folder is not copied.
    """
    target = cfg.storage_dir / "uploads" / str(1)
    target.mkdir(parents=True, exist_ok=True)

    wanted = {p.name for p in cfg.footage_dir.glob("*") if p.is_file()}
    for stale in target.glob("*"):
        if stale.is_file() and stale.name not in wanted:
            stale.unlink()

    for source in cfg.footage_dir.glob("*"):
        if not source.is_file():
            continue
        link = target / source.name
        if link.exists():
            continue
        try:
            link.hardlink_to(source)
        except (OSError, AttributeError):
            shutil.copy2(source, link)


def work_once(cfg, server: Server) -> bool:
    """Claim and run one job. True if there was work."""
    from .runner import run

    try:
        job = server.claim()
    except ServerError as exc:
        log.error("%s", exc)
        raise
    except requests.RequestException as exc:
        log.warning("Could not reach the server: %s", exc)
        return False

    if job is None:
        return False

    log.info("Claimed job %s.", job["job"])
    _sync_footage(cfg)
    try:
        outcome = run(job, cfg, server)
        log.info("Job %s %s", job["job"], outcome)
    except requests.RequestException as exc:
        # The render may well have succeeded; the server will requeue it.
        log.error("Job %s: lost the server while reporting: %s",
                  job["job"], exc)
    except Exception as exc:  # noqa: BLE001 - one bad job must not stop the agent
        log.exception("Job %s crashed: %s", job["job"], exc)
    return True


def loop(cfg, server: Server) -> int:
    log.info("Working for %s. Ctrl+C to stop.", cfg.server)
    while True:
        try:
            busy = work_once(cfg, server)
        except ServerError:
            # A revoked or invalid token will not fix itself by retrying.
            return 1
        except KeyboardInterrupt:
            log.info("Stopped.")
            return 0
        try:
            time.sleep(cfg.poll_seconds if busy else cfg.idle_seconds)
        except KeyboardInterrupt:
            log.info("Stopped.")
            return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent", description="Render ClipForge jobs on this machine.")
    parser.add_argument("--check", action="store_true",
                        help="Verify the token, ffmpeg and footage, then exit.")
    parser.add_argument("--once", action="store_true",
                        help="Take at most one job, then exit.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)

    cfg = agent_config.load()
    # Must happen before anything imports the shared pipeline config.
    agent_config.apply_paths(cfg)

    server = Server(cfg)
    healthy = preflight(cfg, server)
    if args.check:
        log.info("Ready." if healthy else "Not ready. Fix the errors above.")
        return 0 if healthy else 1
    if not healthy:
        return 1

    if args.once:
        return 0 if work_once(cfg, server) else 0
    return loop(cfg, server)


if __name__ == "__main__":
    sys.exit(main())
