"""
settings_schema.py -- Every knob a niche exposes, declared once.

This is the single source of truth for niche settings. The defaults, the API
validation and the editor UI are all generated from it, so a new option is
added in exactly one place and cannot drift between them.

The catalogue mirrors the desktop tool's settings, minus anything that belongs
to the operator rather than the user (API keys, storage paths, publishing
credentials, schedules) and plus the retention rules this product enforces.

Field kinds: bool, int, float, text, list, select, colour.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

GROUPS: List[Dict[str, str]] = [
    {"id": "subject", "name": "Subject",
     "blurb": "What the videos are about, and how clips are found."},
    {"id": "gate", "name": "Show filter",
     "blurb": "Insist clips come from one specific show or series, rather than "
              "anything featuring the same people or topic."},
    {"id": "filters", "name": "Clip filters",
     "blurb": "Which source clips qualify before anything is downloaded."},
    {"id": "cut", "name": "The cut",
     "blurb": "How many clips, how long, and where each excerpt comes from."},
    {"id": "retention", "name": "Retention rules",
     "blurb": "The bar a video must clear before it is allowed to render."},
    {"id": "banner", "name": "Banner",
     "blurb": "The fixed title across the top of every frame."},
    {"id": "checklist", "name": "Numbered list",
     "blurb": "The list that unlocks an entry per clip. This is the single "
              "biggest retention device in the format."},
    {"id": "captions", "name": "Captions",
     "blurb": "Burned-in subtitles, because most short-form is watched muted."},
    {"id": "badge", "name": "Countdown badge",
     "blurb": "An optional corner badge (#5 ... #1) as well as, or instead of, "
              "the list."},
    {"id": "frame", "name": "Video",
     "blurb": "Resolution, framing and encoding quality."},
    {"id": "copyright", "name": "Copyright guard",
     "blurb": "Find music in a source clip and cut around it."},
    {"id": "upload", "name": "Upload",
     "blurb": "How finished videos are published to your channel. Start on "
              "Private until you have watched a few results."},
]


def field(key: str, group: str, kind: str, default: Any, label: str,
          help: str = "", **extra) -> Dict[str, Any]:
    return {"key": key, "group": group, "kind": kind, "default": default,
            "label": label, "help": help, **extra}


FIELDS: List[Dict[str, Any]] = [
    # ---------------------------------------------------------- subject --- #
    field("description", "subject", "text", "",
          "What this niche is",
          "Written for the AI that picks clips. Be specific: 'funny studio "
          "banter between the four pundits on a football panel show' beats "
          "'football'.", multiline=True),
    field("search_terms", "subject", "list", [],
          "Search terms",
          "What to search for in each source. Leave empty to use everything "
          "available (your uploads, for instance)."),
    field("exclude_terms", "subject", "list", [],
          "Never include",
          "A clip whose title or tags contain any of these is dropped."),
    field("sources", "subject", "list", ["upload"],
          "Sources",
          "Where footage comes from. Your own uploads, or YouTube, which "
          "collects and ranks candidate clips for you."),
    field("search_mode", "subject", "select", "hashtag",
          "Search mode",
          "How search terms become YouTube pages. Hashtag reads a tag's "
          "Shorts tab, search reads results filtered to under four minutes.",
          options=["hashtag", "search", "both"]),
    field("source_playlists", "subject", "list", [],
          "Playlists",
          "Paste a YouTube playlist link, one per line, and clips are taken "
          "from it. The link from the address bar while you are watching works "
          "too -- the playlist is picked out of it. Watch Later, Liked videos "
          "and auto-generated mixes cannot be read by a server.",
          placeholder="https://www.youtube.com/playlist?list=..."),
    field("source_channels", "subject", "list", [],
          "Source channels",
          "Pull from specific channels rather than a general search. Only used "
          "by sources that have channels."),
    field("channel_search_terms", "subject", "list", [],
          "Archive searches",
          "Searched inside each source channel. A channel's recent uploads are "
          "not its best material, especially for a seasonal show."),
    field("channel_tabs", "subject", "list", ["videos", "shorts"],
          "Channel sections",
          "Which parts of a channel to read. Long-form segments usually live "
          "under videos, not shorts."),
    field("candidate_pool_size", "subject", "int", 40,
          "Candidates to consider", "How many clips to look at before picking.",
          min=5, max=300),
    field("reuse_after_days", "subject", "int", 60,
          "Reuse a clip after (days)",
          "A clip you have already published is skipped for this long. 0 "
          "reuses freely, which makes every run pick the same best clips.",
          min=0, max=3650),

    # ------------------------------------------------------------- gate --- #
    field("require_show_match", "gate", "bool", False,
          "Only from one show",
          "Refuse clips that merely feature the same people or subject. Turn "
          "this on when your niche is one specific programme."),
    field("show_name", "gate", "text", "",
          "Show name",
          "Given to the AI, e.g. 'the CBS Sports Golazo / UCL Today studio "
          "show'."),
    field("show_terms", "gate", "list", [],
          "Show keywords",
          "A clip qualifies if any of these appear in its title, description, "
          "tags or channel name."),
    field("show_people", "gate", "list", [],
          "Regulars",
          "One person per line. Separate a person's aliases with | so "
          "'thierry henry|thierry|henry' is never counted as two people. Two "
          "different regulars named together imply the show."),

    # ---------------------------------------------------------- filters --- #
    field("min_view_count", "filters", "int", 0,
          "Minimum views", "Ignored by sources that do not report views.",
          min=0, max=100_000_000),
    field("min_duration_seconds", "filters", "int", 5,
          "Shortest clip", "Source clips shorter than this are skipped.",
          min=1, max=600),
    field("max_duration_seconds", "filters", "int", 600,
          "Longest clip",
          "Source clips longer than this are skipped. Raise it to allow full "
          "segments you cut a moment out of.", min=5, max=7200),
    field("max_video_age_days", "filters", "int", 0,
          "Maximum age (days)", "0 means any age.", min=0, max=3650),
    field("blocked_uploaders", "filters", "list", [],
          "Blocked channels",
          "Channels whose clips you never want. Useful for anyone who burns "
          "their own banner into their uploads."),
    field("trusted_uploaders", "filters", "list", [],
          "Trusted channels",
          "Channels exempt from the checks below, because their footage is the "
          "original rather than someone else's edit of it."),
    field("reject_derivative", "filters", "bool", True,
          "Skip other people's edits",
          "Refuse fan edits, AMVs and compilations. Re-cutting one gives you "
          "their music, their captions and their watermark burned into your "
          "video, and the moment is usually already speed-ramped."),
    field("derivative_terms", "filters", "list", [],
          "Also treat as an edit",
          "Added to the built-in list. Whole words only, so \"edit\" does not "
          "match \"credits\"."),
    field("long_clip_seconds", "filters", "float", 75.0,
          "Treat as a full segment above",
          "A source longer than this is a haystack rather than a clip: its "
          "transcript and its audio are searched and the best moments are cut "
          "out of it, instead of taking whatever happens to be in the middle. "
          "The \"Longest clip\" limit does not apply to these.",
          min=10, max=3600),

    # -------------------------------------------------------------- cut --- #
    field("clips", "cut", "int", 5, "Number of clips", "", min=2, max=12),
    field("target_seconds", "cut", "int", 105, "Total length (seconds)", "",
          min=10, max=300),
    field("min_clip_seconds", "cut", "float", 8.0, "Shortest segment", "",
          min=1, max=120),
    field("max_clip_seconds", "cut", "float", 26.0, "Longest segment", "",
          min=2, max=180),
    field("clip_trim_strategy", "cut", "select", "center",
          "Take the excerpt from",
          "Where in a source clip the excerpt is taken when it is longer than "
          "its slot.", options=["start", "center", "end"]),
    field("moments_per_video", "cut", "int", 2,
          "Most moments from one video",
          "A full episode holds several good beats, but taking five from one "
          "of them makes a video that plays as a single scene. Lower this to "
          "spread the cut across more episodes.", min=1, max=6),
    field("moment_min_gap_seconds", "cut", "float", 90.0,
          "Keep moments this far apart (seconds)",
          "Two moments cut from the same episode a few seconds apart are one "
          "moment shown twice.", min=0, max=1800),
    field("skip_intro_seconds", "cut", "float", 20.0,
          "Ignore the opening (seconds)",
          "A title sequence is the loudest, most quotable stretch of an "
          "episode and never the moment anybody wants.", min=0, max=600),
    field("skip_outro_seconds", "cut", "float", 30.0,
          "Ignore the ending (seconds)",
          "Credits, for the same reason.", min=0, max=600),
    field("moment_keywords", "cut", "list", [],
          "Words that mark a good moment",
          "Scored higher when they are said inside a candidate window. For a "
          "comedy niche these are the catchphrases; leave it empty to rank on "
          "dialogue and audio alone."),
    field("moment_audio_scan", "cut", "bool", True,
          "Listen for the moment too",
          "Reads the loudness of a long source so a beat with no dialogue is "
          "still found. Costs a few seconds per episode; turn it off if your "
          "renders are timing out."),
    field("countdown", "cut", "bool", True,
          "Countdown order",
          "Hold the best clip until last. Turn off for formats where the "
          "strongest moment should open."),

    # -------------------------------------------------------- retention --- #
    field("hook_seconds", "retention", "float", 2.0,
          "Hook must land within",
          "How long the opening clip may take to reach the action.",
          min=0.5, max=15),
    field("max_shot_seconds", "retention", "float", 30.0,
          "Longest unbroken shot",
          "A single shot running past this is where viewers leave.",
          min=2, max=120),

    # ----------------------------------------------------------- banner --- #
    field("banner_enabled", "banner", "bool", True, "Show banner", ""),
    field("banner_line1", "banner", "text", "TOP {count}",
          "Line 1", "{count} becomes the real number of clips."),
    field("banner_line2", "banner", "text", "", "Line 2", ""),
    field("banner_font", "banner", "text", "Impact", "Font", ""),
    field("banner_font_size", "banner", "int", 64, "Size", "", min=16, max=160),
    field("banner_accent_colour", "banner", "colour", "#FFB400",
          "Line 1 colour", ""),
    field("banner_colour", "banner", "colour", "#E62020", "Line 2 colour", ""),

    # -------------------------------------------------------- checklist --- #
    field("checklist_enabled", "checklist", "bool", True, "Show the list", ""),
    field("checklist_font", "checklist", "text", "Arial Black", "Font", ""),
    field("checklist_font_size", "checklist", "int", 40, "Size", "",
          min=14, max=120),
    field("checklist_x", "checklist", "int", 34, "Left position (px)", "",
          min=0, max=1000),
    field("checklist_y", "checklist", "int", 1303, "Top position (px)",
          "1920 is the bottom of the frame. Put the list under the picture if "
          "your footage is letterboxed.", min=0, max=1900),

    # --------------------------------------------------------- captions --- #
    field("captions_enabled", "captions", "bool", True, "Burn in captions", ""),
    field("caption_font", "captions", "text", "Arial Black", "Font", ""),
    field("caption_font_size", "captions", "int", 54, "Size", "", min=16, max=140),
    field("caption_colour", "captions", "colour", "#FFFFFF", "Colour", ""),
    field("caption_margin_v", "captions", "int", 700, "Height from bottom (px)",
          "", min=0, max=1800),
    field("caption_max_words", "captions", "int", 4, "Words per line", "",
          min=1, max=12),
    field("caption_uppercase", "captions", "bool", False, "Capitals", ""),

    # ------------------------------------------------------------ badge --- #
    field("countdown_overlay", "badge", "bool", False,
          "Show a corner badge", "An alternative to the numbered list."),
    field("countdown_font_size", "badge", "int", 72, "Size", "", min=20, max=180),
    field("countdown_position", "badge", "select", "top-left", "Position", "",
          options=["top-left", "top-right", "top-center",
                   "bottom-left", "bottom-right"]),
    field("countdown_caption", "badge", "bool", False,
          "Label under the badge", "Show the clip's label beneath the number."),

    # ------------------------------------------------------------ frame --- #
    field("width", "frame", "int", 1080, "Width", "", min=240, max=2160),
    field("height", "frame", "int", 1920, "Height", "", min=240, max=3840),
    field("fps", "frame", "int", 30, "Frames per second", "",
          options=[24, 25, 30, 50, 60]),
    field("background", "frame", "select", "pad", "Fit footage by",
          "pad puts black bars around it, blur fills them with a blurred copy, "
          "crop zooms in and loses the edges.",
          options=["pad", "blur", "crop"]),
    field("blur_sigma", "frame", "float", 22.0, "Blur strength", "",
          min=1, max=60),
    field("crf", "frame", "int", 20, "Quality (lower is better)", "",
          min=14, max=32),
    field("preset", "frame", "select", "veryfast", "Encoding speed", "",
          options=["ultrafast", "veryfast", "fast", "medium", "slow"]),
    field("audio_bitrate", "frame", "select", "160k", "Audio bitrate", "",
          options=["96k", "128k", "160k", "192k", "256k"]),
    field("normalize_audio", "frame", "bool", False, "Even out loudness",
          "Levels clips that were recorded at different volumes."),

    # -------------------------------------------------------- copyright --- #
    field("copyright_scan", "copyright", "bool", True,
          "Scan for music",
          "Reads the source's own caption tags to find music, then cuts "
          "around it. Music is the usual cause of a claim."),
    field("max_music_coverage", "copyright", "float", 0.25,
          "Reject above this much music",
          "Share of an excerpt that may contain music.", min=0.05, max=1.0),
    field("music_padding_seconds", "copyright", "float", 0.6,
          "Clearance around music (s)", "", min=0.0, max=5.0),

    # ----------------------------------------------------------- upload --- #
    field("auto_upload", "upload", "bool", True,
          "Publish after rendering",
          "Turn off to keep videos in your library and download them yourself."),
    field("privacy_status", "upload", "select", "private", "Visibility",
          "Unlisted and private videos still count towards your channel, and "
          "are the safe choice while you are checking results.",
          options=["private", "unlisted", "public"]),
    field("category_id", "upload", "select", "24", "Category",
          "YouTube's category for the video. 24 is Entertainment.",
          options=["1", "10", "17", "20", "22", "23", "24", "26", "27", "28"]),
    field("made_for_kids", "upload", "bool", False, "Made for kids",
          "Required by YouTube on every upload."),
    field("publish_delay_minutes", "upload", "int", 0,
          "Schedule publish after (min)",
          "Above 0 the video uploads as private and goes public later. "
          "Scheduling requires private visibility.", min=0, max=20160),
    field("title_suffix", "upload", "text", "",
          "Add to every title", "Appended to the generated title, e.g. #Shorts."),
]

BY_KEY: Dict[str, Dict[str, Any]] = {f["key"]: f for f in FIELDS}


def defaults() -> Dict[str, Any]:
    """Every field at its default value."""
    return {f["key"]: (list(f["default"]) if isinstance(f["default"], list)
                       else f["default"]) for f in FIELDS}


def schema() -> Dict[str, Any]:
    """The catalogue, shaped for the editor UI."""
    return {
        "groups": [
            {**group,
             "fields": [f for f in FIELDS if f["group"] == group["id"]]}
            for group in GROUPS
        ]
    }


def _coerce(spec: Dict[str, Any], value: Any) -> Any:
    """Force one value into the field's type and range."""
    kind = spec["kind"]
    if kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    if kind in {"int", "float"}:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return spec["default"]
        if "min" in spec:
            number = max(float(spec["min"]), number)
        if "max" in spec:
            number = min(float(spec["max"]), number)
        return int(round(number)) if kind == "int" else round(number, 3)

    if kind == "list":
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(",")]
        elif isinstance(value, (list, tuple)):
            parts = [str(p).strip() for p in value]
        else:
            return list(spec["default"])
        return [p for p in parts if p][:80]

    if kind == "select":
        options = [str(o) for o in spec.get("options", [])]
        text = str(value).strip()
        return text if text in options else spec["default"]

    if kind == "colour":
        text = str(value).strip()
        if text.startswith("#") and len(text) in (4, 7):
            return text.upper()
        return spec["default"]

    text = str(value).replace("\r", " ").strip()
    return text[:600]


def sanitise(incoming: Optional[Dict[str, Any]],
             base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge user input over a base, keeping only known keys in range.

    Unknown keys are dropped rather than stored, so a niche can never carry a
    setting the renderer does not understand.
    """
    merged = dict(defaults())
    if base:
        for key, value in base.items():
            if key in BY_KEY:
                merged[key] = value
    for key, value in (incoming or {}).items():
        spec = BY_KEY.get(key)
        if spec is not None:
            merged[key] = _coerce(spec, value)

    # Cross-field sanity: a minimum above a maximum silently breaks planning.
    if merged["min_clip_seconds"] > merged["max_clip_seconds"]:
        merged["min_clip_seconds"] = merged["max_clip_seconds"]
    if merged["min_duration_seconds"] > merged["max_duration_seconds"]:
        merged["min_duration_seconds"] = merged["max_duration_seconds"]
    return merged
