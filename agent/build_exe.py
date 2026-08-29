"""
build_exe.py -- Produce agent/ClipForgeAgent.exe

    python agent/build_exe.py             build
    python agent/build_exe.py --clean     rebuild from scratch

One self-contained .exe so a subscriber does not need Python installed. ffmpeg
is deliberately left out: it is around 90MB, it is better installed and updated
by the user, and the agent checks for it on --check and explains how.

The .exe reads agent.env and uses footage/ and work/ from the folder it sits
in, so it is left beside them rather than in dist/. A stray copy in dist/ would
look for a config that is not there and report itself unpaired.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = HERE / "ClipForgeAgent.spec"
EXE_NAME = "ClipForgeAgent.exe"


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
    print(
        "\nTo hand this to someone, they need three things in one folder:\n"
        f"  {EXE_NAME}\n"
        "  agent.env      copied from agent.env.example, with their token\n"
        "  footage\\       their own clips\n"
        "\nThen: ClipForgeAgent.exe --check\n"
        "ffmpeg must be on PATH. winget install Gyan.FFmpeg"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
