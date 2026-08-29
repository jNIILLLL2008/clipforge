"""
overlay.py -- Banner, progressive checklist and captions as one ASS layer.

Ported from the single-channel tool and generalised: every string and position
comes from the niche's format, so a "Top 5" countdown and a caption-only meme
cut are the same code path with different settings.

ASS colours are ``&HAABBGGRR`` -- alpha first, then blue, green, red.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

PLAY_W, PLAY_H = 1080, 1920
_ASS_UNSAFE = str.maketrans({"{": "(", "}": ")", "\\": "/", "\r": " ", "\n": " "})


def _rgb(value: str, alpha: str = "00") -> str:
    value = (value or "").strip().lstrip("#")
    if len(value) != 6:
        value = "FFFFFF"
    return f"&H{alpha}{value[4:6]}{value[2:4]}{value[0:2]}".upper()


def _clock(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"


def _clean(text: str) -> str:
    return " ".join((text or "").translate(_ASS_UNSAFE).split()).strip()


def _fill_count(template: str, count: int) -> str:
    """{count} in banner text becomes the real number of clips."""
    if "{count}" in (template or ""):
        return template.replace("{count}", str(count))
    return re.sub(r"\bTOP\s+\d+\b", f"TOP {count}", template or "",
                  flags=re.IGNORECASE)


@dataclass
class Caption:
    start: float
    end: float
    text: str


_VTT_TIME = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})"
)
_TAGS = re.compile(r"<[^>]*>")

#: A whole cue that says only that something non-verbal happened. Matched
#: against the entire cue, never a substring: "[Music] I'm swinging" still has
#: speech in it and is worth keeping.
_NON_SPEECH = re.compile(
    r"[\[\(\u266a\u266b\s]*"
    r"(music|applause|laughter|laughs|cheering|clapping|silence|"
    r"instrumental|singing|sighs|gasps|screaming|theme|intro|outro)"
    r"[\]\)\u266a\u266b\s.]*"
    # Or no words at all: a cue of bare music notes, which is how many
    # auto-caption tracks mark a song rather than spelling out [Music].
    r"|[\u266a\u266b\u2669\u266c\s.\-]+",
    re.IGNORECASE,
)


def parse_vtt(path: Path, limit: int = 4000) -> List[Caption]:
    """Read a WebVTT file into timed captions.

    Auto-captions roll: each cue repeats the previous line plus a new word.
    Cues that merely extend the one before are collapsed, or the burned-in
    text stutters.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    cues: List[Caption] = []
    pending: Optional[List[float]] = None
    buffer: List[str] = []

    def flush() -> None:
        if pending is None:
            return
        text = " ".join(_TAGS.sub("", " ".join(buffer)).split()).strip()
        # A cue that is only a non-speech marker is not a caption. YouTube's
        # auto-captions emit [Music] over every scored moment, and an animated
        # series is scored end to end -- burning those in puts "[Music]"
        # across the screen for most of the video.
        if text and not _NON_SPEECH.fullmatch(text):
            cues.append(Caption(pending[0], pending[1], text))

    for line in raw.splitlines():
        match = _VTT_TIME.search(line)
        if match:
            flush()
            buffer = []
            h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(g) for g in match.groups())
            pending = [
                h1 * 3600 + m1 * 60 + s1 + ms1 / (1000 if ms1 > 99 else 100),
                h2 * 3600 + m2 * 60 + s2 + ms2 / (1000 if ms2 > 99 else 100),
            ]
        elif pending is not None:
            stripped = line.strip()
            if stripped and not stripped.isdigit() and not stripped.startswith(
                ("WEBVTT", "NOTE", "Kind:", "Language:", "STYLE")
            ):
                buffer.append(stripped)
        if len(cues) >= limit:
            break
    flush()

    deduped: List[Caption] = []
    for cue in cues:
        if deduped:
            previous = deduped[-1]
            if cue.text == previous.text:
                previous.end = max(previous.end, cue.end)
                continue
            if cue.text.startswith(previous.text):
                remainder = cue.text[len(previous.text):].strip()
                if not remainder:
                    previous.end = max(previous.end, cue.end)
                    continue
                cue = Caption(cue.start, cue.end, remainder)
        deduped.append(cue)
    return deduped


def chunk(cue: Caption, max_words: int) -> List[Caption]:
    """Split a long cue into short lines sharing its time span."""
    words = cue.text.split()
    if len(words) <= max_words:
        return [cue]
    pieces = [words[i:i + max_words] for i in range(0, len(words), max_words)]
    span = max(cue.end - cue.start, 0.4) / len(pieces)
    return [
        Caption(cue.start + i * span, cue.start + (i + 1) * span, " ".join(p))
        for i, p in enumerate(pieces)
    ]


@dataclass
class OverlayItem:
    number: int
    label: str
    timeline_start: float
    duration: float
    captions: List[Caption] = field(default_factory=list)

    @property
    def timeline_end(self) -> float:
        return self.timeline_start + self.duration


@dataclass
class OverlayPlan:
    items: List[OverlayItem] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(item.duration for item in self.items)


def build_ass(plan: OverlayPlan, fmt: Dict, watermark: str = "") -> str:
    """Render the whole overlay stack as one ASS document."""
    total = plan.total
    accent = _rgb(fmt.get("banner_accent_colour", "#FFB400"))
    secondary = _rgb(fmt.get("banner_colour", "#E62020"))
    white, black = _rgb("#FFFFFF"), _rgb("#000000")

    banner_font = fmt.get("banner_font", "Impact")
    list_font = fmt.get("checklist_font", "Arial Black")
    caption_font = fmt.get("caption_font", "Arial Black")
    banner_size = int(fmt.get("banner_font_size", 64))
    list_size = int(fmt.get("checklist_font_size", 40))
    caption_size = int(fmt.get("caption_font_size", 54))
    caption_margin = int(fmt.get("caption_margin_v", 700))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {PLAY_W}
PlayResY: {PLAY_H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Banner,{banner_font},{banner_size},{accent},{white},{black},&H90000000,-1,0,0,0,100,100,1,0,1,4,3,8,30,30,26,1
Style: Checklist,{list_font},{list_size},{white},{white},{black},&H90000000,-1,0,0,0,100,100,0,0,1,3,2,7,0,0,0,1
Style: Caption,{caption_font},{caption_size},{white},{white},{black},&H90000000,-1,0,0,0,100,100,0,0,1,5,3,2,60,60,{caption_margin},1
Style: Mark,{list_font},30,&H64FFFFFF,{white},{black},&H90000000,0,0,0,0,100,100,0,0,1,2,1,3,24,24,24,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: List[str] = []

    def say(start: float, end: float, style: str, text: str, layer: int = 0) -> None:
        if end - start < 0.05 or not text:
            return
        events.append(
            f"Dialogue: {layer},{_clock(start)},{_clock(end)},{style},,0,0,0,,{text}"
        )

    # --- banner ----------------------------------------------------------- #
    if fmt.get("banner_enabled") and total > 0:
        count = len(plan.items)
        line1 = _clean(_fill_count(fmt.get("banner_line1", ""), count))
        line2 = _clean(_fill_count(fmt.get("banner_line2", ""), count))
        if line1 or line2:
            text = line1
            if line2:
                text = f"{text}\\N{{\\c{secondary}&}}{line2}" if text else line2
            say(0.0, total, "Banner", text)

    # --- progressive checklist -------------------------------------------- #
    if fmt.get("checklist_enabled") and plan.items:
        x = int(fmt.get("checklist_x", 34))
        y = int(fmt.get("checklist_y", 1303))
        # Guard against a list positioned off the bottom of the frame.
        y = min(y, PLAY_H - int(fmt.get("checklist_font_size", 40)) * len(plan.items) - 20)
        for revealed, item in enumerate(plan.items, start=1):
            lines = []
            for position, entry in enumerate(plan.items, start=1):
                number = f"{{\\c{accent}&}}{entry.number}.{{\\c{white}&}}"
                lines.append(
                    f"{number} {_clean(entry.label)[:34]}" if position <= revealed
                    else number
                )
            say(item.timeline_start, item.timeline_end, "Checklist",
                f"{{\\pos({x},{y})}}" + "\\N".join(lines), layer=1)

    # --- countdown badge --------------------------------------------------- #
    if fmt.get("countdown_overlay") and plan.items:
        # Numpad alignment: 7 top-left, 9 top-right, 8 top-centre, 1/3 bottom.
        align = {"top-left": 7, "top-right": 9, "top-center": 8,
                 "bottom-left": 1, "bottom-right": 3}.get(
                     str(fmt.get("countdown_position", "top-left")), 7)
        size = int(fmt.get("countdown_font_size", 72))
        total_items = len(plan.items)
        for position, item in enumerate(plan.items, start=1):
            # Countdown counts down: first shown carries the highest number.
            number = total_items - position + 1 if fmt.get("countdown") else position
            text = (f"{{\\an{align}\\fs{size}\\c{accent}&}}#{number}")
            if fmt.get("countdown_caption") and item.label:
                text += f"{{\\fs{int(size * 0.42)}\\c{white}&}}\\N{_clean(item.label)[:28]}"
            say(item.timeline_start, item.timeline_end, "Banner", text, layer=1)

    # --- captions ---------------------------------------------------------- #
    if fmt.get("captions_enabled"):
        upper = bool(fmt.get("caption_uppercase"))
        for item in plan.items:
            for caption in item.captions:
                text = _clean(caption.text)
                if not text:
                    continue
                say(
                    item.timeline_start + caption.start,
                    min(item.timeline_start + caption.end, item.timeline_end),
                    "Caption",
                    text.upper() if upper else text,
                    layer=2,
                )

    # --- free-plan watermark ------------------------------------------------ #
    if watermark and total > 0:
        say(0.0, total, "Mark", _clean(watermark), layer=3)

    return header + "\n".join(events) + "\n"


def write_ass(plan: OverlayPlan, destination: Path, fmt: Dict,
              watermark: str = "") -> Optional[Path]:
    """Write the overlay next to the render, or None when nothing is enabled."""
    if not (fmt.get("banner_enabled") or fmt.get("checklist_enabled")
            or fmt.get("captions_enabled") or watermark):
        return None
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(build_ass(plan, fmt, watermark), encoding="utf-8")
    return destination
