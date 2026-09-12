import { interpolate } from "remotion";
import type { SceneId } from "./timeline";
import { FPS, SCENE_ORDER, WINDOWS, cutFrame, sec } from "./timeline";

/*
 * The narration and the music bed.
 *
 * NARRATION
 * One take, public/tutorial/voiceover.mp3: the nine lines below, joined with
 * blank lines, read by Higgsfield's Seed Speech engine in its preset voice
 * "Arthur". Each line is played in its own scene from inside that one file.
 *
 *   from, to   where the line's speech starts and ends in the take, in
 *              seconds, measured off its waveform (the pauses between lines
 *              are the stretches under -38dB).
 *   at         seconds after the scene's window opens (WINDOWS in
 *              timeline.ts) that the line starts.
 *
 * The beats in steps.ts are timed against these lines, so a click lands as
 * its word is spoken. Moving a line means checking the beats in its step.
 * Changing a line's words means a new take, and re-measuring from/to.
 *
 * MUSIC
 * public/tutorial/music.mp3, from `node promo/tools/make_tutorial_music.mjs`.
 * It runs the whole video and ducks under every line.
 */

export const VOICEOVER = "tutorial/voiceover.mp3";
export const MUSIC = "tutorial/music.mp3";

/** Below 1 so a voice peak and the music under it can't clip together. */
export const VOICE_VOLUME = 0.85;

export type Line = { scene: SceneId; at: number; from: number; to: number; text: string };

export const LINES: readonly Line[] = [
  { scene: "intro", at: 0.9, from: 0.21, to: 2.93, text: "Let's connect your YouTube channel to ClipForge." },
  { scene: "step1", at: 0.5, from: 3.5, to: 7.07, text: "ClipForge uploads through a Google Cloud project of your own." },
  {
    scene: "step2",
    at: 0.4,
    from: 7.73,
    to: 12.61,
    text: "First, open Google Cloud and create a new project. Any name works.",
  },
  {
    scene: "step3",
    at: 0.3,
    from: 13.03,
    to: 17.74,
    text: "Then search the library for YouTube Data API v3, and click Enable.",
  },
  {
    scene: "step4",
    at: 0.4,
    from: 18.32,
    to: 22.91,
    text: "On the consent screen, choose External, then add an app name and your email.",
  },
  {
    scene: "step5",
    at: 0.4,
    from: 23.53,
    to: 30.17,
    text: "Here's the step everyone misses. Add the Google account that owns your channel as a test user, or sign-in gets blocked.",
  },
  {
    scene: "step6",
    at: 0.4,
    from: 30.72,
    to: 38.96,
    text: "Copy ClipForge's redirect address. Create an OAuth client ID for a web application, and paste the address in, character for character.",
  },
  {
    scene: "step7",
    at: 0.3,
    from: 39.41,
    to: 44.22,
    text: "Finally, paste the client ID and secret into ClipForge, and hit Save and connect.",
  },
  { scene: "outro", at: 0.8, from: 44.88, to: 46.75, text: "That's it. You're ready to publish." },
];

// A little air either side of each line's measured speech, well inside the
// pauses around it (the shortest is 450ms).
const LEAD = 0.05;
const TAIL = 0.15;

/** The line's clip in the take, in frames, for <Audio trimBefore / trimAfter>. */
export const clipOf = (line: Line) => ({
  trimBefore: Math.floor((line.from - LEAD) * FPS),
  trimAfter: Math.ceil((line.to + TAIL) * FPS),
});

/** The global frames the line's clip starts and stops on. */
export const spanOf = (line: Line) => {
  const { trimBefore, trimAfter } = clipOf(line);
  const start = cutFrame(line.scene) + sec(line.at) - Math.round(LEAD * FPS);
  return { start, end: start + (trimAfter - trimBefore) };
};

/*
 * The music's level, as a gain on the bed. It sits about 18dB under the voice
 * while a line plays and comes up to about 12dB under in the gaps, and further
 * before the first line and after the last, where nothing is speaking.
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
  throw new Error("LINES must have one line per scene, in SCENE_ORDER.");
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
