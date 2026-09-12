import React from "react";
import { Easing, interpolate, spring } from "remotion";
import { C, MONO, SPRING, TAGLINE_COLOR, WORDMARK_TYPE } from "../brand";
import { CLAMP, riseStyle } from "../motion";
import { Mark } from "./Mark";

/*
 * The lockup, with the metrics measured off the brand kit's own rendered
 * lockup: the mark's 64-unit box is 0.9362em of the wordmark's size, and the
 * gap between the box and the wordmark is 0.3082em. The tagline sits under the
 * wordmark, aligned to the wordmark rather than the mark, as on the banner.
 */
const GLYPH_EM = 0.9362;
const GAP_EM = 0.3082;

export type LockupMotion = {
  draw: number;
  spark: number;
  sparkTurn: number;
  bloom: number;
  word: number;
  tag: number;
};

export const LOCKUP_AT_REST: LockupMotion = {
  draw: 1,
  spark: 1,
  sparkTurn: 0,
  bloom: 1,
  word: 1,
  tag: 1,
};

/**
 * The bracket draws on, the spark strikes with a bloom, then the wordmark and
 * the tagline lift and unblur in. Everything is timed from `start`.
 */
export const lockupEntrance = (frame: number, fps: number, start: number): LockupMotion => {
  const strike = spring({ frame: frame - (start + 15), fps, config: SPRING.pop });
  return {
    draw: interpolate(frame, [start, start + 18], [0, 1], {
      ...CLAMP,
      easing: Easing.bezier(0.65, 0, 0.35, 1),
    }),
    spark: strike,
    sparkTurn: 45 * (1 - strike),
    bloom: interpolate(frame, [start + 15, start + 38], [0, 1], CLAMP),
    word: spring({ frame: frame - (start + 23), fps, config: SPRING.text }),
    tag: spring({ frame: frame - (start + 29), fps, config: SPRING.text }),
  };
};

type LockupProps = {
  /** The wordmark's font size, in px. Everything else scales from it. */
  size: number;
  /** "brand": gradient mark, ink wordmark. "ink": the whole lockup in ink. */
  tone?: "brand" | "ink";
  tagline?: boolean;
  motion?: LockupMotion;
};

export const Lockup: React.FC<LockupProps> = ({
  size,
  tone = "brand",
  tagline = false,
  motion = LOCKUP_AT_REST,
}) => {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `${GLYPH_EM}em auto`,
        columnGap: `${GAP_EM}em`,
        alignItems: "center",
        fontSize: size,
      }}
    >
      <Mark
        size={GLYPH_EM * size}
        paint={tone === "brand" ? "gradient" : C.ink}
        draw={motion.draw}
        spark={motion.spark}
        sparkTurn={motion.sparkTurn}
        bloom={motion.bloom}
      />
      <div style={{ ...WORDMARK_TYPE, color: C.ink, ...riseStyle(motion.word, size * 0.18) }}>
        Clipforge
      </div>
      {tagline ? (
        <div
          style={{
            gridColumn: 2,
            marginTop: size * 0.26,
            fontFamily: MONO,
            fontWeight: 500,
            fontSize: size * 0.22,
            letterSpacing: "0.22em",
            color: TAGLINE_COLOR,
            whiteSpace: "nowrap",
            ...riseStyle(motion.tag, 14, 6),
          }}
        >
          RAW FOOTAGE IN · FINISHED CUTS OUT
        </div>
      ) : null}
    </div>
  );
};
