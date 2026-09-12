// Synthesises the music bed for the YouTube setup tutorial.
//
//   node promo/tools/make_tutorial_music.mjs
//
// Writes promo/public/tutorial/music.mp3. Everything is generated here from
// oscillators and seeded noise, like the launch ad's effects in make_audio.py,
// so the bed carries no licence questions. Plain Node, no dependencies beyond
// the ffmpeg Remotion ships, which encodes the MP3.
//
// It is built to sit under a narrator. 120bpm puts a beat on every half
// second, so every cut in timeline.ts (all on whole seconds) lands on a beat.
// Warm pads on Fmaj7, G6, Em7, Am7, four seconds each, a sub bass, a soft bell
// arpeggio through a ping-pong delay, and quiet half-time drums. The drums come
// in on the cut to step 1 at 4s and stop at the outro's cut at 55s, where the
// progression resolves to Cmaj9 as the lockup returns, and the bed fades out
// by the end.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SR = 44100;
const BEAT = 60 / 120;
const BAR = BEAT * 4;
const LENGTH = 60;
const N = Math.round(LENGTH * SR);

const DRUMS_IN = 4;
const DRUMS_OUT = 55;
const FINAL_CHORD = 56;

const OUT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../public/tutorial");

// ------------------------------------------------------------------ utils --
let seed = 0x2545f491;
const noise = () => {
  seed ^= seed << 13;
  seed ^= seed >>> 17;
  seed ^= seed << 5;
  return ((seed >>> 0) / 4294967296) * 2 - 1;
};
const hz = (midi) => 440 * Math.pow(2, (midi - 69) / 12);
const at = (seconds) => Math.round(seconds * SR);
const bus = () => [new Float32Array(N), new Float32Array(N)];

/** Band-limited saw: the naive ramp with its discontinuity smoothed by polyBLEP. */
const polyblep = (t, dt) => {
  if (t < dt) {
    t /= dt;
    return t + t - t * t - 1;
  }
  if (t > 1 - dt) {
    t = (t - 1) / dt;
    return t * t + t + t + 1;
  }
  return 0;
};

/** RBJ cookbook biquad, run in place over a channel, retuned every 64 samples. */
const biquad = (x, type, cutoffAt, q = 0.707) => {
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  let b0 = 0, b1 = 0, b2 = 0, a1 = 0, a2 = 0;
  for (let i = 0; i < x.length; i++) {
    if (i % 64 === 0) {
      const w = (2 * Math.PI * Math.min(cutoffAt(i / SR), SR * 0.45)) / SR;
      const cos = Math.cos(w), alpha = Math.sin(w) / (2 * q);
      const a0 = 1 + alpha;
      if (type === "low") {
        b0 = (1 - cos) / 2 / a0; b1 = (1 - cos) / a0; b2 = b0;
      } else {
        b0 = (1 + cos) / 2 / a0; b1 = -(1 + cos) / a0; b2 = b0;
      }
      a1 = (-2 * cos) / a0; a2 = (1 - alpha) / a0;
    }
    const y = b0 * x[i] + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
    x2 = x1; x1 = x[i]; y2 = y1; y1 = y;
    x[i] = y;
  }
  return x;
};

// ----------------------------------------------------------------- chords --
// Pad voicings sit in octave 3-4 so they stay under the voice's formants.
const CHORDS = {
  Fmaj7: { root: 41, pad: [53, 57, 60, 64], bells: [65, 69, 72, 76] },
  G6: { root: 43, pad: [55, 59, 62, 64], bells: [67, 71, 74, 76] },
  Em7: { root: 40, pad: [52, 55, 59, 62], bells: [64, 67, 71, 74] },
  Am7: { root: 45, pad: [57, 60, 64, 67], bells: [69, 72, 76, 79] },
  Cmaj9: { root: 36, pad: [52, 55, 59, 62], bells: [72, 76, 79, 83, 86] },
};
const LOOP = ["Fmaj7", "G6", "Em7", "Am7"];

/** [start, end, chord] for the whole bed: the loop every 4s, then the resolution. */
const SCHEDULE = [];
for (let t = 0; t < FINAL_CHORD; t += 4) SCHEDULE.push([t, Math.min(t + 4, FINAL_CHORD), LOOP[(t / 4) % 4]]);
SCHEDULE.push([FINAL_CHORD, LENGTH, "Cmaj9"]);
const chordAt = (t) => SCHEDULE.find(([s, e]) => t >= s && t < e)[2];

// -------------------------------------------------------------------- pad --
const pad = bus();
for (const [start, end, name] of SCHEDULE) {
  const first = start === 0;
  const last = name === "Cmaj9";
  const attack = first ? 2.4 : 0.7;
  // The final chord rings to the end; the master fade takes it out.
  const release = last ? 0 : 1.3;
  const s0 = at(start), s1 = Math.min(N, at(end + release));
  for (const note of CHORDS[name].pad) {
    // Three saws per note, detuned and spread, for width without chorus.
    for (const [cents, left, right] of [[-7, 0.85, 0.35], [0, 0.6, 0.6], [7, 0.35, 0.85]]) {
      const f = hz(note) * Math.pow(2, cents / 1200);
      const dt = f / SR;
      let phase = noise() * 0.5 + 0.5;
      for (let i = s0; i < s1; i++) {
        const t = (i - s0) / SR;
        let env = Math.min(1, t / attack);
        if (!last && i >= at(end)) env *= Math.max(0, 1 - (i - at(end)) / (release * SR));
        const v = (2 * phase - 1 - polyblep(phase, dt)) * env * 0.05;
        pad[0][i] += v * left;
        pad[1][i] += v * right;
        phase += dt;
        if (phase >= 1) phase -= 1;
      }
    }
  }
}
// A slow sweep of the filter, so the pad breathes over each 16s loop.
for (const ch of pad) biquad(ch, "low", (t) => 950 + 450 * (0.5 + 0.5 * Math.sin((2 * Math.PI * t) / 16)), 0.8);

// ------------------------------------------------------------------- bass --
const bass = bus();
const kickTimes = [];
for (let bar = DRUMS_IN; bar < DRUMS_OUT; bar += BAR) {
  for (const offset of [0, 1.25]) if (bar + offset < DRUMS_OUT) kickTimes.push(bar + offset);
}
{
  let phase = 0;
  let k = -1;
  for (let i = at(DRUMS_IN); i < at(DRUMS_OUT + 0.5); i++) {
    const t = i / SR;
    const f = hz(CHORDS[chordAt(Math.min(t, FINAL_CHORD - 0.01))].root);
    phase += f / SR;
    const inEnv = Math.min(1, (t - DRUMS_IN) / 0.05) * Math.max(0, Math.min(1, (DRUMS_OUT + 0.4 - t) / 0.4));
    // Duck under each kick, recovering over ~150ms, so the two don't pile up.
    while (k + 1 < kickTimes.length && kickTimes[k + 1] <= t) k++;
    const pump = k < 0 ? 1 : 1 - 0.55 * Math.exp(-(t - kickTimes[k]) / 0.15);
    const v = Math.tanh(1.6 * Math.sin(2 * Math.PI * phase)) * 0.12 * inEnv * pump;
    bass[0][i] += v;
    bass[1][i] += v;
  }
}

// ------------------------------------------------------------------ bells --
// A soft FM bell: a sine with a brief 2:1 modulator on the attack.
const bells = bus();
const bell = (time, midi, level, pan) => {
  const f = hz(midi);
  const s0 = at(time), s1 = Math.min(N, s0 + at(1.2));
  for (let i = s0; i < s1; i++) {
    const t = (i - s0) / SR;
    const index = 1.4 * Math.exp(-t / 0.06);
    const v =
      Math.sin(2 * Math.PI * f * t + index * Math.sin(2 * Math.PI * 2 * f * t)) *
      Math.exp(-t / 0.32) *
      Math.min(1, t / 0.004) *
      level;
    bells[0][i] += v * (1 - pan);
    bells[1][i] += v * pan;
  }
};
// The spark striking in the intro, then a few notes while the lockup settles.
bell(0.7, 84, 0.07, 0.5);
bell(1.45, 76, 0.045, 0.35);
bell(1.95, 79, 0.045, 0.65);
// Eighth notes through each chord's tones, with rests, from step 1 to the outro.
const MASK = [1, 0, 1, 1, 0, 1, 0, 1];
for (let t = DRUMS_IN, k = 0; t < DRUMS_OUT; t += BEAT / 2, k++) {
  if (!MASK[k % 8]) continue;
  const tones = CHORDS[chordAt(t)].bells;
  const accent = k % 8 === 0 ? 1 : 0.7;
  bell(t, tones[k % tones.length], 0.04 * accent, k % 2 ? 0.7 : 0.3);
}
// The resolution: Cmaj9 rising as the lockup draws back on.
CHORDS.Cmaj9.bells.forEach((note, n) => bell(FINAL_CHORD + n * 0.25, note, 0.05, 0.3 + n * 0.1));
for (const ch of bells) biquad(ch, "low", () => 3200);

// ------------------------------------------------------------------ drums --
const drums = bus();
const hit = (time, fn, pan = 0.5) => {
  const s0 = at(time);
  for (let i = s0; i < Math.min(N, s0 + at(0.6)); i++) {
    const v = fn((i - s0) / SR);
    drums[0][i] += v * (1 - pan) * 2;
    drums[1][i] += v * pan * 2;
  }
};
const kick = (t) => {
  const f = 48 + 72 * Math.exp(-t / 0.035);
  return Math.sin(2 * Math.PI * f * t) * Math.exp(-t / 0.26) * 0.42;
};
for (const k of kickTimes) hit(k, kick);
const rim = bus();
for (let bar = DRUMS_IN; bar < DRUMS_OUT; bar += BAR) {
  const s0 = at(bar + 1.0);
  for (let i = s0; i < Math.min(N, s0 + at(0.25)); i++) {
    const t = (i - s0) / SR;
    const v = (noise() * 0.7 + Math.sin(2 * Math.PI * 190 * t) * 0.5) * Math.exp(-t / 0.07) * 0.1;
    rim[0][i] += v * 0.55;
    rim[1][i] += v * 0.45;
  }
}
for (const ch of rim) biquad(ch, "high", () => 900);
const hats = bus();
for (let t = DRUMS_IN, k = 0; t < DRUMS_OUT; t += BEAT / 2, k++) {
  const s0 = at(t);
  const level = k % 2 ? 0.05 : 0.03;
  for (let i = s0; i < Math.min(N, s0 + at(0.08)); i++) {
    const v = noise() * Math.exp(-(i - s0) / SR / 0.03) * level;
    hats[0][i] += v * 0.4;
    hats[1][i] += v * 0.6;
  }
}
for (const ch of hats) biquad(ch, "high", () => 7000);

// ------------------------------------------------------- delay and reverb --
// Ping-pong on the bells: a dotted eighth, bouncing left and right.
// The first echo lands left, the next right at 45%, and so on.
const delayed = bus();
{
  const d = at(BEAT * 0.75);
  for (let i = d; i < N; i++) {
    const mono = (bells[0][i - d] + bells[1][i - d]) * 0.5;
    delayed[0][i] = mono + 0.45 * delayed[1][i - d];
    delayed[1][i] = 0.45 * delayed[0][i - d];
  }
}

// Freeverb, cut down: four damped combs into two allpasses per side.
const reverb = (input, spread) => {
  const out = new Float32Array(N);
  for (const len of [1116, 1188, 1277, 1356].map((l) => l + spread)) {
    const buf = new Float32Array(len);
    let idx = 0, store = 0;
    for (let i = 0; i < N; i++) {
      const y = buf[idx];
      store = y * 0.78 + store * 0.22;
      buf[idx] = input[i] + store * 0.84;
      idx = (idx + 1) % len;
      out[i] += y;
    }
  }
  for (const len of [556, 441].map((l) => l + spread)) {
    const buf = new Float32Array(len);
    let idx = 0;
    for (let i = 0; i < N; i++) {
      const b = buf[idx];
      buf[idx] = out[i] + b * 0.5;
      out[i] = b - out[i];
      idx = (idx + 1) % len;
    }
  }
  return out;
};
const send = bus();
for (let c = 0; c < 2; c++) for (let i = 0; i < N; i++) send[c][i] = pad[c][i] * 0.5 + bells[c][i] + delayed[c][i] * 0.5;
const wet = [reverb(send[0], 0), reverb(send[1], 23)];

// ----------------------------------------------------------------- master --
const master = bus();
for (let c = 0; c < 2; c++) {
  for (let i = 0; i < N; i++) {
    master[c][i] =
      pad[c][i] + bass[c][i] + bells[c][i] + delayed[c][i] * 0.55 +
      drums[c][i] + rim[c][i] + hats[c][i] + wet[c][i] * 0.045;
  }
  biquad(master[c], "high", () => 32);
}
// Fade to silence over the last 1.5s, so the render's last frame is quiet.
for (let i = at(LENGTH - 1.6); i < N; i++) {
  const g = Math.max(0, (N - 0.1 * SR - i) / (1.5 * SR));
  master[0][i] *= g;
  master[1][i] *= g;
}
let peak = 0;
for (const ch of master) for (const v of ch) peak = Math.max(peak, Math.abs(v));
const gain = 0.89 / peak;

fs.mkdirSync(OUT_DIR, { recursive: true });
const data = Buffer.alloc(N * 4);
for (let i = 0; i < N; i++) {
  data.writeInt16LE(Math.round(Math.max(-1, Math.min(1, master[0][i] * gain)) * 32767), i * 4);
  data.writeInt16LE(Math.round(Math.max(-1, Math.min(1, master[1][i] * gain)) * 32767), i * 4 + 2);
}
const header = Buffer.alloc(44);
header.write("RIFF", 0);
header.writeUInt32LE(36 + data.length, 4);
header.write("WAVEfmt ", 8);
header.writeUInt32LE(16, 16);
header.writeUInt16LE(1, 20);
header.writeUInt16LE(2, 22);
header.writeUInt32LE(SR, 24);
header.writeUInt32LE(SR * 4, 28);
header.writeUInt16LE(4, 32);
header.writeUInt16LE(16, 34);
header.write("data", 36);
header.writeUInt32LE(data.length, 40);
// The WAV is 10MB, so it goes through a temp file and only the MP3 is kept,
// encoded with the ffmpeg Remotion ships.
const wav = path.join(os.tmpdir(), `tutorial-music-${process.pid}.wav`);
const mp3 = path.join(OUT_DIR, "music.mp3");
fs.writeFileSync(wav, Buffer.concat([header, data]));
const encode = spawnSync(
  "npx",
  ["remotion", "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", wav, "-c:a", "libmp3lame", "-b:a", "192k", mp3],
  { cwd: path.resolve(OUT_DIR, "../.."), stdio: "inherit", shell: process.platform === "win32" },
);
fs.rmSync(wav, { force: true });
if (encode.status !== 0) {
  console.error("encoding failed");
  process.exit(1);
}
console.log(`wrote ${mp3} (peak scaled by ${gain.toFixed(2)})`);
