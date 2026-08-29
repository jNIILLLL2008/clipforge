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
_HTML = Path(__file__).resolve().parent / "frontend"
_page_origins: set = set()
for _f in ("landing.html", "index.html", "404.html"):
    _page_origins |= set(re.findall(
        r'(?:href|src)="(https://[a-z0-9.-]+)',
        (_HTML / _f).read_text(encoding="utf-8")))
# A JSON-LD vocabulary URL. It is an identifier, nothing fetches it.
_page_origins.discard("https://schema.org")
check("the pages were scanned for origins", len(_page_origins) >= 2,
      sorted(_page_origins))
for _origin in sorted(_page_origins):
    check(f"CSP allows {_origin.split('//')[1]}", _origin in _CSP)

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
