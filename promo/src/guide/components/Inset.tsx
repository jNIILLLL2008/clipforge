import React from "react";
import { Easing, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C, MONO, SPRING } from "../../shared/brand";
import { useBeatFrame } from "../../shared/clock";
import { CLAMP, riseStyle } from "../../shared/motion";
import type { Inset } from "../guide";

/**
 * A picture laid over the scene: the preview frame beside the banner fields,
 * the preview's warning, the walkthrough's poster. It pops in, can swap to a
 * second picture, can ring a region of itself, and carries a label under it.
 */
export const InsetView: React.FC<{ inset: Inset }> = ({ inset }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const at = useBeatFrame();
  const start = at(inset.at);
  if (frame < start) return null;

  const pop = spring({ frame: frame - start, fps, config: SPRING.pop });
  const gone = inset.until === undefined ? 0 : interpolate(frame, [at(inset.until), at(inset.until) + 8], [0, 1], CLAMP);
  if (gone >= 1) return null;
  const width = inset.displayWidth;
  const height = (width * inset.height) / inset.width;
  const swap = inset.swapTo ? interpolate(frame, [at(inset.swapTo.at), at(inset.swapTo.at) + 8], [0, 1], CLAMP) : 0;
  const ringStart = inset.ring ? at(inset.ring.at) : null;
  const drawn =
    ringStart === null
      ? 0
      : interpolate(frame, [ringStart, ringStart + 14], [0, 1], { ...CLAMP, easing: Easing.bezier(0.65, 0, 0.35, 1) });

  return (
    <div
      style={{
        position: "absolute",
        left: inset.left,
        top: inset.top,
        width,
        opacity: interpolate(pop, [0, 0.6], [0, 1], CLAMP) * (1 - gone),
        transformOrigin: "50% 60%",
        transform: `scale(${0.9 + 0.1 * Math.min(1.04, pop)}) translateY(${-10 * gone}px)`,
      }}
    >
      <div
        style={{
          position: "relative",
          width,
          height,
          borderRadius: 12,
          overflow: "hidden",
          boxShadow: `inset 0 0 0 1px ${C.hairlineFirm}, 0 30px 80px rgba(0, 0, 0, 0.55)`,
          backgroundColor: C.surface,
        }}
      >
        <Img src={staticFile(inset.image)} style={{ position: "absolute", inset: 0, width, height }} />
        {inset.swapTo ? (
          <Img
            src={staticFile(inset.swapTo.image)}
            style={{ position: "absolute", inset: 0, width, height, opacity: swap }}
          />
        ) : null}
        {inset.play ? (
          <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", backgroundColor: "rgba(8, 8, 10, 0.25)" }}>
            <div
              style={{
                width: 64,
                height: 64,
                borderRadius: 999,
                backgroundColor: C.ember,
                display: "grid",
                placeItems: "center",
                boxShadow: "0 12px 34px rgba(226, 96, 58, 0.34)",
              }}
            >
              <svg width={22} height={22} viewBox="0 0 24 24" style={{ marginLeft: 4 }}>
                <path d="M8 5.5v13l11-6.5z" fill={C.onEmber} />
              </svg>
            </div>
          </div>
        ) : null}
        <div style={{ position: "absolute", inset: 0, borderRadius: 12, boxShadow: `inset 0 0 0 1px ${C.hairlineFirm}` }} />
      </div>
      {inset.ring && ringStart !== null && frame >= ringStart ? (
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <rect
            x={inset.ring.rect[0] * width}
            y={inset.ring.rect[1] * height}
            width={inset.ring.rect[2] * width}
            height={inset.ring.rect[3] * height}
            rx={6}
            fill="none"
            stroke={C.ember}
            strokeWidth={2.5}
            pathLength={1}
            strokeDasharray={drawn >= 1 ? undefined : "1 1"}
            strokeDashoffset={drawn >= 1 ? undefined : 1 - drawn}
            style={{ filter: "drop-shadow(0 0 10px rgba(226, 96, 58, 0.6))" }}
          />
        </svg>
      ) : null}
      {inset.label ? (
        <div
          style={{
            marginTop: 12,
            fontFamily: MONO,
            fontWeight: 500,
            fontSize: 16,
            letterSpacing: "0.08em",
            color: C.emberInk,
            whiteSpace: "nowrap",
            ...riseStyle(spring({ frame: frame - (start + 6), fps, config: SPRING.text }), 10, 4),
          }}
        >
          {inset.label}
        </div>
      ) : null}
    </div>
  );
};
