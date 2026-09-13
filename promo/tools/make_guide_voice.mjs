// Reads the setup guide's narration with ElevenLabs, as one take, and measures
// where every line starts and ends in it.
//
//   node promo/tools/make_guide_voice.mjs --check    the key, the quota, the voices, and what the take will use
//   node promo/tools/make_guide_voice.mjs            writes public/guide/voiceover.mp3 and src/guide/voiceover.json
//   node promo/tools/make_guide_voice.mjs --measure  measures the last take again, without reading a new one
//   node promo/tools/make_guide_voice.mjs --voice <id> --model <id>
//
// The key is ELEVENLABS_API_KEY, from the environment or from promo/.env,
// which git ignores. It starts with sk_ and ElevenLabs shows it once, when the
// key is created. The 64-character hex string listed on the API keys page is
// the key's ID, and the API refuses it.
//
// The whole script goes in one request, lines separated by blank lines, so
// the read keeps one voice and one pace from scene to scene. ElevenLabs sends
// the start and end time of every character along with the audio. Each line's
// from/to come from its first and last character, then move out to where its
// waveform starts and stops (a -38dB gate, as the tutorial's were measured),
// so a trailing consonant is never cut. src/guide/soundtrack.ts places each
// line in its scene from voiceover.json. Change a line here, run this again,
// and check the beats in that scene against the new read.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT = [
  { scene: "intro", text: "Let's set up ClipForge, from download to your first video." },
  {
    scene: "agent",
    text: "Start on Home. Scroll down to Render agent and download it. The agent renders your videos on your own PC, using your own connection.",
  },
  {
    scene: "ffmpeg",
    text: "Unzip it into its own folder. Inside is ffmpeg, the engine that cuts your clips, adds the banner and captions, and encodes the video. Keep it with the agent.",
  },
  {
    scene: "pair",
    text: "Now run ClipForgeAgent. Your browser opens with a code. Check it matches the one in the agent's window, click Pair it, and that's done.",
  },
  { scene: "niche", text: "Next, Settings. Say what your niche is, and add a few search terms." },
  { scene: "banner", text: "Lines one and two are the banner across the top of every video." },
  {
    scene: "sources",
    text: "Then the part that matters most. Paste a playlist, or name the YouTube channels to take clips from. That's how you get the clips you actually want.",
  },
  {
    scene: "longform",
    text: "Full-length videos are fine in a playlist. The AI finds the best moments and cuts them in for you.",
  },
  { scene: "showfilter", text: "Turn on Only from one show to keep every clip on your niche, then save." },
  { scene: "youtube", text: "Back on Home, connect your YouTube channel. Set up publishing walks you through it." },
  { scene: "publish", text: "When everything says Ready, click Publish now." },
  { scene: "outro", text: "That's it. ClipForge takes it from here." },
];

const option = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
};

// George: a warm, unhurried British narrator from ElevenLabs' default voices.
const VOICE = option("voice", "JBFqnCBsd6RMkjVDRZzb");
const MODEL = option("model", "eleven_multilingual_v2");
const API = "https://api.elevenlabs.io/v1";

const PROMO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MP3 = path.join(PROMO, "public/guide/voiceover.mp3");
const JSON_OUT = path.join(PROMO, "src/guide/voiceover.json");

const TEXT = SCRIPT.map((line) => line.text).join("\n\n");

const readKey = () => {
  if (process.env.ELEVENLABS_API_KEY) return process.env.ELEVENLABS_API_KEY.trim();
  const env = path.join(PROMO, ".env");
  if (!fs.existsSync(env)) return "";
  const match = fs.readFileSync(env, "utf8").match(/^\s*ELEVENLABS_API_KEY\s*=\s*(.*)$/m);
  return match ? match[1].trim().replace(/^["']|["']$/g, "") : "";
};

const KEY = readKey();
if (!KEY.startsWith("sk_")) {
  console.error(
    KEY
      ? "ELEVENLABS_API_KEY doesn't start with sk_, so it's probably the key's ID. Create or rotate a key on elevenlabs.io and copy the sk_ value it shows."
      : "No ELEVENLABS_API_KEY. Put `ELEVENLABS_API_KEY=sk_...` in promo/.env (git ignores it) or set it in the environment.",
  );
  process.exit(1);
}

const call = async (route, init = {}) => {
  const res = await fetch(`${API}${route}`, {
    ...init,
    headers: { "xi-api-key": KEY, "Content-Type": "application/json", ...init.headers },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body.detail?.message ?? JSON.stringify(body).slice(0, 300);
    throw new Error(`${route}: ${res.status} ${detail}`);
  }
  return body;
};

if (process.argv.includes("--check")) {
  const sub = await call("/user/subscription");
  console.log(`plan ${sub.tier}: ${sub.character_count} of ${sub.character_limit} characters used this period`);
  console.log(`the take is ${TEXT.length} characters`);
  // Listing voices needs the key's voices_read permission; the take doesn't.
  const listed = await call("/voices").catch((error) => {
    console.log(`(no voice list: ${error.message})`);
    return { voices: [] };
  });
  for (const v of listed.voices) {
    const labels = Object.values(v.labels ?? {}).join(", ");
    console.log(`${v.voice_id === VOICE ? "*" : " "} ${v.voice_id}  ${v.name}  (${v.category}${labels ? `; ${labels}` : ""})`);
  }
  process.exit(0);
}

// The alignment is kept beside the renders (out/ is git-ignored), so the take
// can be measured again with --measure without paying for another read.
const ALIGNMENT = path.join(PROMO, "out/guide-voice-alignment.json");
let alignment;
if (process.argv.includes("--measure")) {
  const kept = JSON.parse(fs.readFileSync(ALIGNMENT, "utf8"));
  if (kept.text !== TEXT) throw new Error("the kept take was read from a different script; run without --measure");
  ({ alignment } = kept);
} else {
  console.log(`reading ${SCRIPT.length} lines, ${TEXT.length} characters, voice ${VOICE}, model ${MODEL}`);
  // 128kbps is the best MP3 the free plan returns, and plenty for a voice.
  const take = await call(`/text-to-speech/${VOICE}/with-timestamps?output_format=mp3_44100_128`, {
    method: "POST",
    body: JSON.stringify({
      text: TEXT,
      model_id: MODEL,
      voice_settings: { stability: 0.5, similarity_boost: 0.75, style: 0, use_speaker_boost: true },
    }),
  });
  fs.mkdirSync(path.dirname(MP3), { recursive: true });
  fs.writeFileSync(MP3, Buffer.from(take.audio_base64, "base64"));
  ({ alignment } = take);
  fs.mkdirSync(path.dirname(ALIGNMENT), { recursive: true });
  fs.writeFileSync(ALIGNMENT, JSON.stringify({ text: TEXT, alignment }));
}

// Where each line's first and last characters are spoken. The alignment is
// normally one entry per character of TEXT; if the service ever normalises the
// text, find each line in what it did read instead.
// Timed from the first and last letters: punctuation and the blank lines
// between lines take up the silence around them, so their times say little.
const { characters, character_start_times_seconds: starts, character_end_times_seconds: ends } = alignment;
const spoken = characters.join("");
const letter = /[\p{L}\p{N}]/u;
let cursor = 0;
const aligned = SCRIPT.map((line) => {
  const at = spoken.indexOf(line.text, cursor);
  if (at === -1) throw new Error(`couldn't find the ${line.scene} line in the alignment`);
  cursor = at + line.text.length;
  let first = at;
  while (!letter.test(spoken[first])) first++;
  let last = at + line.text.length - 1;
  while (!letter.test(spoken[last])) last--;
  return { ...line, from: starts[first], to: ends[last] };
});

// The take as 10ms loudness windows, decoded with the ffmpeg Remotion ships.
// That build has no raw PCM muxer, so it writes a WAV down the pipe; a piped
// WAV can't go back to fill in its sizes, so the samples are simply
// everything after the data chunk's header.
const RATE = 16000;
const WINDOW = RATE / 100;
const decoded = spawnSync(
  "npx",
  [
    "remotion", "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", MP3,
    "-ac", "1", "-ar", String(RATE), "-c:a", "pcm_s16le", "-bitexact", "-map_metadata", "-1", "-f", "wav", "-",
  ],
  { cwd: PROMO, shell: process.platform === "win32", maxBuffer: 1 << 28 },
);
if (decoded.status !== 0) throw new Error(`decoding the take failed: ${decoded.stderr}`);
const wav = decoded.stdout;
let chunk = 12;
while (wav.toString("ascii", chunk, chunk + 4) !== "data") {
  if (chunk >= wav.length) throw new Error("the decoded take has no data chunk");
  const size = wav.readUInt32LE(chunk + 4);
  chunk += 8 + size + (size & 1);
}
const pcm = wav.subarray(chunk + 8);
const samples = new Int16Array(pcm.buffer.slice(pcm.byteOffset, pcm.byteOffset + (pcm.length & ~1)));
const loud = [];
for (let i = 0; i + WINDOW <= samples.length; i += WINDOW) {
  let sum = 0;
  for (let j = i; j < i + WINDOW; j++) sum += (samples[j] / 32768) ** 2;
  loud.push(10 * Math.log10(sum / WINDOW + 1e-12) > -38);
}
const duration = samples.length / RATE;

// From the aligned edges to the gate, in 10ms windows. An edge that lands on
// sound follows it outwards until it goes quiet: a start back up to 0.3s, an
// end on up to 0.5s, stepping over pauses of up to 60ms inside a word (the
// closure before a final t). An edge that lands on quiet comes in to the
// nearest sound, up to a second. Neither passes the neighbouring line's
// aligned edge, and the pause between lines, even the 0.15s one before the
// outro, stops the walk before that.
const BRIDGE = 6;
const lines = aligned.map((line, i) => {
  const floor = i === 0 ? 0 : Math.ceil(aligned[i - 1].to * 100);
  const ceiling = i === aligned.length - 1 ? loud.length : Math.floor(aligned[i + 1].from * 100);
  let a = Math.floor(line.from * 100);
  if (loud[a]) {
    const stop = Math.max(floor, a - 30);
    while (a > stop && loud[a - 1]) a--;
  } else {
    const stop = Math.min(a + 100, Math.floor(line.to * 100));
    while (a < stop && !loud[a]) a++;
  }
  // b is the first quiet window after the line: the line ends at b / 100.
  let b = Math.floor(line.to * 100);
  if (loud[b]) {
    const stop = Math.min(ceiling, b + 50);
    while (b < stop) {
      if (loud[b]) {
        b++;
        continue;
      }
      let gap = 0;
      while (b + gap < stop && !loud[b + gap]) gap++;
      if (gap > BRIDGE || b + gap >= stop) break;
      b += gap;
    }
  } else {
    const stop = Math.max(a + 1, b - 100);
    while (b > stop && !loud[b - 1]) b--;
  }
  return { scene: line.scene, text: line.text, from: a / 100, to: b / 100 };
});
for (let i = 1; i < lines.length; i++) {
  if (lines[i].from <= lines[i - 1].to) {
    throw new Error(`${lines[i - 1].scene} and ${lines[i].scene} run together at ${lines[i].from}s; no pause to cut them at`);
  }
}

fs.writeFileSync(JSON_OUT, `${JSON.stringify({ voice: VOICE, model: MODEL, lines }, null, 2)}\n`);
console.log(`wrote ${path.relative(PROMO, MP3)} (${duration.toFixed(2)}s) and ${path.relative(PROMO, JSON_OUT)}`);
for (const line of lines) {
  console.log(`${line.scene.padEnd(11)} ${line.from.toFixed(2).padStart(6)} -> ${line.to.toFixed(2).padStart(6)}  ${(line.to - line.from).toFixed(2)}s`);
}
