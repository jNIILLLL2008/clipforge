import React from "react";
import {
  Easing,
  interpolate,
  interpolateColors,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C, SPRING } from "../brand";
import type { Box, PlaneLayout } from "../layout";
import { grow, ringBox } from "../layout";
import { CLAMP, mix } from "../motion";
import type { Step } from "../steps";
import { BAKED_RING_STROKE, beatsOf, targetOf } from "../steps";
import { windowFrame } from "../timeline";

/** How much room the spotlight leaves around a ring, in CSS px. */
const SPOT_PAD = 8;
const DIM = 0.5;
const DRAW_FRAMES = 14;
const FADE_OUT_FRAMES = 8;

/*
 * The rings and the spotlight for one step.
 *
 * A ring draws on as a hot ember-ink stroke, glows once and settles into
 * ember, sitting exactly on the ring baked into the screenshot (or just
 * outside a plain control). It stays until the next ring starts.
 *
 * The spotlight dims everything but the current target. It is one element
 * whose cutout glides from target to target, rather than a dim per ring, so
 * the eye is carried along with it.
 */
export const Highlights: React.FC<{ step: Step; plane: PlaneLayout }> = ({ step, plane }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rings = beatsOf(step, "ring").map((beat) => ({
    start: windowFrame(step.id, beat.at),
    box: ringBox(plane, targetOf(step, beat.target)),
  }));
  if (rings.length === 0) return null;

  let current = -1;
  for (let i = 0; i < rings.length; i++) {
    if (rings[i].start <= frame) current = i;
  }

  let spot: Box = grow(rings[Math.max(0, current)].box, SPOT_PAD * plane.k);
  if (current > 0) {
    const from = grow(rings[current - 1].box, SPOT_PAD * plane.k);
    const t = spring({ frame: frame - rings[current].start, fps, config: SPRING.spotlight });
    spot = {
      x: mix(from.x, spot.x, t),
      y: mix(from.y, spot.y, t),
      w: mix(from.w, spot.w, t),
      h: mix(from.h, spot.h, t),
      r: mix(from.r, spot.r, t),
    };
  }
  const dim = interpolate(frame, [rings[0].start, rings[0].start + 12], [0, DIM], CLAMP);

  return (
    <>
      {dim > 0 ? (
        <div
          style={{
            position: "absolute",
            left: spot.x,
            top: spot.y,
            width: spot.w,
            height: spot.h,
            borderRadius: spot.r,
            // A spread shadow as big as the frame paints the dim; the element
            // itself is the rounded cutout. The plane's overflow clips it.
            boxShadow: `0 0 0 4000px rgba(11, 11, 13, ${dim})`,
          }}
        />
      ) : null}
      {rings.map((ring, i) => {
        const end = i + 1 < rings.length ? rings[i + 1].start : Infinity;
        if (frame < ring.start || frame > end + FADE_OUT_FRAMES) return null;
        return <Ring key={i} box={ring.box} start={ring.start} end={end} k={plane.k} />;
      })}
    </>
  );
};

const Ring: React.FC<{ box: Box; start: number; end: number; k: number }> = ({
  box,
  start,
  end,
  k,
}) => {
  const frame = useCurrentFrame();
  const drawn = interpolate(frame, [start, start + DRAW_FRAMES], [0, 1], {
    ...CLAMP,
    easing: Easing.bezier(0.65, 0, 0.35, 1),
  });
  const settle = [start + DRAW_FRAMES - 2, start + DRAW_FRAMES + 16];
  const stroke = interpolateColors(frame, settle, [C.emberInk, C.ember]);
  const width = interpolate(frame, settle, [4.4, BAKED_RING_STROKE], CLAMP) * k;
  const glow = interpolate(
    frame,
    [start + DRAW_FRAMES - 4, start + DRAW_FRAMES + 4, start + DRAW_FRAMES + 22],
    [0, 1, 0.35],
    CLAMP,
  );
  const opacity = end === Infinity ? 1 : interpolate(frame, [end, end + FADE_OUT_FRAMES], [1, 0], CLAMP);

  return (
    <div style={{ position: "absolute", inset: 0, opacity }}>
      <div
        style={{
          position: "absolute",
          left: box.x,
          top: box.y,
          width: box.w,
          height: box.h,
          borderRadius: box.r,
          boxShadow: "0 0 28px rgba(226, 96, 58, 0.55)",
          opacity: glow,
        }}
      />
      <svg
        width="100%"
        height="100%"
        style={{ position: "absolute", inset: 0, overflow: "visible" }}
      >
        <rect
          x={box.x}
          y={box.y}
          width={box.w}
          height={box.h}
          rx={box.r}
          fill="none"
          stroke={stroke}
          strokeWidth={width}
          pathLength={1}
          strokeDasharray={drawn >= 1 ? undefined : "1 1"}
          strokeDashoffset={drawn >= 1 ? undefined : 1 - drawn}
        />
      </svg>
    </div>
  );
};
