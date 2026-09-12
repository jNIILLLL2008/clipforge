import type { SceneId } from "./timeline";
import { WINDOWS } from "./timeline";

/*
 * What each step shows and does. StepScene reads this; no step has timing of
 * its own in JSX.
 *
 * THE SCREENSHOTS
 * public/step1.png to step7.png are the "Connect your channel" modal from
 * frontend/app.js, captured at 2x (1360px wide, the modal is 680 CSS px) with
 * a transparent page behind the card, so its rounded corners come through.
 * `node promo/tools/capture_modal.mjs` makes them.
 *
 * RECTS
 * Every rect is [left, top, width, height] as fractions (0 to 1) of its
 * screenshot. They were measured off the modal's DOM at capture time, not
 * eyeballed: the SVG rings by their geometry (the centre of the stroke), the
 * buttons and inputs by their bounding boxes. If the modal changes, rerun the
 * capture script, which prints fresh numbers, rather than nudging these by
 * hand. Radii are in the modal's own CSS px.
 *
 * BEATS
 * `at` is seconds after the step's window opens (see WINDOWS in timeline.ts;
 * a beat at 0 lands on the cut). Actions:
 *   ring    draw the ember ring on a target, dim the rest of the screenshot
 *           and move the spotlight there. It stays until the next ring.
 *   point   glide the cursor to a target's centre, arriving at `at`.
 *   click   the same, then press and send out a ripple at `at`.
 *   zoom    push the camera in on `focus` (a target key, or [x, y] fractions
 *           of the screenshot) to `scale`. Starts at `at`, settles in about
 *           0.8s.
 *   unzoom  ease the camera back to the whole screenshot.
 *   fill    put text in a field: `text` is pasted (or typed over `seconds`),
 *           `masked` types that many dots over `seconds`.
 *   chip    pop a small label on a target's top-right corner.
 *
 * TUNING A ZOOM
 *   - Reframe: change `focus`. A target key zooms on its centre; [x, y] lets
 *     you aim anywhere. Moving x or y by 0.02 is a small nudge.
 *   - Closer or wider: change `scale`. 1.3 is a gentle push, 1.6 is close.
 *   - Earlier or later: change `at`. Leave about a second between an `unzoom`
 *     and the end of the window, so the plane is at rest when it slides out.
 *   - The camera moves the focus toward the middle of the screenshot's box but
 *     never far enough to drag an edge of the screenshot into view, so a
 *     focus near an edge ends up off-centre. That is on purpose. The maths is
 *     in components/Camera.tsx.
 *   - Set showGuides in the Studio props panel to see a 10% grid, every rect
 *     and every zoom focus drawn over the screenshot.
 */

export type Rect = readonly [left: number, top: number, width: number, height: number];

/** The modal's width in CSS px. Radii and insets below are in these units. */
export const CARD_CSS_WIDTH = 680;
/** The card's own corner radius, baked into the screenshots' transparent corners. */
export const CARD_CSS_RADIUS = 16;

// The rings the modal draws around its illustrations: rx 5 and a 2-unit
// stroke in a 420-unit SVG that renders 640 CSS px wide.
const RING = 7.61;
export const BAKED_RING_STROKE = 3.05;

export type Target = {
  rect: Rect;
  /** Corner radius, in the modal's CSS px. */
  radius: number;
  /**
   * The screenshot already has an ember ring on exactly this rect, so the
   * animated ring is drawn on top of it rather than around it.
   */
  baked?: boolean;
  /** For fill beats: where text starts inside the field, and how it is set. */
  field?: { inset: number; fontSize: number; background: string };
};

export type Beat =
  | { at: number; action: "ring"; target: string }
  | { at: number; action: "point"; target: string }
  | { at: number; action: "click"; target: string }
  | { at: number; action: "zoom"; focus: string | readonly [number, number]; scale: number }
  | { at: number; action: "unzoom" }
  | { at: number; action: "fill"; target: string; text?: string; masked?: number; seconds?: number }
  | { at: number; action: "chip"; target: string; text: string };

/** `until`, when set, is when the callout lifts away; otherwise it stays to the end of the step. */
export type Callout =
  | { at: number; until?: number; kind: "badge"; text: string }
  | {
      at: number;
      until?: number;
      kind: "url";
      text: string;
      typeSeconds: number;
      copiedAt: number;
    };

export type Step = {
  id: SceneId;
  n: number;
  image: string;
  width: number;
  height: number;
  headline: string;
  sub: string;
  /** Replaces the sub line partway through the step. */
  subLater?: { at: number; text: string };
  /** Sits above the caption card. */
  callout?: Callout;
  targets: Record<string, Target>;
  beats: readonly Beat[];
};

const REDIRECT_URI = "https://clipforgee.app/api/youtube/callback";

// The modal's inputs: --surface-2 fill, 1px border, .7rem of padding.
const INPUT_FIELD = { inset: 12.2, fontSize: 16, background: "#191920" };

export const STEPS: readonly Step[] = [
  {
    id: "step1",
    n: 1,
    image: "step1.png",
    width: 1360,
    height: 872,
    headline: "ClipForge uploads through your own Google Cloud project",
    sub: "On a shared one, every customer splits about six uploads a day. Yours is yours alone.",
    targets: {
      next: { rect: [0.8684, 0.8526, 0.102, 0.1084], radius: 12 },
    },
    beats: [
      { at: 2.4, action: "ring", target: "next" },
      { at: 3.4, action: "click", target: "next" },
    ],
  },
  {
    id: "step2",
    n: 2,
    image: "step2.png",
    width: 1360,
    height: 968,
    headline: "Create a Google Cloud project",
    sub: "Select a project, then New project. Any name works.",
    targets: {
      selectProject: { rect: [0.2402, 0.3384, 0.2777, 0.0692], radius: RING, baked: true },
      newProject: { rect: [0.5851, 0.5209, 0.2105, 0.0755], radius: RING, baked: true },
    },
    beats: [
      { at: 1.0, action: "ring", target: "selectProject" },
      { at: 1.5, action: "point", target: "selectProject" },
      { at: 2.2, action: "zoom", focus: "newProject", scale: 1.45 },
      { at: 2.4, action: "ring", target: "newProject" },
      { at: 3.3, action: "click", target: "newProject" },
      { at: 4.9, action: "unzoom" },
    ],
  },
  {
    id: "step3",
    n: 3,
    image: "step3.png",
    width: 1360,
    height: 1008,
    headline: "Enable the YouTube Data API v3",
    sub: "Search the API Library for it, then Enable.",
    targets: {
      search: { rect: [0.0566, 0.4378, 0.5912, 0.0724], radius: RING, baked: true },
      enable: { rect: [0.7329, 0.5766, 0.1792, 0.0785], radius: RING, baked: true },
    },
    beats: [
      { at: 1.0, action: "ring", target: "search" },
      { at: 1.5, action: "point", target: "search" },
      { at: 2.6, action: "zoom", focus: "enable", scale: 1.4 },
      { at: 2.8, action: "ring", target: "enable" },
      { at: 3.7, action: "click", target: "enable" },
      { at: 5.8, action: "unzoom" },
    ],
  },
  {
    id: "step4",
    n: 4,
    image: "step4.png",
    width: 1360,
    height: 1032,
    headline: "Choose External on the consent screen",
    sub: "Then add an app name and your email, and save.",
    targets: {
      external: { rect: [0.0566, 0.4864, 0.4479, 0.0589], radius: RING, baked: true },
    },
    beats: [
      { at: 1.0, action: "ring", target: "external" },
      { at: 1.3, action: "zoom", focus: "external", scale: 1.5 },
      { at: 2.5, action: "click", target: "external" },
      { at: 4.9, action: "unzoom" },
    ],
  },
  {
    id: "step5",
    n: 5,
    image: "step5.png",
    width: 1360,
    height: 1164,
    headline: "Add yourself as a test user",
    sub: "Use the Google account that owns your channel.",
    callout: { at: 4.7, kind: "badge", text: "The step everybody misses" },
    targets: {
      addUsers: { rect: [0.0566, 0.4945, 0.2598, 0.0732], radius: RING, baked: true },
      warning: { rect: [0.0297, 0.6867, 0.9406, 0.0809], radius: 12 },
    },
    beats: [
      // The Test users block: its label, + Add users and the email field.
      { at: 1.0, action: "zoom", focus: [0.44, 0.54], scale: 1.55 },
      { at: 1.5, action: "ring", target: "addUsers" },
      { at: 2.6, action: "click", target: "addUsers" },
      { at: 4.2, action: "unzoom" },
      { at: 4.5, action: "ring", target: "warning" },
    ],
  },
  {
    id: "step6",
    n: 6,
    image: "step6.png",
    width: 1360,
    height: 1222,
    headline: "Create an OAuth client ID",
    sub: "Type Web application, with this exact redirect URI.",
    subLater: {
      at: 7.9,
      text: "It must match exactly, or Google refuses with redirect_uri_mismatch.",
    },
    // Gone before the Web application ring, whose field it would otherwise cover.
    callout: {
      at: 0.7,
      until: 4.0,
      kind: "url",
      text: REDIRECT_URI,
      typeSeconds: 1.5,
      copiedAt: 2.9,
    },
    targets: {
      copyRow: { rect: [0.0297, 0.2366, 0.9406, 0.1068], radius: 12 },
      copyButton: { rect: [0.8497, 0.2513, 0.1051, 0.0774], radius: 12 },
      clientIdType: { rect: [0.0566, 0.4864, 0.3449, 0.0597], radius: RING, baked: true },
      webApp: { rect: [0.0566, 0.6059, 0.3449, 0.0597], radius: RING, baked: true },
      // An accent-stroked field, not a ring, so the ring goes around it.
      redirectField: {
        rect: [0.4552, 0.6109, 0.4837, 0.0498],
        radius: 6.1,
        field: { inset: 9, fontSize: 12, background: "#131316" },
      },
    },
    beats: [
      { at: 0.9, action: "ring", target: "copyRow" },
      { at: 2.9, action: "click", target: "copyButton" },
      { at: 4.0, action: "ring", target: "clientIdType" },
      { at: 4.3, action: "point", target: "clientIdType" },
      { at: 5.2, action: "ring", target: "webApp" },
      { at: 5.5, action: "point", target: "webApp" },
      { at: 6.5, action: "zoom", focus: "redirectField", scale: 1.5 },
      { at: 6.7, action: "ring", target: "redirectField" },
      { at: 7.5, action: "click", target: "redirectField" },
      { at: 7.9, action: "fill", target: "redirectField", text: REDIRECT_URI },
      { at: 9.9, action: "unzoom" },
    ],
  },
  {
    id: "step7",
    n: 7,
    image: "step7.png",
    width: 1360,
    height: 918,
    headline: "Paste your Client ID and secret into ClipForge",
    sub: "Then Save and connect.",
    targets: {
      clientId: { rect: [0.0297, 0.3204, 0.9406, 0.0935], radius: 12, field: INPUT_FIELD },
      clientSecret: { rect: [0.0297, 0.5578, 0.9406, 0.0935], radius: 12, field: INPUT_FIELD },
      save: { rect: [0.7305, 0.86, 0.2398, 0.103], radius: 12 },
    },
    // Masked dots only. Never a realistic-looking ID or secret.
    beats: [
      { at: 0.9, action: "ring", target: "clientId" },
      { at: 1.1, action: "chip", target: "clientId", text: "ends in .apps.googleusercontent.com" },
      { at: 1.4, action: "click", target: "clientId" },
      { at: 1.6, action: "fill", target: "clientId", masked: 28, seconds: 0.9 },
      { at: 2.7, action: "ring", target: "clientSecret" },
      { at: 2.9, action: "chip", target: "clientSecret", text: "starts with GOCSPX-" },
      { at: 3.2, action: "click", target: "clientSecret" },
      { at: 3.4, action: "fill", target: "clientSecret", masked: 22, seconds: 0.8 },
      { at: 4.4, action: "ring", target: "save" },
      { at: 5.0, action: "click", target: "save" },
    ],
  },
];

export const TOTAL_STEPS = STEPS.length;

export const beatsOf = <A extends Beat["action"]>(step: Step, action: A) =>
  step.beats.filter((b): b is Extract<Beat, { action: A }> => b.action === action);

export const targetOf = (step: Step, key: string): Target => {
  const target = step.targets[key];
  if (!target) {
    throw new Error(`${step.id}: no target called "${key}".`);
  }
  return target;
};

/** The centre of a target, or a literal [x, y], as fractions of the screenshot. */
export const focusOf = (step: Step, focus: string | readonly [number, number]) => {
  if (typeof focus !== "string") {
    return { x: focus[0], y: focus[1] };
  }
  const [l, t, w, h] = targetOf(step, focus).rect;
  return { x: l + w / 2, y: t + h / 2 };
};

// Fail loudly while tuning: a typo'd target or a beat outside its window.
for (const step of STEPS) {
  const [open, close] = WINDOWS[step.id];
  let last = -Infinity;
  for (const beat of step.beats) {
    if (beat.at < last) {
      throw new Error(`${step.id}: beats must be in time order (${beat.at}s comes after ${last}s).`);
    }
    if (beat.at < 0 || beat.at > close - open) {
      throw new Error(`${step.id}: a ${beat.action} beat at ${beat.at}s is outside its ${close - open}s window.`);
    }
    if ("target" in beat) {
      targetOf(step, beat.target);
    }
    if (beat.action === "zoom") {
      focusOf(step, beat.focus);
    }
    if (beat.action === "fill" && !targetOf(step, beat.target).field) {
      throw new Error(`${step.id}: "${beat.target}" has no field settings, so it cannot be filled.`);
    }
    last = beat.at;
  }
  const callout = step.callout;
  if (callout?.until !== undefined && callout.until <= callout.at) {
    throw new Error(`${step.id}: the callout's until (${callout.until}s) must come after its at (${callout.at}s).`);
  }
}
