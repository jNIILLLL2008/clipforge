"""
build_exe.py -- Produce agent/ClipForgeAgent.exe, and the .zip around it.

    python agent/build_exe.py                build the .exe
    python agent/build_exe.py --clean        rebuild from scratch
    python agent/build_exe.py --bundle       .exe + ffmpeg, in one .zip

One self-contained .exe so a subscriber does not need Python installed.

ffmpeg stays *beside* the .exe rather than inside it. Two static binaries are
about 200MB, and PyInstaller's onefile mode unpacks its whole payload into a
temporary directory on every launch: burying them would mean writing 200MB to
disk each time a long-running background agent starts. --bundle puts them in
the same .zip instead, which gets a subscriber the same one-download install
without that cost. Without --bundle the .exe still works: it fetches ffmpeg
into ffmpeg/ on first run.

The .exe reads agent.env and uses footage/ and work/ from the folder it sits
in, so it is left beside them rather than in dist/. A stray copy in dist/ would
look for a config that is not there and report itself unpaired.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = HERE / "ClipForgeAgent.spec"
EXE_NAME = "ClipForgeAgent.exe"
ZIP_NAME = "ClipForgeAgent-windows.zip"

#: What the .zip tells someone to do. Three lines, because it is three steps.
READ_ME = """ClipForge render agent
======================

1. Keep these files together in this folder.
2. Double-click ClipForgeAgent.exe
3. Your browser opens. Sign in if you need to, check the code matches the one
   in the agent's window, and click "Pair it".

That is the whole install. There is no token to copy and no file to edit.

The agent then waits for work. Leave it running, or close it and start it
again whenever you want it to render.

Put your own clips in a folder called "footage" beside the .exe if you use the
upload source. You do not need to for YouTube sourcing.

ffmpeg
------
ffmpeg.exe and ffprobe.exe in ffmpeg\\ are unmodified builds from
https://www.gyan.dev/ffmpeg/builds/ -- FFmpeg is free software licensed under
the GPL v2 or later, and its licence is in ffmpeg\\LICENSE. Source for this
build is available from https://ffmpeg.org/download.html and
https://github.com/GyanD/codexffmpeg
"""


def bundle(exe: Path) -> int:
    """Zip the .exe together with ffmpeg, ready to publish."""
    ffmpeg_dir = HERE / "ffmpeg"
    needed = [ffmpeg_dir / "ffmpeg.exe", ffmpeg_dir / "ffprobe.exe"]
    missing = [p for p in needed if not p.is_file()]
    if missing:
        print("\nffmpeg is not unpacked yet, so there is nothing to bundle.")
        print("Run the agent once and let it fetch ffmpeg, or:")
        print("  python -c \"import pathlib, agent.ffmpeg as f; "
              "f.download(pathlib.Path('agent'))\"")
        return 1

    archive = HERE / ZIP_NAME
    archive.unlink(missing_ok=True)
    # Deflate, not store: the two binaries compress to roughly half, and this
    # is a file every subscriber downloads once.
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(exe, EXE_NAME)
        z.writestr("READ ME FIRST.txt", READ_ME)
        for name in ("ffmpeg.exe", "ffprobe.exe", "LICENSE", "README.txt"):
            source = ffmpeg_dir / name
            if source.is_file():
                z.write(source, f"ffmpeg/{name}")

    size = archive.stat().st_size / 1_048_576
    print(f"\nBundled {archive}  ({size:.1f} MB)")
    print("\nUpload that to a GitHub release and point AGENT_DOWNLOAD_URL at "
          "it.\nThe subscriber unzips it, runs the .exe, and clicks one "
          "button.")
    return 0


def main() -> int:
    if not SPEC.exists():
        print(f"Missing spec file: {SPEC}")
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Install it with:\n"
              "    pip install pyinstaller")
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

    built = ROOT / "dist" / EXE_NAME
    if not built.exists():
        print("\nBuild reported success but the .exe is missing.")
        return 1

    installed = HERE / EXE_NAME
    try:
        shutil.copy2(built, installed)
    except OSError as error:
        print(f"\nBuilt {built} but could not copy it to {HERE}: {error}")
        return 0

    shutil.rmtree(ROOT / "dist", ignore_errors=True)
    shutil.rmtree(ROOT / "build", ignore_errors=True)

    size = installed.stat().st_size / 1_048_576
    print(f"\nBuilt {installed}  ({size:.1f} MB)")

    if "--bundle" in sys.argv:
        return bundle(installed)

    print(
        "\nHand someone this .exe on its own and it works: on first run it "
        "fetches\nffmpeg into ffmpeg/ beside itself, then opens the browser "
        "to pair.\n\nTo save them that download, ship the .zip instead:\n"
        "  python agent/build_exe.py --bundle"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
