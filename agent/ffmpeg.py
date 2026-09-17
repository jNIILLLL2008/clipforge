"""
ffmpeg.py -- Make sure there is an ffmpeg, without asking anyone to install one.

The agent cannot cut a frame without ffmpeg, and "install ffmpeg first" is the
same kind of instruction as "paste this token into a file": true, easy for a
developer, and a wall for everyone else. So the agent handles it, on Windows
and on macOS alike.

Three places are checked, in this order:

1. Beside the agent, in ``ffmpeg/``. This is what the packaged download ships,
   so a subscriber who took the .zip already has it and nothing is fetched.
2. On PATH, plus the places a Mac keeps them that a double-clicked program
   cannot see. Somebody who already runs ffmpeg keeps using their own build,
   at their own version, which is the polite thing to do.
3. Downloaded once into ``ffmpeg/`` beside the agent.

The binaries are deliberately kept *next to* the agent rather than inside it.
A static ffmpeg and ffprobe are about 100MB each, and PyInstaller's onefile
mode unpacks its whole payload into a temporary directory on every single
launch -- burying them would put a 200MB copy on the disk every time the agent
starts, for a program that is meant to sit running all day.

Both platforms need a *GPL* build, because the pipeline encodes with libx264
and an LGPL ffmpeg has no software H.264 encoder at all, and both need libass,
because the overlay is burnt in as an ASS subtitle layer.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Optional, Tuple

log = logging.getLogger("agent.ffmpeg")

WINDOWS = sys.platform.startswith("win")
MACOS = sys.platform == "darwin"
SUFFIX = ".exe" if WINDOWS else ""

#: gyan.dev is the Windows builder ffmpeg.org itself links to, and the URL
#: always points at the current release rather than a pinned version, so this
#: does not rot. The build is GPL because the pipeline encodes with libx264,
#: which is GPL: an LGPL build has no software H.264 encoder at all.
DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
CHECKSUM_URL = DOWNLOAD_URL + ".sha256"

#: The macOS equivalent, and the reason it is a different shape: there is no
#: one archive with everything in it. ffmpeg.martin-riedl.de publishes a zip
#: per binary per architecture, each with a .sha256 beside it, behind a
#: /redirect/latest/ path that resolves to the current version -- so this does
#: not rot either. The builds are --enable-gpl --enable-libx264
#: --enable-libass, which is what the pipeline needs, and they are signed,
#: which Apple silicon insists on before it will run anything at all.
MAC_BASE = "https://ffmpeg.martin-riedl.de/redirect/latest/macos"
MAC_SOURCE_NOTE = (
    "FFmpeg is free software under the GPL. Source: "
    "https://ffmpeg.org/download.html -- build script: "
    "https://git.martin-riedl.de/ffmpeg/build-script")

#: What we take out of the archive. ffplay is another 104MB of a program that
#: plays video in a window, which a render agent has no use for.
WANTED = {f"ffmpeg{SUFFIX}", f"ffprobe{SUFFIX}"}

#: Where a Mac keeps binaries that PATH will not mention. A program started
#: from Finder inherits launchd's PATH -- /usr/bin:/bin:/usr/sbin:/sbin --
#: rather than the one the person's shell sets up, so a Homebrew ffmpeg is
#: invisible to shutil.which even though it is right there. Looking by hand is
#: the difference between "you already have one" and a download nobody needed.
MAC_EXTRA_PATHS = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin")


class FFmpegError(RuntimeError):
    """Written to be read by the person running the agent."""


def _dir(home: Path) -> Path:
    return home / "ffmpeg"


def install_hint() -> str:
    """How to install ffmpeg by hand, for whichever machine this is."""
    if WINDOWS:
        return "winget install Gyan.FFmpeg"
    if MACOS:
        return "brew install ffmpeg"
    return "sudo apt install ffmpeg"


def _on_path(name: str) -> Optional[Path]:
    """Find a binary on PATH, or where a Mac hides one from a Finder launch."""
    found = shutil.which(name)
    if found:
        return Path(found)
    if MACOS:
        for folder in MAC_EXTRA_PATHS:
            candidate = Path(folder) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    return None


def find(home: Path) -> Tuple[Optional[Path], Optional[Path]]:
    """Locate ffmpeg and ffprobe, or (None, None). Never downloads."""
    local = _dir(home)
    pair = (local / f"ffmpeg{SUFFIX}", local / f"ffprobe{SUFFIX}")
    if all(p.is_file() for p in pair):
        return pair

    ffmpeg, ffprobe = _on_path("ffmpeg"), _on_path("ffprobe")
    if ffmpeg and ffprobe:
        return ffmpeg, ffprobe
    return None, None


def unblock(paths: Iterable[Path]) -> None:
    """Undo what a browser download did to these files, on macOS.

    Anything unpacked from a .zip that a browser fetched carries
    com.apple.quarantine, and a binary from an unidentified developer with
    that attribute set is refused rather than run. The agent's own downloads
    are not quarantined -- the attribute is applied by the app that did the
    downloading, and requests is not one of those -- so this only matters for
    binaries that arrived inside the packaged .zip. Clearing it costs nothing
    when there was nothing set.
    """
    if not MACOS:
        return
    for path in paths:
        if not path.exists():
            continue
        try:
            path.chmod(0o755)
        except OSError:
            pass
        try:
            subprocess.run(["xattr", "-d", "com.apple.quarantine", str(path)],
                           capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            # xattr ships with macOS. If it is missing, the attribute it would
            # have removed is almost certainly missing too.
            pass


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


def _progress(done: int, total: int, label: str = "") -> None:
    """One rewritten line, because this is a long wait with nothing else on
    screen and a silent minute reads as a hang."""
    head = f"  {label:<8}" if label else "  "
    if total <= 0:
        sys.stdout.write(f"\r{head}{done / 1e6:6.1f} MB")
    else:
        share = done / total
        bar = "#" * int(share * 28)
        sys.stdout.write(f"\r{head}[{bar:<28}] {share * 100:5.1f}%  "
                         f"{done / 1e6:6.1f} / {total / 1e6:.1f} MB")
    sys.stdout.flush()


def _fetch(url: str, destination: Path, label: str = "") -> Tuple[str, str]:
    """Download one file with a progress bar.

    Returns where it really came from and what it hashed to. The first of
    those matters on macOS, where the download is a /redirect/latest/ path and
    the checksum is published beside the *resolved* file rather than beside
    the redirect, so the caller cannot know where to ask until it has asked.
    """
    import requests

    digest = hashlib.sha256()
    try:
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            done = 0
            with open(destination, "wb") as handle:
                for chunk in response.iter_content(1 << 20):
                    handle.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    _progress(done, total, label)
            came_from = response.url
        print()
    except Exception as exc:  # noqa: BLE001 - one message, whatever went wrong
        destination.unlink(missing_ok=True)
        raise FFmpegError(f"Could not download ffmpeg: {exc}") from exc
    return came_from, digest.hexdigest()


def _published_checksum(url: str) -> str:
    """The .sha256 published next to a download, or "" if there is not one.

    A checksum from the same host proves the download arrived intact rather
    than proving the host is honest. That is worth having on its own: a
    truncated 28MB file is a far likelier failure here than a compromised
    builder.
    """
    import requests

    try:
        text = requests.get(url, timeout=30).text.strip()
    except Exception:  # noqa: BLE001 - a missing checksum must not block the install
        log.debug("No checksum published at %s; continuing without one.", url)
        return ""
    return text.split()[0] if text else ""


def mac_arch() -> str:
    """Which macOS build to fetch: Apple silicon or Intel.

    Asked of the machine rather than of this process. A subscriber who
    downloaded the Intel agent onto an Apple silicon Mac is running under
    Rosetta, where platform.machine() describes the translation and not the
    computer. ffmpeg is a separate process and does not have to share that
    fate, so the encode -- which is the part that takes the minutes -- still
    runs native.
    """
    if platform.machine().lower() in ("arm64", "aarch64"):
        return "arm64"
    try:
        answer = subprocess.run(["sysctl", "-n", "sysctl.proc_translated"],
                                capture_output=True, text=True, timeout=10)
        if answer.stdout.strip() == "1":
            return "arm64"
    except (OSError, subprocess.SubprocessError):
        pass
    return "amd64"


def _unpack(archive: Path, name: str, target: Path) -> None:
    """Take one named binary out of a zip, wherever in it that binary sits."""
    try:
        with zipfile.ZipFile(archive) as bundle:
            member = next((entry for entry in bundle.namelist()
                           if os.path.basename(entry) == name), None)
            if member is None:
                raise FFmpegError(f"The {name} download did not contain "
                                  f"{name}.")
            with bundle.open(member) as src, open(target / name, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    except (zipfile.BadZipFile, OSError) as exc:
        raise FFmpegError(f"The {name} download was unreadable: {exc}") from exc


def _download_mac(target: Path) -> Tuple[Path, Path]:
    """Fetch ffmpeg and ffprobe, which are two separate downloads here."""
    arch = mac_arch()
    print("\n  ffmpeg is not installed, so the agent is fetching its own copy.")
    print(f"  About 57 MB, once. It goes in {target}")
    print(f"  {MAC_SOURCE_NOTE}\n")

    for name in ("ffmpeg", "ffprobe"):
        archive = target / f"{name}.zip"
        # A release build is a tagged ffmpeg and the snapshot is the same
        # builder following master. Prefer the release; but an architecture
        # can go a while published only as snapshots, and that is not a good
        # enough reason to send a subscriber off to install ffmpeg by hand.
        came_from = actual = ""
        failure: Optional[FFmpegError] = None
        for variant in ("release", "snapshot"):
            try:
                came_from, actual = _fetch(
                    f"{MAC_BASE}/{arch}/{variant}/{name}.zip",
                    archive, label=name)
                break
            except FFmpegError as exc:
                failure = exc
                log.debug("No %s build of %s for %s: %s",
                          variant, name, arch, exc)
        else:
            raise failure or FFmpegError("Could not download ffmpeg.")

        expected = _published_checksum(came_from + ".sha256")
        if expected and expected != actual:
            archive.unlink(missing_ok=True)
            raise FFmpegError(
                f"The {name} download did not match its published checksum, "
                f"so it was thrown away. Try again; if it keeps happening, "
                f"install ffmpeg yourself with: {install_hint()}")

        try:
            _unpack(archive, name, target)
        finally:
            archive.unlink(missing_ok=True)

    return target / "ffmpeg", target / "ffprobe"


def _download_windows(target: Path) -> Tuple[Path, Path]:
    """Fetch ffmpeg, which arrives here as one archive with both in it."""
    archive = target / "download.zip"
    expected = _published_checksum(CHECKSUM_URL)

    print("\n  ffmpeg is not installed, so the agent is fetching its own copy.")
    print(f"  About 110 MB, once. It goes in {target}\n")

    _, actual = _fetch(DOWNLOAD_URL, archive)
    if expected and expected != actual:
        archive.unlink(missing_ok=True)
        raise FFmpegError(
            "The ffmpeg download did not match its published checksum, so it "
            "was thrown away. Try again; if it keeps happening, install "
            f"ffmpeg yourself with: {install_hint()}")

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

    return target / f"ffmpeg{SUFFIX}", target / f"ffprobe{SUFFIX}"


def download(home: Path) -> Tuple[Path, Path]:
    """Fetch ffmpeg into ``ffmpeg/`` beside the agent. Windows and macOS."""
    if not (WINDOWS or MACOS):
        raise FFmpegError(
            "ffmpeg is missing. Install it with your package manager:\n"
            f"    {install_hint()}")

    target = _dir(home)
    target.mkdir(parents=True, exist_ok=True)
    ffmpeg, ffprobe = (_download_mac(target) if MACOS
                       else _download_windows(target))

    if not (ffmpeg.is_file() and ffprobe.is_file()):
        raise FFmpegError("The ffmpeg download did not contain what it should. "
                          f"Install it yourself with: {install_hint()}")
    # Written a byte at a time out of a zip, so whatever permissions the
    # archive recorded did not come with them.
    for binary in (ffmpeg, ffprobe):
        try:
            binary.chmod(0o755)
        except OSError:
            pass

    if not works(ffmpeg):
        raise FFmpegError("The downloaded ffmpeg will not run on this machine. "
                          f"Install it yourself with: {install_hint()}")

    print(f"  ffmpeg is ready in {target}\n")
    return ffmpeg, ffprobe


def ensure(home: Path, auto: bool = True) -> Tuple[Path, Path]:
    """Return a working ffmpeg and ffprobe, fetching them if allowed."""
    ffmpeg, ffprobe = find(home)
    if ffmpeg and ffprobe:
        if works(ffmpeg):
            return ffmpeg, ffprobe
        # On a Mac the usual reason a perfectly good binary will not run is
        # that it came out of a .zip the browser downloaded and is still
        # quarantined. Worth one repair attempt before spending 57MB
        # replacing a file that was never the problem.
        unblock((ffmpeg, ffprobe))
        if works(ffmpeg):
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
