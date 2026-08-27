"""
engine.py -- Turn a set of clips into one vertical video.

ffmpeg is driven directly rather than through a wrapper, because the concat
filtergraph and the burned-in overlay have to be built in one pass: a second
encode over a finished file costs quality and time for nothing.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..config import settings
from ..logging_setup import get_logger
from .overlay import OverlayPlan, write_ass

log = get_logger("render.engine")


class RenderError(RuntimeError):
    pass


@dataclass
class Segment:
    path: Path
    start: float
    duration: float
    label: str = ""


@dataclass
class RenderResult:
    path: Path
    duration: float
    width: int
    height: int
    size_bytes: int
    thumbnail: Optional[Path] = None


def probe(path: Path) -> Dict:
    try:
        out = subprocess.run(
            [settings.ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout
        return json.loads(out)
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        raise RenderError(f"Could not read {path.name}: {exc}") from exc


def media_summary(path: Path) -> Tuple[float, bool, int, int]:
    """(duration, has_audio, width, height)."""
    info = probe(path)
    duration = float(info.get("format", {}).get("duration") or 0.0)
    width = height = 0
    has_audio = False
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video" and not width:
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            if not duration:
                duration = float(stream.get("duration") or 0.0)
        elif stream.get("codec_type") == "audio":
            has_audio = True
    return duration, has_audio, width, height


def _vertical_filters(index: int, fmt: Dict, has_audio: bool,
                      start: float, duration: float) -> Tuple[str, str, str]:
    """Build the per-input filter chain. Returns (video_chain, audio_chain, labels)."""
    width = int(fmt.get("width", 1080))
    height = int(fmt.get("height", 1920))
    fps = int(fmt.get("fps", 30))
    style = fmt.get("background", "pad")

    vin, vout = f"{index}:v", f"v{index}"
    trim = f"trim=start={start:.3f}:duration={duration:.3f},setpts=PTS-STARTPTS"

    if style == "crop":
        compose = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                   f"crop={width}:{height}")
    elif style == "blur":
        # Blurred, zoomed copy behind the letterboxed original.
        sigma = float(fmt.get("blur_sigma", 22.0))
        compose = (
            f"split=2[bg{index}][fg{index}];"
            f"[bg{index}]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},gblur=sigma={sigma}[bgb{index}];"
            f"[fg{index}]scale={width}:{height}:force_original_aspect_ratio=decrease[fgs{index}];"
            f"[bgb{index}][fgs{index}]overlay=(W-w)/2:(H-h)/2"
        )
    else:  # pad
        compose = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")

    video = f"[{vin}]{trim},{compose},setsar=1,fps={fps}[{vout}]"

    if has_audio:
        audio = (f"[{index}:a]atrim=start={start:.3f}:duration={duration:.3f},"
                 f"asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:"
                 f"sample_rates=44100:channel_layouts=stereo[a{index}]")
    else:
        # Silence keeps the concat filter's stream count consistent.
        audio = (f"anullsrc=r=44100:cl=stereo,atrim=duration={duration:.3f},"
                 f"asetpts=PTS-STARTPTS[a{index}]")
    return video, audio, f"[{vout}][a{index}]"


def render(segments: Sequence[Segment], plan: OverlayPlan, fmt: Dict,
           destination: Path, watermark: str = "") -> RenderResult:
    """Cut, stack and burn a finished vertical video."""
    if not segments:
        raise RenderError("Nothing to render.")

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    overlay = write_ass(plan, destination.with_suffix(".ass"), fmt, watermark)

    inputs: List[str] = []
    chains: List[str] = []
    labels: List[str] = []
    anull_needed = False

    for index, segment in enumerate(segments):
        duration, has_audio, _, _ = media_summary(segment.path)
        if duration <= 0:
            raise RenderError(f"{segment.path.name} has no readable duration.")
        length = max(0.5, min(segment.duration, duration - segment.start))

        inputs.extend(["-i", str(segment.path)])
        video, audio, label = _vertical_filters(index, fmt, has_audio,
                                                segment.start, length)
        chains.append(video)
        if not has_audio:
            anull_needed = True
        chains.append(audio)
        labels.append(label)

    concat = f"{''.join(labels)}concat=n={len(segments)}:v=1:a=1[vcat][aout]"
    chains.append(concat)

    video_out = "vcat"
    if overlay is not None:
        # libass wants forward slashes and an escaped drive colon.
        escaped = str(overlay).replace("\\", "/").replace(":", "\\:")
        chains.append(f"[vcat]ass='{escaped}'[vout]")
        video_out = "vout"

    command = [settings.ffmpeg, "-hide_banner", "-nostdin", "-y"]
    if anull_needed:
        command.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
        # The synthetic input shifts indices, so rebuild with the offset.
        return _render_with_silence(segments, plan, fmt, destination, watermark)

    audio_out = "aout"
    if fmt.get("normalize_audio"):
        # Even out clips recorded at wildly different levels.
        chains.append("[aout]loudnorm=I=-16:TP=-1.5:LRA=11[anorm]")
        audio_out = "anorm"

    command.extend(inputs)
    command.extend([
        "-filter_complex", ";".join(chains),
        "-map", f"[{video_out}]", "-map", f"[{audio_out}]",
        "-c:v", "libx264", "-preset", str(fmt.get("preset", "veryfast")),
        "-crf", str(int(fmt.get("crf", 20))), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", str(fmt.get("audio_bitrate", "160k")),
        "-movflags", "+faststart",
        str(destination),
    ])

    log.info("Rendering %d segment(s) -> %s", len(segments), destination.name)
    result = subprocess.run(command, capture_output=True, text=True,
                            errors="replace", timeout=1800)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-6:])
        raise RenderError(f"ffmpeg failed: {tail}")

    return _finalise(destination)


def _render_with_silence(segments, plan, fmt, destination, watermark) -> RenderResult:
    """Fallback path when a clip has no audio track.

    Rather than juggle input offsets, each silent clip gets a generated audio
    track written alongside it first, so the main path stays simple.
    """
    patched: List[Segment] = []
    for segment in segments:
        duration, has_audio, _, _ = media_summary(segment.path)
        if has_audio:
            patched.append(segment)
            continue
        fixed = segment.path.with_name(f"{segment.path.stem}_snd.mp4")
        subprocess.run(
            [settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(segment.path),
             "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-shortest", "-c:v", "copy", "-c:a", "aac", str(fixed)],
            check=True, capture_output=True, timeout=600,
        )
        patched.append(Segment(fixed, segment.start, segment.duration, segment.label))

    # Every clip now has audio, so the normal path applies.
    return render(patched, plan, fmt, destination, watermark)


def _finalise(destination: Path) -> RenderResult:
    duration, _, width, height = media_summary(destination)
    thumbnail = destination.with_suffix(".jpg")
    try:
        subprocess.run(
            [settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-ss", f"{min(1.5, max(duration / 3, 0.2)):.2f}", "-i", str(destination),
             "-frames:v", "1", "-vf", "scale=360:-1", str(thumbnail)],
            check=True, capture_output=True, timeout=120,
        )
    except (subprocess.SubprocessError, OSError):
        thumbnail = None

    return RenderResult(
        path=destination,
        duration=duration,
        width=width,
        height=height,
        size_bytes=destination.stat().st_size,
        thumbnail=thumbnail,
    )
