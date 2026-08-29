"""
ffmpeg.py -- Make sure there is an ffmpeg, without asking anyone to install one.

The agent cannot cut a frame without ffmpeg, and "install ffmpeg first" is the
same kind of instruction as "paste this token into a file": true, easy for a
developer, and a wall for everyone else. So the agent handles it.

Three places are checked, in this order:

1. Beside the agent, in ``ffmpeg/``. This is what the packaged download ships,
   so a subscriber who took the .zip already has it and nothing is fetched.
2. On PATH. Somebody who already runs ffmpeg keeps using their own build, at
   their own version, which is the polite thing to do.
3. Downloaded once into ``ffmpeg/`` beside the agent.

The binaries are deliberately kept *next to* the .exe rather than inside it.
A static ffmpeg and ffprobe are about 100MB each, and PyInstaller's onefile
mode unpacks its whole payload into a temporary directory on every single
launch -- burying them would put a 200MB copy on the disk every time the agent
starts, for a program that is meant to sit running all day.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger("agent.ffmpeg")

WINDOWS = sys.platform.startswith("win")
SUFFIX = ".exe" if WINDOWS else ""

#: gyan.dev is the Windows builder ffmpeg.org itself links to, and the URL
#: always points at the current release rather than a pinned version, so this
#: does not rot. The build is GPL because the pipeline encodes with libx264,
#: which is GPL: an LGPL build has no software H.264 encoder at all.
DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
CHECKSUM_URL = DOWNLOAD_URL + ".sha256"

#: What we take out of the archive. ffplay is another 104MB of a program that
#: plays video in a window, which a render agent has no use for.
WANTED = {f"ffmpeg{SUFFIX}", f"ffprobe{SUFFIX}"}


class FFmpegError(RuntimeError):
    """Written to be read by the person running the agent."""


def _dir(home: Path) -> Path:
    return home / "ffmpeg"


def find(home: Path) -> Tuple[Optional[Path], Optional[Path]]:
    """Locate ffmpeg and ffprobe, or (None, None). Never downloads."""
    local = _dir(home)
    pair = (local / f"ffmpeg{SUFFIX}", local / f"ffprobe{SUFFIX}")
    if all(p.is_file() for p in pair):
        return pair

    found = (shutil.which("ffmpeg"), shutil.which("ffprobe"))
    if all(found):
        return Path(found[0]), Path(found[1])
    return None, None


def works(ffmpeg: Path) -> bool:
    """Confirm the binary actually runs before relying on it.

    A half-written file from an interrupted download is still a file, and
    finding out it is broken in the middle of a render costs the subscriber a
    job they were waiting on.
    """
    try:
        result = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-version"],
            capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _progress(done: int, total: int) -> None:
    """One rewritten line, because this is a 110MB wait with nothing else on
    screen and a silent minute reads as a hang."""
    if total <= 0:
        sys.stdout.write(f"\r  {done / 1e6:6.1f} MB")
    else:
        share = done / total
        bar = "#" * int(share * 28)
        sys.stdout.write(f"\r  [{bar:<28}] {share * 100:5.1f}%  "
                         f"{done / 1e6:6.1f} / {total / 1e6:.1f} MB")
    sys.stdout.flush()


def download(home: Path) -> Tuple[Path, Path]:
    """Fetch ffmpeg into ``ffmpeg/`` beside the agent. Windows only."""
    import requests

    if not WINDOWS:
        raise FFmpegError(
            "ffmpeg is missing. Install it with your package manager:\n"
            "    macOS   brew install ffmpeg\n"
            "    Linux   sudo apt install ffmpeg")

    target = _dir(home)
    target.mkdir(parents=True, exist_ok=True)
    archive = target / "download.zip"

    # The checksum comes from the same host as the archive, so it proves the
    # download arrived intact rather than proving the host is honest. That is
    # worth having: a truncated 110MB file is a far likelier failure here than
    # a compromised builder.
    expected = ""
    try:
        expected = requests.get(CHECKSUM_URL, timeout=30).text.strip().split()[0]
    except Exception:  # noqa: BLE001 - a missing checksum must not block the install
        log.debug("No checksum published; continuing without one.")

    print("\n  ffmpeg is not installed, so the agent is fetching its own copy.")
    print(f"  About 110 MB, once. It goes in {target}\n")

    digest = hashlib.sha256()
    try:
        with requests.get(DOWNLOAD_URL, stream=True, timeout=60) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            done = 0
            with open(archive, "wb") as handle:
                for chunk in response.iter_content(1 << 20):
                    handle.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    _progress(done, total)
        print()
    except Exception as exc:  # noqa: BLE001 - one message, whatever went wrong
        archive.unlink(missing_ok=True)
        raise FFmpegError(f"Could not download ffmpeg: {exc}") from exc

    if expected and digest.hexdigest() != expected:
        archive.unlink(missing_ok=True)
        raise FFmpegError(
            "The ffmpeg download did not match its published checksum, so it "
            "was thrown away. Try again; if it keeps happening, install "
            "ffmpeg yourself with: winget install Gyan.FFmpeg")

    print("  Unpacking...")
    try:
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.namelist():
                name = os.path.basename(entry)
                if name in WANTED or name in ("LICENSE", "README.txt"):
                    with bundle.open(entry) as src, \
                            open(target / name, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
    except (zipfile.BadZipFile, OSError) as exc:
        raise FFmpegError(f"The ffmpeg download was unreadable: {exc}") from exc
    finally:
        archive.unlink(missing_ok=True)

    ffmpeg, ffprobe = target / f"ffmpeg{SUFFIX}", target / f"ffprobe{SUFFIX}"
    if not (ffmpeg.is_file() and ffprobe.is_file()):
        raise FFmpegError("The ffmpeg download did not contain what it should. "
                          "Install it yourself with: winget install Gyan.FFmpeg")
    for binary in (ffmpeg, ffprobe):
        try:
            binary.chmod(0o755)
        except OSError:
            pass

    if not works(ffmpeg):
        raise FFmpegError("The downloaded ffmpeg will not run on this machine. "
                          "Install it yourself with: winget install Gyan.FFmpeg")

    print(f"  ffmpeg is ready in {target}\n")
    return ffmpeg, ffprobe


def ensure(home: Path, auto: bool = True) -> Tuple[Path, Path]:
    """Return a working ffmpeg and ffprobe, fetching them if allowed."""
    ffmpeg, ffprobe = find(home)
    if ffmpeg and ffprobe and works(ffmpeg):
        return ffmpeg, ffprobe
    if not auto:
        raise FFmpegError(
            "ffmpeg is missing. Run the agent without --no-download and it "
            "will fetch one, or install it yourself:\n"
            "    Windows   winget install Gyan.FFmpeg\n"
            "    macOS     brew install ffmpeg\n"
            "    Linux     sudo apt install ffmpeg")
    return download(home)


def apply(ffmpeg: Path, ffprobe: Path) -> None:
    """Point the shared pipeline at these binaries.

    backend.app.config reads FFMPEG_BINARY once at import, so this has to run
    before anything pulls the pipeline in.
    """
    os.environ["FFMPEG_BINARY"] = str(ffmpeg)
    os.environ["FFPROBE_BINARY"] = str(ffprobe)
    # Some of what the pipeline shells out to looks ffmpeg up on PATH rather
    # than through the setting, so put ours where that will find it too.
    folder = str(ffmpeg.parent)
    if folder not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
