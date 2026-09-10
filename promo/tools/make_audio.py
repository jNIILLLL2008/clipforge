"""Synthesises the ClipForge ad's music bed and sound effects.

Everything here is generated from scratch so the promo renders offline and
carries no licence questions, and so the beat lands exactly on the cuts: the
video is 60fps and the bed runs at 180bpm, which puts a kick every 20 frames
and a downbeat on every word of the opening.
"""

import os
import struct
import wave

import numpy as np

SR = 44100
OUT = "C:/Users/jaini/clipforge/promo/public"

FPS = 60
BEAT = 1.0 / 3.0  # 180 bpm
DURATION = 15.1


def frames(n):
    return n / FPS


def t_axis(seconds):
    return np.arange(int(seconds * SR)) / SR


def write_wav(path, mono_or_stereo, peak=0.89):
    x = np.asarray(mono_or_stereo, dtype=np.float64)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    m = np.max(np.abs(x))
    if m > 0:
        x = x / m * peak
    data = (x * 32767.0).astype("<i2")
    with wave.open(path, "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(data.tobytes())
    return path


def band(x, low=None, high=None):
    """Zero-phase band limit via FFT. Fine for one-shots and static beds."""
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    mask = np.ones_like(freqs)
    if low is not None:
        mask *= 1.0 / (1.0 + (low / np.maximum(freqs, 1e-6)) ** 4)
    if high is not None:
        mask *= 1.0 / (1.0 + (freqs / high) ** 4)
    return np.fft.irfft(spec * mask, n=len(x))


def sweep_band(x, low_start, low_end, high_start, high_end, blocks=48):
    """Time-varying band-pass, done blockwise. Good enough for whooshes."""
    out = np.zeros_like(x)
    edges = np.linspace(0, len(x), blocks + 1).astype(int)
    win = np.hanning(2)
    del win
    for i in range(blocks):
        a, b = edges[i], edges[i + 1]
        if b <= a:
            continue
        p = i / max(blocks - 1, 1)
        seg = band(
            x[a:b],
            low=low_start + (low_end - low_start) * p,
            high=high_start + (high_end - high_start) * p,
        )
        out[a:b] = seg
    return out


def env(t, attack, decay):
    a = np.clip(t / max(attack, 1e-6), 0, 1)
    d = np.exp(-np.maximum(t, 0) / decay)
    return a * d


def place(buf, sample, at_seconds, gain=1.0):
    i = int(at_seconds * SR)
    n = min(len(sample), len(buf) - i)
    if i < 0 or n <= 0:
        return
    buf[i : i + n] += sample[:n] * gain


# --------------------------------------------------------------- one-shots --


def kick():
    t = t_axis(0.34)
    f = 45 + 150 * np.exp(-t / 0.022)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(t, 0.001, 0.105)
    tick = band(np.random.default_rng(1).normal(0, 1, len(t)), low=1800) * env(
        t, 0.0002, 0.006
    )
    return np.tanh((body + tick * 0.35) * 1.6)


def hat(open_=False):
    dur = 0.16 if open_ else 0.055
    t = t_axis(dur)
    n = np.random.default_rng(2 if open_ else 3).normal(0, 1, len(t))
    return band(n, low=6800) * env(t, 0.0004, dur / 3.6)


def stab(freq, dur=0.26):
    t = t_axis(dur)
    x = np.zeros_like(t)
    for h, amp in ((1, 1.0), (2, 0.5), (3, 0.32), (4, 0.18), (6, 0.09)):
        x += amp * np.sin(2 * np.pi * freq * h * t)
    x *= env(t, 0.004, dur / 3.2)
    return band(x, high=2600) * 0.5


def sub(freq, dur):
    t = t_axis(dur)
    x = np.sin(2 * np.pi * freq * t)
    x += 0.18 * np.sin(2 * np.pi * freq * 2 * t)
    return np.tanh(x * 1.25) * env(t, 0.008, dur * 1.9)


# ------------------------------------------------------------------- music --


def build_music():
    n = int(DURATION * SR)
    drums = np.zeros(n)
    bassline = np.zeros(n)
    tops = np.zeros(n)

    k = kick()
    h_closed = hat()
    h_open = hat(open_=True)

    # Kicks. Sparse under the opening words, then four to the floor from the
    # moment the phones arrive (frame 120), out to the end card (frame 690).
    kick_times = [frames(0), frames(40), frames(80)]
    tt = frames(120)
    while tt < frames(690):
        kick_times.append(tt)
        tt += BEAT
    for i, kt in enumerate(kick_times):
        place(drums, k, kt, 1.0 if i > 2 else 0.85)
    # One last hit as the camera bursts through into the end card.
    place(drums, k, frames(690), 1.15)

    # Hats: offbeats from frame 120, doubling up for the last stretch.
    tt = frames(120) + BEAT / 2
    while tt < frames(690):
        place(tops, h_closed, tt, 0.30)
        if tt > frames(480):
            place(tops, h_closed, tt - BEAT / 4, 0.16)
        tt += BEAT
    tt = frames(160)
    while tt < frames(690):
        place(tops, h_open, tt, 0.16)
        tt += BEAT * 4

    # Bass: A minor loop, one root per bar of four beats.
    roots = [55.00, 55.00, 43.65, 49.00]
    tt = frames(120)
    i = 0
    while tt < frames(700):
        place(bassline, sub(roots[i % 4], BEAT * 4 * 0.92), tt, 0.9)
        tt += BEAT * 4
        i += 1

    # Stabs, only once the ad is at full energy behind the headline.
    stab_notes = [220.0, 261.63, 220.0, 196.00, 220.0, 293.66, 261.63, 220.0]
    tt = frames(480)
    i = 0
    while tt < frames(690):
        place(tops, stab(stab_notes[i % len(stab_notes)]), tt, 0.34)
        tt += BEAT
        i += 1

    # Sidechain the low end to the kick so the bass breathes.
    t = np.arange(n) / SR
    duck = np.ones(n)
    for kt in kick_times:
        d = t - kt
        m = d >= 0
        duck[m] = np.minimum(duck[m], 1.0 - 0.72 * np.exp(-d[m] / 0.085))
    bassline *= duck

    # A drone under the opening, and a pad tail under the end card.
    drone = band(
        np.sin(2 * np.pi * 55 * t) + 0.5 * np.sin(2 * np.pi * 82.4 * t), high=400
    )
    drone *= np.interp(
        t,
        [0, frames(20), frames(110), frames(140)],
        [0.0, 0.30, 0.30, 0.0],
    )
    pad = band(
        np.sin(2 * np.pi * 110 * t)
        + 0.6 * np.sin(2 * np.pi * 164.8 * t)
        + 0.4 * np.sin(2 * np.pi * 220 * t),
        high=1400,
    )
    pad *= np.interp(
        t,
        [frames(688), frames(706), frames(820), frames(890)],
        [0.0, 0.26, 0.22, 0.0],
    )

    mix = drums * 0.85 + bassline * 0.75 + tops * 0.65 + drone + pad

    # A short breath either side of the click, so the click SFX lands in a gap.
    mix *= np.interp(
        t,
        [frames(404), frames(416), frames(422), frames(436)],
        [1.0, 0.35, 0.35, 1.0],
        left=1.0,
        right=1.0,
    )

    stereo = np.stack([mix, mix], axis=1)
    # Widen the tops only; keep the low end mono.
    wide = np.stack([tops, np.roll(tops, 380)], axis=1) * 0.2
    return np.tanh((stereo + wide) * 1.05)


# --------------------------------------------------------------------- sfx --


def sfx_boom():
    t = t_axis(0.85)
    f = 38 + 190 * np.exp(-t / 0.05)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(t, 0.001, 0.24)
    snap = band(np.random.default_rng(7).normal(0, 1, len(t)), low=900) * env(
        t, 0.0003, 0.02
    )
    return np.tanh((body * 1.3 + snap * 0.4) * 1.4)


def sfx_whoosh():
    t = t_axis(1.05)
    n = np.random.default_rng(11).normal(0, 1, len(t))
    swept = sweep_band(n, 180, 900, 1600, 9000)
    swell = np.sin(np.pi * np.clip(t / 1.05, 0, 1)) ** 1.6
    doppler = np.sin(2 * np.pi * np.cumsum(90 + 500 * t) / SR) * 0.12
    return (swept * swell) + doppler * swell


def sfx_click():
    t = t_axis(0.09)
    n = np.random.default_rng(13).normal(0, 1, len(t))
    down = band(n, low=2200, high=11000) * env(t, 0.0002, 0.0045)
    body = np.sin(2 * np.pi * 320 * t) * env(t, 0.0004, 0.012) * 0.5
    up = band(n[::-1], low=3000) * env(np.maximum(t - 0.045, 0), 0.0002, 0.004) * 0.5
    return np.tanh((down + body + up) * 2.2)


def sfx_riser():
    t = t_axis(1.6)
    n = np.random.default_rng(17).normal(0, 1, len(t))
    swept = sweep_band(n, 400, 5200, 2200, 15000)
    tone = np.sin(2 * np.pi * np.cumsum(np.linspace(220, 1500, len(t))) / SR)
    grow = (t / 1.6) ** 2.2
    return np.tanh((swept * 0.8 + tone * 0.35) * grow * 2.0)


def sfx_impact():
    t = t_axis(1.9)
    f = 34 + 220 * np.exp(-t / 0.06)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(t, 0.001, 0.42)
    n = np.random.default_rng(19).normal(0, 1, len(t))
    crack = band(n, low=1200) * env(t, 0.0004, 0.05)
    tail = band(n, low=200, high=3000) * env(t, 0.02, 0.55) * 0.22
    x = body * 1.35 + crack * 0.5 + tail
    for delay, gain in ((0.09, 0.3), (0.17, 0.18), (0.28, 0.1)):
        x += np.roll(tail, int(delay * SR)) * gain
    return np.tanh(x * 1.3)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    write_wav(os.path.join(OUT, "music.wav"), build_music(), peak=0.72)
    write_wav(os.path.join(OUT, "sfx-boom.wav"), sfx_boom())
    write_wav(os.path.join(OUT, "sfx-whoosh.wav"), sfx_whoosh(), peak=0.7)
    write_wav(os.path.join(OUT, "sfx-click.wav"), sfx_click(), peak=0.8)
    write_wav(os.path.join(OUT, "sfx-riser.wav"), sfx_riser(), peak=0.62)
    write_wav(os.path.join(OUT, "sfx-impact.wav"), sfx_impact())
    print("wrote wavs")
    del struct
