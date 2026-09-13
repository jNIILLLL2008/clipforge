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
import { useBeatFrame } from "../clock";
import { CLAMP, mix } from "../motion";
import type { Box, PlaneLayout, Shot } from "../plane";
import { DEFAULT_RING_STROKE, grow, ringBox, targetOf } from "../plane";

/** How much room the spotlight leaves around a ring, in CSS px. */
const SPOT_PAD = 8;
const DIM = 0.5;
const DRAW_FRAMES = 14;
const FADE_OUT_FRAMES = 8;

type Ring = { start: number; end: number; box: Box; run: number };

/*
 * The rings and the spotlight on one shot.
 *
 * A ring draws on as a hot ember-ink stroke, glows once and settles into
 * ember, sitting exactly on a ring baked into the screenshot (or just outside
 * a plain control). It stays until the next ring starts, or a clear.
 *
 * The spotlight dims everything but the current target. It is one element
 * whose cutout glides from target to target, rather than a dim per ring, so
 * the eye is carried along with it. A clear lifts it; the next ring after a
 * clear starts a fresh run, dimming in again rather than gliding.
 */
export const Highlights: React.FC<{ shot: Shot; plane: PlaneLayout }> = ({ shot, plane }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const at = useBeatFrame();
  const stroke = shot.ringStroke ?? DEFAULT_RING_STROKE;

  const rings: Ring[] = [];
  const clears: number[] = [];
  let run = 0;
  for (const beat of shot.beats) {
    if (beat.action !== "ring" && beat.action !== "clear") continue;
    const start = at(beat.at);
    const last = rings[rings.length - 1];
    if (last && last.end === Infinity) last.end = start;
    if (beat.action === "clear") {
      clears.push(start);
      run++;
      continue;
    }
    rings.push({ start, end: Infinity, box: ringBox(plane, targetOf(shot, beat.target)), run });
  }
  if (rings.length === 0) return null;

  let current = -1;
  for (let i = 0; i < rings.length; i++) {
    if (rings[i].start <= frame) current = i;
  }
  const ring = rings[Math.max(0, current)];

  let spot: Box = grow(ring.box, SPOT_PAD * plane.k);
  const previous = current > 0 ? rings[current - 1] : null;
  if (previous && previous.run === ring.run) {
    const from = grow(previous.box, SPOT_PAD * plane.k);
    const t = spring({ frame: frame - ring.start, fps, config: SPRING.spotlight });
    spot = {
      x: mix(from.x, spot.x, t),
      y: mix(from.y, spot.y, t),
      w: mix(from.w, spot.w, t),
      h: mix(from.h, spot.h, t),
      r: mix(from.r, spot.r, t),
    };
  }
  const runStart = rings.find((r) => r.run === ring.run)?.start ?? ring.start;
  const lifted = clears.filter((c) => c >= runStart && c <= frame).pop();
  const dim =
    interpolate(frame, [runStart, runStart + 12], [0, DIM], CLAMP) *
    (lifted === undefined ? 1 : interpolate(frame, [lifted, lifted + FADE_OUT_FRAMES], [1, 0], CLAMP));

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
      {rings.map((r, i) => {
        if (frame < r.start || frame > r.end + FADE_OUT_FRAMES) return null;
        return <RingView key={i} ring={r} k={plane.k} stroke={stroke} />;
      })}
    </>
  );
};

const RingView: React.FC<{ ring: Ring; k: number; stroke: number }> = ({ ring, k, stroke }) => {
  const frame = useCurrentFrame();
  const { box, start, end } = ring;
  const drawn = interpolate(frame, [start, start + DRAW_FRAMES], [0, 1], {
    ...CLAMP,
    easing: Easing.bezier(0.65, 0, 0.35, 1),
  });
  const settle = [start + DRAW_FRAMES - 2, start + DRAW_FRAMES + 16];
  const colour = interpolateColors(frame, settle, [C.emberInk, C.ember]);
  const width = interpolate(frame, settle, [4.4, stroke], CLAMP) * k;
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
          stroke={colour}
          strokeWidth={width}
          pathLength={1}
          strokeDasharray={drawn >= 1 ? undefined : "1 1"}
          strokeDashoffset={drawn >= 1 ? undefined : 1 - drawn}
        />
      </svg>
    </div>
  );
};
