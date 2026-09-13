"""
guide_payloads.py -- The API responses the setup guide's captures are made from.

Run by capture_guide.mjs, not by hand:

    .venv/Scripts/python promo/tools/guide_payloads.py OUT.json

Boots the real backend in-process against a throwaway SQLite database, as
selftest.py does, signs up a throwaway account, sets it up the way a new
subscriber's Studio looks before they have done anything, and records what the
app's own endpoints answer. That includes two preview frames from the real
pipeline, before and after the banner's second line changes.

capture_guide.mjs then serves these to the real frontend, so every screen in
the guide is the app's own markup and styles with neutral data in it: no
person's name, no computer's name, no channel.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="clipforge-guide-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{(TMP / 'guide.db').as_posix()}",
    "STORAGE_DIR": str(TMP / "storage"),
    # YouTube is listed on the live site's Footage row, so it is here too.
    "ENABLED_SOURCES": "upload,youtube",
    "ALLOW_UNLICENSED_SOURCES": "true",
    "RENDER_WORKERS": "1",
    "RUN_SCHEDULER": "false",
    "RATE_LIMIT_ENABLED": "false",
    "SECRET_KEY": "guide-capture-only",
    # Only read to decide whether the AI metadata row says Ready. Nothing in
    # this script calls the model.
    "ANTHROPIC_API_KEY": "guide-capture-not-a-key",
    "AGENT_DOWNLOAD_URL": "https://clipforgee.app/download/agent",
})
# Never inherit real payment or Google credentials, whatever this machine has.
for leaked in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
               "STRIPE_PRICE_STARTER", "STRIPE_PRICE_PRO",
               "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
    os.environ[leaked] = ""

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.db import session_scope  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.models import Plan, User  # noqa: E402

EMAIL = "you@example.com"

# A fresh Studio, before setup. The banner and the switches are what the live
# site shows at this point; everything the guide has somebody type is empty,
# which is also what makes the preview list what is missing.
BEFORE = {
    "description": "",
    "search_terms": [],
    "sources": ["youtube", "upload"],
    "source_playlists": [],
    "source_channels": [],
    "require_show_match": True,
    "show_name": "",
    "show_terms": [],
    "show_people": [],
    "banner_line1": "TOP {count} FROM",
    "banner_line2": "YOUR SHOW",
    "clips": 5,
    "target_seconds": 120,
    "moment_audio_scan": True,
    "ai_moment_ranking": True,
    "auto_upload": True,
    "privacy_status": "private",
}


def main(out_path: str) -> None:
    with TestClient(app) as client:
        signup = client.post("/api/auth/signup",
                             json={"email": EMAIL, "password": "guide-capture-pass-7"})
        signup.raise_for_status()
        with session_scope() as db:
            user = db.query(User).filter(User.email == EMAIL).one()
            user.plan = Plan.STARTER
            user.onboarded = True  # no setup wizard over the screenshots

        saved = client.put("/api/studio/settings", json={"settings": BEFORE})
        saved.raise_for_status()
        settings = saved.json()["settings"]

        def preview(cfg):
            response = client.post("/api/studio/preview",
                                   json={"settings": cfg, "at_clip": 2})
            response.raise_for_status()
            return base64.b64encode(response.content).decode("ascii")

        studio = client.get("/api/studio").json()

        # Connected and ready, as it is at the end of the guide. The channel
        # is a placeholder, never a real one.
        ready = json.loads(json.dumps(studio))
        ready["ready"] = True
        ready["blocked_by"] = []
        ready["youtube"] = {"configured": True, "connected": True, "channel": "Your channel"}
        for row in ready["status"]:
            if row["id"] == "youtube":
                row.clear()
                row.update({"id": "youtube", "label": "YouTube account",
                            "detail": "Your channel", "state": "ready"})

        payloads = {
            "me": client.get("/api/me").json(),
            "studio_setup": studio,
            "studio_ready": ready,
            "settings": client.get("/api/studio/settings").json(),
            "review": client.post("/api/studio/review",
                                  json={"settings": settings}).json(),
            "agent": client.get("/api/agent/status").json(),
            "preview_before": preview(settings),
            "preview_after": preview({**settings, "banner_line2": "FORMULA 1"}),
        }

    Path(out_path).write_text(json.dumps(payloads), encoding="utf-8")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
