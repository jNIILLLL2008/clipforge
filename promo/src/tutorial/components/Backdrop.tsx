import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { C } from "../brand";

// The hairlines repeat every 28px across a 118deg gradient. Sliding the layer
// sideways by one full repeat lands on an identical image, so the drift can
// wrap on that distance without a visible jump.
const LINE_ANGLE = 118;
const LINE_PERIOD = 28;
const X_REPEAT = LINE_PERIOD / Math.sin((LINE_ANGLE * Math.PI) / 180);
const DRIFT_PX_PER_SEC = 9;

/**
 * The brand banner, animated: near-black canvas, faint diagonal hairlines, a
 * warm ember bloom from the right, and a vignette so the frame never reads as
 * a flat fill.
 *
 * `holdFrom` stops the drift and the breathing at that frame, for an ending
 * that holds still.
 */
export const Backdrop: React.FC<{ holdFrom?: number }> = ({ holdFrom = Infinity }) => {
  const frame = Math.min(useCurrentFrame(), holdFrom);
  const { fps } = useVideoConfig();
  const t = frame / fps;

  return (
    <AbsoluteFill style={{ backgroundColor: C.canvas, overflow: "hidden" }}>
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse 60% 90% at 78% 55%, rgba(226, 96, 58, 0.35), rgba(226, 96, 58, 0) 70%)",
          opacity: 0.94 + 0.06 * Math.sin((t / 6) * Math.PI * 2),
        }}
      />
      <div
        style={{
          position: "absolute",
          left: -80,
          top: -40,
          width: 1920 + 160,
          height: 1080 + 80,
          backgroundImage: `repeating-linear-gradient(${LINE_ANGLE}deg, rgba(255, 255, 255, 0.035) 0px, rgba(255, 255, 255, 0.035) 1px, rgba(255, 255, 255, 0) 1.6px, rgba(255, 255, 255, 0) ${LINE_PERIOD}px)`,
          transform: `translateX(${-((t * DRIFT_PX_PER_SEC) % X_REPEAT)}px)`,
        }}
      />
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse 75% 85% at 50% 50%, rgba(0, 0, 0, 0) 55%, rgba(0, 0, 0, 0.55) 100%)",
        }}
      />
    </AbsoluteFill>
  );
};
