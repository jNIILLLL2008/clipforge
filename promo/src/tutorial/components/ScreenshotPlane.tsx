import React from "react";
import { Img, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C, SPRING } from "../brand";
import type { PlaneLayout } from "../layout";
import { CARD_CSS_RADIUS } from "../steps";
import type { Step } from "../steps";
import { Chips, Fills } from "./Annotations";
import { Camera } from "./Camera";
import { Cursor } from "./Cursor";
import { Guides } from "./Guides";
import { Highlights } from "./Highlights";

/*
 * The screenshot, and everything that points at it.
 *
 *   box       where the screenshot rests in the frame
 *   tilt      the 3D entrance, flattening as it settles
 *   viewport  the card's rounded rect: clips everything inside, carries the
 *             shadow and the hairline edge
 *   camera    the zoom (Camera.tsx). It lives inside the viewport, so a zoom
 *             magnifies within the card's frame instead of spilling over the
 *             caption, the stepper and the edge of the video.
 *   content   the image, the fills, the spotlight, the rings, the chips and
 *             the cursor, in that order, so chips and the cursor sit above
 *             the dim.
 *
 * Everything in the content layer positions itself in fractions of the
 * screenshot, inside the camera and the tilt, so every ring and cursor stays
 * on its pixel whatever the plane is doing.
 */
export const ScreenshotPlane: React.FC<{
  step: Step;
  plane: PlaneLayout;
  showGuides: boolean;
}> = ({ step, plane, showGuides }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: SPRING.plane });
  const radius = CARD_CSS_RADIUS * plane.k;

  return (
    <div
      style={{
        position: "absolute",
        left: plane.left,
        top: plane.top,
        width: plane.W,
        height: plane.H,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          transformOrigin: "50% 50%",
          transform: `perspective(1600px) rotateX(${16 * (1 - enter)}deg) rotateY(${-8 * (1 - enter)}deg) translateY(${60 * (1 - enter)}px) scale(${0.92 + 0.08 * enter})`,
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: radius,
            overflow: "hidden",
            boxShadow:
              "0 40px 120px rgba(0, 0, 0, 0.6), 0 24px 90px -12px rgba(226, 96, 58, 0.14)",
          }}
        >
          <Camera step={step} plane={plane}>
            <Img
              src={staticFile(step.image)}
              style={{ display: "block", width: plane.W, height: plane.H }}
            />
            <Fills step={step} plane={plane} />
            <Highlights step={step} plane={plane} />
            <Chips step={step} plane={plane} />
            <Cursor step={step} plane={plane} />
            {showGuides ? <Guides step={step} plane={plane} /> : null}
          </Camera>
          <div
            style={{
              position: "absolute",
              inset: 0,
              borderRadius: radius,
              boxShadow: `inset 0 0 0 1px ${C.hairlineFirm}`,
            }}
          />
        </div>
      </div>
    </div>
  );
};
