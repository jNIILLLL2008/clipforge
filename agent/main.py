"""
main.py -- The render agent.

Polls the server for work, renders it here, sends the result back. That is the
whole program. It runs on a subscriber's own machine because YouTube answers a
home connection and refuses a datacentre, and because their computer can do the
ffmpeg encode that the server would otherwise be billed for.

The intended install is: download it, run it. On the first run it has no token,
so it opens the browser and pairs itself -- see pairing.py. Nobody is asked to
edit a file.

    ClipForgeAgent.exe               pair if needed, then work until stopped
    ClipForgeAgent.exe --check       confirm the token and settings
    ClipForgeAgent.exe --pair        pair again, replacing the current token

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
from . import pairing
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


def _owns_console() -> bool:
    """True when closing would take the window with us.

    A .exe started by double-clicking gets a console of its own, and that
    console disappears the instant the process returns -- including on the
    error the person needed to read. One started from an already-open terminal
    shares it, and pausing there would be an annoyance instead.

    Windows distinguishes the two by how many processes are attached to the
    console: only us, or us and the shell that launched us.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        buffer = (ctypes.c_uint * 8)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(buffer, 8)
        return count <= 1
    except Exception:  # noqa: BLE001 - guessing wrong costs one Enter press
        return False


def _hold_window(code: int) -> int:
    """Keep a double-clicked window open long enough to read."""
    if _owns_console():
        try:
            print()
            input("Press Enter to close this window. ")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


def ensure_paired(args) -> Optional[object]:
    """Load the configuration, pairing first if there is no token yet.

    Returns None when pairing did not happen, which is not an error: somebody
    closed the browser, or the code timed out. They run it again.
    """
    cfg = agent_config.load(require_token=False)

    if args.pair or not cfg.token:
        if args.pair and cfg.token:
            log.info("Pairing again. The token this agent uses now will stop "
                     "working as soon as the new one is approved.")
        token = pairing.pair_and_save(
            cfg.server, agent_config.save_pairing,
            open_browser=not args.no_browser)
        if not token:
            return None
        log.info("Saved to %s.", agent_config.DEFAULT_FILE)
        cfg = agent_config.load()
    return cfg


def preflight(cfg, server: Server) -> bool:
    """Check everything a run needs before claiming work with it.

    Failing here costs nothing. Failing after claiming a job means the
    subscriber watches a run die for a reason they cannot see.
    """
    ok = True

    if not shutil.which("ffmpeg"):
        log.error(
            "ffmpeg is missing, and nothing can be cut without it.\n"
            "        Install it, then start this again:\n"
            "          Windows   winget install Gyan.FFmpeg\n"
            "          macOS     brew install ffmpeg\n"
            "          Linux     sudo apt install ffmpeg")
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
    parser.add_argument("--pair", action="store_true",
                        help="Pair with an account again, replacing the "
                             "current token.")
    parser.add_argument("--unpair", action="store_true",
                        help="Forget the token on this machine.")
    parser.add_argument("--no-browser", action="store_true",
                        help="Print the pairing link instead of opening it.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)

    if args.unpair:
        agent_config.clear_token()
        log.info("Token removed from %s. Revoke it on the website too if the "
                 "machine is not yours any more.", agent_config.DEFAULT_FILE)
        return _hold_window(0)

    cfg = ensure_paired(args)
    if cfg is None:
        return _hold_window(1)

    # Must happen before anything imports the shared pipeline config.
    agent_config.apply_paths(cfg)

    server = Server(cfg)
    healthy = preflight(cfg, server)
    if args.check:
        log.info("Ready." if healthy else "Not ready. Fix the errors above.")
        return _hold_window(0 if healthy else 1)
    if not healthy:
        return _hold_window(1)

    if args.once:
        work_once(cfg, server)
        return _hold_window(0)
    return _hold_window(loop(cfg, server))


if __name__ == "__main__":
    sys.exit(main())
