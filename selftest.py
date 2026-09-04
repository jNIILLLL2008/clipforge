"""
selftest.py -- End-to-end check with no network, keys or Google account.

Runs the real app through FastAPI's TestClient: create an account, change
settings, upload footage, press the button, and wait for the worker. Synthetic
clips stand in for real footage so this needs nothing but ffmpeg.

    .venv\\Scripts\\python.exe selftest.py
"""

from __future__ import annotations

import os
import re
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
    line = f"  [{mark}] {label}{suffix}"
    try:
        print(line)
    except UnicodeEncodeError:
        # A Windows console is cp1252 by default, and one music note in a
        # caption test used to end the entire run with a traceback. The
        # result of the check is what matters, not the glyph.
        encoding = sys.stdout.encoding or "ascii"
        print(line.encode(encoding, "replace").decode(encoding))
    if not condition:
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n== {title} ==")


TMP = Path(tempfile.mkdtemp(prefix="clipforge-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(TMP / 'test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(TMP / "storage")
os.environ["ENABLED_SOURCES"] = "upload"
os.environ["RENDER_WORKERS"] = "1"
# The suite signs up several accounts in a few seconds, which is precisely
# what the signup limit is meant to refuse. The limiter is tested directly
# in the security section rather than through the whole suite.
os.environ["RATE_LIMIT_ENABLED"] = "false"
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
section("the numbered list")
# The list was clip.title[:34]: the uploader's title, hard-truncated. A real
# render read "The Spectacular Spider-Man (2008-2" and "Origin 2 | Marvel's
# Spider-Man | D". Every case below is from that video.
from backend.app.render import labels as _labels  # noqa: E402


class _T:
    def __init__(self, title):
        self.title = title


_REAL = [
    "Real power loading \U0001F512 \u00b7The Spectacular Spider-Man",
    "Flash Confronts Peter \U0001F621| The Spectacular Spider-Man",
    "The Spectacular Spider-Man (2008-2009) - Peter meets Gwen",
    "How Did I Ever Live Without You? | The Spectacular Spider-Man",
    "Origin 2 | Marvel's Spider-Man | Disney XD",
]
_WANT = [
    "Real power loading",
    "Flash Confronts Peter",
    "Peter meets Gwen",
    "How Did I Ever Live Without You?",
    "Origin 2",
]
_got = _labels.for_clips([_T(t) for t in _REAL],
                         {"show_terms": ["spectacular spider-man"]})
for _g, _w in zip(_got, _WANT):
    check(f"label: {_w}", _g == _w, _g)

# The channel name is identifiable without any configuration at all, because
# it is the segment that appears on every clip and a moment never does.
_blind = _labels.for_clips([_T(t) for t in _REAL], {})
check("boilerplate is found with no show_terms set", _blind == _WANT, _blind)

check("emoji are gone",
      not any(ord(c) > 0x2500 for label in _got for c in label), _got)
check("no dangling separator",
      not any(label.rstrip().endswith(("|", "-", "\u00b7", ":")) for label in _got))
check("nothing is cut mid-word",
      all(label == label.strip() and "  " not in label for label in _got))

check("a shouted title is calmed down",
      _labels.clean("PETER PARKER FUNNY MOMENTS") == "Peter Parker Funny Moments")
check("quality tags are dropped",
      _labels.clean("Spider-Man vs Venom FIGHT [HD] 1080p")
      == "Spider-Man vs Venom FIGHT")
check("a title that is only the series still yields something",
      _labels.clean("The Spectacular Spider-Man",
                    {"show_terms": ["spectacular spider-man"]}) != "")
check("an empty title falls back to a number",
      _labels.for_clips([_T("")]) == ["Moment 1"])
check("truncation lands on a word boundary",
      not _labels.clean("Peter Parker fights Doctor Octopus on a moving train",
                        limit=30).endswith(("Docto", "Octop", "movin")),
      _labels.clean("Peter Parker fights Doctor Octopus on a moving train",
                    limit=30))

# The other thing burned into that video: [Music] across most of the runtime.
from backend.app.render.overlay import _NON_SPEECH  # noqa: E402

for _name, _cue in [("[Music]", "[Music]"), ("[music]", "[music]"),
                    ("[Applause]", "[Applause]"), ("(laughter)", "(laughter)"),
                    ("a music note", "\u266a"),
                    ("two music notes", "\u266a\u266a"),
                    ("[ Music ] with spaces", "[ Music ]")]:
    check(f"non-speech cue dropped: {_name}",
          bool(_NON_SPEECH.fullmatch(_cue)))
for _cue in ["[Music] I am swinging", "the music was loud", "Peter, no!"]:
    check(f"real speech kept: {_cue[:26]}",
          not _NON_SPEECH.fullmatch(_cue))


section("videos reach the length they ask for")
# target_seconds used to be a ceiling. Every clip got a fixed target/clips
# share, so one short source made the whole video shorter and nothing took up
# the slack: 120s with a single 12-second clip in the set produced 108s.
from backend.app.render.pipeline import _plan_segments as _plan  # noqa: E402


class _SrcClip:
    def __init__(self, duration):
        self.duration = float(duration)
        self.local_path = Path("x.mp4")
        self.title = "Clip"


def _length(durations, target, max_clip=32.0, clips=None):
    fmt = {"target_seconds": target, "max_clip_seconds": max_clip,
           "min_clip_seconds": 8.0, "clip_trim_strategy": "center"}
    segs = _plan([_SrcClip(d) for d in durations], fmt)
    return round(sum(s.duration for s in segs), 1)


check("a full set reaches two minutes",
      _length([60] * 5, 120) == 120.0, _length([60] * 5, 120))
# The case that was broken. The long clips cover for the short one, inside
# max_clip_seconds.
check("one short source no longer shortens the video",
      _length([12, 60, 60, 60, 60], 120) == 120.0,
      _length([12, 60, 60, 60, 60], 120))
check("nor do several",
      _length([12, 18, 60, 60, 60], 120) == 120.0,
      _length([12, 18, 60, 60, 60], 120))
# Headroom is what makes it possible; without it the arithmetic cannot work.
check("with no headroom it still falls short, honestly",
      _length([12, 60, 60, 60, 60], 120, max_clip=24.0) < 120.0,
      _length([12, 60, 60, 60, 60], 120, max_clip=24.0))
check("the cap is still respected",
      all(s.duration <= 32.0 + 0.01 for s in _plan(
          [_SrcClip(300) for _ in range(5)],
          {"target_seconds": 300, "max_clip_seconds": 32.0,
           "min_clip_seconds": 8.0})))
check("and it never overshoots the target",
      _length([300] * 5, 120) <= 120.0, _length([300] * 5, 120))

# What sourcing actually did, recorded on the job. A run that has run out of
# fresh footage still produces a video -- it reuses the clips published longest
# ago rather than failing -- and said nowhere that is indistinguishable from a
# source being ignored entirely.
from backend.app.render.pipeline import gather as _gather  # noqa: E402
import backend.app.sources as _reg  # noqa: E402
from backend.app.sources.base import SourceClip as _PSC  # noqa: E402


class _StubSource:
    name, reusable, needs_key, last_problem = "upload", True, False, ""

    #: Thirty seconds, which is under the 75s that makes a source a haystack.
    #: These are clips: each is used whole, so having published one is a
    #: reason to skip it. A source long enough to cut several moments out of
    #: is a different case with different counters, checked just below.
    duration = 30.0

    def available(self):
        return True

    def search(self, terms, limit):
        out = []
        for i in range(6):
            c = _PSC(source="upload", external_id=f"s{i:09d}", title=f"clip {i}",
                     url=f"http://x/{i}", author="a", duration=self.duration,
                     licence="ok", reusable=True, attribution_required=False)
            c.extra = {"view_count": 100 - i, "description": "", "age_days": 1}
            c.tags = []
            out.append(c)
        return out[:limit]


class _StubEpisodes(_StubSource):
    """The same six sources, long enough to be searched rather than used.

    Five minutes: over the 75s that makes a source a haystack, and under the
    600s default ceiling, so this tests the haystack rule rather than the
    length filter. A real episode clears that ceiling too and is let through
    by the playlist exemption instead -- checked in its own section.
    """

    duration = 300.0


_saved_for_job = _reg.for_job
_reg.for_job = lambda names, uid=None, cfg=None: [_StubSource()]
try:
    _cfg = sanitise({"sources": ["upload"], "clips": 4})
    _rep = {}
    _gather(_cfg, 4, None, None, report=_rep)
    check("a run records how many candidates it saw", _rep["candidates"] == 6, _rep)
    check("and reports no reuse when there was none", _rep["reused"] == 0, _rep)

    # Five of six already published: only one is fresh for a four-clip video.
    _hist = {("upload", f"s{i:09d}"): "2026-01-0%d" % (i + 1) for i in range(5)}
    _rep2 = {}
    _gather(_cfg, 4, None, _hist, report=_rep2)
    check("a thin pool is reported as reuse, not silence",
          _rep2["reused"] == 3, _rep2)
    check("and says how little was left to choose from",
          _rep2["unused_available"] == 1, _rep2)
    check("and names the repeats", len(_rep2["reused_titles"]) == 3, _rep2)

    # A long source is not spent by having been mined once: the rest of the
    # episode was never published. It is not silently fine either, so the run
    # says how many it went back to rather than reporting no reuse at all.
    _reg.for_job = lambda names, uid=None, cfg=None: [_StubEpisodes()]
    _rep3 = {}
    _pool3 = _gather(_cfg, 4, None, _hist, report=_rep3)
    check("an episode already mined is still offered", len(_pool3) == 6, _rep3)
    check("and is reported as returned to, not as a repeat",
          _rep3["reused"] == 0 and _rep3["remined"] == 5, _rep3)
    check("the least-mined episode comes first",
          _pool3[0].external_id == "s000000005",
          [c.external_id for c in _pool3])
finally:
    _reg.for_job = _saved_for_job

# The advice that explains it before a run is spent.
from backend.app.render.advice import review as _rev  # noqa: E402

_short = _rev({"sources": ["youtube"], "clips": 5, "target_seconds": 120,
               "max_clip_seconds": 15, "banner_enabled": True})
check("an unreachable length is called out",
      any("cannot reach your target length" in f.title.lower()
          for f in _short.findings),
      [f.title for f in _short.findings])
check("and it is said exactly once",
      sum("reach" in f.title.lower() for f in _short.findings) == 1,
      [f.title for f in _short.findings])
# A warning was not enough. clips x max_clip is a hard ceiling on the whole
# video, so 5 clips capped at 12s render exactly 60s however large the target
# is -- which reads as the length setting being ignored, after the render has
# been spent.
# But a near miss must not block: the shipped defaults are 4 clips at 26s
# against a 105s target, which is 104s, and stopping a run over one second
# would be its own bug.
check("a near miss only warns",
      _rev({"sources": ["upload"], "clips": 4}, upload_count=20).can_run,
      [f.title for f in _rev({"sources": ["upload"], "clips": 4},
                             upload_count=20).blockers])
check("an unreachable length blocks the run",
      not _rev({"sources": ["youtube"], "clips": 5, "target_seconds": 120,
                "max_clip_seconds": 12}).can_run)
_reach = [f for f in _rev({"sources": ["youtube"], "clips": 5,
                           "target_seconds": 120, "max_clip_seconds": 12}
                          ).findings if "reach" in f.title.lower()][0]
check("and says what the video would actually come out as",
      "60s" in _reach.detail, _reach.detail)
check("and how to fix it in numbers, not adjectives",
      "24s" in _reach.fix, _reach.fix)
_tight = _rev({"sources": ["youtube"], "clips": 5, "target_seconds": 120,
               "max_clip_seconds": 24, "banner_enabled": True})
check("and a target with no slack gets a tip",
      any("No slack" in f.title for f in _tight.findings))
_roomy = _rev({"sources": ["youtube"], "clips": 5, "target_seconds": 120,
               "max_clip_seconds": 32, "banner_enabled": True})
check("a workable one says nothing about length",
      not any("length" in f.title.lower() or "slack" in f.title.lower()
              for f in _roomy.findings),
      [f.title for f in _roomy.findings])

# Every level the advice emits must be one the frontend can sort and colour.
_known = {"blocker", "warning", "tip"}
_all_levels = set()
for _cfg in ({"sources": [], "clips": 5},
             {"sources": ["youtube"], "clips": 5, "target_seconds": 120,
              "max_clip_seconds": 15, "banner_enabled": True},
             {"sources": ["youtube"], "clips": 5, "target_seconds": 120,
              "max_clip_seconds": 24, "banner_enabled": True}):
    _all_levels |= {f.level for f in _rev(_cfg).findings}
check("advice only emits levels the app renders",
      _all_levels <= _known, sorted(_all_levels))

# The presets ship two minutes, and ship it reachable.
from backend.app.niches import BUILTIN_NICHES as _NICHES  # noqa: E402

for _slug in ("top5", "show"):
    _n = next(n for n in _NICHES if n["slug"] == _slug)["settings"]
    check(f"{_slug} preset is two minutes", _n["target_seconds"] == 120,
          _n["target_seconds"])
    check(f"{_slug} preset can reach it",
          _n["max_clip_seconds"] * _n["clips"] >= _n["target_seconds"] * 1.15,
          f'{_n["max_clip_seconds"]} x {_n["clips"]}')


section("clips are not reused")
# Every clip a job used was written to job_clips and never read back, so each
# run scored the same pool with the same model and picked the same five. The
# subscriber sees the same moments over and over.
from datetime import timedelta as _timedelta  # noqa: E402
from backend.app.db import session_scope as _session_scope  # noqa: E402
from backend.app.render.history import recently_used as _recent  # noqa: E402
from backend.app.models import (  # noqa: E402
    Job as _J, JobClip as _JC, JobStatus as _JS, User as _U, utcnow as _utcnow,
)
from backend.app.sources.base import SourceClip as _SC  # noqa: E402

_ru = TestClient(app)
_ru.post("/api/auth/signup",
         json={"email": "reuse@example.com", "password": "reuse-pass-77"})
with _session_scope() as _db:
    _uid = _db.query(_U).filter(_U.email == "reuse@example.com").first().id

check("a fresh account has no history", _recent(None, _uid, 60) == {})

with _session_scope() as _db:
    _done = _J(owner_id=_uid, public_id="hist-done", status=_JS.DONE,
               title="Done", finished_at=_utcnow())
    _failed = _J(owner_id=_uid, public_id="hist-failed", status=_JS.FAILED,
                 title="Failed", finished_at=_utcnow())
    _db.add_all([_done, _failed])
    _db.flush()
    _db.add_all([
        _JC(job_id=_done.id, source="youtube", external_id="USED1", position=1),
        _JC(job_id=_done.id, source="youtube", external_id="USED2", position=2),
        _JC(job_id=_failed.id, source="youtube", external_id="NEVERSHIPPED",
            position=1),
    ])

with _session_scope() as _db:
    _hist = _recent(_db, _uid, 60)
check("clips from a finished job are remembered",
      ("youtube", "USED1") in _hist and ("youtube", "USED2") in _hist, sorted(_hist))
# A failed run published nothing, so burning its clips punishes somebody for a
# video that never went out.
check("clips from a failed job are not",
      ("youtube", "NEVERSHIPPED") not in _hist, sorted(_hist))

with _session_scope() as _db:
    check("the window is respected", _recent(_db, _uid, 0) == {})
    _old = _recent(_db, _uid, 60)
check("another account sees none of it",
      _recent(None, _uid + 999, 60) == {})
with session_scope() as _db:
    _dated = _recent(_db, _uid, 60)
check("history records when each clip went out",
      all(isinstance(v, str) and v for v in _dated.values()), _dated)

# The filter itself, and the rule that a repeat beats a failed run.
class _PC:
    def __init__(self, ext):
        self.source, self.external_id = "youtube", ext


def _funnel(pool, used, wanted):
    """The rule gather() applies, in isolation."""
    fresh = [c for c in pool if (c.source, c.external_id) not in used]
    stale = [c for c in pool if (c.source, c.external_id) in used]
    if len(fresh) >= wanted:
        return fresh
    when = used if hasattr(used, "get") else {}
    stale.sort(key=lambda c: str(when.get((c.source, c.external_id)) or ""))
    return fresh + stale[:max(0, wanted - len(fresh))]


_used = {("youtube", "USED1"): "2026-08-01", ("youtube", "USED2"): "2026-08-20"}
_plenty = [_PC("USED1"), _PC("USED2"), _PC("FRESH1"), _PC("FRESH2"),
           _PC("FRESH3"), _PC("FRESH4"), _PC("FRESH5")]
check("used clips are dropped when there is enough left",
      [c.external_id for c in _funnel(_plenty, _used, 5)]
      == ["FRESH1", "FRESH2", "FRESH3", "FRESH4", "FRESH5"])

# The real failure: seven survived selection, five had been published, and a
# five-clip job was handed a pool of two because the guard asked for two.
_thin = [_PC("USED1"), _PC("USED2"), _PC("FRESH1"), _PC("FRESH2")]
_topped = _funnel(_thin, _used, 5)
check("a thin pool is topped back up instead of starving",
      len(_topped) == 4, [c.external_id for c in _topped])
check("fresh clips still come first",
      [c.external_id for c in _topped][:2] == ["FRESH1", "FRESH2"],
      [c.external_id for c in _topped])
# If something has to repeat it should be the one seen longest ago, not the
# one that keeps winning -- that was the original complaint.
check("the oldest use is the one repeated first",
      [c.external_id for c in _topped][2] == "USED1",
      [c.external_id for c in _topped])
check("a set with no dates still works",
      len(_funnel(_thin, {("youtube", "USED1"), ("youtube", "USED2")}, 5)) == 4)
check("nothing is topped up when the job is small enough",
      len(_funnel(_thin, _used, 2)) == 2)

from backend.app.settings_schema import BY_KEY as _SK  # noqa: E402
check("reuse window defaults to something non-zero",
      _SK["reuse_after_days"]["default"] > 0, _SK["reuse_after_days"]["default"])

# The agent has no database, so the history travels with the claimed job.
check("the claim payload carries the history",
      "already_used" in Path("backend/app/routes/agent.py").read_text(encoding="utf-8"))
check("and the agent turns it back into pairs",
      "already_used" in Path("agent/runner.py").read_text(encoding="utf-8"))


section("a show filter with nothing in it")
# On with no keywords used to reject every clip, so the run failed and the
# obvious response was to switch the filter off -- which is how a Spectacular
# Spider-Man niche ended up with Marvel's Spider-Man and The Amazing
# Spider-Man in the same video.
from backend.app.render.selection import (  # noqa: E402
    derived_show_terms as _derive, matches_show as _matches,
)


def _clip(title):
    return _SC(source="youtube", external_id="x", title=title, url="", extra={})


_niche = {"require_show_match": True, "search_terms": [
    "spectacular spider-man funny moments",
    "spectacular spider-man best scenes",
    "spectacular spider-man peter parker funny",
]}
check("the show is derived from the search terms",
      _derive(_niche) == ["spectacular spider-man"], _derive(_niche))
check("the right show is kept",
      _matches(_clip("The Spectacular Spider-Man - Peter meets Gwen"), _niche)[0])
for _wrong in ["Origin 2 | Marvel's Spider-Man | Disney XD",
               "The Amazing Spider-Man - Bad Days"]:
    check(f"wrong show dropped: {_wrong[:34]}",
          not _matches(_clip(_wrong), _niche)[0])

# Configuration still wins over the guess.
_typed = {**_niche, "show_terms": ["amazing spider-man"]}
check("typed keywords beat the derived ones",
      _matches(_clip("The Amazing Spider-Man - Bad Days"), _typed)[0])

# And with nothing to go on it must not silently reject the entire run.
_thin_niche = {"require_show_match": True, "search_terms": ["funny"]}
check("one vague term derives nothing", _derive(_thin_niche) == [])
check("and clips are let through rather than the run failing",
      _matches(_clip("Anything at all"), _thin_niche)[0])


section("other people's edits")
# Sourcing from a fan edit is the worst outcome available: their music, their
# captions and their watermark come with it, and the moment is usually already
# speed-ramped. The settings screen has always claimed there was a check for
# this; there was not.
from backend.app.render.selection import (  # noqa: E402
    is_derivative as _is_deriv, _split_camel as _camel,
)
def _cand(title, author="", tags=None, description=""):
    return _SC(source="youtube", external_id="x", title=title, url="",
               author=author, tags=tags or [],
               extra={"description": description})


_ON = {"reject_derivative": True}

# Somebody talking about the show is not footage from the show. A ranking
# video called "The Top 5 Spider-Man Series" reached a finished render: half
# of it is a man at a desk, and it passed the show filter because a video
# discussing the show naturally names the show in its description.
for _title, _term in [
    ("The Top 5 Spider-Man Series", "top 5"),
    ("Spectacular Spider-Man REACTION", "reaction"),
    ("Ranking every Spider-Man cartoon", "ranking every"),
    ("Spider-Man tier list", "tier list"),
    ("The Spectacular Spider-Man retrospective", "retrospective"),
    ("Spider-Man 2008 review", "review"),
    ("worst to best Spider-Man shows", "worst to best"),
    ("First time watching Spectacular Spider-Man", "first time watching"),
]:
    _got, _hit = _is_deriv(_cand(_title), _ON)
    check(f"commentary dropped: {_title[:34]}", _got and _hit == _term, _hit)

# The cost of getting that wrong is rejecting real scenes, so check the shape
# of title these terms sit near.
for _scene in [
    "The Spectacular Spider-Man - Peter meets Gwen",
    "Peter Parker fights Doctor Octopus",
    "Gwen and Harry at the dance",
    "Spider-Man saves the train",
    "Editorial cut of season 2",
]:
    check(f"scene kept: {_scene[:36]}", not _is_deriv(_cand(_scene), _ON)[0],
          _is_deriv(_cand(_scene), _ON)[1])

for _title, _term in [
    ("Spectacular Spider-Man EDIT | phonk", "edit"),
    ("spider-man amv - Ready For It", "amv"),
    ("Peter Parker funny moments compilation", "compilation"),
    ("Spidey twixtor clips 4k", "twixtor"),
    ("every scene of Venom in season 2", "every scene"),
    ("Gwen Stacy tribute", "tribute"),
]:
    _got, _hit = _is_deriv(_cand(_title), _ON)
    check(f"caught: {_title[:38]}", _got and _hit == _term, _hit)

# The whole reason the match is whole-word. A substring test rejects most of
# the pool: "edit" lives inside credits, editorial and meditation.
for _clean in [
    "Spectacular Spider-Man - Peter meets Gwen",
    "End credits scene",
    "Editorial: why season 3 never happened",
    "A meditation on power and responsibility",
    "The Sinister Six attack | Season 2",
]:
    _got, _hit = _is_deriv(_cand(_clean), _ON)
    check(f"kept: {_clean[:40]}", not _got, _hit)

# The video-essay openers. Both of these reached a finished render: they are a
# person at a desk talking over stills, and neither title contains any of the
# single words above.
for _essay in [
    "What If...? The Spectacular Spider-Man",
    "THIS Is Why Spectacular Spider-man Was Cancelled",
    "The Truth About Spectacular Spider-Man",
    "What Happened To Spectacular Spider-Man?",
    "The Problem With Spider-Man 3",
    "Everything Wrong With Spider-Man",
    "The Rise and Fall of Spectacular Spider-Man",
    "We Need To Talk About Spider-Man",
    "Spectacular Spider-Man Revisited",
]:
    _got, _hit = _is_deriv(_cand(_essay), _ON)
    check(f"dropped: {_essay[:44]}", _got, "an essay reached the render")

# And the words those phrases are built from are ordinary English, so footage
# that merely contains one must survive. Banning "why" or "truth" or "story"
# outright would throw away the clips this is meant to find.
for _real in [
    "Why I Love You - Peter and MJ scene",
    "The Story of My Life - episode clip",
    "Doc Ock Truth Serum Scene",
    "Spidey saves Gwen | Spectacular Spider-Man",
]:
    _got, _hit = _is_deriv(_cand(_real), _ON)
    check(f"kept: {_real[:44]}", not _got, _hit)

# Channel names run words together where a word boundary cannot see them.
check("camelCase channel names are split", _camel("SpideyEdits") == "Spidey Edits")
check("so an edits channel is caught",
      _is_deriv(_cand("Peter vs Doc Ock", author="SpideyEdits"), _ON)[0] is True)

# The three ways out.
check("the filter can be turned off",
      _is_deriv(_cand("spider-man edit"), {"reject_derivative": False})[0] is False)
check("a trusted channel is exempt",
      _is_deriv(_cand("spider-man edit", author="Marvel HQ"),
                {"reject_derivative": True,
                 "trusted_uploaders": ["Marvel HQ"]})[0] is False,
      "this is what the Trusted channels box always said it did")
check("a niche can add its own terms",
      _is_deriv(_cand("spidey slideshow"),
                {"reject_derivative": True,
                 "derivative_terms": ["slideshow"]})[0] is True)

# On by default, for every niche, which is the point.
from backend.app.settings_schema import BY_KEY as _KEYS  # noqa: E402
check("on by default for every niche",
      _KEYS["reject_derivative"]["default"] is True)

# Searching for the thing you just refused is the obvious mistake, and one I
# put in the setup guide myself before this check existed.
from backend.app.render.advice import review as _review  # noqa: E402

_clash = _review({"sources": ["youtube"], "clips": 5, "target_seconds": 105,
                  "banner_enabled": True,
                  "search_terms": ["spiderman funny compilation"]})
check("searching for edits while refusing them warns",
      any("refusing them" in f.title for f in _clash.findings),
      [f.title for f in _clash.findings])
_ok = _review({"sources": ["youtube"], "clips": 5, "target_seconds": 105,
               "banner_enabled": True,
               "search_terms": ["peter parker funny scene"]})
check("and a clean search does not",
      not any("refusing them" in f.title for f in _ok.findings))

# A backspace byte got into this file once, through a shell escaping layer,
# and turned the word-boundary regex into something that matched nothing.
import backend.app.render.advice as _adv  # noqa: E402
check("the boundary is a real regex escape", _adv.BOUNDARY == chr(92) + "b",
      repr(_adv.BOUNDARY))
for _mod in ("backend/app/render/advice.py", "backend/app/render/selection.py"):
    check(f"no stray control bytes in {_mod.split('/')[-1]}",
          chr(8) not in Path(_mod).read_text(encoding="utf-8"))


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
section("moments are cut out of long videos")
# Pasting a playlist fixed *where* clips come from. It did not fix the other
# half: a source video still became exactly one clip, taken from whatever was
# in the middle of it. A twenty-minute episode gave one excerpt and the reuse
# history then burned the whole episode, so a playlist of ten episodes was
# spent after ten runs and the same scenes came back.
#
# long_clip_seconds has promised the fix in its own help text since the
# settings screen was written -- "longer clips get a timed transcript so the
# moment can be located inside them" -- and nothing read it.
from backend.app.render import moments as _mo  # noqa: E402


def _vtt(path: Path, cues) -> Path:
    """A WebVTT file from (start, end, text) triples."""
    def stamp(value):
        return (f"{int(value // 3600):02d}:{int(value % 3600 // 60):02d}:"
                f"{value % 60:06.3f}")

    body = ["WEBVTT", ""]
    for start, end, text in cues:
        body += [f"{stamp(start)} --> {stamp(end)}", text, ""]
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def _episode(name, cues, duration=600.0, external_id="EP1"):
    clip = SourceClip(source="youtube", external_id=external_id,
                      title="The Show - Episode 1", url="", duration=duration)
    clip.extra = {"subtitle_path": str(_vtt(TMP / f"{name}.vtt", cues))}
    return clip


def _chatter(start, end, words=6, tag="line"):
    """Dialogue cues at two-second intervals across a stretch."""
    out, when, index = [], start, 0
    while when + 1.6 <= end:
        index += 1
        out.append((when, when + 1.6,
                    " ".join(f"{tag}{index}word{n}" for n in range(words))))
        when += 2.0
    return out


_FMT = sanitise({"clips": 5, "target_seconds": 120, "min_clip_seconds": 8,
                 "max_clip_seconds": 32, "long_clip_seconds": 75,
                 "moments_per_video": 2, "moment_min_gap_seconds": 90,
                 "skip_intro_seconds": 45, "skip_outro_seconds": 45,
                 "moment_audio_scan": False})
check("a two-minute five-clip video gives each moment 24 seconds",
      _mo.slot_seconds(_FMT) == 24.0, _mo.slot_seconds(_FMT))

# Dialogue at 300s and at 450s, near-silence elsewhere, and a burst inside the
# title sequence that must be ignored precisely because it is the titles.
_cues = (_chatter(0, 40, tag="intro")
         + _chatter(300, 330, tag="scene")
         + _chatter(450, 480, tag="other")
         + [(120, 122, "one line"), (200, 202, "another line"),
            (560, 562, "closing line")])
_ep = _episode("dense", _cues)
_found = _mo.mine(_ep, _FMT, 2)
check("a long source yields more than one moment", len(_found) == 2, len(_found))
_starts = sorted(round(c.start) for c in _found)
check("both dense scenes are found",
      any(abs(s - 300) <= 30 for s in _starts)
      and any(abs(s - 450) <= 30 for s in _starts), _starts)
check("the title sequence is skipped", all(s >= 40 for s in _starts), _starts)
check("the moments do not overlap each other",
      abs(_starts[0] - _starts[1]) >= 24.0, _starts)
check("nothing runs past the end of the episode",
      all(c.start + c.duration <= _ep.duration + 0.01 for c in _found))
check("each moment says what won it", all(c.why for c in _found),
      [c.why for c in _found])

# The excerpt is the history key, not the episode.
check("a moment identifies itself by where it starts",
      _found[0].moment_id() == f"EP1@{int(round(_found[0].start))}",
      _found[0].moment_id())
_used_moment = {("youtube", f"EP1@{int(round(_starts[0]))}"): "2026-08-01"}
_again = _mo.mine(_ep, _FMT, 1, _used_moment)
check("a moment already published is not cut again",
      _again and abs(_again[0].start - _starts[0]) > 24.0,
      [c.start for c in _again])
check("but the rest of the episode is still available", len(_again) == 1)

# Rows written before moments existed name the video and nothing else. They
# always used the middle, so the middle is all that is spent.
_legacy = _mo.mine(_ep, _FMT, 1, {("youtube", "EP1"): "2026-07-01"})
check("an old whole-video row burns the middle it used, not the episode",
      _legacy and abs(_legacy[0].start - 450) <= 30, [c.start for c in _legacy])

# No captions and no audio scan: still several different moments, because
# five identical windows from the top of the episode is not an answer.
_blind = SourceClip(source="youtube", external_id="EP2", title="Episode 2",
                    url="", duration=600.0)
_spread = _mo.mine(_blind, _FMT, 3)
check("with nothing to go on the moments are still spread out",
      len({round(c.start) for c in _spread}) == 3, [c.start for c in _spread])

# Reaction markers move the score; a stretch of nothing but score does not.
_react = _episode("react", _chatter(300, 330, tag="a")
                  + _chatter(450, 480, tag="b")
                  + [(452, 454, "[Laughter]"), (458, 460, "[Applause]")],
                  external_id="EP3")
check("laughter beats the same amount of dialogue without it",
      abs(_mo.mine(_react, _FMT, 2)[0].start - 450) <= 30,
      [round(c.start) for c in _mo.mine(_react, _FMT, 2)])
_musical = _episode("music", [(300 + n * 2, 302 + n * 2, "[Music]")
                              for n in range(15)]
                    + _chatter(450, 480, tag="talk"), external_id="EP4")
check("a stretch that is only the score is not the moment",
      abs(_mo.mine(_musical, _FMT, 1)[0].start - 450) <= 30,
      _mo.mine(_musical, _FMT, 1)[0].start)

# Spread across the playlist. Five moments from one episode is a video that
# plays as a single scene, which reads as "it reuses the same clips" whether
# or not the clips are literally repeats.
_a = [_mo.Cut(clip=_ep, start=10, score=0.9),
      _mo.Cut(clip=_ep, start=200, score=0.8),
      _mo.Cut(clip=_ep, start=400, score=0.7)]
_b = [_mo.Cut(clip=_react, start=10, score=0.6),
      _mo.Cut(clip=_react, start=300, score=0.5)]
check("everyone's best comes before anyone's second best",
      [c.score for c in _mo._interleave([_a, _b], 4)] == [0.9, 0.6, 0.8, 0.5],
      [c.score for c in _mo._interleave([_a, _b], 4)])
check("and one video can still fill the gap when it is the only one",
      len(_mo._interleave([_a], 3)) == 3)

# Which episodes to return to first, so successive runs walk the playlist.
from backend.app.render.pipeline import (  # noqa: E402
    _plan_segments as _plan2, _times_mined as _mined,
)

check("an episode counts once for every moment taken from it",
      _mined(_PC("EP1"), {("youtube", "EP1@300"): "", ("youtube", "EP1@450"): "",
                          ("youtube", "OTHER@10"): ""}) == 2)
check("a whole-video row counts once",
      _mined(_PC("EP1"), {("youtube", "EP1"): ""}) == 1)
check("and a different video not at all",
      _mined(_PC("EP9"), {("youtube", "EP1@1"): ""}) == 0)


# The planner has to honour the moment, and must not run off the end of the
# source when the moment sits near it.
class _Src:
    def __init__(self, duration):
        self.duration = float(duration)
        self.local_path = Path("x.mp4")
        self.title = "Episode"


_cuts = [_mo.Cut(clip=None, start=300.0, source_duration=600.0),
         _mo.Cut(clip=None, start=588.0, source_duration=600.0)]
_segs = _plan2([_Src(600), _Src(600)], dict(_FMT), _cuts)
check("the segment starts where the moment does", _segs[0].start == 300.0,
      _segs[0].start)
check("a moment near the end is truncated, not overrun",
      _segs[1].start + _segs[1].duration <= 600.01,
      (_segs[1].start, _segs[1].duration))
check("without cuts the trim strategy still decides",
      _plan2([_Src(600)], {**_FMT, "clip_trim_strategy": "start"})[0].start == 0.0)

# The numbered list is the retention device, and three moments cut from one
# episode all carry that episode's title.
from backend.app.render.labels import for_cuts as _for_cuts  # noqa: E402

_same = [_mo.Cut(clip=_ep, start=10, label="You have got to be kidding"),
         _mo.Cut(clip=_ep, start=200, label="I never asked for this"),
         _mo.Cut(clip=_ep, start=400, label="")]
_list = _for_cuts(_same, {})
check("what was said names the moment",
      _list[0] == "You have got to be kidding", _list[0])
check("every entry in the list is different", len(set(_list)) == 3, _list)
check("and a moment with no quote still gets an entry", bool(_list[2]), _list)
_quiet = [_mo.Cut(clip=_ep, start=n * 100, label="") for n in range(3)]
check("three cuts from one episode never read as the same entry three times",
      len(set(_for_cuts(_quiet, {}))) == 3, _for_cuts(_quiet, {}))

# Auto-captions arrive lowercase and unpunctuated.
check("an auto-caption line is capitalised for the list",
      _mo._titleish("how did i ever live without you")
      == "How Did I Ever Live Without You",
      _mo._titleish("how did i ever live without you"))
check("a line that already has capitals is left alone",
      _mo._titleish("Peter Parker vs Flash") == "Peter Parker vs Flash")

# The loudness pass, against the real ffmpeg rather than a fixture: it is one
# regex against one tool's output, which makes it the fragile part.
_loud_file = TMP / "loudness.mp4"
subprocess.run(
    [settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
     "-f", "lavfi", "-i", "color=c=black:s=320x180:d=60:r=15",
     "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
     "-af", "volume=eval=frame:volume='if(between(t,30,45),1,0.02)'",
     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
     "-c:a", "aac", "-shortest", str(_loud_file)],
    check=True, capture_output=True, timeout=180)
_curve = _mo._loudness(_loud_file)
check("ffmpeg's loudness output is understood", len(_curve) > 20, len(_curve))
_in_burst = [v for t, v in _curve if 33 <= t <= 43]
_outside = [v for t, v in _curve if t < 25 or t > 50]
check("the loud passage reads louder than the quiet one",
      bool(_in_burst) and bool(_outside)
      and sum(_in_burst) / len(_in_burst) > sum(_outside) / len(_outside) + 10,
      (round(sum(_in_burst) / max(1, len(_in_burst)), 1),
       round(sum(_outside) / max(1, len(_outside)), 1)))
check("a file that is not there is not a crash",
      _mo._loudness(TMP / "missing.mp4") == [])
check("nor is a caption file that is not there",
      _mo._cues(SourceClip(source="s", external_id="x", title="", url="")) == [])


section("the niche description finally reaches the clip picker")
# The settings screen has said "Written for the AI that picks clips" since it
# was written, and the description only ever went to the title writer. The
# choice of which twenty seconds was made entirely by dialogue density and
# loudness -- which is a good proxy for "a scene is happening" and says
# nothing about *which* scene. Three niches on one playlist got identical
# cuts, because nothing in the scoring could tell them apart.
from backend.app.render import curator as _cur  # noqa: E402

check("no key means no ranking, and no crash",
      _cur.rank([{"excerpt": "a"}, {"excerpt": "b"}],
                description="funny moments") == {},
      "the heuristic ordering stands, exactly as before")

_saved_key = settings.anthropic_api_key
settings.anthropic_api_key = "test-key-never-used"
try:
    check("a niche with no description is not ranked either",
          _cur.rank([{"excerpt": "a"}, {"excerpt": "b"}], description="  ") == {},
          "there is nothing to rank against, and guessing beats nothing badly")
    check("a single candidate is not worth a round trip",
          _cur.rank([{"excerpt": "a"}], description="funny") == {})
finally:
    settings.anthropic_api_key = _saved_key

# The model's reply, in the shapes models actually send.
check("plain JSON is read",
      _cur._extract('{"scores": [{"n": 1, "score": 0.5}]}')["scores"][0]["n"] == 1)
check("a fenced reply is read",
      _cur._extract('```json\n{"scores": []}\n```') == {"scores": []})
check("a trailing comma is repaired",
      _cur._extract('{"scores": [{"n": 1, "score": 0.5},]}') is not None)
check("prose around the JSON is tolerated",
      _cur._extract('Here you go:\n{"scores": []}\nhope that helps') == {"scores": []})
check("an unusable reply is not guessed at", _cur._extract("sorry, no") is None)

# Judgement is weighted over measurement but never replaces it: a transcript
# cannot show that a stretch plays over a black screen or wall-to-wall music.
check("with no judgement the measurement stands",
      _cur.blend(0.4, None) == 0.4)
check("judgement outweighs measurement",
      _cur.blend(0.0, 1.0) > _cur.blend(1.0, 0.0),
      (_cur.blend(0.0, 1.0), _cur.blend(1.0, 0.0)))
check("but measurement is never ignored",
      _cur.blend(1.0, 0.5) > _cur.blend(0.0, 0.5))

# What is said inside the window, which is what the curator reads.
_talky = _episode("excerpt", _chatter(300, 330, tag="scene"), external_id="EP7")
_one = _mo.mine(_talky, {**_FMT, "moment_audio_scan": False}, 1)[0]
check("a mined moment carries what was said in it",
      "scene" in _one.excerpt and len(_one.excerpt) > 20, _one.excerpt[:60])
check("and the excerpt is capped",
      len(_mo._excerpt([], 0, 10)) == 0
      and len(_one.excerpt) <= 420)

# The whole point: with a curator the heuristic shortlists rather than
# decides, and the shortlist is cut back to size only after ranking -- so a
# moment the niche wants is not thrown away for measuring quieter.
_ranked_calls = []


def _fake_rank(candidates, *, description, niche_name=""):
    _ranked_calls.append((list(candidates), description, niche_name))
    # Reverse the heuristic's preference, so a change is unmistakable.
    return {i: {"score": (i + 1) / len(candidates), "why": "fits the niche"}
            for i in range(len(candidates))}


_saved_rank, _saved_avail = _cur.rank, _cur.available
_cur.rank, _cur.available = _fake_rank, (lambda: True)
try:
    _fmt_ai = sanitise({**_FMT, "description": "every time the landlord shows up",
                        "moments_per_video": 2, "ai_moment_ranking": True})
    _spread_ep = _episode("curated", _chatter(100, 140, tag="a")
                          + _chatter(250, 290, tag="b")
                          + _chatter(400, 440, tag="c"), external_id="EP8")
    _out = _mo.plan([_spread_ep], _fmt_ai, 2, niche_name="Landlord Moments")
    check("the curator was asked once, not once per moment",
          len(_ranked_calls) == 1, len(_ranked_calls))
    check("it was given the subscriber's own words",
          _ranked_calls[0][1] == "every time the landlord shows up",
          _ranked_calls[0][1])
    check("and the niche name", _ranked_calls[0][2] == "Landlord Moments")
    check("it saw more candidates than the video needs",
          len(_ranked_calls[0][0]) > 2, len(_ranked_calls[0][0]))
    check("each candidate came with a timestamp and what was said",
          all("start" in c and "excerpt" in c for c in _ranked_calls[0][0]))
    check("the video still gets only its share from one video",
          len(_out) == 2, len(_out))
    check("and the ranking decided which, not the loudness",
          all(c.why == "fits the niche" for c in _out), [c.why for c in _out])

    # Off by setting, and off without a key, must both fall straight back.
    _ranked_calls.clear()
    _mo.plan([_spread_ep], {**_fmt_ai, "ai_moment_ranking": False}, 2)
    check("the setting turns it off", not _ranked_calls)
finally:
    _cur.rank, _cur.available = _saved_rank, _saved_avail

_ranked_calls.clear()
_off = _mo.plan([_episode("noai", _chatter(300, 340, tag="x"), external_id="EP9")],
                sanitise({**_FMT, "description": "anything"}), 1)
check("with no key at all the moments are still found",
      len(_off) == 1 and _off[0].mined,
      [(round(c.start), c.why) for c in _off])

section("a playlist entry is an episode, not a clip")
# Discovery already treats a usable playlist as the whole list of pages to
# scan, so when there is one every candidate is a video somebody chose. The
# filters are all inference from titles, and inference is what let a scene
# from the Andrew Garfield film into a Spectacular Spider-Man video. Being
# chosen outranks all of it -- and the length limit especially, because a
# full episode is the haystack a clip gets cut out of.
from backend.app.render.selection import (  # noqa: E402
    from_a_chosen_playlist as _chosen,
)

_PLAYLIST = ["https://www.youtube.com/playlist?list=PLabc123def456"]
check("a usable playlist is recognised", _chosen({"source_playlists": _PLAYLIST}))
check("no playlist means the filters do their usual work",
      not _chosen({"source_playlists": []}))
check("and neither Watch Later nor a link with no list= counts",
      not _chosen({"source_playlists": ["https://www.youtube.com/playlist?list=WL",
                                        "https://www.youtube.com/watch?v=abcdefghijk"]}),
      "the source refuses to scan those, so they buy no exemption here")


def _candidate(title, duration=1320.0, views=12):
    clip = SourceClip(source="youtube", external_id="E1", title=title, url="",
                      duration=duration)
    clip.extra = {"description": "", "view_count": views}
    return clip


_base = {"require_show_match": True, "show_terms": ["some other show"],
         "max_duration_seconds": 600, "min_view_count": 20000,
         "reject_derivative": True}
_from_list = sanitise({**_base, "source_playlists": _PLAYLIST})
_from_search = sanitise(_base)
_ep_clip = _candidate("Season 1 Marathon - every episode part 2")

check("a 22-minute episode is not thrown out for being long",
      passes_filters(_ep_clip, _from_list)[0],
      passes_filters(_ep_clip, _from_list)[1])
check("nor for having few views",
      passes_filters(_candidate("Episode 4", views=12), _from_list)[0])
check("the word list does not reject the subscriber's own episode listing",
      not _is_deriv(_ep_clip, _from_list)[0], _is_deriv(_ep_clip, _from_list)[1])
check("and the show filter does not have to guess",
      _matches(_ep_clip, _from_list)[0])

# None of which is relaxed for anything that merely turned up in a search.
check("a long search result is still too long",
      not passes_filters(_ep_clip, _from_search)[0],
      passes_filters(_ep_clip, _from_search)[1])
check("an edit from a search is still an edit",
      _is_deriv(_ep_clip, _from_search)[0], _is_deriv(_ep_clip, _from_search)[1])
check("a video essay from a search is still refused",
      _is_deriv(_candidate("THIS Is Why Spectacular Spider-man Was Cancelled"),
                _from_search)[0])
check("and a search result still has to prove the show",
      not _matches(_candidate("Origin 2 | Marvel's Spider-Man"), _from_search)[0])

# The advice that explains the arithmetic before a run is spent.
_greedy = _review({"sources": ["youtube"], "clips": 5, "target_seconds": 120,
                   "max_clip_seconds": 32, "banner_enabled": True,
                   "moments_per_video": 5, "source_playlists": _PLAYLIST})
check("taking every clip from one episode is called out",
      any("one episode" in f.title for f in _greedy.findings),
      [f.title for f in _greedy.findings])
_sane = _review({"sources": ["youtube"], "clips": 5, "target_seconds": 120,
                 "max_clip_seconds": 32, "banner_enabled": True,
                 "moments_per_video": 2, "source_playlists": _PLAYLIST})
check("and is not, at a sensible limit",
      not any("one episode" in f.title for f in _sane.findings),
      [f.title for f in _sane.findings])
check("a playlist is said to go further than it used to",
      any("moment(s) cut from each" in f.detail for f in _sane.findings),
      [f.detail for f in _sane.findings if "runs out" in f.title])

# The preset a subscriber reaches for when they want one programme.
from backend.app.niches import BUILTIN_NICHES as _BUILTINS  # noqa: E402

_show_preset = next(n for n in _BUILTINS if n["slug"] == "show")["settings"]
check("the One TV Show preset mines long sources",
      _show_preset["long_clip_seconds"] <= 120
      and _show_preset["moments_per_video"] >= 2,
      (_show_preset["long_clip_seconds"], _show_preset["moments_per_video"]))
check("it allows a full episode through the length filter",
      _show_preset["max_duration_seconds"] >= 1320,
      _show_preset["max_duration_seconds"])
check("it skips the title sequence and the credits",
      _show_preset["skip_intro_seconds"] > 0
      and _show_preset["skip_outro_seconds"] > 0)
check("and does not take the whole video from one episode",
      _show_preset["moments_per_video"] < _show_preset["clips"])
check("the guided setup asks for the playlist on the show step",
      "source_playlists" in Path("frontend/app.js").read_text(encoding="utf-8"))


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
# A new account has "Publish after rendering" on, and this server has no
# Google credentials, so the promise cannot be kept. It used to read "off",
# which is how somebody presses Publish and gets a file that went nowhere
# with the screen still saying Ready.
_yt_row = next(r for r in studio["status"] if r["id"] == "youtube")
check("youtube publishing is reported as needing action, not as merely off",
      _yt_row["state"] == "action", _yt_row)
check("and the row says what will happen instead",
      "go nowhere" in _yt_row["detail"], _yt_row["detail"])
check("which stops the home screen claiming it is ready",
      "YouTube account" in studio["blocked_by"], studio["blocked_by"])
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
section("configuration advice")
from backend.app.render.advice import review as review_cfg  # noqa: E402

check("uploads-only with no uploads is a blocker",
      not review_cfg(sanitise({"sources": ["upload"]}), upload_count=0).can_run)
check("uploads-only with uploads is fine",
      review_cfg(sanitise({"sources": ["upload"], "clips": 4}),
                 upload_count=6).can_run)
check("no source at all is a blocker",
      not review_cfg(sanitise({"sources": []})).can_run)

empty_gate = review_cfg(sanitise({
    "sources": ["upload"], "require_show_match": True,
    "show_terms": [], "show_people": [],
}), upload_count=5)
check("show filter with nothing to match on is a blocker", not empty_gate.can_run)

fine = review_cfg(sanitise({
    "sources": ["upload"], "clips": 6, "target_seconds": 60,
    "min_clip_seconds": 5, "max_clip_seconds": 20, "checklist_enabled": True,
}), upload_count=10)
check("a workable config raises no blockers", fine.can_run,
      [f.title for f in fine.blockers])

# --- playlists, pasted as links ---------------------------------------- #
from backend.app.sources.youtube_source import (  # noqa: E402
    YouTubeSource, playlist_problem, playlist_url,
)

# The point of the feature is that you paste whatever the address bar gives
# you. The second case is the one that matters: copying the URL while watching
# yields a *video* link carrying the playlist, and taken literally it would
# fetch one video and silently ignore the playlist.
_PL = "https://www.youtube.com/playlist?list=PLtest123abc"
for _paste, _want in [
    ("https://www.youtube.com/playlist?list=PLtest123abc", _PL),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLtest123abc&index=4", _PL),
    ("https://youtu.be/dQw4w9WgXcQ?list=PLtest123abc", _PL),
    ("https://m.youtube.com/playlist?list=PLtest123abc", _PL),
    ("  https://www.youtube.com/playlist?list=PLtest123abc  ", _PL),
    ("PLtest123abc", _PL),
]:
    check(f"paste {_paste.strip()[:44]!r} resolves",
          playlist_url(_paste) == _want, playlist_url(_paste))

# Things that must never become a playlist URL. A bare word is the one that
# would otherwise sail through and 404 much later.
for _junk in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ",
              "https://www.youtube.com/@somechannel",
              "football", "", "   "):
    check(f"{_junk.strip()[:44]!r} is refused", playlist_url(_junk) == "")

# Playlists that exist but a server can never read, and are worth saying so
# about rather than returning nothing.
for _private in ("https://www.youtube.com/playlist?list=WL",
                 "https://www.youtube.com/playlist?list=LL",
                 "https://www.youtube.com/watch?v=a&list=RDabcdef"):
    check(f"{_private[-22:]!r} is refused", playlist_url(_private) == "")
check("a private playlist is explained as private, not as a bad link",
      "private" in playlist_problem(
          "https://www.youtube.com/playlist?list=WL"))
check("a mix is explained as a mix",
      "mix" in playlist_problem(
          "https://www.youtube.com/watch?v=a&list=RDabcdef"))
check("a plain video link is explained as having no playlist",
      "list=" in playlist_problem(
          "https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

# A playlist is the most explicit thing a user can say, so it is scanned
# before channel tabs and keyword searches.
_yt = YouTubeSource({
    "source_playlists": ["https://www.youtube.com/watch?v=x&list=PLtest123abc"],
    "source_channels": ["@somechannel"],
    "channel_tabs": ["shorts"],
})
_urls = _yt.build_sources(["funny moments"])
check("a pasted playlist becomes a discovery URL", _PL in _urls, _urls)
# Ordering was the first attempt and it did not work: the scan only stops once
# the pool is full, so a playlist shorter than candidate_pool_size still fell
# through into a hashtag search, and the results were then re-ranked by view
# count together. A playlist is an instruction, so it is now the whole list.
check("a playlist is the only thing scanned", _urls == [_PL], _urls)
check("channels are not searched behind it",
      not any("@somechannel" in u for u in _urls), _urls)
check("nor is a hashtag search", not any("hashtag" in u for u in _urls), _urls)
# But only a *usable* one takes over. A bad paste must not silently disable
# the channels and terms that would otherwise have worked.
_fallback = YouTubeSource({
    "source_playlists": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    "source_channels": ["@somechannel"],
    "channel_tabs": ["shorts"],
}).build_sources(["funny moments"])
check("an unusable paste falls back to channels and searches",
      any("@somechannel" in u for u in _fallback)
      and any("hashtag" in u for u in _fallback), _fallback)
check("an unusable link is dropped rather than scanned",
      YouTubeSource({"source_playlists":
                     ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]}
                    ).build_sources([]) == [], "a bad paste produced a URL")

# A playlist alone is a complete configuration: no search terms needed.
_only = YouTubeSource({"source_playlists": [_PL]}).build_sources([])
check("a playlist on its own is enough to look at", _only == [_PL], _only)

# Ranking. A search has nothing to go on but view count, but a playlist has an
# order somebody chose, and sorting that by popularity throws the choice away
# and opens every run with the same well-known clip.
from backend.app.sources.base import SourceClip as _SC  # noqa: E402


def _fake_clip(_vid, _views):
    _c = _SC(source="youtube", external_id=_vid, title=f"clip {_vid}",
             url=f"https://www.youtube.com/watch?v={_vid}", author="a",
             duration=30.0, licence="x", reusable=False,
             attribution_required=True)
    _c.extra = {"view_count": _views, "description": "", "age_days": None}
    return _c


# Deliberately not in view order, so the two rankings disagree.
_authored = [_fake_clip("aaaaaaaaaaa", 10),
             _fake_clip("bbbbbbbbbbb", 9_000_000),
             _fake_clip("ccccccccccc", 500)]


def _order_from(_cfg):
    _src = YouTubeSource(_cfg)
    _src.available = lambda: True
    _src._flat_scan = lambda url, limit: _authored
    _src.enrich = lambda clip: True
    return [_c.external_id for _c in _src.search(["anything"], 3)]


check("a playlist keeps the order its author put it in",
      _order_from({"source_playlists": [_PL]})
      == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"],
      _order_from({"source_playlists": [_PL]}))
check("a search still ranks by view count",
      _order_from({"source_channels": ["@c"]})
      == ["bbbbbbbbbbb", "ccccccccccc", "aaaaaaaaaaa"],
      _order_from({"source_channels": ["@c"]}))

_pl_cfg = {"sources": ["youtube"], "source_playlists": [_PL]}
check("a good playlist raises no blocker",
      review_cfg(sanitise(_pl_cfg), available_sources=["youtube"]).can_run)
check("a link with no playlist in it is a blocker",
      not review_cfg(sanitise({"sources": ["youtube"], "source_playlists": [
          "https://www.youtube.com/watch?v=dQw4w9WgXcQ"]}),
          available_sources=["youtube"]).can_run)
check("one bad link among good ones only warns",
      review_cfg(sanitise({"sources": ["youtube"], "source_playlists": [
          _PL, "https://www.youtube.com/watch?v=dQw4w9WgXcQ"]}),
          available_sources=["youtube"]).can_run)
check("playlists set without the YouTube source are flagged",
      any(f.title.startswith("Playlists are set")
          for f in review_cfg(sanitise({
              "sources": ["upload"], "clips": 3, "source_playlists": [_PL]}),
              upload_count=9,
              available_sources=["upload", "youtube"]).findings))

slow = review_cfg(sanitise({
    "sources": ["upload"], "clips": 3, "target_seconds": 180,
    "max_clip_seconds": 60, "checklist_enabled": True,
}), upload_count=10)
check("a static edit is warned about",
      any("pace" in f.title.lower() for f in slow.findings),
      [f.title for f in slow.findings][:2])

silent = review_cfg(sanitise({
    "sources": ["upload"], "clips": 6, "target_seconds": 60,
    "captions_enabled": False, "checklist_enabled": False,
    "banner_enabled": False,
}), upload_count=10)
check("no on-screen text is warned about",
      any("read" in f.title.lower() for f in silent.findings),
      [f.title for f in silent.findings][:2])

section("layout preview")
from backend.app.render import preview as preview_mod  # noqa: E402

frame = preview_mod.build(sanitise({
    "clips": 5, "banner_line1": "TOP {count}", "checklist_enabled": True,
    "captions_enabled": True, "search_terms": ["first thing", "second thing"],
}), at_clip=3)
check("renders a PNG", frame[:8] == b"\x89PNG\r\n\x1a\n", frame[:4])
check("of a sensible size", 5_000 < len(frame) < 400_000, f"{len(frame):,} bytes")

bare = preview_mod.build(sanitise({
    "clips": 3, "banner_enabled": False, "checklist_enabled": False,
    "captions_enabled": False,
}), at_clip=1)
check("works with every overlay switched off",
      bare[:8] == b"\x89PNG\r\n\x1a\n")

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

# sync is deliberately lenient: with no Stripe customer there is nothing to
# ask about, so it reports the current plan rather than erroring.
_sync = client.post("/api/billing/sync")
check("sync answers without Stripe configured", _sync.status_code == 200,
      _sync.status_code)
check("and reports the current plan", _sync.json().get("plan") == "free",
      _sync.json())
check("sync needs a session",
      TestClient(app).post("/api/billing/sync").status_code == 401)

# Where Stripe sends somebody after they pay. This was "/", the marketing
# page, which has no handling for ?billing=success and no sign-in state on
# screen: a completed purchase looked like being thrown out of the product.
_billing_src = Path("backend/app/routes/billing.py").read_text(encoding="utf-8")
check("checkout returns you to the app, not the landing page",
      '/app?billing=success' in _billing_src)
check("and so does cancelling",
      '/app?billing=cancelled' in _billing_src)
check("no redirect still points at the landing page",
      '"/?billing=' not in _billing_src.replace("'", '"'))
check("the app rewrites the url to /app afterwards",
      "'/app'" in Path("frontend/app.js").read_text(encoding="utf-8")
      .split("billing === 'success'")[1][:900])

# Relying on one webhook event is fragile: an operator who subscribed only to
# checkout events would have seen nothing happen.
check("checkout.session.completed is handled",
      "checkout.session.completed" in _billing_src)
check("subscription events still are",
      "customer.subscription.created" in _billing_src
      and "customer.subscription.deleted" in _billing_src)

# The plan is applied from a subscription object without any Stripe call, so
# this half is testable directly -- and it is the half that decides the plan.
from backend.app.routes.billing import _apply_subscription, _find_user  # noqa: E402

_buyer = TestClient(app)
_buyer.post("/api/auth/signup",
            json={"email": "buyer@example.com", "password": "buyer-pass-77"})
with session_scope() as _db:
    _b = _db.query(User).filter(User.email == "buyer@example.com").one()
    _bid, _ = _b.id, _b.stripe_customer_id
    _b.stripe_customer_id = "cus_test_123"
    check("a new account starts free", _b.plan == Plan.FREE, _b.plan)

# The price has to be one this server recognises, or _plan_for_price returns
# None and the account is left alone -- which is the failure mode below.
settings.stripe_price_pro = "price_test_pro"
settings.stripe_price_starter = "price_test_starter"
_sub = {
    "id": "sub_test_1", "status": "active", "customer": "cus_test_123",
    "metadata": {"user_id": str(_bid)},
    "items": {"data": [{"price": {"id": "price_test_pro"}}]},
}
with session_scope() as _db:
    _apply_subscription(_db, _sub)
with session_scope() as _db:
    _b = _db.get(User, _bid)
    check("an active pro subscription makes the account pro",
          _b.plan == Plan.PRO, _b.plan)
    check("and the subscription id is kept",
          _b.stripe_subscription_id == "sub_test_1")
    check("and the allowance resets for the new period",
          _b.renders_this_period == 0)

# The webhook must find the account even when the metadata is missing, which
# is the case for events Stripe generates itself later on.
with session_scope() as _db:
    check("the customer id alone identifies the account",
          _find_user(_db, {"customer": "cus_test_123"}) is not None)
    check("and an unknown customer resolves to nobody",
          _find_user(_db, {"customer": "cus_nobody"}) is None)

# A price the server does not recognise is how somebody ends up paying and
# staying free. It must not silently succeed.
with session_scope() as _db:
    _apply_subscription(_db, {**_sub, "items": {"data": [
        {"price": {"id": "price_someone_changed_in_stripe"}}]}})
with session_scope() as _db:
    check("an unknown price leaves the plan alone rather than downgrading",
          _db.get(User, _bid).plan == Plan.PRO,
          _db.get(User, _bid).plan)

# Objects from the Stripe SDK are not dictionaries. Reading .get("data") on
# one raises KeyError: 'get' -- attribute lookup misses, __getattr__ forwards
# to __getitem__, and there is no key named "get". This 500'd a real purchase,
# and could not be caught by any test that did not model the object properly.
from backend.app.routes.billing import _plain  # noqa: E402


class _StripeLike:
    """No .get, attribute access forwards to keys, lists left unconverted."""

    def __init__(self, data):
        self._data = dict(data)

    def __getattr__(self, key):
        try:
            return self._data[key]
        except KeyError:
            raise KeyError(key)

    def to_dict_recursive(self):
        return {k: (v.to_dict_recursive() if isinstance(v, _StripeLike) else v)
                for k, v in self._data.items()}


_raised = ""
try:
    _StripeLike({"data": []}).get("data")
except KeyError as _exc:
    _raised = str(_exc)
check("the failure mode is reproduced", "get" in _raised, _raised)

_fake_sub = _StripeLike({
    "id": "sub_stripeobj", "status": "active", "customer": "cus_test_123",
    "metadata": {"user_id": str(_bid)},
    "items": _StripeLike({"data": [
        _StripeLike({"price": _StripeLike({"id": "price_test_starter"})})]}),
})

check("_plain returns a real dict", isinstance(_plain(_fake_sub), dict))
check("and converts nested objects too",
      isinstance(_plain(_fake_sub)["items"], dict))
check("_plain of None is an empty dict", _plain(None) == {})
check("_plain of a plain dict is unchanged", _plain({"a": 1}) == {"a": 1})

# The whole point: a Stripe-shaped object must apply without raising.
with session_scope() as _db:
    _apply_subscription(_db, _fake_sub)
with session_scope() as _db:
    check("a Stripe object applies its plan without a 500",
          _db.get(User, _bid).plan == Plan.STARTER, _db.get(User, _bid).plan)

# Put it back to pro for the cancellation check below.
with session_scope() as _db:
    _apply_subscription(_db, _sub)

# Cancelling has to take it away again.
with session_scope() as _db:
    _apply_subscription(_db, {**_sub, "status": "canceled"})
with session_scope() as _db:
    check("a cancelled subscription drops back to free",
          _db.get(User, _bid).plan == Plan.FREE)



section("setup asks the question that decides the outcome")
# Where footage comes from used to be asked only by the "One TV show" preset,
# because the step was gated on require_show_match and that is the only preset
# which sets it. Somebody picking "a ranked countdown" -- the first and most
# obvious option -- was never asked, and fell through to a keyword search.
# That is the configuration that produced four finished videos which were
# mostly not the show at all.
_APP = Path("frontend/app.js").read_text(encoding="utf-8")

check("the sourcing question is its own step",
      "Where do the clips come from?" in _APP)
check("and is not gated on the show filter any more",
      "skipUnless: () => state.settings.require_show_match" not in _APP,
      "that gate is what hid it from six of the seven presets")
check("the playlist step follows the sourcing answer, not the preset",
      "skipUnless: () => guideChoice.source === 'playlist'" in _APP)
check("and the upload path asks for search terms instead",
      "skipUnless: () => guideChoice.source !== 'playlist'" in _APP)

# Setup before the tour. The tour explains the product; the guide configures
# it. Until now the explaining was automatic and the configuring sat behind a
# link, so a new subscriber met a 79-field form before being asked anything.
check("a new account is taken through setup, not the tour",
      "openGuide({ firstRun: true })" in _APP)
check("and the tour still runs, after setup rather than before",
      "if (guideFirstRun)" in _APP and "openTour();" in _APP)
check("the playlist option is hidden when the server cannot use YouTube",
      "youtubeUsable()" in _APP,
      "offering it would walk somebody into a source the registry refuses")

# Choosing your own footage must not leave the show filter on with nothing to
# match against, which rejects every clip and blocks the run.
check("picking uploads turns off a show filter it cannot satisfy",
      "state.settings.require_show_match = false" in _APP)

# The gap that opens up once "a YouTube playlist" is the default answer: it is
# possible to choose it and paste nothing, which falls back to keyword search.
_no_list = _review({"sources": ["youtube", "upload"], "clips": 5,
                    "target_seconds": 120, "max_clip_seconds": 32,
                    "banner_enabled": True})
check("choosing YouTube and pasting no playlist refuses the run",
      not _no_list.can_run, [f.title for f in _no_list.findings])
_with_list = _review({"sources": ["youtube", "upload"], "clips": 5,
                      "target_seconds": 120, "max_clip_seconds": 32,
                      "banner_enabled": True, "moments_per_video": 2,
                      "source_playlists":
                          ["https://www.youtube.com/playlist?list=PLabc123def456"]})
check("and is silent once a playlist is pasted",
      _with_list.can_run, [f.title for f in _with_list.findings])
check("uploads-only is not nagged about playlists",
      not any("playlist" in f.title.lower()
              for f in _review({"sources": ["upload"], "clips": 5,
                                "target_seconds": 120, "max_clip_seconds": 32,
                                "banner_enabled": True},
                               upload_count=6).findings))

# Choosing "a YouTube playlist" and then pasting nothing lands on exactly the
# configuration the step exists to prevent. The advice does say so on the last
# step, but by then it reads as a complaint about a decision already taken.
check("an empty playlist will not advance the step",
      "Paste a playlist link, or go back" in _APP)
check("nor will a plain video link, which is the usual mistake",
      "That is not a playlist link" in _APP)
check("finishing is refused on a blocking configuration",
      "f.level === 'blocker'" in _APP,
      "the comment above GUIDE has always claimed this and nothing enforced it")
check("the setup modal scrolls so its buttons stay reachable",
      "guide-scroll" in Path("frontend/index.html").read_text(encoding="utf-8")
      and "min-height: 0" in Path("frontend/styles.css").read_text(encoding="utf-8"),
      "Save and finish sat at y=762 in a 720px window")

# The configuration the guide's playlist path produces has to actually run.
_guided = sanitise({**next(n for n in _BUILTINS if n["slug"] == "top5")["settings"],
                    "sources": ["youtube", "upload"],
                    "source_playlists":
                        ["https://www.youtube.com/playlist?list=PLabc123def456"]})
check("what the playlist path produces can run",
      _review(_guided, upload_count=0,
              available_sources=["upload", "youtube"]).can_run,
      [f.title for f in _review(_guided, upload_count=0,
                                available_sources=["upload", "youtube"]).findings
       if f.level == "blocker"])

section("a blind YouTube search is refused, not filtered")
# Three rounds of filtering were tried on this pool. The derivative list grew
# to sixty terms, the show filter learned to count regulars, video-essay
# openers were added by name -- and the same three clips kept coming back: a
# schoolwork video about the scientific method, a scene from the Andrew
# Garfield film, and somebody's edit with WAVYPAUSED burned into it. Every one
# is an honest match for "spectacular spider-man funny". The pool is the
# problem, and no filter recovers from a pool that is mostly the wrong thing.
_BASE = {"clips": 5, "target_seconds": 120, "max_clip_seconds": 32,
         "banner_enabled": True}


def _can_run(**extra):
    return _review({**_BASE, **extra}, upload_count=6,
                   available_sources=["upload", "youtube"]).can_run


check("YouTube with nothing naming what to use is refused",
      not _can_run(sources=["youtube", "upload"]))
check("a playlist is a decision, and is honoured",
      _can_run(sources=["youtube", "upload"], moments_per_video=2,
               source_playlists=["https://www.youtube.com/playlist?list=PLabc123def456"]))
check("so is a named channel",
      _can_run(sources=["youtube", "upload"], source_channels=["@somechannel"]))
check("uploads-only is untouched by any of this",
      _can_run(sources=["upload"]))
check("and the refusal says what to do about it",
      any("Paste a playlist" in f.fix for f in
          _review({**_BASE, "sources": ["youtube", "upload"]},
                  upload_count=6).findings if f.level == "blocker"))

# The advice is consulted by exactly one route. The API creates jobs without
# it and the daily scheduler never sees it, so somebody who set automation up
# once would go on producing these every morning. The refusal has to live
# where every path passes through.
from backend.app.render.pipeline import (  # noqa: E402
    _refuse_blind_search as _refuse,
)
from backend.app.render.engine import RenderError as _RE  # noqa: E402


class _YT:
    name = "youtube"


class _Up:
    name = "upload"


def _refused(settings_dict, adapters):
    try:
        _refuse(settings_dict, adapters)
        return False
    except _RE:
        return True


check("the pipeline refuses it too, not just the button",
      _refused({}, [_YT()]))
check("a playlist gets through the pipeline gate",
      not _refused({"source_playlists": ["PLabc123def456ghi"]}, [_YT()]))
check("a channel gets through the pipeline gate",
      not _refused({"source_channels": ["@somechannel"]}, [_YT()]))
check("and a job with no YouTube source is never affected",
      not _refused({}, [_Up()]))
check("blank entries do not count as naming anything",
      _refused({"source_playlists": ["", "  "], "source_channels": [""]}, [_YT()]))

# "Is the fix live yet?" was answerable only by watching behaviour change --
# and when behaviour did not change, a deploy that had not happened looked
# exactly like a fix that had not worked.
_health = client.get("/api/health").json()
check("health reports which commit is running", "build" in _health, _health)
check("and says so even outside a deployment", bool(_health["build"]), _health)

section("a video that goes nowhere says why")
# "Publish now" rendering a file that never reached the channel, with the run
# marked done and nothing anywhere explaining it. Three separate conditions
# have to hold before a video is uploaded, and when one did not the only
# record was the word "skipped" -- which reads identically whether it was a
# dry run, whether publishing is switched off in settings, whether no channel
# is connected, or whether the server has no Google credentials at all.
from backend.app.worker import _upload_decision as _decide  # noqa: E402
import backend.app.youtube as _yt  # noqa: E402

_ON = {"auto_upload": True}
_saved_configured = _yt.configured

check("a dry run says it was a dry run",
      _decide(_ON, dry_run=True, refresh_token="t")[1].startswith("Dry run"),
      _decide(_ON, dry_run=True, refresh_token="t")[1])
check("the setting being off says so, and names the setting",
      "Publish after rendering" in
      _decide({"auto_upload": False}, dry_run=False, refresh_token="t")[1])

_yt.configured = lambda user=None: False
try:
    _wants, _why = _decide(_ON, dry_run=False, refresh_token="t")
    check("no Google project anywhere says so, and points at the setup",
          not _wants and "publishing setup" in _why, _why)
    check("but an account with its own project is not stopped by that",
          _decide(_ON, dry_run=False, refresh_token="t",
                  google_app=("id.apps.googleusercontent.com", "sec"))[0],
          "their project is the one that matters, not the server's")
finally:
    _yt.configured = _saved_configured

_yt.configured = lambda user=None: True
try:
    _wants, _why = _decide(_ON, dry_run=False, refresh_token="")
    check("no connected channel says that instead", not _wants
          and "no YouTube account is connected" in _why, _why)
    check("and with everything in place it uploads, saying nothing",
          _decide(_ON, dry_run=False, refresh_token="t") == (True, ""))
finally:
    _yt.configured = _saved_configured

# The reason has to name the thing the reader can change, so the subscriber's
# own settings are checked before the server's configuration.
_yt.configured = lambda user=None: False
try:
    check("their own setting is named before the server's",
          "Publish after rendering" in
          _decide({"auto_upload": False}, dry_run=False, refresh_token="")[1])
finally:
    _yt.configured = _saved_configured

# The Home screen said "Ready" while promising a publish it could not make.
from backend.app.routes.studio import _readiness  # noqa: E402


class _U:
    id = 1
    youtube_connected = False
    youtube_channel_title = ""


_yt2 = None
import backend.app.routes.studio as _studio_mod  # noqa: E402

_saved_studio_yt = _studio_mod.youtube.configured
_studio_mod.youtube.configured = lambda user=None: False
try:
    _rows = {r["id"]: r for r in _readiness(_U(), {"auto_upload": True,
                                                   "sources": ["upload"]})}
    check("with publishing off the server and auto-upload on, it needs action",
          _rows["youtube"]["state"] == "action", _rows["youtube"])
    check("and says the videos will go nowhere",
          "go nowhere" in _rows["youtube"]["detail"], _rows["youtube"]["detail"])
    _quiet = {r["id"]: r for r in _readiness(_U(), {"auto_upload": False,
                                                    "sources": ["upload"]})}
    check("but it stays quiet for somebody not asking to publish",
          _quiet["youtube"]["state"] == "off", _quiet["youtube"])
finally:
    _studio_mod.youtube.configured = _saved_studio_yt

# Diagnosable from outside, without logging in as anybody.
_h = client.get("/api/health").json()
check("health says whether this server can publish at all",
      "publishing" in _h and isinstance(_h["publishing"], bool), _h)

section("each account publishes on its own Google project")
# One shared project is 10,000 API units a day and an upload costs 1,600 --
# about six uploads a day across every customer there will ever be. Raising
# that needs an audit of an app that downloads YouTube videos, which is not an
# audit anybody passes. A project the subscriber owns has its own ceiling and
# needs nothing from anybody.
import backend.app.youtube as _ytm  # noqa: E402


class _Acct:
    def __init__(self, cid="", secret=""):
        self.google_client_id = cid
        self.google_client_secret = secret

    @property
    def has_google_app(self):
        return bool(self.google_client_id and self.google_client_secret)


_theirs = _Acct("theirs.apps.googleusercontent.com", "GOCSPX-theirs")
check("an account's own client is preferred",
      _ytm.credentials_for(_theirs)[0] == "theirs.apps.googleusercontent.com")
check("and it counts as configured even when the server is not",
      _ytm.configured(_theirs))
check("an account without one falls back to the server",
      _ytm.credentials_for(_Acct()) == (settings.google_client_id,
                                        settings.google_client_secret))
check("half a client is not a client",
      not _ytm.configured(_Acct("only-an-id.apps.googleusercontent.com", "")))
check("the client config carries their pair, not the server's",
      _ytm._client_config(_theirs)["web"]["client_secret"] == "GOCSPX-theirs")

# A refresh token belongs to the client that issued it: renewing it against a
# different client_id fails with invalid_client, so the pair that made the
# token has to be the pair that renews it.
_creds_seen = {}


class _FakeCreds:
    def __init__(self, **kw):
        _creds_seen.update(kw)


_saved_libs = _ytm._require_libs
_ytm._require_libs = lambda: (_FakeCreds, None, None, None, None)
try:
    _ytm._credentials("refresh-abc", "theirs.apps.googleusercontent.com",
                      "GOCSPX-theirs")
    check("refreshing uses the client that issued the token",
          _creds_seen["client_id"] == "theirs.apps.googleusercontent.com",
          _creds_seen.get("client_id"))
finally:
    _ytm._require_libs = _saved_libs

# The endpoints. A secret goes in and never comes back out.
_r = client.put("/api/youtube/app", json={
    "client_id": "1234.apps.googleusercontent.com",
    "client_secret": "GOCSPX-a-real-looking-secret"})
check("credentials save", _r.status_code == 200, _r.text[:120])
_got = client.get("/api/youtube/app").json()
check("the client id is readable, so a typo can be spotted",
      _got["client_id"] == "1234.apps.googleusercontent.com", _got)
check("the secret is never returned, only its presence",
      _got["has_secret"] is True and "client_secret" not in _got, _got)
check("and the account now counts as configured", _got["configured"] is True)
check("the redirect address is given, because it must match exactly",
      _got["redirect_uri"].endswith("/api/youtube/callback"), _got)

_bad = client.put("/api/youtube/app", json={"client_id": "12345",
                                            "client_secret": "x"})
check("something that is not a client id is refused", _bad.status_code == 422)
check("and says which field is wrong and where to find it",
      "apps.googleusercontent.com" in _bad.json()["detail"], _bad.json())

# Re-saving without retyping the secret must not wipe it.
client.put("/api/youtube/app", json={
    "client_id": "5678.apps.googleusercontent.com", "client_secret": ""})
check("a blank secret leaves the stored one alone",
      client.get("/api/youtube/app").json()["has_secret"] is True)
check("but the new id is stored",
      client.get("/api/youtube/app").json()["client_id"]
      == "5678.apps.googleusercontent.com")

# Changing the client invalidates the channel connection: the old refresh
# token cannot be renewed by a new client, and Google answers invalid_client.
with session_scope() as _db:
    _u = _db.query(User).filter(User.email == "tester@example.com").one()
    _u.youtube_refresh_token = "old-token"
    _u.youtube_channel_title = "Old Channel"
client.put("/api/youtube/app", json={
    "client_id": "9999.apps.googleusercontent.com",
    "client_secret": "GOCSPX-new"})
with session_scope() as _db:
    _u = _db.query(User).filter(User.email == "tester@example.com").one()
    check("changing the client drops a connection it could not renew",
          not _u.youtube_refresh_token, _u.youtube_refresh_token)

# Clearing the id clears the secret with it, rather than leaving an orphan.
client.put("/api/youtube/app", json={"client_id": "", "client_secret": ""})
_cleared = client.get("/api/youtube/app").json()
check("clearing the id clears the secret too",
      _cleared["has_secret"] is False and _cleared["configured"] is False,
      _cleared)

# The home screen has to send people to the right place: there is nothing to
# sign in to until a project exists.
_rows = {r["id"]: r for r in client.get("/api/studio").json()["status"]}
check("with no project the row offers the walkthrough",
      _rows["youtube"].get("action") == "setup-publishing", _rows["youtube"])
client.put("/api/youtube/app", json={
    "client_id": "1111.apps.googleusercontent.com",
    "client_secret": "GOCSPX-x"})
_rows = {r["id"]: r for r in client.get("/api/studio").json()["status"]}
check("with a project it offers the sign-in instead",
      _rows["youtube"].get("action") == "connect", _rows["youtube"])
client.put("/api/youtube/app", json={"client_id": "", "client_secret": ""})

# The walkthrough itself.
_APPJS = Path("frontend/app.js").read_text(encoding="utf-8")
check("the setup is six steps with drawings of the console",
      "PUB_STEPS" in _APPJS and "PUB_ART" in _APPJS)
check("the redirect address is offered to copy, not retyped",
      "pub-copy-btn" in _APPJS and "navigator.clipboard" in _APPJS)
check("the test-user trap is called out, since it is what blocks sign-in",
      "Access blocked" in _APPJS)
check("and there is a way out for somebody who will not publish",
      "pub-skip" in _APPJS and "auto_upload = false" in _APPJS)
check("publishing setup follows the niche setup on a first run",
      "pubThenTour" in _APPJS)

section("an expired channel connection says so and asks for one click")
# Until a subscriber's Google project is verified, its refresh tokens expire
# after seven days. So this is the ordinary end of a connection rather than a
# rare fault: it works all week, then uploads start failing with whatever
# Google's client library happened to raise, and the home screen goes on
# saying "Not connected" as though setup was never finished.
from backend.app.youtube import (  # noqa: E402
    YouTubeAuthError as _AuthErr, _is_auth_failure as _is_auth,
)


class _Resp:
    def __init__(self, status):
        self.status = status


class _Http(Exception):
    def __init__(self, status, message=""):
        super().__init__(message or f"HTTP {status}")
        self.resp = _Resp(status)


class RefreshError(Exception):
    """Named to match what google.auth actually raises."""


for _name, _exc in [
    ("google's own RefreshError", RefreshError("invalid_grant")),
    ("an invalid_grant message", Exception("invalid_grant: bad")),
    ("a revoked token", Exception("Token has been expired or revoked.")),
    ("the wrong client", Exception("unauthorized_client")),
    ("a 401", _Http(401)),
]:
    check(f"a dead connection is recognised: {_name}", _is_auth(_exc))

for _name, _exc in [
    ("a server wobble", _Http(503)),
    ("a rate limit", _Http(429, "quotaExceeded")),
    ("a broken pipe", OSError("connection reset by peer")),
    ("a missing file", Exception("The rendered file is missing.")),
]:
    check(f"but a retriable failure is not: {_name}", not _is_auth(_exc))

check("quota exhaustion is not mistaken for a dead login",
      not _is_auth(_Http(403, "quotaExceeded")),
      "the fix for that is waiting, not signing in again")

# The whole point of the separate type: retrying a dead token spends five
# backoffs -- about a minute of a render worker -- to arrive at the same
# answer, with the cause buried under "Upload failed".
check("it is refused immediately rather than retried",
      issubclass(_AuthErr, Exception) and _AuthErr is not Exception)

# What the subscriber is told, in one sentence, in all three places.
from backend.app.youtube import _AUTH_MESSAGE as _MSG  # noqa: E402

check("the message says what happened and what to do",
      "expired" in _MSG and "Reconnect" in _MSG, _MSG)

# A connection that cannot be renewed is cleared, so the home screen stops
# claiming a channel is attached and offers the one click that fixes it.
# A project has to exist before a connection to it can expire.
client.put("/api/youtube/app", json={
    "client_id": "4444.apps.googleusercontent.com",
    "client_secret": "GOCSPX-four"})
with session_scope() as _db:
    _u = _db.query(User).filter(User.email == "tester@example.com").one()
    _u.youtube_refresh_token = "dead-token"
    _u.youtube_channel_title = "Some Channel"
    _u.youtube_disconnected_reason = ""

_rows = {r["id"]: r for r in client.get("/api/studio").json()["status"]}
check("while it looks alive the row is ready",
      _rows["youtube"]["state"] == "ready", _rows["youtube"])

with session_scope() as _db:
    _u = _db.query(User).filter(User.email == "tester@example.com").one()
    _u.youtube_refresh_token = None
    _u.youtube_channel_title = ""
    _u.youtube_disconnected_reason = _MSG

_rows = {r["id"]: r for r in client.get("/api/studio").json()["status"]}
check("once it dies the row explains rather than saying 'Not connected'",
      "expired" in _rows["youtube"]["detail"], _rows["youtube"])
check("and still offers the sign-in",
      _rows["youtube"]["action"] == "connect", _rows["youtube"])
check("the reason reaches the export too",
      "expired" in client.get("/api/me/export").json()["youtube"]
      ["disconnected_reason"])

# Disconnecting on purpose is not an expiry, and must not be explained as one.
client.post("/api/youtube/disconnect")
_rows = {r["id"]: r for r in client.get("/api/studio").json()["status"]}
check("a deliberate disconnect leaves no expiry notice behind",
      _rows["youtube"]["detail"] == "Not connected", _rows["youtube"])

# Saving new credentials invalidates the sign-in, and says which of the two
# reasons that is.
client.put("/api/youtube/app", json={
    "client_id": "2222.apps.googleusercontent.com",
    "client_secret": "GOCSPX-two"})
with session_scope() as _db:
    _u = _db.query(User).filter(User.email == "tester@example.com").one()
    _u.youtube_refresh_token = "t"
client.put("/api/youtube/app", json={
    "client_id": "3333.apps.googleusercontent.com",
    "client_secret": "GOCSPX-three"})
_rows = {r["id"]: r for r in client.get("/api/studio").json()["status"]}
check("changing credentials explains itself as its own reason",
      "credentials" in _rows["youtube"]["detail"], _rows["youtube"])

# And connecting again clears whatever was said before.
with session_scope() as _db:
    _u = _db.query(User).filter(User.email == "tester@example.com").one()
    _u.youtube_refresh_token = "fresh"
    _u.youtube_channel_title = "Reconnected"
    _u.youtube_disconnected_reason = ""
_rows = {r["id"]: r for r in client.get("/api/studio").json()["status"]}
check("a working connection says the channel name and nothing else",
      _rows["youtube"]["state"] == "ready"
      and _rows["youtube"]["detail"] == "Reconnected", _rows["youtube"])
client.post("/api/youtube/disconnect")
client.put("/api/youtube/app", json={"client_id": "", "client_secret": ""})

section("the watermark names a domain we actually own")
# It was the same literal in three files -- the worker, the studio route and
# the agent's claim payload -- and it named clipforge.app, which is a parked
# reseller page belonging to somebody else. Every free-plan video published
# was advertising a stranger's ad inventory.
from backend.app.config import settings as _cfg  # noqa: E402

_SRC = {name: Path(f"backend/app/{name}").read_text(encoding="utf-8")
        for name in ("worker.py", "routes/studio.py", "routes/agent.py")}
for _name, _text in _SRC.items():
    check(f"{_name} no longer hardcodes a domain",
          '"clipforge.app"' not in _text and '"clipforgee.app"' not in _text)
    check(f"{_name} reads the one setting",
          "settings.watermark" in _text)
check("which has a default", bool(_cfg.watermark), _cfg.watermark)
check("and the default is a domain we bought",
      _cfg.watermark == "clipforgee.app", _cfg.watermark)
check("it can be changed without a deploy",
      "WATERMARK_TEXT" in Path("backend/app/config.py").read_text(encoding="utf-8"),
      "a domain can change faster than a release")

# The agent's fallback server. Moving it is safe because pairing writes the
# server it paired against into agent.env, so an installed agent keeps using
# that; only a fresh download reads the default.
_AGENT = Path("agent/config.py").read_text(encoding="utf-8")
check("a fresh agent install points at the real domain",
      "https://clipforgee.app" in _AGENT)
check("and pairing still persists whatever it paired against",
      'values["CLIPFORGE_SERVER"] = server' in _AGENT,
      "which is why changing the default cannot strand an existing install")


section("the setup guide has a page of its own")
# The Google Cloud half of setup happens on somebody else's website, which
# makes a dialog the wrong container for it: it cannot be read on a second
# screen, cannot be sent to whoever actually administers the Google account,
# and cannot be found again by somebody who closed it.
_conn = client.get("/connect")
check("the guide is served", _conn.status_code == 200, _conn.status_code)
_html = _conn.text
check("it is a real page, not the app shell",
      "Connect your channel" in _html and "<title>" in _html)
check("all seven steps are there",
      _html.count('class="cx-step"') == 7, _html.count('class="cx-step"'))

# Promoted out of a warning inside step 3, because the first person to follow
# the guide skipped it there and lost an hour to Access blocked. A numbered
# walkthrough teaches you that the numbers are the work and the prose between
# them is commentary, so the thing that decides whether setup finishes has to
# be a number.
check("adding a test user is a step of its own, not a footnote",
      "<h2>Add yourself as a test user</h2>" in _html)
check("and the walkthrough has it too, so the two cannot diverge",
      "title: 'Add yourself as a test user'"
      in Path("frontend/app.js").read_text(encoding="utf-8"))
check("it explains why Google's own error misleads",
      "talks about verification rather than test users" in _html)

# The address has to reach Google's field exactly, so it is generated from the
# server's own configuration rather than typed into the page. Hardcoding it
# is how a guide ends up naming the domain the product used to be on.
check("no placeholder survives into the served page", "__ORIGIN__" not in _html)
check("the redirect address is built from PUBLIC_URL",
      f"{settings.public_url}/api/youtube/callback" in _html,
      settings.public_url)
check("and it can be copied rather than retyped",
      'id="cx-copy"' in _html and "clipboard" in _html)

# The two things that silently stop a setup finishing.
_flat = " ".join(_html.split())
check("the test-user trap is called out",
      "Access blocked" in _flat and "Test users" in _flat)
check("so is the exact-match rule on the address",
      "redirect_uri_mismatch" in _html)

check("it is discoverable", "/connect" in client.get("/sitemap.xml").text)
check("and reachable from the walkthrough",
      'href="/connect"' in Path("frontend/app.js").read_text(encoding="utf-8"))

# A <b> that merely opens a paragraph is not a section label. Without the
# child combinator, "Audience > Test users" mid-sentence rendered as an
# uppercase orange block.
_css = Path("frontend/connect.css").read_text(encoding="utf-8")
check("the trap label styles only its own heading",
      ".cx-trap > b:first-child" in _css and ".cx-trap b:first-child {" not in _css)


section("a new account is told to make its own Google project")
# The regression that made bring-your-own-credentials invisible. The server's
# credentials were an unconditional fallback, so on any deployment whose
# operator had configured Google -- which is every deployment that publishes
# anything -- a brand-new subscriber read as already set up. The walkthrough
# never appeared, the home screen offered "Connect" instead of "Set up
# publishing", and anybody who did connect spent the operator's quota. It
# looked like it worked, for about six uploads a day between everyone.
import backend.app.youtube as _yt3  # noqa: E402

_saved_pair = (settings.google_client_id, settings.google_client_secret)
_saved_shared = settings.shared_google_app
settings.google_client_id = "server.apps.googleusercontent.com"
settings.google_client_secret = "GOCSPX-server"
settings.shared_google_app = False


def _acct(own=False, admin=False):
    class A:
        google_client_id = "mine.apps.googleusercontent.com" if own else ""
        google_client_secret = "GOCSPX-mine" if own else ""
        is_admin = admin

        @property
        def has_google_app(self):
            return bool(self.google_client_id and self.google_client_secret)
    return A()


try:
    check("a new subscriber does not inherit the server's project",
          not _yt3.configured(_acct()),
          "otherwise nothing ever asks them to make their own")
    check("and is given no credentials to publish with",
          _yt3.credentials_for(_acct()) == ("", ""))
    check("their own project is used once they have one",
          _yt3.credentials_for(_acct(own=True))[0]
          == "mine.apps.googleusercontent.com")
    check("the operator still falls back to the server's",
          _yt3.credentials_for(_acct(admin=True))[0]
          == "server.apps.googleusercontent.com",
          "so a single-operator install keeps working")

    settings.shared_google_app = True
    check("and a single-tenant install can opt everyone back in",
          _yt3.configured(_acct()),
          "ALLOW_SHARED_GOOGLE_APP, for a deployment with one account")
    settings.shared_google_app = False

    # What the home screen tells them, which is the part that was missing.
    _rows = {r["id"]: r for r in client.get("/api/studio").json()["status"]}
    check("the row sends them to the walkthrough, not to a sign-in",
          _rows["youtube"].get("action") == "setup-publishing", _rows["youtube"])
    check("and says what happens if they skip it",
          "go nowhere" in _rows["youtube"]["detail"], _rows["youtube"]["detail"])
    check("the screen stops claiming it is ready",
          "YouTube account" in client.get("/api/studio").json()["blocked_by"])
finally:
    settings.google_client_id, settings.google_client_secret = _saved_pair
    settings.shared_google_app = _saved_shared

check("sharing is off unless a deployment asks for it",
      _saved_shared is False,
      "the default that makes each account bring its own project")


section("first-run tour")
check("a new account has not seen it",
      client.get("/api/studio").json()["onboarded"] is False)
check("marking it seen sticks",
      client.post("/api/studio/onboarded?seen=true").json()["onboarded"] is True)
check("and it stays seen", client.get("/api/studio").json()["onboarded"] is True)
check("it can be replayed",
      client.post("/api/studio/onboarded?seen=false").json()["onboarded"] is False)
client.post("/api/studio/onboarded?seen=true")

section("waiting for the database")
from backend.app.db import wait_for_database  # noqa: E402

start = time.time()
wait_for_database(timeout=5)
check("returns immediately when the database is up", time.time() - start < 2,
      f"{time.time() - start:.2f}s")

# A container often starts before its network does; the app must retry rather
# than crash-loop, but still give up eventually instead of hanging forever.
import sqlalchemy  # noqa: E402

import backend.app.db as db_module  # noqa: E402

real_engine = db_module.engine
db_module.engine = sqlalchemy.create_engine(
    "postgresql+psycopg://nobody:nobody@127.0.0.1:1/none")
start = time.time()
try:
    wait_for_database(timeout=2)
    check("gives up on an unreachable database", False, "did not raise")
except Exception:
    elapsed = time.time() - start
    check("retries then gives up on an unreachable database",
          2 <= elapsed < 12, f"{elapsed:.1f}s")
finally:
    db_module.engine = real_engine

section("public url always carries a scheme")
from backend.app.config import _normalise_public_url as pub  # noqa: E402

# A hosting dashboard shows the domain without a scheme, so pasting a bare host
# is the obvious mistake -- and it makes Stripe reject checkout with a 500.
check("bare host gets https", pub("example.up.railway.app")
      == "https://example.up.railway.app")
check("https is left alone", pub("https://x.com") == "https://x.com")
check("http is left alone", pub("http://x.com") == "http://x.com")
check("localhost gets http, not https", pub("localhost:8000")
      == "http://localhost:8000")
check("127.0.0.1 gets http", pub("127.0.0.1:8000") == "http://127.0.0.1:8000")
check("trailing slash removed", pub("https://x.com/") == "https://x.com")
check("empty stays empty", pub("") == "")

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

# The backfill has to be a literal the column's own type accepts, and that
# cannot be checked on SQLite -- which is the whole reason this shipped.
# SQLite takes 0 into a JSON column and FALSE into anything, so the suite was
# green while production said
#
#     column "sourcing_report" is of type json
#     but default expression is of type integer
#
# The ALTER failed, the failure was logged at warning, startup carried on, and
# the first query against jobs took the app down with a traceback pointing at
# the render worker. So this checks every column against the PostgreSQL
# dialect, without needing a PostgreSQL to talk to.
import json as _json  # noqa: E402

from sqlalchemy import Boolean as _Bool, Integer as _Int  # noqa: E402
from sqlalchemy import Numeric as _Num, String as _Str  # noqa: E402
from sqlalchemy import types as _sa_types  # noqa: E402
from sqlalchemy.dialects import postgresql as _pg  # noqa: E402

from backend.app.db import _backfill_default  # noqa: E402
from backend.app.models import Base as _Base  # noqa: E402

_bad_json, _bad_bool, _checked = [], [], 0
for _table in _Base.metadata.sorted_tables:
    for _col in _table.columns:
        _lit = _backfill_default(_col)
        if not _lit:
            continue
        _checked += 1
        _where = f"{_table.name}.{_col.name}"
        if isinstance(_col.type, _sa_types.JSON):
            try:
                _json.loads(_lit.strip("'"))
            except ValueError:
                _bad_json.append(f"{_where}={_lit}")
        elif isinstance(_col.type, _Bool) and _lit not in ("TRUE", "FALSE"):
            _bad_bool.append(f"{_where}={_lit}")

check("every column that gets a default was checked", _checked > 20, _checked)
check("no JSON column is back-filled with something that is not JSON",
      not _bad_json, _bad_json)
check("no boolean column is back-filled with 1 or 0",
      not _bad_bool, _bad_bool)

# The two shapes, pinned by name. A dict-defaulted column and a
# list-defaulted one must not both come out as {}.
_jobs = _Base.metadata.tables["jobs"]
check("a dict-defaulted JSON column back-fills as an empty object",
      _backfill_default(_jobs.columns["sourcing_report"]) == "'{}'",
      _backfill_default(_jobs.columns["sourcing_report"]))
check("a list-defaulted JSON column back-fills as an empty array",
      _backfill_default(_jobs.columns["tags"]) == "'[]'",
      _backfill_default(_jobs.columns["tags"]))
check("a boolean back-fills as a boolean",
      _backfill_default(_jobs.columns["automated"]) == "FALSE",
      _backfill_default(_jobs.columns["automated"]))
check("a text column back-fills as an empty string",
      _backfill_default(_jobs.columns["error"]) == "''",
      _backfill_default(_jobs.columns["error"]))
check("a column with no sensible backfill is left without one",
      _backfill_default(_jobs.columns["created_at"]) == "",
      "a NOT NULL timestamp is not something to guess at")

# SQLAlchemy wraps a zero-argument default so it takes an execution context,
# so `dict` arrives as `lambda ctx: dict()`. Calling it bare raises TypeError,
# and swallowing that silently is what made tags come out as {} instead of [].
from backend.app.db import _python_default, _NO_DEFAULT  # noqa: E402

check("a callable default is actually called",
      _python_default(_jobs.columns["tags"]) == []
      and _python_default(_jobs.columns["options"]) == {},
      (_python_default(_jobs.columns["tags"]),
       _python_default(_jobs.columns["options"])))
from backend.app.db import _sql_literal  # noqa: E402

check("a timestamp default is not turned into a literal for old rows",
      _sql_literal(_python_default(_jobs.columns["created_at"]),
                   _jobs.columns["created_at"]) == "",
      "utcnow describes the row being written, not the rows already there")

# And the generated SQL, on the dialect that rejected it.
_pgd = _pg.dialect()
_clauses = []
for _name in ("sourcing_report", "tags", "automated"):
    _c = _jobs.columns[_name]
    _clauses.append(f'ADD COLUMN "{_name}" {_c.type.compile(_pgd)} '
                    f'DEFAULT {_backfill_default(_c)}')
check("the postgres clause no longer defaults JSON to an integer",
      not any("JSON DEFAULT 0" in c for c in _clauses), _clauses)
check("nor a boolean to one",
      not any("BOOLEAN DEFAULT 1" in c for c in _clauses), _clauses)

# The failure is now said out loud. A warning nobody reads, followed by a
# crash somewhere else, is what turned a one-line schema gap into an outage.
import logging as _logging  # noqa: E402


class _Catcher(_logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


_catch = _Catcher()
_dblog = _logging.getLogger("clipforge.db")
_dblog.addHandler(_catch)
try:
    with engine.begin() as conn:
        conn.execute(_text("ALTER TABLE users DROP COLUMN onboarded"))
    # A column of a type the helper will not guess at, so the ALTER is fine,
    # then one that cannot work -- a duplicate -- to force the error path.
    from backend.app.db import _add_missing_columns as _fix
    _fix()
finally:
    _dblog.removeHandler(_catch)
check("re-adding a dropped column is reported at info, not error",
      not [r for r in _catch.records if r.levelno >= _logging.ERROR],
      [r.getMessage() for r in _catch.records])
check("and the column is back", "onboarded" in
      {c["name"] for c in _inspect(engine).get_columns("users")})

section("studio: settings round-trip")
# A plan ceiling that clamps in silence is indistinguishable from a setting
# that did not save: the box reads 60 afterwards either way, and every render
# then comes out the wrong length for a reason nothing on screen explains.
_capped = client.put("/api/studio/settings", json={
    "settings": {"target_seconds": 120, "clips": 8}}).json()
check("the free plan still caps length and clip count",
      _capped["settings"]["target_seconds"] == 60
      and _capped["settings"]["clips"] == 5,
      (_capped["settings"]["target_seconds"], _capped["settings"]["clips"]))
check("but it says so rather than clamping in silence",
      bool(_capped.get("notice")), _capped.get("notice"))
check("and names both the number asked for and the cap",
      "120" in _capped["notice"] and "60" in _capped["notice"],
      _capped["notice"])
check("a value inside the plan is saved untouched and says nothing",
      client.put("/api/studio/settings", json={
          "settings": {"target_seconds": 45}}).json().get("notice") == "")

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

def _db_id_of(public_id: str) -> int:
    """The worker takes row ids; the API only ever exposes public ones."""
    from backend.app.models import Job as _J
    with _session_scope() as db:
        return db.query(_J).filter(_J.public_id == public_id).first().id


section("the render agent")
# The agent is the same pipeline on the subscriber's machine. The server still
# decides whether a job may run, so the interesting cases are the refusals.
import io as _io
import json as _json

agent_owner = TestClient(app)
agent_owner.post("/api/auth/signup",
                 json={"email": "agent@example.com", "password": "agent-pass-77"})
check("not paired until asked",
      agent_owner.get("/api/agent/status").json()["paired"] is False)

_tok = agent_owner.post("/api/agent/token").json()["token"]
check("a token is issued", len(_tok) > 20, len(_tok))
AGENT = {"Authorization": f"Bearer {_tok}"}

check("an unknown token is refused",
      TestClient(app).get("/api/agent/hello",
                          headers={"Authorization": "Bearer nope"}).status_code == 401)
check("no token is refused",
      TestClient(app).get("/api/agent/hello").status_code == 401)
check("a valid token identifies its owner",
      TestClient(app).get("/api/agent/hello", headers=AGENT).json()["email"]
      == "agent@example.com")

check("an empty queue answers 204",
      TestClient(app).post("/api/agent/claim", headers=AGENT).status_code == 204)

agent_owner.put("/api/studio/settings",
                json={"settings": {"sources": ["upload"], "clips": 3}})
_job = agent_owner.post("/api/jobs", json={"dry_run": True}).json()["id"]

_claim = TestClient(app).post("/api/agent/claim", headers=AGENT)
check("the agent claims the queued job", _claim.json()["job"] == _job)
check("the claim carries the resolved settings",
      isinstance(_claim.json()["settings"], dict)
      and "clips" in _claim.json()["settings"])
check("a claimed job is not handed out twice",
      TestClient(app).post("/api/agent/claim", headers=AGENT).status_code == 204)

TestClient(app).post(f"/api/agent/jobs/{_job}/progress", headers=AGENT,
                     json={"stage": "rendering", "detail": "Encoding"})
check("progress from the agent reaches the app",
      agent_owner.get(f"/api/jobs/{_job}").json()["status"] == "rendering")

# Another subscriber's agent must not see, touch or finish this job.
stranger = TestClient(app)
stranger.post("/api/auth/signup",
              json={"email": "stranger@example.com", "password": "stranger-pass-9"})
_other = stranger.post("/api/agent/token").json()["token"]
check("another account's agent cannot touch the job",
      TestClient(app).post(f"/api/agent/jobs/{_job}/progress",
                           headers={"Authorization": f"Bearer {_other}"},
                           json={"stage": "rendering"}).status_code == 404)

_result = {
    "duration": 42.5, "score": 91.2, "title": "Top 3",
    "retention": {"score": 91.2, "rejected": False},
    "labels": ["One", "Two", "Three"], "credits": "",
    "settings": {"auto_upload": False},
    "clips": [{"source": "upload", "external_id": "a.mp4", "title": "A",
               "duration": 14.0, "label": "One", "licence": "User upload"}],
}
_done = TestClient(app).post(
    f"/api/agent/jobs/{_job}/complete", headers=AGENT,
    data={"result": _json.dumps(_result)},
    files={"video": ("clip.mp4", _io.BytesIO(b"mp4" * 2048), "video/mp4")})
check("a finished render is accepted", _done.status_code == 200, _done.text[:90])

_state = agent_owner.get(f"/api/jobs/{_job}").json()
check("the job is done", _state["status"] == "done", _state["status"])
check("the retention score is recorded",
      abs(float(_state["retention_score"]) - 91.2) < 0.01, _state["retention_score"])
check("the uploaded file is measured",
      int(_state["size_bytes"]) >= 4096, _state["size_bytes"])

check("a finished job cannot be completed again",
      TestClient(app).post(
          f"/api/agent/jobs/{_job}/complete", headers=AGENT,
          data={"result": _json.dumps(_result)},
          files={"video": ("c.mp4", _io.BytesIO(b"x"), "video/mp4")}
      ).status_code == 409)

agent_owner.delete("/api/agent/token")
check("revoking the token stops the agent at once",
      TestClient(app).get("/api/agent/hello", headers=AGENT).status_code == 401)


section("the server stands down for a live agent")
# Both the local pool and the agent claim from the same QUEUED pool, and the
# pool is in-process, so it used to win every time -- sending the job to the
# datacentre address that YouTube refuses, which is the exact thing the agent
# exists to avoid.
import backend.app.worker as _worker  # noqa: E402
from backend.app.models import Job as _Job, JobStatus as _JobStatus  # noqa: E402


class _FakeUser:
    def __init__(self, token, seen):
        self.agent_token = token
        self.agent_last_seen = seen


check("no agent means the server renders it",
      _worker.agent_is_live(_FakeUser(None, _utcnow())) is False)
# Paired months ago and never opened since. These people must still get
# videos, so a token on its own is not enough to stand down for.
check("paired but never started does not count",
      _worker.agent_is_live(_FakeUser("tok", None)) is False)
check("an agent that just polled counts",
      _worker.agent_is_live(_FakeUser("tok", _utcnow())) is True)
check("one that stopped polling does not",
      _worker.agent_is_live(_FakeUser(
          "tok", _utcnow() - _timedelta(seconds=3600))) is False)
check("the cutoff is the configured window",
      _worker.agent_is_live(_FakeUser("tok", _utcnow() - _timedelta(
          seconds=settings.agent_online_seconds - 5))) is True)
check("and just past it, it is not",
      _worker.agent_is_live(_FakeUser("tok", _utcnow() - _timedelta(
          seconds=settings.agent_online_seconds + 5))) is False)
# Postgres returns aware datetimes and SQLite naive ones; comparing the wrong
# one raises TypeError inside a worker thread, where nobody would see it.
check("a naive timestamp does not explode",
      _worker.agent_is_live(_FakeUser(
          "tok", _utcnow().replace(tzinfo=None))) is True)

# The heartbeat this all rests on. agent_user() stamps agent_last_seen, but
# the idle path used to return 204 without committing, so an agent polling
# every 20 seconds looked like it had never connected at all.
_hb = TestClient(app)
_hb.post("/api/auth/signup",
         json={"email": "heartbeat@example.com", "password": "heartbeat-77"})
_hb_token = _hb.post("/api/agent/token").json()["token"]
_hb_head = {"Authorization": f"Bearer {_hb_token}"}
check("a fresh agent has never been seen",
      _hb.get("/api/agent/status").json()["last_seen"] == "")
check("an empty queue still answers 204",
      TestClient(app).post("/api/agent/claim", headers=_hb_head).status_code == 204)
check("but polling an empty queue records the heartbeat",
      _hb.get("/api/agent/status").json()["last_seen"] != "",
      _hb.get("/api/agent/status").json()["last_seen"])

# And the decision itself: a queued job belonging to someone with a live agent
# is left alone rather than rendered here.
_hb.put("/api/studio/settings", json={"settings": {"sources": ["upload"], "clips": 3}})
_left = _hb.post("/api/jobs", json={"dry_run": True}).json()["id"]
_worker._process(_db_id_of(_left))
with _session_scope() as _db:
    _row = _db.query(_Job).filter(_Job.public_id == _left).first()
    _status, _detail = _row.status, _row.stage_detail
check("the job is left queued for the agent", _status == _JobStatus.QUEUED, _status)
check("and says so", _detail == "Waiting for your render agent", _detail)


section("a stale agent says so")
# The agent is a PyInstaller build with the render pipeline inside it, so
# fixing the pipeline here does nothing for an older .exe -- and because the
# server stands down for a live agent, an old .exe renders everything. A build
# from 17:42 kept producing 17:42 output for hours after the fixes deployed,
# and nothing anywhere said so.
import backend.app.routes.agent as _agent_routes  # noqa: E402

_ver = TestClient(app)
_ver.post("/api/auth/signup",
          json={"email": "stale@example.com", "password": "stale-pass-77"})
_ver_tok = _ver.post("/api/agent/token").json()["token"]
_VH = {"Authorization": f"Bearer {_ver_tok}"}

_current = TestClient(app).get(
    "/api/agent/hello",
    headers={**_VH, "X-ClipForge-Pipeline": str(_agent_routes.PIPELINE_VERSION)}
).json()
check("a current agent is not nagged",
      _current["update_available"] is False, _current.get("update_note"))
check("and is told the server's version",
      _current["pipeline_version"] == _agent_routes.PIPELINE_VERSION)

_old = TestClient(app).get(
    "/api/agent/hello",
    headers={**_VH, "X-ClipForge-Pipeline": "1"}).json()
check("an older build is told to update", _old["update_available"] is True)
check("and told what it costs it",
      "old clip labels" in _old["update_note"], _old["update_note"][:60])
check("and what it is running", _old["your_pipeline_version"] == 1)

# Every build before this change sends no header at all. That is precisely the
# build that needs telling, so a missing header counts as stale.
_none = TestClient(app).get("/api/agent/hello", headers=_VH).json()
check("a build too old to report a version still counts as stale",
      _none["update_available"] is True, _none["your_pipeline_version"])

_junk = TestClient(app).get(
    "/api/agent/hello", headers={**_VH, "X-ClipForge-Pipeline": "banana"}).json()
check("a malformed version does not 500", _junk["update_available"] is True)

# The two numbers are edited by hand in two files, so check they agree.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent as _agent_pkg  # noqa: E402

check("agent and server agree on the pipeline version",
      _agent_pkg.PIPELINE_VERSION == _agent_routes.PIPELINE_VERSION,
      f"agent {_agent_pkg.PIPELINE_VERSION} vs server "
      f"{_agent_routes.PIPELINE_VERSION}")
check("the agent sends the header",
      "X-ClipForge-Pipeline" in Path("agent/client.py").read_text(encoding="utf-8"))


section("re-pairing after a revoke")
# Unpairing on the website revokes the token, but the agent still has it in
# agent.env. It saw a token, skipped pairing, failed authentication, and
# printed an instruction to press a button that no longer exists.
import agent.client as _ac  # noqa: E402
import agent.main as _am  # noqa: E402
import agent.config as _acfg  # noqa: E402

check("a rejected token has its own error type",
      issubclass(_ac.AuthError, _ac.ServerError))

_revoked = TestClient(app)
_revoked.post("/api/auth/signup",
              json={"email": "revoked@example.com", "password": "revoked-pw-9"})
_rev_token = _revoked.post("/api/agent/token").json()["token"]
check("the token works while paired",
      TestClient(app).get("/api/agent/hello",
                          headers={"Authorization": f"Bearer {_rev_token}"}
                          ).status_code == 200)
_revoked.delete("/api/agent/token")
check("and 401s once unpaired on the website",
      TestClient(app).get("/api/agent/hello",
                          headers={"Authorization": f"Bearer {_rev_token}"}
                          ).status_code == 401)

# The agent's side of that. A config file holding the dead token must not stop
# it reaching the pairing flow.
_dead = TMP / "revoked-agent.env"
_dead.write_text(
    "CLIPFORGE_SERVER=https://example.invalid\n"
    f"CLIPFORGE_AGENT_TOKEN={_rev_token}\n", encoding="utf-8")
_deadcfg = _acfg.load(path=_dead, require_token=False)
check("a revoked token still loads as a token", bool(_deadcfg.token))
check("so pairing would be skipped without the recovery",
      _deadcfg.token != "")

# clear_token is what breaks the loop, and it must not lose the server.
_acfg.clear_token(path=_dead)
_after = _acfg.load(path=_dead, require_token=False)
check("clearing the token frees it to pair", _after.token == "")
check("and keeps the server address", _after.server == "https://example.invalid")

# The message must not send anyone to a button that was removed.
_msg = ""
try:
    raise _ac.AuthError(
        "The server rejected this agent's token. It was most likely "
        "unpaired on the website.")
except _ac.AuthError as _exc:
    _msg = str(_exc)
check("the error does not describe the removed Settings button",
      "Generate a new one" not in _msg, _msg)
check("main knows how to recover", hasattr(_am, "_token_was_rejected"))
check("ensure_paired can be forced past an existing token",
      "force" in _am.ensure_paired.__code__.co_varnames)


section("pairing an agent")
# The flow that replaced "copy this token into a file". Its whole reason for
# existing is that a subscriber never handles the secret, so the checks are
# about who can collect it and who cannot.
pair_owner = TestClient(app)
pair_owner.post("/api/auth/signup",
                json={"email": "pairer@example.com", "password": "pair-pass-77"})

_started = TestClient(app).post("/api/agent/pair/start",
                                json={"label": "DESKTOP-TEST"}).json()
_code, _secret = _started["code"], _started["device_secret"]
check("starting needs no account", len(_code) == 9 and _code[4] == "-", _code)
check("the code avoids letters read as digits",
      not set(_code.replace("-", "")) & set("ILOU01"), _code)
check("a device secret comes back", len(_secret) > 20)
check("the verify url carries the code", _code in _started["verify_url"],
      _started["verify_url"])

check("polling before approval says pending",
      TestClient(app).post("/api/agent/pair/poll",
                           json={"device_secret": _secret}).json()["status"]
      == "pending")
check("an unknown secret is not told anything else",
      TestClient(app).post("/api/agent/pair/poll",
                           json={"device_secret": "made-up"}).json()["status"]
      == "expired")

# Approving is the only step that needs a session, and it is the only step
# that attaches the pairing to an account.
check("approving needs a signed-in session",
      TestClient(app).post("/api/agent/pair/approve",
                           json={"code": _code}).status_code == 401)
check("the page can see which machine is asking",
      pair_owner.get(f"/api/agent/pair/lookup?code={_code}").json()["label"]
      == "DESKTOP-TEST")
check("a code typed without its dash still resolves",
      pair_owner.get(
          f"/api/agent/pair/lookup?code={_code.replace('-', '').lower()}"
      ).json()["found"] is True)
check("an invented code is simply not found",
      pair_owner.get("/api/agent/pair/lookup?code=ZZZZ-ZZZZ").json()["found"]
      is False)

check("approval succeeds",
      pair_owner.post("/api/agent/pair/approve",
                      json={"code": _code}).json()["ok"] is True)
check("the same code cannot be approved twice",
      pair_owner.post("/api/agent/pair/approve",
                      json={"code": _code}).status_code == 409)

_collected = TestClient(app).post("/api/agent/pair/poll",
                                  json={"device_secret": _secret}).json()
check("the agent collects a token", len(_collected.get("token", "")) > 20)
check("and is told which account it joined",
      _collected.get("email") == "pairer@example.com")
check("the token actually works",
      TestClient(app).get(
          "/api/agent/hello",
          headers={"Authorization": f"Bearer {_collected['token']}"}
      ).status_code == 200)

# The row keeps nothing once the agent has it, so a copy of the secret taken
# afterwards is worth nothing.
check("a token is handed over exactly once",
      TestClient(app).post("/api/agent/pair/poll",
                           json={"device_secret": _secret}).json()["status"]
      == "expired")

# An expired code must not be approvable, whatever the clock says elsewhere.
from backend.app.models import AgentPairing as _Pairing  # noqa: E402

_stale = TestClient(app).post("/api/agent/pair/start", json={}).json()
with _session_scope() as _db:
    _row = _db.query(_Pairing).filter(
        _Pairing.code == _stale["code"]).first()
    _row.expires_at = _utcnow() - _timedelta(minutes=1)
check("an expired code is not found",
      pair_owner.get(
          f"/api/agent/pair/lookup?code={_stale['code']}").json()["found"]
      is False)
check("and cannot be approved",
      pair_owner.post("/api/agent/pair/approve",
                      json={"code": _stale["code"]}).status_code == 404)
check("its agent is told to start over",
      TestClient(app).post(
          "/api/agent/pair/poll",
          json={"device_secret": _stale["device_secret"]}).json()["status"]
      == "expired")

# The page the agent sends people to has to exist and has to be the app,
# because the app is what knows how to show a sign-in first.
_pair_page = TestClient(app).get("/pair?code=ABCD-2345")
check("/pair serves the app", _pair_page.status_code == 200
      and "id=\"pair\"" in _pair_page.text)
check("crawlers are kept off it",
      "Disallow: /pair" in TestClient(app).get("/robots.txt").text)


section("the agent client")
# The agent ships as part of this repo so it cannot drift from the pipeline it
# calls. These are the mistakes that would only show up on a subscriber's
# machine, where nobody is watching.
import agent.client as _agent_client  # noqa: E402
import agent.config as _agent_config  # noqa: E402

check("the agent imports without a config",
      hasattr(_agent_client, "Server") and hasattr(_agent_config, "load"))

_missing = TMP / "agent-empty.env"
_missing.write_text("# nothing here\n", encoding="utf-8")
_saved = {k: os.environ.pop(k, None)
          for k in ("CLIPFORGE_SERVER", "CLIPFORGE_AGENT_TOKEN")}
try:
    _agent_config.load(_missing)
    check("an unconfigured agent refuses to start", False, "it started anyway")
except SystemExit as exc:
    check("an unconfigured agent refuses to start",
          "CLIPFORGE_AGENT_TOKEN" in str(exc))
finally:
    for k, v in _saved.items():
        if v is not None:
            os.environ[k] = v

_conf = TMP / "agent.env"
_conf.write_text(
    "CLIPFORGE_SERVER=https://example.test/\n"
    "CLIPFORGE_AGENT_TOKEN=abc123\n"
    f"CLIPFORGE_WORK_DIR={TMP / 'agentwork'}\n"
    f"CLIPFORGE_FOOTAGE_DIR={TMP / 'agentfootage'}\n",
    encoding="utf-8")
_saved2 = {k: os.environ.pop(k, None)
           for k in ("CLIPFORGE_SERVER", "CLIPFORGE_AGENT_TOKEN",
                     "CLIPFORGE_WORK_DIR", "CLIPFORGE_FOOTAGE_DIR")}
try:
    _cfg = _agent_config.load(_conf)
    check("the trailing slash is trimmed from the server",
          _cfg.server == "https://example.test", _cfg.server)
    check("the token is read", _cfg.token == "abc123")
    check("footage is presented to the pipeline as user 1's uploads",
          _cfg.storage_dir.name == "storage")
    _sent = _agent_client.Server(_cfg).session.headers.get("Authorization")
    check("every call carries the token", _sent == "Bearer abc123", _sent)
finally:
    for k, v in _saved2.items():
        if v is not None:
            os.environ[k] = v


section("ffmpeg comes with it")
# "Install ffmpeg first" was the last instruction standing between a
# subscriber and a working agent. These check the finding, not the fetching:
# downloading 110MB is not something a test suite should do on every run.
import agent.ffmpeg as _ff  # noqa: E402

_ffhome = TMP / "ffhome"
_ffhome.mkdir(parents=True, exist_ok=True)

_saved_path = os.environ.get("PATH", "")
os.environ["PATH"] = ""            # no system ffmpeg may mask these
try:
    check("nothing found on a bare machine", _ff.find(_ffhome) == (None, None))

    _stub = _ffhome / "ffmpeg"
    _stub.mkdir()
    for _n in (f"ffmpeg{_ff.SUFFIX}", f"ffprobe{_ff.SUFFIX}"):
        (_stub / _n).write_bytes(b"not a real binary")

    _found = _ff.find(_ffhome)
    check("a copy beside the agent is found", _found[0] == _stub / f"ffmpeg{_ff.SUFFIX}")
    # This is the interrupted-download case, and the whole reason find() and
    # works() are separate: the file exists and is still no use.
    check("but a broken one does not pass works()", _ff.works(_found[0]) is False)

    _refused = ""
    try:
        _ff.ensure(_ffhome, auto=False)
    except _ff.FFmpegError as _exc:
        _refused = str(_exc)
    check("--no-download refuses rather than fetching", "missing" in _refused,
          _refused.splitlines()[0] if _refused else "no error raised")
    check("and still says how to install it by hand", "winget" in _refused)
finally:
    os.environ["PATH"] = _saved_path

# apply() is the reason the pipeline uses the bundled build and not whatever
# else is on the machine. backend.app.config reads these once, at import.
# Compared through Path so this does not depend on the separator: on Windows
# "X:/ff" comes back out as "X:\ff".
_fake_ffmpeg, _fake_ffprobe = Path("X:/ff/ffmpeg.exe"), Path("X:/ff/ffprobe.exe")
_ff.apply(_fake_ffmpeg, _fake_ffprobe)
check("FFMPEG_BINARY is pointed at ours",
      os.environ["FFMPEG_BINARY"] == str(_fake_ffmpeg), os.environ["FFMPEG_BINARY"])
check("FFPROBE_BINARY too", os.environ["FFPROBE_BINARY"] == str(_fake_ffprobe))
check("and the folder goes on PATH for anything that shells out",
      str(_fake_ffmpeg.parent) in os.environ["PATH"].split(os.pathsep))
check("the pipeline reads that setting",
      "FFMPEG_BINARY" in Path("backend/app/config.py").read_text(encoding="utf-8"))

check("ffplay is not something we ever want",
      "ffplay" not in _ff.WANTED, sorted(_ff.WANTED))
check("the download is checksummed",
      _ff.CHECKSUM_URL.endswith(".sha256"))
check("and comes over https", _ff.DOWNLOAD_URL.startswith("https://"))

for _k in ("FFMPEG_BINARY", "FFPROBE_BINARY"):
    os.environ.pop(_k, None)


section("security")
from backend.app.security import _CSP, _Buckets, _limit_for  # noqa: E402

# --- the response headers a browser acts on --------------------------- #
_h = client.get("/api/health").headers
check("a CSP is sent", "content-security-policy" in _h)
check("framing is refused", _h.get("x-frame-options") == "DENY", _h.get("x-frame-options"))
check("MIME sniffing is refused", _h.get("x-content-type-options") == "nosniff")
check("a referrer policy is set", "referrer-policy" in _h)
check("a permissions policy is set", "permissions-policy" in _h)

# The CSP has to allow exactly what the pages load, or it silently breaks
# them: the response is a 200 and the image renders its alt text. A hardcoded
# list of origins here is what let that ship, so read the pages instead.
#
# Only what the browser *fetches* counts. A src= is always a subresource, and
# so is an href on <link>, but an href on an <a> is somewhere the reader may
# choose to go -- CSP does not govern navigation, and the policy pages link
# out to Stripe, Google and the ICO on purpose. Adding those to the CSP would
# grant fetch permissions to origins nothing ever fetches, which is the
# opposite of what this check is for.
_HTML = Path(__file__).resolve().parent / "frontend"
_page_origins: set = set()
for _f in ("landing.html", "index.html", "404.html",
           "privacy.html", "terms.html", "cookies.html"):
    _markup = (_HTML / _f).read_text(encoding="utf-8")
    _page_origins |= set(re.findall(r'src="(https://[a-z0-9.-]+)', _markup))
    for _tag in re.findall(r"<link\b[^>]*>", _markup):
        _page_origins |= set(re.findall(r'href="(https://[a-z0-9.-]+)', _tag))
# A JSON-LD vocabulary URL. It is an identifier, nothing fetches it.
_page_origins.discard("https://schema.org")
check("the pages were scanned for origins", len(_page_origins) >= 2,
      sorted(_page_origins))
for _origin in sorted(_page_origins):
    check(f"CSP allows {_origin.split('//')[1]}", _origin in _CSP)

# The other half of the same rule: an origin the pages only ever link to must
# stay out of the CSP. This is what stops somebody "fixing" a failure above by
# pasting every hostname on the page into the header.
_linked_only = set()
for _f in ("privacy.html", "terms.html", "cookies.html"):
    _markup = (_HTML / _f).read_text(encoding="utf-8")
    for _tag in re.findall(r"<a\b[^>]*>", _markup):
        _linked_only |= set(re.findall(r'href="(https://[a-z0-9.-]+)', _tag))
_linked_only -= _page_origins
check("the policy pages link out to somewhere", len(_linked_only) >= 2,
      sorted(_linked_only))
for _origin in sorted(_linked_only):
    check(f"CSP does not grant {_origin.split('//')[1]}", _origin not in _CSP)

# blob: is the one that cannot be caught by scanning markup. app.js turns the
# /api/studio/preview PNG body into an object URL, in the settings preview and
# again in the guided walkthrough; without blob: neither ever paints.
_img_src = _CSP.split("img-src ", 1)[1].split(";", 1)[0]
check("CSP allows blob: images", "blob:" in _img_src, _img_src)
check("app.js still needs it", "createObjectURL" in
      (_HTML / "app.js").read_text(encoding="utf-8"))
check("CSP forbids plugins", "object-src 'none'" in _CSP)
check("CSP forbids being framed", "frame-ancestors 'none'" in _CSP)
check("CSP pins the base URI", "base-uri 'self'" in _CSP)

# HSTS must not be sent over plain HTTP: a browser would pin localhost to
# HTTPS for a year on a developer's machine.
check("no HSTS over plain http", "strict-transport-security" not in _h)
check("HSTS behind an HTTPS proxy",
      "strict-transport-security" in
      client.get("/api/health", headers={"X-Forwarded-Proto": "https"}).headers)

# --- the limiter itself ------------------------------------------------ #
_b = _Buckets()
_allowed = [_b.hit("someone", 3, 60.0)[0] for _ in range(5)]
check("the first requests inside the limit pass", _allowed[:3] == [True] * 3)
check("the ones over it are refused", _allowed[3:] == [False, False])
check("a refusal says how long to wait", _b.hit("someone", 3, 60.0)[1] >= 1)
check("a different caller has its own budget", _b.hit("someone-else", 3, 60.0)[0])
check("a window that has passed frees up",
      _Buckets().hit("fresh", 1, 0.0001)[0] and
      (time.sleep(0.01) or _Buckets().hit("fresh", 1, 0.0001)[0]))

# Longest prefix wins, so /api/auth/login is stricter than /api.
check("deleting an account is limited far more tightly than logging in",
      _limit_for("/api/me/delete")[1][0] < _limit_for("/api/auth/login")[1][0],
      f'{_limit_for("/api/me/delete")[1]} vs {_limit_for("/api/auth/login")[1]}')
check("login is limited more tightly than the rest of the api",
      _limit_for("/api/auth/login")[1][0] < _limit_for("/api/me")[1][0],
      f"{_limit_for('/api/auth/login')[1]} vs {_limit_for('/api/me')[1]}")
check("an unknown path is not limited", _limit_for("/static/x.css")[1] is None)

# --- cookies ----------------------------------------------------------- #
# secure_cookies follows the environment: on in production, off in
# development, because a Secure cookie is never returned over plain http.
from backend.app.config import Settings  # noqa: E402

_saved_env = os.environ.get("ENV")
os.environ["ENV"] = "production"
check("cookies are Secure in production", Settings().secure_cookies)
os.environ["ENV"] = "dev"
check("cookies are not Secure in development", not Settings().secure_cookies)
if _saved_env is None:
    os.environ.pop("ENV", None)
else:
    os.environ["ENV"] = _saved_env

_set = client.post("/api/auth/signup",
                   json={"email": "cookie@example.com",
                         "password": "cookie-pass-9"}).headers.get("set-cookie", "")
check("the session cookie is HttpOnly", "HttpOnly" in _set, _set[:40])
check("and SameSite is set", "SameSite" in _set)

# --- what the crawlers and assistants get ------------------------------ #
_robots = client.get("/robots.txt")
check("robots.txt is served", _robots.status_code == 200)
check("it points at the sitemap", "Sitemap:" in _robots.text)
check("it keeps crawlers out of the app", "Disallow: /app" in _robots.text)
check("sitemap.xml is served", client.get("/sitemap.xml").status_code == 200)
_llms = client.get("/llms.txt")
check("llms.txt is served", _llms.status_code == 200)
check("and says what the product does not do",
      "does not" in _llms.text.lower())

# --- 404 ---------------------------------------------------------------- #
_missing = client.get("/no-such-page")
check("a missing page is a real page", _missing.status_code == 404
      and "text/html" in _missing.headers.get("content-type", ""),
      _missing.headers.get("content-type"))
_missing_api = client.get("/api/no-such-thing")
check("a missing api route stays JSON", _missing_api.status_code == 404
      and _missing_api.json().get("detail"))


section("policies and consent")

# The policy pages are rendered through token substitution rather than served
# from disk, so the failure mode is a page that ships "__LEGAL_EMAIL__" to a
# regulator. Every page is checked for leftovers, including the two that are
# not policies but go through the same renderer.
_POLICY_PATHS = ("/privacy", "/terms", "/cookies")

for _path in _POLICY_PATHS + ("/", "/app"):
    _page = client.get(_path)
    check(f"{_path} is served", _page.status_code == 200, _page.status_code)
    _left = set(re.findall(r"__[A-Z_]+__", _page.text))
    check(f"{_path} has no unreplaced tokens", not _left, _left or "")

# A privacy notice has to name a controller and a way to reach them. Both come
# from config, so this fails loudly on a deployment that has not set them.
_privacy = client.get("/privacy").text
check("the privacy policy names the controller",
      settings.legal_entity in _privacy)
check("and gives a contact address",
      settings.legal_contact_email in _privacy)
check("and states the erasure right",
      "Erasure" in _privacy)
_terms = client.get("/terms").text
# Collapsed, because the sentences being looked for are wrapped in the source
# and a raw substring match would only be testing where the line breaks fall.
_terms_flat = " ".join(_terms.split())
check("the terms name the governing law",
      settings.legal_jurisdiction in _terms)
check("and address rights in third-party footage",
      "does not give you the right to it" in _terms_flat)
check("and do not claim ownership of the user's videos",
      "You own the footage you upload" in _terms_flat)

# The cookie policy has to describe this deployment, not a generic one.
_cookies = client.get("/cookies").text
check("the cookie policy names the session cookie", "cf_token" in _cookies)
if settings.optional_trackers:
    check("it lists the optional cookies", "_ga" in _cookies)
else:
    check("it says there is nothing optional to accept",
          "There are currently none" in _cookies)
    check("and does not describe cookies it never sets",
          "_ga" not in _cookies)

# The gate itself. Nothing optional may be reachable from the markup, because
# a tracker in the page loads before anybody has answered the notice.
for _path in ("/", "/app") + _POLICY_PATHS:
    _page = client.get(_path).text
    check(f"{_path} loads the consent script", "/static/consent.js" in _page)
    check(f"{_path} inlines no tracker",
          "googletagmanager" not in _page and "google-analytics" not in _page)

_declared = re.search(r'data-optional="([^"]*)"', client.get("/").text)
check("the page declares what it will ask about",
      _declared is not None and
      _declared.group(1) == ",".join(settings.optional_trackers),
      _declared.group(1) if _declared else "absent")

# The CSP must move with the config. Listing analytics origins on a deployment
# that does not run analytics grants a permission for nothing; omitting them on
# one that does blocks the script after consent was given, which is worse.
from backend.app.security import _build_csp  # noqa: E402

_saved_ga = settings.ga_measurement_id
settings.ga_measurement_id = ""
check("no analytics origins in the CSP when it is off",
      "googletagmanager" not in _build_csp())
settings.ga_measurement_id = "G-SELFTEST"
_csp_on = _build_csp()
check("the tag manager is allowed when it is on",
      "https://www.googletagmanager.com" in _csp_on)
check("and so is the endpoint it reports to",
      "https://www.google-analytics.com" in _csp_on)
settings.ga_measurement_id = _saved_ga

# Somebody has to be able to find these.
_sitemap = client.get("/sitemap.xml").text
for _path in _POLICY_PATHS:
    check(f"the sitemap lists {_path}", f"<loc>{settings.public_url}{_path}</loc>" in _sitemap)

# And reach them from anywhere on the site.
for _path in ("/", "/app") + _POLICY_PATHS:
    _page = client.get(_path).text
    check(f"{_path} links to the policies",
          'href="/privacy"' in _page and 'href="/terms"' in _page)

# Accepting the terms happens at the button that creates the account.
check("the sign-up form states what it accepts",
      "By creating an account you agree to the" in client.get("/app").text)

# /privacy tells people which screen to go to. That instruction is markup in a
# different file, and nothing else would notice if the panel moved.
_app_html = (Path(__file__).resolve().parent / "frontend" / "index.html").read_text(
    encoding="utf-8")
_account_screen = re.search(
    r'<section id="tab-(\w+)"[^>]*>(?:(?!</section>).)*?id="h-account"',
    _app_html, re.S)
check("the account controls live on a known screen", _account_screen is not None)
if _account_screen:
    _screen = _account_screen.group(1)
    check("the data controls sit on that same screen",
          re.search(
              r'<section id="tab-' + _screen + r'"[^>]*>(?:(?!</section>).)*?id="h-data"',
              _app_html, re.S) is not None,
          f"h-data is not inside tab-{_screen}")
    # The nav label is what the policy has to name, not the element id.
    _label = re.search(
        r'aria-controls="tab-' + _screen + r'".*?<span class="lbl">([^<]+)</span>',
        _app_html, re.S)
    check("the policy names the screen the user actually sees",
          _label is not None and _label.group(1) in client.get("/privacy").text,
          f"nav says {_label.group(1) if _label else '?'}")


section("your data")

# The two rights /privacy promises. If these break, the policy becomes a claim
# the product does not honour.
_rights_email = "erasure@example.com"
_rights_pw = "erase-me-please-1"
client.post("/api/auth/signup",
            json={"email": _rights_email, "password": _rights_pw})

_export = client.get("/api/me/export")
check("the export is served", _export.status_code == 200, _export.status_code)
check("as a download", "attachment" in _export.headers.get("content-disposition", ""))
_dump = _export.json()
check("it contains the account", _dump["account"]["email"] == _rights_email)
for _key in ("account", "settings", "billing", "youtube", "automation",
             "render_agent", "niches", "jobs", "uploads"):
    check(f"the export covers {_key}", _key in _dump)
# Two things that must never leave the server, even to their owner: a hash
# helps nobody who has it legitimately, and the refresh token is a live
# credential for somebody's channel.
check("it withholds the password hash", "pbkdf2$" not in _json.dumps(_dump))
check("and the refresh token",
      _dump["youtube"]["refresh_token"].startswith("Held, but withheld"))

check("deletion refuses a wrong password",
      client.post("/api/me/delete",
                  json={"password": "not-the-password",
                        "confirm": "DELETE"}).status_code == 403)
check("and refuses without the typed confirmation",
      client.post("/api/me/delete",
                  json={"password": _rights_pw, "confirm": ""}).status_code == 400)
check("the account survives a refused deletion",
      client.get("/api/me").status_code == 200)

check("deletion works when both are right",
      client.post("/api/me/delete",
                  json={"password": _rights_pw,
                        "confirm": "DELETE"}).status_code == 200)
with session_scope() as _db:
    check("the row is gone",
          _db.query(User).filter(User.email == _rights_email).one_or_none() is None)
client.cookies.clear()
check("and the credentials no longer work",
      client.post("/api/auth/login",
                  json={"email": _rights_email,
                        "password": _rights_pw}).status_code >= 400)


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
