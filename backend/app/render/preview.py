"""
preview.py -- A single frame showing exactly what the finished video will look like.

The point of a preview is fidelity. A CSS mock-up of the layout would be quick
but would drift from the renderer the moment either changed, and the user would
find out only after spending a render. So this builds the frame the same way
the real pipeline does: the same background composition, the same ASS overlay
generator, burned in by the same ffmpeg.

It is deliberately cheap -- one frame, no audio, no encode -- so it can be
called every time somebody edits a setting.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..logging_setup import get_logger
from .overlay import Caption, OverlayItem, OverlayPlan, write_ass

log = get_logger("render.preview")

# Placeholder entries when the user has not run anything yet. Deliberately
# generic: the point is to show the layout, not to promise this content.
SAMPLE_LABELS = [
    "The opening hook",
    "Second moment",
    "Third moment",
    "Fourth moment",
    "The payoff",
    "Bonus clip",
    "Seventh",
    "Eighth",
    "Ninth",
    "Tenth",
    "Eleventh",
    "Twelfth",
]

SAMPLE_CAPTION = "this is where the captions sit"


def _labels_for(fmt: Dict, count: int) -> List[str]:
    """Prefer the user's own search terms so the preview feels like theirs."""
    terms = [str(t).strip() for t in (fmt.get("search_terms") or []) if str(t).strip()]
    labels: List[str] = []
    for index in range(count):
        if index < len(terms):
            labels.append(terms[index][:34].title())
        else:
            labels.append(SAMPLE_LABELS[index % len(SAMPLE_LABELS)])
    return labels


def _background_source(fmt: Dict, user_upload: Optional[Path]) -> List[str]:
    """ffmpeg input args for the frame behind the overlay.

    A real uploaded clip is used when there is one, because seeing the overlay
    against actual footage is the whole point. Otherwise a neutral grey stands
    in -- not black, or the letterboxing would be invisible.
    """
    if user_upload and user_upload.exists():
        # A few seconds in, to skip fades and black leader frames.
        return ["-ss", "2", "-i", str(user_upload)]
    return ["-f", "lavfi", "-i", "color=c=0x3a3a40:s=1280x720:d=1"]


def _compose(fmt: Dict) -> str:
    """The same scale/pad/crop the renderer uses, so framing matches."""
    width = int(fmt.get("width", 1080))
    height = int(fmt.get("height", 1920))
    style = str(fmt.get("background", "pad"))

    if style == "crop":
        return (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}")
    if style == "blur":
        sigma = float(fmt.get("blur_sigma", 22.0))
        return (
            f"split=2[bg][fg];"
            f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},gblur=sigma={sigma}[bgb];"
            f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
        )
    return (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")


def build(fmt: Dict, *, at_clip: int = 2, user_upload: Optional[Path] = None,
          watermark: str = "", scale_to: int = 540) -> bytes:
    """Render one PNG of the layout. Returns the image bytes.

    ``at_clip`` picks which moment to show. The default of 2 is deliberate: it
    is the first frame where the numbered list has revealed more than one
    entry, which is the thing people most want to check.
    """
    count = max(2, min(int(fmt.get("clips", 5)), 12))
    at_clip = max(1, min(at_clip, count))
    per_clip = max(1.0, float(fmt.get("target_seconds", 105)) / count)
    labels = _labels_for(fmt, count)

    # A plan whose timings put `at_clip` on screen at t=0 of the frame we grab.
    plan = OverlayPlan()
    for position in range(1, count + 1):
        plan.items.append(OverlayItem(
            number=position,
            label=labels[position - 1],
            timeline_start=(position - 1) * per_clip,
            duration=per_clip,
            captions=[Caption(0.0, per_clip, SAMPLE_CAPTION)]
            if fmt.get("captions_enabled") else [],
        ))

    workspace = Path(tempfile.mkdtemp(prefix="cf-preview-"))
    try:
        ass_path = write_ass(plan, workspace / "overlay.ass", fmt, watermark)
        output = workspace / "preview.png"

        chain = _compose(fmt)
        if ass_path is not None:
            escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")
            chain += f",ass='{escaped}'"
        # Scale down for delivery: a full 1080x1920 PNG is needlessly large
        # for something shown at a few hundred pixels wide.
        chain += f",scale={scale_to}:-1"

        # Seek into the middle of the chosen clip so the overlay state is the
        # steady one, not a transition.
        seek = (at_clip - 1) * per_clip + per_clip / 2

        command = [
            settings.ffmpeg, "-hide_banner", "-nostdin", "-y",
            *_background_source(fmt, user_upload),
            "-filter_complex", f"[0:v]loop=loop=-1:size=1,trim=duration=1,{chain}[out]",
            "-map", "[out]", "-frames:v", "1",
            "-ss", "0",
            str(output),
        ]
        # The ASS timeline is absolute, so shift the overlay instead of seeking
        # the source: setpts moves the frame to the moment we want to show.
        command[command.index("-filter_complex") + 1] = (
            f"[0:v]loop=loop=-1:size=1,trim=duration=1,"
            f"setpts=PTS+{seek}/TB,{chain}[out]"
        )

        result = subprocess.run(command, capture_output=True, text=True,
                                errors="replace", timeout=90)
        if result.returncode != 0 or not output.exists():
            tail = "\n".join(result.stderr.strip().splitlines()[-4:])
            raise RuntimeError(f"preview render failed: {tail}")

        return output.read_bytes()
    finally:
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)
