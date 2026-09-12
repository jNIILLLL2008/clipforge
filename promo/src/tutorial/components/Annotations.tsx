import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, MONO, SANS, SPRING } from "../brand";
import type { PlaneLayout } from "../layout";
import { rectPx, ringBox } from "../layout";
import { CLAMP } from "../motion";
import type { Step } from "../steps";
import { beatsOf, targetOf } from "../steps";
import { sec, windowFrame } from "../timeline";

/*
 * Text put into the screenshot's fields. A fill covers the field's placeholder
 * with the field's own background, then sets the text where the app would:
 * a pasted URL in mono, or a row of masked dots typed on. Never a realistic
 * ID or secret.
 */
export const Fills: React.FC<{ step: Step; plane: PlaneLayout }> = ({ step, plane }) => {
  const frame = useCurrentFrame();

  return (
    <>
      {beatsOf(step, "fill").map((beat, i) => {
        const start = windowFrame(step.id, beat.at);
        if (frame < start) return null;
        const target = targetOf(step, beat.target);
        const field = target.field;
        if (!field) return null;

        // Inside the field's 1px border.
        const box = rectPx(plane, target.rect, target.radius);
        const border = 1.2 * plane.k;
        const typing = beat.seconds ? sec(beat.seconds) : 0;
        const shown = (length: number) =>
          typing === 0
            ? length
            : Math.floor(interpolate(frame, [start, start + typing], [0, length], CLAMP));

        const text = beat.masked
          ? "•".repeat(shown(beat.masked))
          : (beat.text ?? "").slice(0, shown((beat.text ?? "").length));

        // Fit the line to the field: Geist Mono advances 0.6em per character.
        const room = box.w - 2 * field.inset * plane.k;
        const fontSize = beat.masked
          ? field.fontSize * plane.k
          : Math.min(field.fontSize * plane.k, room / (0.6 * Math.max(1, (beat.text ?? "").length)));

        const flash = interpolate(frame, [start, start + 2, start + 14], [0, 0.32, 0], CLAMP);

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: box.x + border,
              top: box.y + border,
              width: box.w - border * 2,
              height: box.h - border * 2,
              borderRadius: Math.max(0, box.r - border),
              backgroundColor: field.background,
              opacity: interpolate(frame, [start, start + 3], [0, 1], CLAMP),
              display: "flex",
              alignItems: "center",
              paddingLeft: field.inset * plane.k - border,
              overflow: "hidden",
            }}
          >
            <span
              style={{
                fontFamily: beat.masked ? SANS : MONO,
                fontWeight: beat.masked ? 700 : 500,
                fontSize,
                letterSpacing: beat.masked ? "0.14em" : 0,
                color: C.ink,
                whiteSpace: "nowrap",
              }}
            >
              {text}
            </span>
            <div
              style={{
                position: "absolute",
                inset: 0,
                backgroundColor: C.ember,
                opacity: flash,
              }}
            />
          </div>
        );
      })}
    </>
  );
};

/**
 * A small label that pops onto a target's top-right corner. Drawn after the
 * spotlight, so it is never dimmed.
 */
export const Chips: React.FC<{ step: Step; plane: PlaneLayout }> = ({ step, plane }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <>
      {beatsOf(step, "chip").map((beat, i) => {
        const start = windowFrame(step.id, beat.at);
        if (frame < start) return null;
        const box = ringBox(plane, targetOf(step, beat.target));
        const pop = spring({ frame: frame - start, fps, config: SPRING.pop });

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              right: plane.W - (box.x + box.w),
              bottom: plane.H - box.y + 8 * plane.k,
              transformOrigin: "100% 100%",
              transform: `scale(${0.85 + 0.15 * pop})`,
              opacity: interpolate(pop, [0, 1], [0, 1], CLAMP),
              padding: `${5 * plane.k}px ${11 * plane.k}px`,
              borderRadius: 999,
              backgroundColor: "rgba(19, 19, 22, 0.92)",
              boxShadow: `inset 0 0 0 ${Math.max(1, plane.k)}px ${C.emberEdge}, 0 0 0 999px ${C.emberWash} inset`,
              fontFamily: MONO,
              fontWeight: 500,
              fontSize: 13 * plane.k,
              color: C.emberInk,
              whiteSpace: "nowrap",
            }}
          >
            {beat.text}
          </div>
        );
      })}
    </>
  );
};
