import React from "react";
import { spring, useCurrentFrame, useVideoConfig } from "remotion";
import { SPRING } from "../brand";
import type { PlaneLayout } from "../layout";
import { mix } from "../motion";
import type { Step } from "../steps";
import { beatsOf, focusOf } from "../steps";
import { windowFrame } from "../timeline";

/*
 * The camera: a zoom toward a focus point on the screenshot.
 *
 * THE MATHS
 * Work in the plane's own px, with c = (W/2, H/2) its centre. Scaling by z
 * about c sends a point p to  c + z(p - c).  Adding a translation
 *
 *     t = -z(p - c)
 *
 * would put the focus p exactly on c. But for a focus near an edge that drags
 * the screenshot's edge inside the card's viewport, leaving an empty band
 * where the screenshot was. The scaled plane still covers the viewport as
 * long as
 *
 *     |t.x| <= (z - 1) * W / 2   and   |t.y| <= (z - 1) * H / 2
 *
 * so t is clamped to that. The focus travels toward the centre as far as it
 * can without exposing an edge, and at z = 1 the clamp is zero, so there is
 * nothing to undo on the way out.
 *
 * The camera animates focus and scale, not the translation, and recomputes t
 * every frame. Easing t directly would make the focus point swim sideways
 * during a move.
 *
 * TO ADJUST A ZOOM, edit its beat in steps.ts:
 *   focus  a target key, or [x, y] fractions of the screenshot.
 *          Moving x or y by 0.02 is a small nudge.
 *   scale  1.3 is a gentle push, 1.6 is close.
 *   at     when the move starts. SPRING.camera in brand.ts sets how long it
 *          takes (about 0.8s now); a lower stiffness is slower.
 * Turn on showGuides to see every focus point as a crosshair.
 */

export type CameraState = { scale: number; x: number; y: number };

const REST: CameraState = { scale: 1, x: 0.5, y: 0.5 };

const mixState = (a: CameraState, b: CameraState, t: number): CameraState => ({
  scale: mix(a.scale, b.scale, t),
  x: mix(a.x, b.x, t),
  y: mix(a.y, b.y, t),
});

/**
 * Where the camera is at `frame`. Each zoom or unzoom springs from wherever
 * the camera actually is when it fires, so a move that interrupts another one
 * picks up smoothly instead of snapping.
 */
export const cameraAt = (step: Step, frame: number, fps: number): CameraState => {
  let from = REST;
  let to = REST;
  let start: number | null = null;
  const moves = step.beats.filter((b) => b.action === "zoom" || b.action === "unzoom");

  for (const beat of moves) {
    const at = windowFrame(step.id, beat.at);
    if (at > frame) break;
    if (start !== null) {
      from = mixState(from, to, spring({ frame: at - start, fps, config: SPRING.camera }));
    }
    to = beat.action === "zoom" ? { scale: beat.scale, ...focusOf(step, beat.focus) } : REST;
    start = at;
  }

  if (start === null) return REST;
  return mixState(from, to, spring({ frame: frame - start, fps, config: SPRING.camera }));
};

export const cameraTransform = (cam: CameraState, W: number, H: number) => {
  const reachX = ((cam.scale - 1) * W) / 2;
  const reachY = ((cam.scale - 1) * H) / 2;
  const tx = Math.max(-reachX, Math.min(reachX, -cam.scale * (cam.x - 0.5) * W));
  const ty = Math.max(-reachY, Math.min(reachY, -cam.scale * (cam.y - 0.5) * H));
  return `translate(${tx}px, ${ty}px) scale(${cam.scale})`;
};

export const Camera: React.FC<{ step: Step; plane: PlaneLayout; children: React.ReactNode }> = ({
  step,
  plane,
  children,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cam = cameraAt(step, frame, fps);

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        transformOrigin: "50% 50%",
        transform: cameraTransform(cam, plane.W, plane.H),
      }}
    >
      {children}
    </div>
  );
};

/** Every zoom's focus, for the guides overlay. */
export const zoomFoci = (step: Step) =>
  beatsOf(step, "zoom").map((b) => ({ ...focusOf(step, b.focus), scale: b.scale }));
