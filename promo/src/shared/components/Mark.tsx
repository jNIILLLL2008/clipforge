import React, { useId } from "react";
import { MARK_STOPS } from "../brand";

/*
 * The ClipForge mark, verbatim from the brand kit: an angular C that is also a
 * clip bracket, with a spark struck in its mouth. The C is a stroked polyline
 * on a 64-unit grid at a constant 11-unit stroke. Never convert it to
 * outlines and never re-weight the stroke; scale the whole glyph instead.
 */
const BRACKET = "M50 13H27L15.5 32L27 51H50";
const SPARK = "M45 23L47.26 29.74L54 32L47.26 34.26L45 41L42.74 34.26L36 32L42.74 29.74Z";
const SPARK_CENTRE = { x: 45, y: 32 };

type MarkProps = {
  /** The 64-unit box, in px. */
  size: number;
  /** "gradient" for the brand mark, or any flat colour. */
  paint?: string;
  /** 0 to 1: how much of the bracket is drawn. */
  draw?: number;
  /** The spark's scale. May overshoot 1. */
  spark?: number;
  /** The spark's rotation in degrees. */
  sparkTurn?: number;
  /** 0 to 1: progress through the ember bloom as the spark strikes. Nothing shows at 0 or 1. */
  bloom?: number;
};

export const Mark: React.FC<MarkProps> = ({
  size,
  paint = "gradient",
  draw = 1,
  spark = 1,
  sparkTurn = 0,
  bloom = 0,
}) => {
  // useId can contain characters that break url(#...), so keep only the safe ones.
  const id = `cf-mark-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const fill = paint === "gradient" ? `url(#${id})` : paint;
  const drawn = draw >= 1;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      style={{ display: "block", overflow: "visible" }}
    >
      <defs>
        {/* userSpaceOnUse so the bracket and the spark share one gradient. */}
        <linearGradient
          id={id}
          gradientUnits="userSpaceOnUse"
          x1="8.64"
          y1="-5.38"
          x2="55.36"
          y2="69.38"
        >
          {MARK_STOPS.map((stop) => (
            <stop key={stop.offset} offset={stop.offset} stopColor={stop.color} />
          ))}
        </linearGradient>
        <radialGradient id={`${id}-bloom`}>
          <stop offset="0" stopColor="#FF8A3C" stopOpacity="0.95" />
          <stop offset="0.45" stopColor="#E2603A" stopOpacity="0.45" />
          <stop offset="1" stopColor="#E2603A" stopOpacity="0" />
        </radialGradient>
      </defs>
      {bloom > 0 && bloom < 1 ? (
        <circle
          cx={SPARK_CENTRE.x}
          cy={SPARK_CENTRE.y}
          r={10 + 24 * bloom}
          fill={`url(#${id}-bloom)`}
          opacity={Math.sin(Math.PI * bloom)}
        />
      ) : null}
      <path
        d={BRACKET}
        fill="none"
        stroke={fill}
        strokeWidth={11}
        strokeLinejoin="miter"
        strokeLinecap="butt"
        pathLength={1}
        strokeDasharray={drawn ? undefined : "1 1"}
        strokeDashoffset={drawn ? undefined : 1 - Math.max(0, draw)}
      />
      {spark > 0.001 ? (
        <g
          transform={`translate(${SPARK_CENTRE.x} ${SPARK_CENTRE.y}) rotate(${sparkTurn}) scale(${spark}) translate(${-SPARK_CENTRE.x} ${-SPARK_CENTRE.y})`}
        >
          <path d={SPARK} fill={fill} />
        </g>
      ) : null}
    </svg>
  );
};
