import type { Beat, Focus, Rect, Shot, Target } from "../shared/plane";
import { focusOf, targetOf } from "../shared/plane";
import { CAPTURES } from "./captures";
import type { BoxName } from "./layout";
import type { SceneId } from "./timeline";
import { WINDOWS, windowSeconds } from "./timeline";

/*
 * What every scene of the setup guide shows and does. The scenes read this;
 * no scene has timing of its own in JSX.
 *
 * THE SCREENSHOTS
 * public/guide/ holds captures of the real Studio, made by
 * `node promo/tools/capture_guide.mjs` from the app's own HTML, CSS and JS with
 * a throwaway account's data in it. Nobody's name, computer or channel is in
 * any of them: the account is you@example.com, the computer "Your PC", the
 * channel "Your channel". captures.ts holds their sizes and every target's
 * rect, measured off the DOM, so nothing here is eyeballed.
 *
 * BEATS
 * `at` is seconds after the scene's window opens (WINDOWS in timeline.ts).
 * The actions are listed in shared/plane.ts. They're timed to the narration
 * (soundtrack.ts), so a ring or a click lands on the word that names it; a
 * new take means checking them against its words again.
 *
 * SCENES ON ONE SCREENSHOT
 * niche, banner and sources share settings-subject, as youtube and publish
 * share the Home screen. They hand over with a dissolve rather than a slide,
 * which only works if the screenshot looks the same on both sides of the cut:
 *   - the next scene starts with `camera` where the last one ended,
 *   - fills carry over (carried() below), already typed,
 *   - the last scene clears its ring and sends the cursor off-screen before
 *     the cut, and its caption lifts away (captionExit).
 * The checks at the bottom of this file fail loudly if a handover would jump.
 */

export type CaptureName = keyof typeof CAPTURES;
export type ChecklistItem = "Niche" | "Search terms" | "Banner" | "Playlists" | "Channels" | "One show";
export const CHECKLIST_ITEMS: readonly ChecklistItem[] = [
  "Niche",
  "Search terms",
  "Banner",
  "Playlists",
  "Channels",
  "One show",
];
export const RAIL_STEPS = ["Agent", "ffmpeg", "Pair", "Settings", "Publish"] as const;

export type Segment = {
  capture: CaptureName;
  box: BoxName;
  /** Seconds into the window this segment takes over. The first is 0. */
  at: number;
  /** How it replaces the segment before it. */
  swap?: "scroll" | "crossfade";
  /** "none" for a screenshot carrying on from the scene before. */
  enter?: "tilt" | "none";
  camera?: { scale: number; focus: Focus };
  beats: readonly Beat[];
};

export type Inset = {
  image: string;
  /** Natural size, in px. */
  width: number;
  height: number;
  at: number;
  until?: number;
  /** Where it sits in the frame, and how wide. */
  left: number;
  top: number;
  displayWidth: number;
  swapTo?: { at: number; image: string };
  ring?: { at: number; rect: Rect };
  label?: string;
  play?: boolean;
};

export type SceneSpec = {
  step: 1 | 2 | 3 | 4 | 5;
  headline: string;
  sub: string;
  /** The caption lifts away just before the cut, for a dissolve into the same screenshot. */
  captionExit?: boolean;
  segments: readonly Segment[];
  ticks?: readonly { at: number; item: ChecklistItem }[];
  insets?: readonly Inset[];
};

export type StepSceneId = Exclude<SceneId, "intro" | "outro">;

/** Just past the screenshot's lower right, where the cursor rests: `point` here and it leaves. */
const OFFSCREEN: Target = { rect: [1.04, 1.08, 0, 0], radius: 0 };

export const shotOf = (segment: Segment): Shot => {
  const capture = CAPTURES[segment.capture];
  return {
    image: capture.image,
    width: capture.width,
    height: capture.height,
    targets: { ...capture.targets, offscreen: OFFSCREEN },
    beats: segment.beats,
    camera: segment.camera,
  };
};

type Fill = Extract<Beat, { action: "fill" }>;

/**
 * Fills from scenes before, already typed, so text stays put across a
 * handover. From before the cut: the scene is already fading in over the one
 * it takes over from during the half-transition before its window opens.
 */
const CARRIED_AT = -0.3;
const carried = (...fills: Fill[]): Fill[] =>
  fills.map(({ target, text }) => ({ at: CARRIED_AT, action: "fill", target, text }));

const NICHE = "Top moments from Formula 1 races";
const TERMS = "f1 best overtakes\nf1 team radio moments";
const LINE2 = "FORMULA 1";
const PLAYLIST = "https://www.youtube.com/playlist?list=PLexample";
const CHANNEL = "@examplechannel";

const nicheFills: Fill[] = [
  { at: 2.0, action: "fill", target: "description", text: NICHE, seconds: 1.2 },
  { at: 3.75, action: "fill", target: "searchTerms", text: TERMS, seconds: 1.8 },
];
const bannerFills: Fill[] = [{ at: 1.4, action: "fill", target: "line2Field", text: LINE2, seconds: 0.8 }];

// The youtube and publish scenes are two captures of Home, and "youtubeRow"
// is a little taller on the first (it has the Set up publishing link), so a
// fixed point keeps the camera exactly still across their handover.
const YOUTUBE_FOCUS = [0.358, 0.46] as const;
const NICHE_FOCUS = [0.346, 0.183] as const;
const BANNER_FOCUS = [0.72, 0.402] as const;
const SOURCES_FOCUS = [0.346, 0.76] as const;
const SETTINGS_ZOOM = 1.6;

/** The pairing scene: the agent's terminal beside the browser's dialog. */
export const PAIR = {
  code: "DA6H-SVSG",
  email: "you@example.com",
  /** When the terminal starts printing: "run ClipForgeAgent". */
  printAt: 1.0,
  /** The dialog's code rings: "with a code". */
  codeAt: 3.85,
  /** The terminal's code rings too and a line joins them: "Check it matches". */
  matchAt: 4.55,
  /** The line and its label leave, just before Pair it is pressed. */
  unmatchAt: 6.55,
  /** The agent hears it was approved: "that's done". */
  pairedAt: 8.2,
};

/**
 * The ffmpeg scene's explainer card: in on "the engine", each of its three
 * verbs as it's said, and the winget footer once the line has finished.
 */
export const WHY = { at: 4.5, verbs: [5.2, 7.2, 8.25], wingetAt: 11.2 } as const;

export const SCENES: Record<StepSceneId, SceneSpec> = {
  agent: {
    step: 1,
    headline: "Download the render agent",
    sub: "It renders your videos on your own PC, over your own connection.",
    segments: [
      {
        capture: "home-top",
        box: "app",
        at: 0,
        beats: [{ at: 1.0, action: "ring", target: "agentStatus" }],
      },
      {
        capture: "home-agent",
        box: "app",
        at: 1.75,
        swap: "scroll",
        enter: "none",
        beats: [
          { at: 1.95, action: "zoom", focus: "agentPanel", scale: 1.45 },
          { at: 3.0, action: "ring", target: "download" },
          { at: 3.45, action: "click", target: "download" },
          { at: 3.65, action: "chip", target: "download", text: "ClipForgeAgent-windows.zip" },
          { at: 5.1, action: "ring", target: "agentNote" },
        ],
      },
    ],
  },

  ffmpeg: {
    step: 2,
    headline: "Keep ffmpeg with the agent",
    sub: "It's the video engine. It cuts the clips, burns in the banner and captions, and encodes the video. Nothing renders without it.",
    segments: [
      {
        capture: "explorer-root",
        box: "explorer",
        at: 0,
        beats: [
          { at: 2.3, action: "ring", target: "ffmpeg" },
          // A double-click: two presses on the same spot.
          { at: 2.75, action: "click", target: "ffmpeg" },
          { at: 3.0, action: "click", target: "ffmpeg" },
        ],
      },
      {
        capture: "explorer-ffmpeg",
        box: "explorer",
        at: 3.35,
        swap: "crossfade",
        enter: "none",
        beats: [
          { at: 3.6, action: "ring", target: "ffmpegExe" },
          { at: 4.15, action: "ring", target: "ffprobeExe" },
        ],
      },
      {
        // Back up a folder for "Keep it with the agent": ffmpeg beside ClipForgeAgent.
        capture: "explorer-root",
        box: "explorer",
        at: 9.6,
        swap: "crossfade",
        enter: "none",
        beats: [
          { at: 9.9, action: "ring", target: "ffmpeg" },
          { at: 10.5, action: "ring", target: "agent" },
        ],
      },
    ],
  },

  pair: {
    step: 3,
    headline: "Run the agent, then Pair it",
    sub: "The code in the agent's window matches the one in your browser. One click and you're paired.",
    segments: [
      {
        capture: "pair-dialog",
        box: "pair",
        at: 0,
        beats: [
          { at: PAIR.codeAt, action: "ring", target: "code" },
          { at: 7.2, action: "click", target: "pairIt" },
        ],
      },
      {
        capture: "paired",
        box: "pair",
        at: 7.95,
        swap: "crossfade",
        enter: "none",
        beats: [{ at: 8.5, action: "ring", target: "lead" }],
      },
    ],
  },

  niche: {
    step: 4,
    headline: "Tell it your niche",
    sub: "What the channel is about, and a few search terms.",
    captionExit: true,
    ticks: [
      { at: 3.2, item: "Niche" },
      { at: 5.55, item: "Search terms" },
    ],
    segments: [
      {
        capture: "settings-subject",
        box: "app",
        at: 0,
        beats: [
          { at: 0.4, action: "zoom", focus: NICHE_FOCUS, scale: SETTINGS_ZOOM },
          { at: 1.7, action: "ring", target: "description" },
          { at: 1.85, action: "click", target: "description" },
          nicheFills[0],
          { at: 3.4, action: "ring", target: "searchTerms" },
          { at: 3.55, action: "click", target: "searchTerms" },
          nicheFills[1],
          { at: 8.2, action: "point", target: "offscreen" },
          { at: 8.7, action: "clear" },
        ],
      },
    ],
  },

  banner: {
    step: 4,
    headline: "Name the banner",
    sub: "Lines 1 and 2 run across the top of every video. {count} becomes the number of clips.",
    captionExit: true,
    ticks: [{ at: 2.75, item: "Banner" }],
    segments: [
      {
        capture: "settings-subject",
        box: "app",
        at: 0,
        enter: "none",
        camera: { scale: SETTINGS_ZOOM, focus: NICHE_FOCUS },
        beats: [
          ...carried(...nicheFills),
          { at: 0.25, action: "zoom", focus: BANNER_FOCUS, scale: SETTINGS_ZOOM },
          { at: 0.85, action: "ring", target: "line2" },
          { at: 1.2, action: "click", target: "line2Field" },
          bannerFills[0],
          { at: 6.2, action: "point", target: "offscreen" },
          { at: 6.9, action: "clear" },
        ],
      },
    ],
    insets: [
      {
        image: "guide/preview-before.png",
        width: 516,
        height: 920,
        at: 1.7,
        until: 6.9,
        left: 640,
        top: 250,
        displayWidth: 236,
        swapTo: { at: 2.75, image: "guide/preview-after.png" },
        ring: { at: 2.05, rect: [0.03, 0.015, 0.94, 0.08] },
        label: "the banner, in the preview",
      },
    ],
  },

  sources: {
    step: 4,
    headline: "Point it at the right videos",
    sub: "A playlist, or the channels to take clips from. This is what gets you the clips you want.",
    ticks: [
      { at: 3.95, item: "Playlists" },
      { at: 5.8, item: "Channels" },
    ],
    segments: [
      {
        capture: "settings-subject",
        box: "app",
        at: 0,
        enter: "none",
        camera: { scale: SETTINGS_ZOOM, focus: BANNER_FOCUS },
        beats: [
          ...carried(...nicheFills, ...bannerFills),
          { at: 0.25, action: "zoom", focus: SOURCES_FOCUS, scale: SETTINGS_ZOOM },
          { at: 2.3, action: "ring", target: "playlists" },
          { at: 2.55, action: "click", target: "playlists" },
          { at: 2.75, action: "fill", target: "playlists", text: PLAYLIST, seconds: 1.2 },
          { at: 4.1, action: "ring", target: "channels" },
          { at: 4.7, action: "click", target: "channels" },
          { at: 4.9, action: "fill", target: "channels", text: CHANNEL, seconds: 0.9 },
          { at: 12.4, action: "point", target: "offscreen" },
        ],
      },
    ],
    insets: [
      {
        image: "guide/preview-warning.png",
        width: 1723,
        height: 262,
        at: 9.0,
        // About the page's own size, so its text is readable.
        left: 990,
        top: 250,
        displayWidth: 840,
        label: "leave these empty and the preview tells you",
      },
    ],
  },

  longform: {
    step: 4,
    headline: "Full episodes are fine",
    sub: "Put long videos in the playlist. The AI finds the moments and cuts them in.",
    segments: [
      {
        capture: "settings-cut",
        box: "app",
        at: 0,
        enter: "none",
        beats: [
          { at: 0.3, action: "zoom", focus: [0.345, 0.8], scale: 1.55 },
          { at: 3.0, action: "ring", target: "aiPicks" },
          { at: 4.0, action: "ring", target: "listen" },
          { at: 5.0, action: "zoom", focus: [0.345, 0.105], scale: 1.55 },
          { at: 5.7, action: "ring", target: "clips" },
          { at: 6.8, action: "ring", target: "length" },
        ],
      },
    ],
  },

  showfilter: {
    step: 4,
    headline: "Keep it to one show",
    sub: "Only from one show keeps every clip on your show or niche. Then Save settings.",
    ticks: [{ at: 3.75, item: "One show" }],
    segments: [
      {
        capture: "settings-showfilter",
        box: "app",
        at: 0,
        enter: "none",
        beats: [
          { at: 0.3, action: "zoom", focus: [0.346, 0.16], scale: 1.55 },
          { at: 0.8, action: "ring", target: "showMatch" },
          { at: 1.6, action: "ring", target: "showName" },
          { at: 1.8, action: "click", target: "showNameField" },
          { at: 1.95, action: "fill", target: "showNameField", text: "Formula 1", seconds: 0.6 },
          { at: 2.6, action: "ring", target: "showTerms" },
          { at: 2.8, action: "click", target: "showTerms" },
          { at: 2.95, action: "fill", target: "showTerms", text: "f1, grand prix", seconds: 0.8 },
          { at: 3.8, action: "unzoom" },
          { at: 4.1, action: "ring", target: "save" },
          { at: 4.6, action: "click", target: "save" },
          { at: 4.8, action: "chip", target: "save", text: "Saved" },
        ],
      },
    ],
  },

  youtube: {
    step: 5,
    headline: "Connect your YouTube channel",
    sub: "Set up publishing walks you through it, about five minutes, once.",
    captionExit: true,
    segments: [
      {
        capture: "home-top",
        box: "app",
        at: 0,
        beats: [
          { at: 0.5, action: "zoom", focus: YOUTUBE_FOCUS, scale: 1.45 },
          { at: 1.3, action: "ring", target: "youtubeRow" },
          { at: 3.1, action: "click", target: "setUpPublishing" },
          { at: 8.0, action: "point", target: "offscreen" },
          { at: 8.6, action: "clear" },
        ],
      },
    ],
    insets: [
      {
        image: "guide/youtube-setup-poster.jpg",
        width: 1280,
        height: 720,
        at: 3.6,
        until: 8.6,
        left: 1230,
        top: 300,
        displayWidth: 520,
        label: "connect your youtube channel · 1:00 walkthrough",
        play: true,
      },
    ],
  },

  publish: {
    step: 5,
    headline: "Publish",
    sub: "When everything says Ready, press Publish now.",
    segments: [
      {
        capture: "home-ready",
        box: "app",
        at: 0,
        enter: "none",
        camera: { scale: 1.45, focus: YOUTUBE_FOCUS },
        beats: [
          { at: 0.3, action: "zoom", focus: [0.3, 0.19], scale: 1.5 },
          { at: 0.9, action: "ring", target: "hero" },
          { at: 1.75, action: "ring", target: "publish" },
          { at: 2.15, action: "click", target: "publish" },
          { at: 2.35, action: "chip", target: "publish", text: "Publishing…" },
        ],
      },
    ],
  },
};

/** When Publish now is pressed, in seconds after the publish window opens: the last rail chip ticks. */
export const PUBLISHED_AT = 2.15;

/** Seconds before the window closes that a handing-over caption lifts away. */
export const CAPTION_EXIT_LEAD = 0.45;

// ------------------------------------------------------------ checks --
// Fail loudly while tuning: a typo'd target, a beat outside its window, or a
// handover between scenes on one screenshot that would visibly jump.
const HANDOVERS: readonly [StepSceneId, StepSceneId][] = [
  ["niche", "banner"],
  ["banner", "sources"],
  ["youtube", "publish"],
];

for (const [id, scene] of Object.entries(SCENES) as [StepSceneId, SceneSpec][]) {
  const length = windowSeconds(id);
  scene.segments.forEach((segment, i) => {
    if (i === 0 && segment.at !== 0) throw new Error(`${id}: the first segment must start at 0.`);
    if (i > 0 && segment.at <= scene.segments[i - 1].at) throw new Error(`${id}: segments must be in time order.`);
    const shot = shotOf(segment);
    let last = -Infinity;
    for (const beat of segment.beats) {
      if (beat.at < last) throw new Error(`${id}: beats must be in time order (${beat.at}s comes after ${last}s).`);
      const earliest = beat.action === "fill" && !beat.seconds ? CARRIED_AT : 0;
      if (beat.at < earliest || beat.at > length) throw new Error(`${id}: a ${beat.action} beat at ${beat.at}s is outside its ${length}s window.`);
      if ("target" in beat) targetOf(shot, beat.target);
      if (beat.action === "zoom") focusOf(shot, beat.focus);
      if (beat.action === "fill" && !targetOf(shot, beat.target).field) {
        throw new Error(`${id}: "${beat.target}" has no field settings, so it cannot be filled.`);
      }
      last = beat.at;
    }
  });
  for (const inset of scene.insets ?? []) {
    if (inset.at < 0 || (inset.until ?? inset.at) > length) throw new Error(`${id}: an inset runs outside its window.`);
  }
}

const lastZoom = (segment: Segment) => {
  const zooms = segment.beats.filter((b) => b.action === "zoom" || b.action === "unzoom");
  const final = zooms[zooms.length - 1];
  if (!final) return segment.camera ?? null;
  return final.action === "zoom" ? { scale: final.scale, focus: final.focus } : null;
};

for (const [from, to] of HANDOVERS) {
  const a = SCENES[from].segments[SCENES[from].segments.length - 1];
  const b = SCENES[to].segments[0];
  if (a.capture !== b.capture && !(from === "youtube" && b.capture === "home-ready")) {
    throw new Error(`${from} -> ${to}: a handover must stay on one screenshot.`);
  }
  const end = lastZoom(a);
  const start = b.camera ?? null;
  const same = (x: typeof end, y: typeof start) =>
    x === null || y === null ? x === y : x.scale === y.scale && JSON.stringify(x.focus) === JSON.stringify(y.focus);
  if (!same(end, start)) throw new Error(`${from} -> ${to}: ${to} must start with the camera where ${from} ends.`);
  if (b.enter !== "none") throw new Error(`${from} -> ${to}: ${to} carries on from ${from}, so it must not tilt in.`);
  if (!SCENES[from].captionExit) throw new Error(`${from} -> ${to}: ${from}'s caption must lift away before the cut.`);
  const window = WINDOWS[from][1] - WINDOWS[from][0];
  const clear = a.beats.filter((x) => x.action === "clear").pop();
  const hasRing = a.beats.some((x) => x.action === "ring");
  if (hasRing && (!clear || clear.at > window - 0.5)) {
    throw new Error(`${from} -> ${to}: ${from} must clear its ring at least 0.5s before the cut.`);
  }
}
