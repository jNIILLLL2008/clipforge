"""
make_env.py -- Turn your local .env into variables for a hosting platform.

    .venv\\Scripts\\python.exe make_env.py

Writes railway-env.txt, which you paste into Railway's Variables > Raw Editor
(or Render's "Add from .env"). It is gitignored and holds live secrets, so do
not commit or share it.

It does three things the copy-paste route gets wrong:

* rewrites the settings that only make sense on your laptop -- the Windows
  ffmpeg paths above all, which do not exist in a Linux container;
* forces the production values the app refuses to boot without;
* drops anything the platform provides itself, like PORT.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / ".env"
TARGET = ROOT / "railway-env.txt"

if not SOURCE.exists():
    sys.exit("No .env found. Copy .env.example to .env and fill it in first.")

APP_URL = "https://REPLACE-ME.up.railway.app"

# Values that must change for a container, whatever the local file says.
OVERRIDE = {
    "ENV": "production",
    "DEBUG": "false",
    "SECRET_KEY": secrets.token_urlsafe(32),
    "PUBLIC_URL": APP_URL,
    "GOOGLE_REDIRECT_URI": f"{APP_URL}/api/youtube/callback",
    # Railway fills this in from the Postgres service.
    "DATABASE_URL": "${{Postgres.DATABASE_URL}}",
    "STORAGE_DIR": "/app/storage",
    # The image puts ffmpeg on PATH; a C:\ path would fail instantly.
    "FFMPEG_BINARY": "ffmpeg",
    "FFPROBE_BINARY": "ffprobe",
    # One instance owns the daily scheduler. See the README before scaling out.
    "RUN_SCHEDULER": "true",
}

# Never carry these across: the platform sets them, or they are meaningless
# off your machine.
DROP = {"PORT", "HOST", "YTDLP_COOKIES_FILE"}

existing: dict[str, str] = {}
# utf-8-sig strips a byte-order mark. Windows editors add one, and without this
# the first key parses as "﻿ENV" -- an invisible duplicate that the app
# would never read but the platform would happily store.
for line in SOURCE.read_text(encoding="utf-8-sig").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    if key and key not in DROP:
        existing[key] = value.strip()

merged = {**existing, **OVERRIDE}

lines = [
    "# Paste into Railway: service > Variables > Raw Editor.",
    f"# Replace {APP_URL} with your real Railway domain in BOTH",
    "# PUBLIC_URL and GOOGLE_REDIRECT_URI once you know it.",
    "",
]
lines += [f"{key}={value}" for key, value in sorted(merged.items())]
TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8")

# Report without printing the secrets themselves.
SECRETISH = ("KEY", "SECRET", "TOKEN", "PASSWORD")
print(f"\nWrote {TARGET.name} -- {len(merged)} variables\n")
for key, value in sorted(merged.items()):
    if any(word in key.upper() for word in SECRETISH) and value:
        shown = f"({len(value)} chars, hidden)"
    else:
        shown = value or "(empty)"
    marker = "*" if key in OVERRIDE else " "
    print(f"  {marker} {key:26} {shown[:52]}")

print("\n  * = changed for production")
print(f"\nOpen it with:  notepad {TARGET.name}")
print("Then edit the two REPLACE-ME URLs once Railway gives you a domain.")
print("\nThis file contains live secrets. It is gitignored; keep it that way.")
