import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, MONO, SANS, SPRING } from "../brand";
import { CAPTION_BOTTOM, CAPTION_WIDTH } from "../layout";
import { CLAMP, riseStyle } from "../motion";
import type { Callout, Step } from "../steps";
import { TOTAL_STEPS } from "../steps";
import { sec, windowFrame } from "../timeline";

/** When the caption's lines start rising, in seconds after the cut. */
const TEXT_AT = 0.05;
const STAGGER = 4;

const SUB_TYPE: React.CSSProperties = {
  gridArea: "1 / 1",
  fontFamily: SANS,
  fontWeight: 400,
  fontSize: 26,
  lineHeight: 1.4,
  color: C.inkMuted,
};

/*
 * The caption: a floating glass card at lower left, overlapping the
 * screenshot's edge. Each line lifts and unblurs in, a few frames apart.
 * A callout (the step 5 badge, the step 6 URL) sits above the card; the stack
 * is anchored at the bottom, so a callout grows upward and never moves the card.
 */
export const Caption: React.FC<{ step: Step; left: number }> = ({ step, left }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const start = windowFrame(step.id, TEXT_AT);
  const line = (i: number) =>
    riseStyle(spring({ frame: frame - (start + i * STAGGER), fps, config: SPRING.text }));
  const card = spring({ frame: frame - (start - 4), fps, config: SPRING.plane });

  // The sub line rises with the others; on a step with subLater it lifts away
  // and the replacement rises into the same place.
  const subIn = spring({ frame: frame - (start + 2 * STAGGER), fps, config: SPRING.text });
  const swapAt = step.subLater ? windowFrame(step.id, step.subLater.at) : null;
  const subOut = swapAt === null ? 0 : interpolate(frame, [swapAt, swapAt + 8], [0, 1], CLAMP);
  const laterIn =
    swapAt === null ? 0 : spring({ frame: frame - (swapAt + 5), fps, config: SPRING.text });

  const calloutUntil =
    step.callout?.until === undefined ? null : windowFrame(step.id, step.callout.until);
  const calloutOut =
    calloutUntil === null ? 0 : interpolate(frame, [calloutUntil, calloutUntil + 8], [0, 1], CLAMP);

  return (
    <div
      style={{
        position: "absolute",
        left,
        bottom: CAPTION_BOTTOM,
        width: CAPTION_WIDTH,
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: 18,
      }}
    >
      {step.callout ? (
        <div
          style={{
            opacity: 1 - calloutOut,
            transform: `translateY(${-10 * calloutOut}px)`,
          }}
        >
          <CalloutView step={step} callout={step.callout} />
        </div>
      ) : null}
      <div
        style={{
          boxSizing: "border-box",
          width: "100%",
          padding: "30px 34px 34px",
          borderRadius: 16,
          backgroundColor: "rgba(19, 19, 22, 0.72)",
          backdropFilter: "blur(18px)",
          WebkitBackdropFilter: "blur(18px)",
          boxShadow:
            "inset 0 0 0 1px rgba(255, 255, 255, 0.06), 0 30px 80px rgba(0, 0, 0, 0.45)",
          opacity: interpolate(card, [0, 1], [0, 1], CLAMP),
          transform: `translateY(${(1 - card) * 16}px)`,
        }}
      >
        <div
          style={{
            fontFamily: MONO,
            fontWeight: 500,
            fontSize: 20,
            letterSpacing: "0.14em",
            color: C.emberInk,
            ...line(0),
          }}
        >
          STEP {step.n} OF {TOTAL_STEPS}
        </div>
        <div
          style={{
            marginTop: 14,
            fontFamily: SANS,
            fontWeight: 600,
            fontSize: 46,
            lineHeight: 1.1,
            letterSpacing: "-0.02em",
            color: C.ink,
            ...line(1),
          }}
        >
          {step.headline}
        </div>
        {/* Both sub lines share one grid cell, so the card is sized for the
            longer one from the start and never jumps when they swap. */}
        <div style={{ marginTop: 16, display: "grid" }}>
          <div
            style={{
              ...SUB_TYPE,
              ...riseStyle(subIn),
              opacity: interpolate(subIn, [0, 1], [0, 1], CLAMP) * (1 - subOut),
              transform: `translateY(${(1 - subIn) * 24 - subOut * 10}px)`,
            }}
          >
            {step.sub}
          </div>
          {step.subLater ? (
            <div style={{ ...SUB_TYPE, ...riseStyle(laterIn) }}>{step.subLater.text}</div>
          ) : null}
        </div>
      </div>
    </div>
  );
};

const CalloutView: React.FC<{ step: Step; callout: Callout }> = ({ step, callout }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const at = windowFrame(step.id, callout.at);
  const pop = spring({ frame: frame - at, fps, config: SPRING.pop });

  if (callout.kind === "badge") {
    const glow = interpolate(frame, [at + 3, at + 12, at + 40], [0, 0.7, 0.25], CLAMP);
    return (
      <div
        style={{
          padding: "10px 20px",
          borderRadius: 999,
          backgroundColor: C.ember,
          color: C.onEmber,
          fontFamily: SANS,
          fontWeight: 600,
          fontSize: 24,
          letterSpacing: "-0.01em",
          whiteSpace: "nowrap",
          transformOrigin: "0% 100%",
          transform: `scale(${0.6 + 0.4 * pop})`,
          opacity: interpolate(pop, [0, 0.6], [0, 1], CLAMP),
          boxShadow: `0 0 36px rgba(226, 96, 58, ${glow})`,
        }}
      >
        {callout.text}
      </div>
    );
  }

  // The redirect URI, typed on, then a Copied tick as the cursor hits Copy.
  const typeFrom = at + 6;
  const typeTo = typeFrom + sec(callout.typeSeconds);
  const chars = Math.floor(
    interpolate(frame, [typeFrom, typeTo], [0, callout.text.length], CLAMP),
  );
  const copiedAt = windowFrame(step.id, callout.copiedAt);
  const copiedUntil = copiedAt + sec(1.4);
  const caretOn = frame < copiedAt && (frame < typeTo || Math.floor((frame - typeTo) / 8) % 2 === 0);
  const copied = spring({ frame: frame - copiedAt, fps, config: SPRING.pop });
  const copiedOpacity =
    interpolate(copied, [0, 0.6], [0, 1], CLAMP) *
    interpolate(frame, [copiedUntil, copiedUntil + 8], [1, 0], CLAMP);

  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
        padding: "14px 22px",
        borderRadius: 999,
        backgroundColor: "rgba(19, 19, 22, 0.88)",
        boxShadow: `inset 0 0 0 1px ${C.emberEdge}, 0 20px 50px rgba(0, 0, 0, 0.4)`,
        ...riseStyle(pop, 18, 6),
      }}
    >
      <span
        style={{
          fontFamily: MONO,
          fontWeight: 500,
          fontSize: 22,
          color: C.ink,
          whiteSpace: "pre",
        }}
      >
        {/* The untyped rest is laid out but invisible, so the pill is its
            final width from the first frame. */}
        {callout.text.slice(0, chars)}
        <span style={{ display: "inline-block", width: 0 }}>
          <span
            style={{
              display: "inline-block",
              width: 2,
              height: 24,
              marginLeft: 1,
              verticalAlign: "-5px",
              backgroundColor: C.ember,
              opacity: caretOn ? 1 : 0,
            }}
          />
        </span>
        <span style={{ opacity: 0 }}>{callout.text.slice(chars)}</span>
      </span>
      {frame >= copiedAt ? (
        <div
          style={{
            position: "absolute",
            left: "100%",
            marginLeft: 12,
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 14px",
            borderRadius: 999,
            backgroundColor: C.ember,
            color: C.onEmber,
            fontFamily: SANS,
            fontWeight: 600,
            fontSize: 20,
            whiteSpace: "nowrap",
            transformOrigin: "0% 50%",
            transform: `scale(${0.7 + 0.3 * copied})`,
            opacity: copiedOpacity,
          }}
        >
          <svg width={16} height={16} viewBox="0 0 16 16">
            <path
              d="M3 8.5 L6.5 12 L13 4.5"
              fill="none"
              stroke={C.onEmber}
              strokeWidth={2.4}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Copied
        </div>
      ) : null}
    </div>
  );
};
