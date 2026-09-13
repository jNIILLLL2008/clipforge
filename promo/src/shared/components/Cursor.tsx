import React from "react";
import { Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, SPRING } from "../brand";
import type { BeatFrame } from "../clock";
import { useBeatFrame } from "../clock";
import { CLAMP, mix } from "../motion";
import type { PlaneLayout, Shot } from "../plane";
import { centreOf, rectPx, targetOf } from "../plane";

/** How early the cursor sets off, in seconds, so it arrives on the beat. */
const TRAVEL_SECONDS = 0.6;
/**
 * Where the cursor waits before its first move: just past the screenshot's
 * lower right, outside the card's clip, so it glides in over the edge.
 */
const REST = { x: 1.04, y: 1.08 };
const CURSOR_HEIGHT = 34;
const RIPPLE_FRAMES = 18;

type Waypoint = { x: number; y: number; at: number; leave: number; click: boolean };

const waypoints = (shot: Shot, plane: PlaneLayout, at: BeatFrame, travel: number): Waypoint[] => {
  const out: Waypoint[] = [];
  for (const beat of shot.beats) {
    if (beat.action !== "point" && beat.action !== "click") continue;
    const arrive = at(beat.at);
    const previous = out.length > 0 ? out[out.length - 1].at : -Infinity;
    // Never leave a target before arriving at it.
    const leave = Math.max(arrive - travel, previous + 2);
    const box = rectPx(plane, targetOf(shot, beat.target).rect);
    out.push({ ...centreOf(box), at: arrive, leave, click: beat.action === "click" });
  }
  return out;
};

/** A point along a gentle arc from a to b, bowed upward like a hand moving a mouse. */
const arc = (a: { x: number; y: number }, b: { x: number; y: number }, t: number) => {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy) || 1;
  let nx = -dy / length;
  let ny = dx / length;
  if (ny > 0) {
    nx = -nx;
    ny = -ny;
  }
  const bow = length * 0.16;
  const cx = (a.x + b.x) / 2 + nx * bow;
  const cy = (a.y + b.y) / 2 + ny * bow;
  const u = 1 - t;
  return {
    x: u * u * a.x + 2 * u * t * cx + t * t * b.x,
    y: u * u * a.y + 2 * u * t * cy + t * t * b.y,
  };
};

/**
 * The cursor and its click ripples, in the plane's own px, so they stay on
 * their targets while the plane tilts and zooms.
 */
export const Cursor: React.FC<{ shot: Shot; plane: PlaneLayout }> = ({ shot, plane }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const points = waypoints(shot, plane, useBeatFrame(), Math.round(TRAVEL_SECONDS * fps));
  if (points.length === 0) return null;

  // Walk the moves in order. A move that starts before the last one settled
  // springs from wherever the cursor actually was.
  const rest = { x: REST.x * plane.W, y: REST.y * plane.H };
  let from = rest;
  let pos = rest;
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    if (p.leave > frame) break;
    if (i > 0) {
      const settled = spring({ frame: p.leave - points[i - 1].leave, fps, config: SPRING.cursor });
      from = arc(from, points[i - 1], settled);
    }
    const t = spring({ frame: frame - p.leave, fps, config: SPRING.cursor });
    pos = arc(from, p, t);
  }

  let press = 0;
  for (const p of points) {
    if (!p.click) continue;
    press = Math.max(
      press,
      interpolate(frame, [p.at - 2, p.at + 1, p.at + 8], [0, 1, 0], {
        ...CLAMP,
        easing: Easing.inOut(Easing.quad),
      }),
    );
  }

  const opacity = interpolate(frame, [points[0].leave, points[0].leave + 8], [0, 1], CLAMP);
  const size = CURSOR_HEIGHT;

  return (
    <>
      {points.map((p, i) => {
        if (!p.click || frame < p.at || frame > p.at + RIPPLE_FRAMES) return null;
        const t = interpolate(frame, [p.at, p.at + RIPPLE_FRAMES], [0, 1], {
          ...CLAMP,
          easing: Easing.out(Easing.cubic),
        });
        const r = mix(6, 46, t);
        return (
          <svg
            key={i}
            width="100%"
            height="100%"
            style={{ position: "absolute", inset: 0, overflow: "visible" }}
          >
            <circle cx={p.x} cy={p.y} r={r * 0.6} fill={C.ember} opacity={0.22 * (1 - t)} />
            <circle
              cx={p.x}
              cy={p.y}
              r={r}
              fill="none"
              stroke={C.ember}
              strokeWidth={mix(3.5, 0.8, t)}
              opacity={0.95 * (1 - t)}
            />
          </svg>
        );
      })}
      <svg
        width={size * (24 / 32)}
        height={size}
        viewBox="0 0 24 32"
        style={{
          position: "absolute",
          // The arrow's tip is at (2, 2) in its viewBox; that is the hotspot.
          left: pos.x - 2 * (size / 32),
          top: pos.y - 2 * (size / 32),
          opacity,
          overflow: "visible",
          transformOrigin: `${2 * (size / 32)}px ${2 * (size / 32)}px`,
          transform: `scale(${1 - 0.15 * press})`,
          filter: "drop-shadow(0 3px 6px rgba(0, 0, 0, 0.55))",
        }}
      >
        <path
          d="M2 2 L2 26 L8.2 20.2 L12.3 29.6 L16.4 27.8 L12.4 18.6 L20.6 18.6 Z"
          fill={C.ink}
          stroke={C.canvas}
          strokeWidth={1.5}
          strokeLinejoin="round"
        />
      </svg>
    </>
  );
};
