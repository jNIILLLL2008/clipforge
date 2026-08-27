"""
selftest.py -- End-to-end check with no network, keys or Google account.

Runs the real app through FastAPI's TestClient: create an account, change
settings, upload footage, press the button, and wait for the worker. Synthetic
clips stand in for real footage so this needs nothing but ffmpeg.

    .venv\\Scripts\\python.exe selftest.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

FAILURES: list = []


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "ok  " if condition else "FAIL"
    suffix = f" -- {detail}" if detail != "" else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n== {title} ==")


TMP = Path(tempfile.mkdtemp(prefix="clipforge-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(TMP / 'test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(TMP / "storage")
os.environ["ENABLED_SOURCES"] = "upload"
os.environ["RENDER_WORKERS"] = "1"
os.environ["SECRET_KEY"] = "test-key-not-used-anywhere-real"
# Never inherit the deployment's real Stripe or Google credentials: the suite
# must behave the same on a machine that has them and one that does not, and it
# must never be able to touch a real payment account.
for leaked in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
               "STRIPE_PRICE_STARTER", "STRIPE_PRICE_PRO",
               "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
    os.environ[leaked] = ""

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.config import settings  # noqa: E402
from backend.app.db import init_db, session_scope  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.models import Plan, User  # noqa: E402
from backend.app.render.retention import PlannedClip, score_plan  # noqa: E402
from backend.app.render.selection import matches_show, passes_filters  # noqa: E402
from backend.app.settings_schema import BY_KEY, defaults, sanitise, schema  # noqa: E402
from backend.app.sources.base import SourceClip  # noqa: E402
from backend.app.worker import start_workers  # noqa: E402

init_db()
start_workers()

# --------------------------------------------------------------------------- #
section("retention gate")
FAST = {"hook_seconds": 2.0, "max_shot_seconds": 12.0, "captions_enabled": True,
        "checklist_enabled": True, "countdown": True, "target_seconds": 100}
good = [PlannedClip(duration=12, has_captions=True, hook_at=0.0) for _ in range(6)]
report = score_plan(good, FAST)
check("a well-formed plan passes", report.verdict == "pass", report.score)
slow = score_plan([PlannedClip(duration=60, has_captions=True, hook_at=0.0)] * 2, FAST)
check("a long static shot is punished", slow.score < 80, slow.score)
check("and it says why", any("unbroken" in r for r in slow.reasons))
late = [PlannedClip(duration=12, has_captions=True, hook_at=9.0)] + good[1:]
check("a slow hook is punished", score_plan(late, FAST).score < report.score)
check("empty plan is rejected", score_plan([], FAST).verdict == "reject")

# On-screen text: captions are best, but a list or banner also reads muted.
silent = [PlannedClip(duration=12, has_captions=False, hook_at=0.0) for _ in range(6)]
with_list = score_plan(silent, {**FAST, "checklist_enabled": True})
no_text = score_plan(silent, {**FAST, "checklist_enabled": False,
                              "banner_enabled": False, "countdown": True})
check("a numbered list counts as readable muted", with_list.score > no_text.score,
      f"{with_list.score} vs {no_text.score}")
check("no text at all is called out",
      any("read" in r or "text" in r for r in no_text.reasons), no_text.reasons[:1])
check("captions still score highest",
      score_plan(good, FAST).score >= with_list.score)

section("captions")
from backend.app.render.overlay import chunk as chunk_caption  # noqa: E402
from backend.app.render.overlay import parse_vtt  # noqa: E402

vtt = TMP / "sample.en.vtt"
vtt.write_text(
    "WEBVTT\nKind: captions\n\n"
    "00:00:01.000 --> 00:00:03.000\nhe said\n\n"
    "00:00:03.000 --> 00:00:05.000\nhe said what exactly\n\n"
    "00:00:06.000 --> 00:00:09.000\n<c>a much longer line that needs chunking</c>\n",
    encoding="utf-8")
cues = parse_vtt(vtt)
check("cues parsed", len(cues) >= 2, len(cues))
check("markup stripped", all("<" not in c.text for c in cues))
check("rolling repeat collapsed",
      cues[1].text == "what exactly" if len(cues) > 1 else False,
      cues[1].text if len(cues) > 1 else "")
check("long cue is chunked",
      len(chunk_caption(cues[-1], 3)) > 1, len(chunk_caption(cues[-1], 3)))
check("chunks stay inside the original span",
      all(p.start >= cues[-1].start - .01 and p.end <= cues[-1].end + .01
          for p in chunk_caption(cues[-1], 3)))
check("a missing file is not fatal", parse_vtt(TMP / "nope.vtt") == [])

# --------------------------------------------------------------------------- #
section("settings schema")
cat = schema()
check("schema is grouped", len(cat["groups"]) >= 11, len(cat["groups"]))
count = sum(len(g["fields"]) for g in cat["groups"])
check("exposes the full option set", count >= 60, count)
check("defaults cover every field", set(defaults()) == set(BY_KEY))
check("upload settings present",
      {"auto_upload", "privacy_status", "category_id", "publish_delay_minutes"}
      <= set(BY_KEY))
check("out-of-range clamped", sanitise({"clips": 999})["clips"] == 12)
check("unknown keys dropped", "nonsense" not in sanitise({"nonsense": 1}))
check("comma lists parsed",
      sanitise({"show_terms": "cbs, golazo"})["show_terms"] == ["cbs", "golazo"])
check("bad select falls back", sanitise({"background": "sideways"})["background"] == "pad")
check("min above max corrected",
      sanitise({"min_clip_seconds": 90, "max_clip_seconds": 10})["min_clip_seconds"] == 10)

# --------------------------------------------------------------------------- #
section("show filter")


def clip(title="t", author="", duration=30.0, views=None, desc=""):
    c = SourceClip(source="s", external_id="1", title=title, url="",
                   author=author, duration=duration)
    c.extra = {"view_count": views, "description": desc}
    return c


gate = sanitise({"require_show_match": True, "show_terms": ["cbs", "golazo"],
                 "show_people": ["micah richards|micah|richards",
                                 "jamie carragher|carragher|carra",
                                 "thierry henry|thierry|henry"]})
check("show keyword passes", matches_show(clip("Funny bit on CBS"), gate)[0])
check("two regulars pass", matches_show(clip("Micah and Carragher argue"), gate)[0])
check("one regular is not enough", not matches_show(clip("Micah highlights"), gate)[0])
check("one person's aliases never count as two",
      not matches_show(clip("THIERRY HENRY EVOLUTION 1994-2026"), gate)[0])
check("gate off lets everything through",
      matches_show(clip("random"), {**gate, "require_show_match": False})[0])

filters = sanitise({"min_duration_seconds": 10, "max_duration_seconds": 120,
                    "min_view_count": 1000, "blocked_uploaders": ["Spam Co"]})
check("too short dropped", not passes_filters(clip(duration=4), filters)[0])
check("too few views dropped", not passes_filters(clip(views=10), filters)[0])
check("blocked channel dropped", not passes_filters(clip(author="Spam Co"), filters)[0])
check("unknown views not penalised", passes_filters(clip(views=None), filters)[0])

# --------------------------------------------------------------------------- #
section("accounts")
client = TestClient(app)
check("health responds", client.get("/api/health").json().get("ok") is True)
check("weak password refused",
      client.post("/api/auth/signup",
                  json={"email": "a@b.com", "password": "short"}).status_code == 400)

signup = client.post("/api/auth/signup",
                     json={"email": "Tester@Example.com", "password": "correct-horse-1"})
check("signup works", signup.status_code == 200, signup.status_code)
check("starts on free", signup.json()["user"]["plan"] == "free")
check("duplicate refused",
      client.post("/api/auth/signup",
                  json={"email": "tester@example.com",
                        "password": "correct-horse-1"}).status_code == 400)
check("anonymous rejected", TestClient(app).get("/api/studio").status_code == 401)

# --------------------------------------------------------------------------- #
section("studio: the home screen")
studio = client.get("/api/studio").json()
check("has status rows", len(studio["status"]) >= 3, len(studio["status"]))
check("youtube reported as unconfigured",
      any(r["id"] == "youtube" and r["state"] == "off" for r in studio["status"]))
check("new account is configured to run", studio["overview"]["clips_per_run"] > 0)
check("visibility defaults to private",
      studio["overview"]["visibility"] == "private",
      studio["overview"]["visibility"])
check("automation off by default", studio["automation"]["enabled"] is False)
check("automation not allowed on free", studio["automation"]["allowed"] is False)

blocked = client.put("/api/studio/automation",
                     json={"enabled": True, "time": "09:00", "timezone": ""})
check("free plan cannot enable automation", blocked.status_code == 402,
      blocked.status_code)

# --------------------------------------------------------------------------- #
section("billing surface")
plans_payload = client.get("/api/plans").json()
tiers = {p["id"]: p for p in plans_payload["plans"]}
check("all three plans listed", set(tiers) == {"free", "starter", "pro"}, set(tiers))
check("billing reported off without keys",
      plans_payload["billing_enabled"] is False)
check("nothing is purchasable without Stripe",
      not any(p["purchasable"] for p in plans_payload["plans"]))
check("and the reason is stated", bool(plans_payload["billing_note"]),
      plans_payload["billing_note"][:50])
check("prices come from the configured labels",
      tiers["starter"]["price"] == settings.price_label_starter,
      tiers["starter"]["price"])
check("checkout refuses when unconfigured",
      client.post("/api/billing/checkout?plan=starter").status_code == 503)
check("portal refuses when unconfigured",
      client.post("/api/billing/portal").status_code == 503)
check("webhook cannot be spoofed",
      client.post("/api/billing/webhook", json={"type": "x"}).status_code
      in (400, 503))

section("first-run tour")
check("a new account has not seen it",
      client.get("/api/studio").json()["onboarded"] is False)
check("marking it seen sticks",
      client.post("/api/studio/onboarded?seen=true").json()["onboarded"] is True)
check("and it stays seen", client.get("/api/studio").json()["onboarded"] is True)
check("it can be replayed",
      client.post("/api/studio/onboarded?seen=false").json()["onboarded"] is False)
client.post("/api/studio/onboarded?seen=true")

section("database url from a hosting platform")
from backend.app.config import _normalise_db_url  # noqa: E402

check("Railway/Render postgresql:// gets a driver",
      _normalise_db_url("postgresql://u:p@h:5432/d")
      == "postgresql+psycopg://u:p@h:5432/d")
check("Heroku postgres:// is upgraded too",
      _normalise_db_url("postgres://u:p@h/d") == "postgresql+psycopg://u:p@h/d")
check("an explicit driver is left alone",
      _normalise_db_url("postgresql+psycopg://u:p@h/d")
      == "postgresql+psycopg://u:p@h/d")
check("sqlite is untouched",
      _normalise_db_url("sqlite:///x.db") == "sqlite:///x.db")
check("empty stays empty", _normalise_db_url("") == "")
check("whitespace is trimmed",
      _normalise_db_url("  postgresql://u@h/d  ") == "postgresql+psycopg://u@h/d")

section("schema upgrades on an existing database")
from sqlalchemy import inspect as _inspect, text as _text  # noqa: E402

from backend.app.db import _add_missing_columns, engine  # noqa: E402

# Drop a column the way an older install would not have it, then confirm
# startup puts it back rather than raising "no such column" on every query.
with engine.begin() as conn:
    conn.execute(_text("ALTER TABLE users DROP COLUMN onboarded"))
gone = {c["name"] for c in _inspect(engine).get_columns("users")}
check("column really removed", "onboarded" not in gone)
_add_missing_columns()
back = {c["name"] for c in _inspect(engine).get_columns("users")}
check("startup adds it back", "onboarded" in back)
check("the app works again", client.get("/api/studio").status_code == 200)
check("running it twice changes nothing", _add_missing_columns() is None)

section("studio: settings round-trip")
got = client.get("/api/studio/settings").json()
check("settings and schema returned",
      "settings" in got and "schema" in got)
check("settings are complete", set(got["settings"]) == set(BY_KEY))

saved = client.put("/api/studio/settings", json={"settings": {
    "banner_line1": "TOP {count} FROM",
    "banner_line2": "MY SHOW",
    "banner_accent_colour": "#00FF88",
    "clips": 4,
    "target_seconds": 40,
    "clip_trim_strategy": "start",
    "countdown_overlay": True,
    "countdown_position": "top-right",
    "privacy_status": "unlisted",
    "sources": ["upload"],
    "nonsense_key": "vanish",
}})
check("settings saved", saved.status_code == 200, saved.text[:100])
kept = saved.json()["settings"]
check("text kept", kept["banner_line2"] == "MY SHOW")
check("colour kept", kept["banner_accent_colour"] == "#00FF88")
check("select kept", kept["clip_trim_strategy"] == "start")
check("visibility kept", kept["privacy_status"] == "unlisted")
check("unknown key rejected", "nonsense_key" not in kept)
check("plan ceiling applied to clips", kept["clips"] <= 5, kept["clips"])

presets = client.get("/api/presets").json()["presets"]
check("presets listed", len(presets) >= 6, len(presets))
memes = next(p for p in presets if p["slug"] == "memes")
applied = client.post(f"/api/presets/{memes['id']}/apply")
check("preset applied", applied.status_code == 200)
after = applied.json()["settings"]
check("preset changed the format", after["max_clip_seconds"] <= 7,
      after["max_clip_seconds"])
check("preset kept the user's visibility", after["privacy_status"] == "unlisted",
      after["privacy_status"])

# Put a workable config back for the render below. search_terms must be cleared:
# the upload source filters by filename, and the memes preset left "meme" and
# "reaction" behind, which the test clips do not match.
client.put("/api/studio/settings", json={"settings": {
    "clips": 4, "target_seconds": 40, "sources": ["upload"],
    "search_terms": [], "exclude_terms": [], "require_show_match": False,
    "min_clip_seconds": 5, "max_clip_seconds": 12, "max_shot_seconds": 20,
    "checklist_enabled": True, "countdown": True, "auto_upload": True,
}})
restored = client.get("/api/studio/settings").json()["settings"]
check("search terms cleared for the render", restored["search_terms"] == [])

# --------------------------------------------------------------------------- #
section("footage")
check("non-video refused",
      client.post("/api/uploads",
                  files={"file": ("notes.txt", b"x", "text/plain")}).status_code == 400)


def make_clip(path: Path, colour: str, seconds: int = 8) -> None:
    subprocess.run(
        [settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c={colour}:s=640x360:d={seconds}:r=30",
         "-f", "lavfi", "-i", f"sine=frequency=320:duration={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(path)],
        check=True, capture_output=True, timeout=180)


work = TMP / "clips"
work.mkdir(parents=True, exist_ok=True)
for index, colour in enumerate(("red", "green", "blue", "orange")):
    made = work / f"clip{index}.mp4"
    make_clip(made, colour)
    with made.open("rb") as handle:
        client.post("/api/uploads", files={"file": (made.name, handle, "video/mp4")})
check("uploads listed", len(client.get("/api/uploads").json()["uploads"]) == 4)

# --------------------------------------------------------------------------- #
section("the one button")
run = client.post("/api/studio/run", json={"dry_run": False})
check("run queued", run.status_code == 200, run.text[:120])
job_id = run.json()["id"]

check("a second run is refused while busy",
      client.post("/api/studio/run", json={"dry_run": False}).status_code == 409)

deadline = time.time() + 300
final = {}
while time.time() < deadline:
    final = client.get(f"/api/jobs/{job_id}").json()
    if final["status"] in {"done", "failed", "rejected"}:
        break
    time.sleep(1.5)

check("run finished", final.get("status") == "done",
      f"{final.get('status')}: {final.get('error', '')[:120]}")
if final.get("status") == "done":
    check("scored for retention", final["retention_score"] > 0, final["retention_score"])
    check("clips recorded with licences",
          all(c["licence"] for c in final.get("clips", [])),
          [c["licence"] for c in final.get("clips", [])][:2])
    check("a title was written", bool(final["title"]), final["title"])
    check("tags were written", len(final.get("tags", [])) > 0, len(final.get("tags", [])))
    # No Google credentials in a test, so publishing must be skipped cleanly
    # rather than failing the run.
    check("upload skipped without a channel", final["upload_state"] == "skipped",
          final["upload_state"])
    download = client.get(f"/api/jobs/{job_id}/download")
    check("downloads as mp4", download.status_code == 200
          and download.headers["content-type"] == "video/mp4")
    delivered = TMP / "delivered.mp4"
    delivered.write_bytes(download.content)
    probe = subprocess.run(
        [settings.ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(delivered)],
        capture_output=True, text=True, timeout=60).stdout.strip()
    check("rendered vertical 1080x1920", probe.startswith("1080,1920"), probe)

home = client.get("/api/studio").json()
check("home counts the render", home["overview"]["rendered"] >= 1)
check("home shows nothing published", home["overview"]["published"] == 0)

# --------------------------------------------------------------------------- #
section("allowance")
me = client.get("/api/me").json()
check("the run was counted", me["renders_used"] == 1, me["renders_used"])

# Spend whatever is left, then confirm the next request is refused outright.
for _ in range(me["renders_left"]):
    client.post("/api/jobs", json={"clips": 2, "format": {"target_seconds": 20}})
spent = client.get("/api/me").json()
check("allowance reads as spent", spent["renders_left"] == 0, spent["renders_left"])
blocked = client.post("/api/studio/run", json={"dry_run": False})
check("over quota is refused", blocked.status_code in (402, 409),
      f"{blocked.status_code}: {blocked.json().get('detail','')[:60]}")

# --------------------------------------------------------------------------- #
section("daily automation")
with session_scope() as db:
    db.query(User).filter(User.email == "tester@example.com").one().plan = Plan.PRO

allowed = client.put("/api/studio/automation",
                     json={"enabled": True, "time": "07:30", "timezone": "UTC"})
check("paid plan can enable it", allowed.status_code == 200, allowed.text[:90])
check("time stored", allowed.json()["time"] == "07:30")
check("bad time refused",
      client.put("/api/studio/automation",
                 json={"enabled": True, "time": "25:99"}).status_code == 400)

from backend.app.scheduler import due  # noqa: E402


class FakeUser:
    def __init__(self, **kw):
        self.automate_daily = True
        self.automate_time = "09:00"
        self.automate_timezone = "UTC"
        self.automate_last_run = None
        self.plan = Plan.PRO
        self.__dict__.update(kw)


midday = datetime(2026, 5, 5, 9, 30, tzinfo=timezone.utc)
check("fires once the time has passed", due(FakeUser(), midday))
check("does not fire before the time",
      not due(FakeUser(), datetime(2026, 5, 5, 8, 59, tzinfo=timezone.utc)))
check("does not fire twice in a day",
      not due(FakeUser(automate_last_run=midday - timedelta(minutes=10)), midday))
check("fires again the next day",
      due(FakeUser(automate_last_run=midday - timedelta(days=1)), midday))
check("does not fire for a long-missed window",
      not due(FakeUser(), datetime(2026, 5, 5, 20, 0, tzinfo=timezone.utc)))
check("off means off", not due(FakeUser(automate_daily=False), midday))
check("free plan never fires", not due(FakeUser(plan=Plan.FREE), midday))

# --------------------------------------------------------------------------- #
section("youtube is optional but wired")
from backend.app import youtube  # noqa: E402

check("reports itself unconfigured", youtube.configured() is False)
connect = client.get("/api/youtube/connect")
check("connect refuses without a client", connect.status_code == 503,
      connect.status_code)
check("callback handles a stale link",
      client.get("/api/youtube/callback?code=x&state=bogus").status_code == 200)
check("disconnect always works",
      client.post("/api/youtube/disconnect").json()["connected"] is False)

# --------------------------------------------------------------------------- #
section("isolation")
other = TestClient(app)
other.post("/api/auth/signup",
           json={"email": "someone@else.com", "password": "another-pass-9"})
check("cannot read another user's job",
      other.get(f"/api/jobs/{job_id}").status_code == 404)
check("cannot download it",
      other.get(f"/api/jobs/{job_id}/download").status_code == 404)
check("sees none of their uploads", other.get("/api/uploads").json()["uploads"] == [])
check("has their own settings",
      other.get("/api/studio/settings").json()["settings"]["clips"] != 4)

# --------------------------------------------------------------------------- #
section("the youtube source")
from backend.app import sources as registry  # noqa: E402
from backend.app.sources.youtube_source import YouTubeSource  # noqa: E402

yt = YouTubeSource({})
# This section defines its own opt-in state rather than inheriting whatever
# the deployment's .env happens to say, or "blocked by default" would pass or
# fail depending on the machine it runs on.
settings.allow_unlicensed_sources = False

check("declares itself not reusable", yt.reusable is False)
check("says so in its licence line", "not licensed" in yt.licence_summary.lower())
check("is blocked by default", registry._permitted(yt) is False)
check("never handed to a job by default",
      registry.for_job(["youtube"], 1, {}) == [])

# The URLs it would scan, without touching the network.
built = YouTubeSource({
    "source_channels": ["@somechannel"],
    "channel_tabs": ["videos", "shorts"],
    "channel_search_terms": ["funny moments"],
}).build_sources(["premier league", "football banter"])
check("searches the channel archive first", "/search?query=" in built[0], built[0])
check("then the channel tabs", any(u.endswith("/videos") for u in built))
check("hashtag tabs are slugified",
      any(u.endswith("/hashtag/premierleague/shorts") for u in built),
      [u for u in built if "hashtag" in u][:1])
check("no channels and no terms means no work",
      YouTubeSource({}).build_sources([]) == [])

# Even switched on, the per-clip licence check must still refuse its output.
settings.enabled_sources = list(settings.enabled_sources) + ["youtube"]
settings.allow_unlicensed_sources = False
check("enabling it is not enough on its own",
      registry.for_job(["youtube"], 1, {}) == [])
settings.allow_unlicensed_sources = True
opted_in = registry.for_job(["youtube"], 1, {"source_channels": ["@x"]})
check("an explicit opt-in enables it", len(opted_in) == 1, len(opted_in))
check("and it carries the job's settings",
      opted_in and opted_in[0].config.get("source_channels") == ["@x"])
settings.allow_unlicensed_sources = False

section("licence gate")


class Risky:
    name, label = "risky", "Risky source"
    licence_summary, reusable, needs_key = "unlicensed", False, False

    def available(self) -> bool:
        return True


settings.allow_unlicensed_sources = False
check("unlicensed adapter blocked", registry._permitted(Risky()) is False)
settings.allow_unlicensed_sources = True
check("only an explicit opt-in allows it", registry._permitted(Risky()) is True)
settings.allow_unlicensed_sources = False

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + "=" * 60)
print(f"FAILURES: {len(FAILURES)}" + ("" if not FAILURES else " -> " + "; ".join(FAILURES)))
sys.exit(1 if FAILURES else 0)
