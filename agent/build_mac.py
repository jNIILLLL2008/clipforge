"""
build_mac.py -- Produce agent/ClipForgeAgent for macOS, and the .zip around it.

    python3 agent/build_mac.py                build the binary
    python3 agent/build_mac.py --clean        rebuild from scratch
    python3 agent/build_mac.py --bundle       binary + ffmpeg, in one .zip

This has to run *on a Mac*. PyInstaller freezes the interpreter it is running
under, so there is no cross-compiling it from Windows: the Windows build is
made by build_exe.py on Windows, and this one is made here. Both read the same
ClipForgeAgent.spec, so the two builds cannot drift in what they include.

The build is per-architecture for the same reason. Apple silicon and Intel get
separate .zips, named for the chip, because a frozen Python is the one part of
this that cannot be fat unless the Python it was frozen from was.

ffmpeg stays *beside* the binary rather than inside it, exactly as on Windows:
two static binaries are about 130MB unpacked, and onefile mode unpacks its
whole payload into a temporary directory on every launch.

Two things about a Mac that Windows does not have, and that the .zip has to
answer for:

* Gatekeeper. The build is signed ad-hoc -- enough for Apple silicon to run it
  at all -- but not notarized, because notarizing needs a paid Developer ID.
  Anything a browser downloads is quarantined, and a quarantined binary from
  an unidentified developer is refused rather than run. So the .zip leads with
  a .command the person right-clicks and opens once; that first approval is
  the only one, and the script clears the quarantine flag off everything else
  in the folder before starting the agent.
* The executable bit. Python's zipfile does not record permissions unless it
  is told to, and a binary that arrives without its +x is a binary that will
  not start. Every entry here is written 0755 on purpose.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = HERE / "ClipForgeAgent.spec"
BINARY_NAME = "ClipForgeAgent"
LAUNCHER_NAME = "Start ClipForge Agent.command"

#: What the .zip tells someone to do. The right-click is not a quirk worth
#: hiding: it is the one step macOS insists on for software without a paid
#: Developer ID, and a person who does not expect it reads "is damaged and
#: cannot be opened" as a broken download and gives up.
READ_ME = """ClipForge render agent
======================

1. Keep these files together in this folder. Drag the folder wherever you
   want it to live -- your Applications folder is a good home.
2. RIGHT-CLICK "Start ClipForge Agent.command" and choose Open.
   Then click Open again when macOS asks.

   Right-click, not double-click, and only the first time. macOS refuses
   software it has not seen notarized unless you open it this way once; after
   that, double-clicking works like anything else.

3. Your browser opens. Sign in if you need to, check the code matches the one
   in the agent's window, and click "Pair it".

That is the whole install. There is no token to copy and no file to edit.

The agent then waits for work. Leave it running, or quit it and start it
again whenever you want it to render.

Put your own clips in a folder called "footage" beside the agent if you use
the upload source. You do not need to for YouTube sourcing.

If macOS still says the app cannot be opened
--------------------------------------------
Open Terminal, type "xattr -dr com.apple.quarantine " (with the trailing
space), drag this folder into the window, and press Return. That clears the
same flag the right-click does.

ffmpeg
------
ffmpeg and ffprobe in the ffmpeg folder are unmodified static builds from
https://ffmpeg.martin-riedl.de -- FFmpeg is free software licensed under the
GPL, and the source is at https://ffmpeg.org/download.html. The script that
produced these binaries is at https://git.martin-riedl.de/ffmpeg/build-script
"""

#: Double-clickable, and the only thing in the .zip that a person touches. It
#: clears the quarantine flag from the folder before starting the agent, so
#: the ffmpeg binaries do not each need their own approval, and it holds the
#: window open at the end -- Terminal's default is to leave a finished window
#: showing, but that is a setting, and an agent that fails on startup must not
#: vanish along with the reason.
LAUNCHER = """#!/bin/sh
# Starts the ClipForge render agent. Right-click this file and choose Open
# the first time; double-click it after that.
cd "$(dirname "$0")" || exit 1

# Everything in a downloaded .zip is quarantined, including ffmpeg. One
# approval on this script is enough to clear the rest.
xattr -dr com.apple.quarantine . 2>/dev/null
chmod +x "./{binary}" "./ffmpeg/ffmpeg" "./ffmpeg/ffprobe" 2>/dev/null

"./{binary}" "$@"
status=$?

echo
printf 'The agent has stopped. Press Return to close this window. '
read -r _
exit $status
"""


def arch() -> str:
    """The chip this build is for, as the .zip name says it."""
    machine = platform.machine().lower()
    return "arm64" if machine in ("arm64", "aarch64") else "x86_64"


def zip_name() -> str:
    return f"ClipForgeAgent-macos-{arch()}.zip"


def _add(archive: zipfile.ZipFile, source: Path, name: str,
         executable: bool = False) -> None:
    """Write one file into the .zip, keeping the bit that lets it run.

    ZipFile.write copies the file's own mode, which is right on a Mac and
    wrong everywhere else, so the mode is set explicitly instead. Unpacking
    with Finder, unzip or Archive Utility all honour it.
    """
    info = zipfile.ZipInfo.from_file(source, name)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o755 if executable else 0o644) << 16
    with open(source, "rb") as handle:
        archive.writestr(info, handle.read())


def _add_text(archive: zipfile.ZipFile, name: str, text: str,
              executable: bool = False) -> None:
    info = zipfile.ZipInfo(name)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o755 if executable else 0o644) << 16
    # Zip stores no timestamp of its own for a string, and an entry dated 1980
    # makes Archive Utility complain. Today is closer to the truth anyway.
    info.date_time = time.localtime()[:6]
    archive.writestr(info, text)


def ffmpeg_pair() -> tuple[Path, Path]:
    """The ffmpeg to ship, fetching one if this machine has not got it yet."""
    folder = HERE / "ffmpeg"
    pair = (folder / "ffmpeg", folder / "ffprobe")
    if all(p.is_file() for p in pair):
        return pair

    # The agent does this on a subscriber's machine on its first run, so the
    # build is not doing anything unusual -- it is doing it early, and against
    # the same code, so a broken download shows up here rather than there.
    sys.path.insert(0, str(ROOT))
    from agent import ffmpeg as agent_ffmpeg

    print("No ffmpeg in agent/ffmpeg yet; fetching the one the agent would.")
    return agent_ffmpeg.download(HERE)


def bundle(binary: Path) -> int:
    """Zip the agent together with ffmpeg and the launcher, ready to publish."""
    try:
        ffmpeg, ffprobe = ffmpeg_pair()
    except Exception as error:  # noqa: BLE001 - the message is the useful part
        print(f"\nCould not get an ffmpeg to bundle: {error}")
        return 1

    archive = HERE / zip_name()
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        _add(z, binary, BINARY_NAME, executable=True)
        _add_text(z, LAUNCHER_NAME,
                  LAUNCHER.format(binary=BINARY_NAME), executable=True)
        _add_text(z, "READ ME FIRST.txt", READ_ME)
        _add(z, ffmpeg, "ffmpeg/ffmpeg", executable=True)
        _add(z, ffprobe, "ffmpeg/ffprobe", executable=True)

    size = archive.stat().st_size / 1_048_576
    print(f"\nBundled {archive}  ({size:.1f} MB)")
    print(f"\nThat is the {arch()} build. Macs sold since late 2020 are arm64;"
          "\nan Intel Mac needs the x86_64 one, built on an Intel Mac.")
    print("\nUpload it to a GitHub release and point AGENT_DOWNLOAD_URL_MAC "
          "at it.")
    return 0


def main() -> int:
    if sys.platform != "darwin":
        print("This builds the macOS agent, and it has to run on a Mac.\n"
              "PyInstaller freezes the interpreter it is running under, so\n"
              "there is no cross-compiling this from "
              f"{sys.platform}. On Windows, build the Windows one:\n"
              "    python agent/build_exe.py --clean --bundle")
        return 1

    if not SPEC.exists():
        print(f"Missing spec file: {SPEC}")
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Install it with:\n"
              "    pip3 install pyinstaller")
        return 1

    if "--clean" in sys.argv:
        for folder in ("build", "dist"):
            target = ROOT / folder
            if target.exists():
                print(f"Removing {target} ...")
                shutil.rmtree(target, ignore_errors=True)

    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)]
    print("Building:", " ".join(command))
    # Built from the repo root so "backend.app..." resolves the way it does
    # when the agent is run with -m.
    result = subprocess.run(command, cwd=str(ROOT))
    if result.returncode != 0:
        print("\nBuild failed.")
        return result.returncode

    built = ROOT / "dist" / BINARY_NAME
    if not built.exists():
        print("\nBuild reported success but the binary is missing.")
        return 1

    # The binary reads agent.env and uses footage/ and work/ from the folder it
    # sits in, so it is left beside them rather than in dist/. A stray copy in
    # dist/ would look for a config that is not there and report itself
    # unpaired.
    installed = HERE / BINARY_NAME
    try:
        shutil.copy2(built, installed)
        installed.chmod(0o755)
    except OSError as error:
        print(f"\nBuilt {built} but could not copy it to {HERE}: {error}")
        return 0

    # PyInstaller signs its output ad-hoc, which Apple silicon requires before
    # it will run a binary at all. Copying preserves that signature; saying so
    # here means a failure to sign is noticed at build time rather than by the
    # first subscriber to download it.
    signed = subprocess.run(["codesign", "--verify", "--verbose=1",
                             str(installed)], capture_output=True, text=True)
    if signed.returncode != 0:
        print("\nWarning: the binary is not signed, and Apple silicon will\n"
              "refuse to run it. Sign it by hand with:\n"
              f"    codesign -s - --force {installed}")

    shutil.rmtree(ROOT / "dist", ignore_errors=True)
    shutil.rmtree(ROOT / "build", ignore_errors=True)

    size = installed.stat().st_size / 1_048_576
    print(f"\nBuilt {installed}  ({size:.1f} MB, {arch()})")

    if "--bundle" in sys.argv:
        return bundle(installed)

    print(
        "\nHand someone this binary on its own and it works: on first run it "
        "fetches\nffmpeg into ffmpeg/ beside itself, then opens the browser "
        "to pair. They will\nhave to clear the quarantine flag themselves, "
        "though, which is what the .zip\nand its launcher exist to avoid:\n"
        "  python3 agent/build_mac.py --bundle"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
