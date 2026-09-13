import { interpolate } from "remotion";
import type { SceneId } from "./timeline";
import { FPS, SCENE_ORDER, WINDOWS, cutFrame, sec } from "./timeline";
import take from "./voiceover.json";

/*
 * The narration and the music bed.
 *
 * NARRATION
 * One take, public/guide/voiceover.mp3: twelve lines, one per scene, read by
 * ElevenLabs (voice and model in voiceover.json) and measured by
 * `node promo/tools/make_guide_voice.mjs`, which holds the script. Each line
 * is played in its own scene from inside that one file.
 *
 *   from, to   where the line's speech starts and ends in the take, in
 *              seconds (voiceover.json, written by the tool).
 *   AT         seconds after the scene's window opens (WINDOWS in
 *              timeline.ts) that the line starts.
 *
 * The beats in guide.ts are timed against these lines, so a click lands as
 * its word is spoken. Moving a line means checking the beats in its scene.
 * Changing a line's words means a new take from the tool.
 *
 * MUSIC
 * public/guide/music.mp3, from the tutorial's generator with the guide's cues:
 * the drums come in on the cut to the agent (5s), stop at the cut to the
 * outro (114s), and the progression resolves as the lockup returns.
 *
 *   node promo/tools/make_tutorial_music.mjs --length 120 --drums-in 5 --drums-out 114 --final 115 --out guide
 *
 * It runs the whole video and ducks under every line.
 */

export const VOICEOVER = "guide/voiceover.mp3";
export const MUSIC = "guide/music.mp3";

/** Below 1 so a voice peak and the music under it can't clip together. */
export const VOICE_VOLUME = 0.85;

/**
 * Most lines start half a second in, once the cut has settled. The intro's
 * waits for the lockup to draw on, so "set up ClipForge" lands as the title
 * rises; the outro's lets the last scene blur away first.
 */
const AT: Record<SceneId, number> = {
  intro: 1.2,
  agent: 0.5,
  ffmpeg: 0.5,
  pair: 0.5,
  niche: 0.5,
  banner: 0.5,
  sources: 0.5,
  longform: 0.5,
  showfilter: 0.5,
  youtube: 0.5,
  publish: 0.5,
  outro: 0.6,
};

export type Line = { scene: SceneId; at: number; from: number; to: number; text: string };

export const LINES: readonly Line[] = take.lines.map((line) => {
  const scene = line.scene as SceneId;
  return { ...line, scene, at: AT[scene] };
});

// A little air either side of each line's measured speech, but never into the
// line next to it in the take: "click Publish now" and "That's it" are only
// 0.23s apart there, so those two get less.
const LEAD = 0.1;
const TAIL = 0.15;
const GUARD = 0.08;

/** The line's clip in the take, in frames, for <Audio trimBefore / trimAfter>. */
export const clipOf = (line: Line) => {
  const i = LINES.indexOf(line);
  const floor = i === 0 ? 0 : LINES[i - 1].to + GUARD;
  const ceiling = i === LINES.length - 1 ? Infinity : LINES[i + 1].from - GUARD;
  const lead = Math.max(0, Math.min(LEAD, line.from - floor));
  const tail = Math.max(0, Math.min(TAIL, ceiling - line.to));
  return {
    trimBefore: Math.floor((line.from - lead) * FPS),
    trimAfter: Math.ceil((line.to + tail) * FPS),
  };
};

/** The global frames the line's clip starts and stops on: its speech starts on the line's `at`. */
export const spanOf = (line: Line) => {
  const { trimBefore, trimAfter } = clipOf(line);
  const start = cutFrame(line.scene) + sec(line.at) - (Math.round(line.from * FPS) - trimBefore);
  return { start, end: start + (trimAfter - trimBefore) };
};

/*
 * The music's level, as a gain on the bed, the same as the tutorial's: about
 * 18dB under the voice while a line plays, about 12dB under in the gaps, and
 * further up before the first line and after the last, where nothing is
 * speaking.
 */
const UNDER_SPEECH = 0.13;
const BETWEEN_LINES = 0.26;
const NOTHING_SPEAKING = 0.42;

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

export const musicVolume = (frame: number) => {
  // How far into a duck the bed is: 1 under a line, 0 clear of one. Down
  // over 6 frames into each line, back up over 12 after it.
  const duck = LINES.reduce((most, line) => {
    const { start, end } = spanOf(line);
    return Math.max(most, interpolate(frame, [start - 6, start, end + 4, end + 16], [0, 1, 1, 0], CLAMP));
  }, 0);
  const first = spanOf(LINES[0]);
  const last = spanOf(LINES[LINES.length - 1]);
  const open = Math.max(
    interpolate(frame, [first.start - 12, first.start], [1, 0], CLAMP),
    interpolate(frame, [last.end + 4, last.end + 24], [0, 1], CLAMP),
  );
  const clear = BETWEEN_LINES + (NOTHING_SPEAKING - BETWEEN_LINES) * open;
  return clear + (UNDER_SPEECH - clear) * duck;
};

// Fail loudly while tuning: every scene gets one line, in order, and each
// line finishes inside its own window.
if (LINES.map((l) => l.scene).join() !== SCENE_ORDER.join()) {
  throw new Error("voiceover.json must have one line per scene, in SCENE_ORDER. Run the tool again.");
}
for (const line of LINES) {
  const [open, close] = WINDOWS[line.scene];
  const ends = line.at + (line.to - line.from);
  if (line.to <= line.from) {
    throw new Error(`${line.scene}: the line's to (${line.to}s) must come after its from (${line.from}s).`);
  }
  if (ends > close - open) {
    throw new Error(
      `${line.scene}: the line runs to ${ends.toFixed(2)}s, past its ${close - open}s window. Start it earlier or widen the window.`,
    );
  }
}
