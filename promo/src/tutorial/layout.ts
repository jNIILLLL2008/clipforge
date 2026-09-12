import type { Rect, Step, Target } from "./steps";
import { CARD_CSS_WIDTH } from "./steps";

/*
 * Where things sit in the 1920x1080 frame.
 *
 * The screenshot fits inside PLANE_BOX, centred in it. The caption card hugs
 * the screenshot's left edge, overlapping it by CAPTION_OVERLAP, but never
 * goes further left than CAPTION_LEFT. On the widest screenshots that puts
 * the card at exactly 80px from the edge; on the narrower ones the card and
 * the screenshot move in together, so the pair stays centred in the frame.
 */
export const PLANE_BOX = { left: 600, top: 150, width: 1240, height: 800 };
export const CAPTION_LEFT = 80;
export const CAPTION_BOTTOM = 100;
export const CAPTION_WIDTH = 640;
export const CAPTION_OVERLAP = 120;

/** The stepper and the small lockup share one line above the screenshot. */
export const CHROME_Y = 100;
export const STEPPER_X = PLANE_BOX.left + PLANE_BOX.width / 2;

export type PlaneLayout = {
  left: number;
  top: number;
  /** The screenshot's displayed size at rest. */
  W: number;
  H: number;
  /** Displayed px per modal CSS px. */
  k: number;
  captionLeft: number;
};

export const planeLayout = (step: Step): PlaneLayout => {
  const fit = Math.min(PLANE_BOX.width / step.width, PLANE_BOX.height / step.height);
  const W = step.width * fit;
  const H = step.height * fit;
  const left = PLANE_BOX.left + (PLANE_BOX.width - W) / 2;
  const top = PLANE_BOX.top + (PLANE_BOX.height - H) / 2;
  return {
    left,
    top,
    W,
    H,
    k: W / CARD_CSS_WIDTH,
    captionLeft: Math.max(CAPTION_LEFT, left + CAPTION_OVERLAP - CAPTION_WIDTH),
  };
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
