/*
 * A screenshot and what happens on it, for the videos in promo/.
 *
 * A Shot is an image with its targets (rects as fractions of the image) and
 * its beats (what the rings, the camera and the cursor do, and when). The
 * components in shared/components/ read a Shot. Each video decides where the
 * shot sits in the frame (a PlaneLayout) and which frame a beat's seconds mean
 * (a BeatClock, in clock.tsx).
 */

export type Rect = readonly [left: number, top: number, width: number, height: number];

/** How text sits in a field, for fill beats. In the page's CSS px. */
export type FieldStyle = {
  inset: number;
  fontSize: number;
  background: string;
  /**
   * "sans" sets the text the way the page does, in the field's own colour,
   * size and alignment. Without it a fill is a pasted URL in mono, or masked
   * dots.
   */
  font?: "sans";
  insetRight?: number;
  padTop?: number;
  lineHeight?: number;
  weight?: number;
  color?: string;
  align?: "left" | "right";
  valign?: "center" | "top";
};

export type Target = {
  rect: Rect;
  /** Corner radius, in the page's CSS px. */
  radius: number;
  /**
   * The screenshot already has an ember ring on exactly this rect, so the
   * animated ring is drawn on top of it rather than around it.
   */
  baked?: boolean;
  /** For fill beats: where text starts inside the field, and how it is set. */
  field?: FieldStyle;
};

/** A target key, or [x, y] fractions of the screenshot. */
export type Focus = string | readonly [number, number];

/*
 * `at` is seconds; the BeatClock decides what they count from. Actions:
 *   ring    draw the ember ring on a target, dim the rest of the screenshot
 *           and move the spotlight there. It stays until the next ring.
 *   clear   lift the ring and the dim, leaving the screenshot as it was.
 *   point   glide the cursor to a target's centre, arriving at `at`.
 *   click   the same, then press and send out a ripple at `at`.
 *   zoom    push the camera in on `focus` to `scale`. Starts at `at`, settles
 *           in about 0.8s.
 *   unzoom  ease the camera back to the whole screenshot.
 *   fill    put text in a field: `text` is pasted (or typed over `seconds`),
 *           `masked` types that many dots over `seconds`.
 *   chip    pop a small label on a target's top-right corner.
 */
export type Beat =
  | { at: number; action: "ring"; target: string }
  | { at: number; action: "clear" }
  | { at: number; action: "point"; target: string }
  | { at: number; action: "click"; target: string }
  | { at: number; action: "zoom"; focus: Focus; scale: number }
  | { at: number; action: "unzoom" }
  | { at: number; action: "fill"; target: string; text?: string; masked?: number; seconds?: number }
  | { at: number; action: "chip"; target: string; text: string };

export type Shot = {
  image: string;
  width: number;
  height: number;
  targets: Readonly<Record<string, Target>>;
  beats: readonly Beat[];
  /**
   * Where the camera starts. A shot that carries on from a zoom in the scene
   * before starts there, so the cut between them doesn't show.
   */
  camera?: { scale: number; focus: Focus };
  /** The settled width of an animated ring, in CSS px. */
  ringStroke?: number;
};

/** The YouTube setup modal's own ring: a 2-unit stroke in a 420-unit SVG, 640 CSS px wide. */
export const DEFAULT_RING_STROKE = 3.05;

export const beatsOf = <A extends Beat["action"]>(shot: Shot, action: A) =>
  shot.beats.filter((b): b is Extract<Beat, { action: A }> => b.action === action);

export const targetOf = (shot: Shot, key: string): Target => {
  const target = shot.targets[key];
  if (!target) {
    throw new Error(`${shot.image}: no target called "${key}".`);
  }
  return target;
};

/** The centre of a target, or a literal [x, y], as fractions of the screenshot. */
export const focusOf = (shot: Shot, focus: Focus) => {
  if (typeof focus !== "string") {
    return { x: focus[0], y: focus[1] };
  }
  const [l, t, w, h] = targetOf(shot, focus).rect;
  return { x: l + w / 2, y: t + h / 2 };
};

/** Where a shot sits in the frame, at rest. */
export type PlaneLayout = {
  left: number;
  top: number;
  /** The screenshot's displayed size. */
  W: number;
  H: number;
  /** Displayed px per page CSS px. */
  k: number;
};

export type Box = { x: number; y: number; w: number; h: number; r: number };

/** A rect in the plane's own px (0,0 is the screenshot's top-left at rest). */
export const rectPx = (plane: PlaneLayout, rect: Rect, radius = 0): Box => ({
  x: rect[0] * plane.W,
  y: rect[1] * plane.H,
  w: rect[2] * plane.W,
  h: rect[3] * plane.H,
  r: radius * plane.k,
});

export const grow = (box: Box, by: number): Box => ({
  x: box.x - by,
  y: box.y - by,
  w: box.w + by * 2,
  h: box.h + by * 2,
  r: box.r + by,
});

/** How far an animated ring sits outside a target that has no ring of its own, in CSS px. */
const RING_OFFSET = 4;

/**
 * Where the animated ring goes: exactly on a baked ring, or just outside a
 * plain button or field.
 */
export const ringBox = (plane: PlaneLayout, target: Target): Box => {
  const box = rectPx(plane, target.rect, target.radius);
  return target.baked ? box : grow(box, RING_OFFSET * plane.k);
};

export const centreOf = (box: Box) => ({ x: box.x + box.w / 2, y: box.y + box.h / 2 });
