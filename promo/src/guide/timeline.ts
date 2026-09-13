/*
 * Every cut in the setup guide, in one place. Retiming the video is changing
 * numbers in WINDOWS and nowhere else.
 *
 * WINDOWS says when each scene owns the screen, in seconds. A transition is
 * centred on every boundary: it starts TRANSITION / 2 frames before the cut
 * and finishes TRANSITION / 2 frames after it. So each <TransitionSeries.Sequence>
 * is its window plus half a transition at either end, which is what
 * sceneFrames() works out, and TransitionSeries subtracting the overlaps brings
 * the total back to exactly the last window's end.
 */

export const FPS = 30;

export const sec = (seconds: number) => Math.round(seconds * FPS);

/** Frames per transition. Must be even, so it splits evenly across the cut. */
export const TRANSITION = 18;
const HALF = TRANSITION / 2;

export type SceneId =
  | "intro"
  | "agent"
  | "ffmpeg"
  | "pair"
  | "niche"
  | "banner"
  | "sources"
  | "longform"
  | "showfilter"
  | "youtube"
  | "publish"
  | "outro";

export const SCENE_ORDER: readonly SceneId[] = [
  "intro",
  "agent",
  "ffmpeg",
  "pair",
  "niche",
  "banner",
  "sources",
  "longform",
  "showfilter",
  "youtube",
  "publish",
  "outro",
];

export const WINDOWS: Record<SceneId, readonly [number, number]> = {
  intro: [0, 5],
  agent: [5, 16],
  ffmpeg: [16, 30],
  pair: [30, 44],
  niche: [44, 54],
  banner: [54, 62],
  sources: [62, 76],
  longform: [76, 86],
  showfilter: [86, 96],
  youtube: [96, 106],
  publish: [106, 114],
  outro: [114, 120],
};

const isFirst = (id: SceneId) => id === SCENE_ORDER[0];
const isLast = (id: SceneId) => id === SCENE_ORDER[SCENE_ORDER.length - 1];

/** The global frame a scene's window opens on: the midpoint of the transition into it. */
export const cutFrame = (id: SceneId) => sec(WINDOWS[id][0]);

/** The durationInFrames of a scene's <TransitionSeries.Sequence>. */
export const sceneFrames = (id: SceneId) =>
  sec(WINDOWS[id][1]) -
  sec(WINDOWS[id][0]) +
  (isFirst(id) ? 0 : HALF) +
  (isLast(id) ? 0 : HALF);

/**
 * A scene-local frame for "s seconds after this scene's window opens". Beats
 * in guide.ts are written in these seconds, so a beat at 0 lands on the cut.
 */
export const windowFrame = (id: SceneId, s: number) => (isFirst(id) ? 0 : HALF) + sec(s);

/** How long a scene's window is, in seconds. */
export const windowSeconds = (id: SceneId) => WINDOWS[id][1] - WINDOWS[id][0];

export const TOTAL_FRAMES =
  SCENE_ORDER.reduce((sum, id) => sum + sceneFrames(id), 0) -
  (SCENE_ORDER.length - 1) * TRANSITION;

if (TRANSITION % 2 !== 0) {
  throw new Error(`TRANSITION must be even, got ${TRANSITION}.`);
}
for (let i = 1; i < SCENE_ORDER.length; i++) {
  const before = WINDOWS[SCENE_ORDER[i - 1]];
  const after = WINDOWS[SCENE_ORDER[i]];
  if (before[1] !== after[0]) {
    throw new Error(
      `WINDOWS must be contiguous: ${SCENE_ORDER[i - 1]} ends at ${before[1]}s but ${SCENE_ORDER[i]} starts at ${after[0]}s.`,
    );
  }
}
