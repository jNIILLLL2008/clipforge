import type { PlaneLayout } from "../shared/plane";
import type { Step } from "./steps";
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

export type TutorialPlane = PlaneLayout & { captionLeft: number };

export const planeLayout = (step: Step): TutorialPlane => {
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
