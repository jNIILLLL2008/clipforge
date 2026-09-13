import type { PlaneLayout } from "../shared/plane";

/*
 * Where things sit in the 1920x1080 frame.
 *
 * The app screens are 16:9 captures of the whole Studio, so they fill APP_BOX
 * exactly. At rest the page's 14px text lands near 11px, which is why every
 * scene zooms in on what it is talking about. The caption card sits lower
 * left, overlapping the screenshot's sidebar; the settings checklist sits in
 * the free column above it, clear of the screenshot, so it never covers the
 * field being talked about.
 *
 * In the pairing scene the agent's terminal takes the left and the browser's
 * dialog the right, so the two codes can be joined across the middle.
 */
export type BoxName = "app" | "explorer" | "pair";

export type Box = { left: number; top: number; width: number; height: number };

export const BOXES: Record<BoxName, Box> = {
  app: { left: 560, top: 176, width: 1280, height: 720 },
  explorer: { left: 560, top: 176, width: 1280, height: 720 },
  pair: { left: 990, top: 206, width: 780, height: 640 },
};

export const TERMINAL_BOX: Box = { left: 150, top: 200, width: 660, height: 430 };

export const CAPTION = { left: 80, bottom: 84, width: 600 };

/** The small lockup and the step rail share one line above the screenshot. */
export const CHROME_Y = 96;
export const LOCKUP_X = 80;
export const RAIL_X = BOXES.app.left + BOXES.app.width / 2;

export const CHECKLIST = { left: 80, top: 236, width: 400 };

/** The viewport's corner radius for a full-screen capture, in the frame's px. */
export const PLANE_RADIUS = 14;

/** A capture fitted into a box, centred, with `k` in displayed px per page CSS px. */
export const planeFor = (
  capture: { width: number; height: number; cssWidth: number },
  box: Box,
): PlaneLayout => {
  const fit = Math.min(box.width / capture.width, box.height / capture.height);
  const W = capture.width * fit;
  const H = capture.height * fit;
  return {
    left: box.left + (box.width - W) / 2,
    top: box.top + (box.height - H) / 2,
    W,
    H,
    k: W / capture.cssWidth,
  };
};
