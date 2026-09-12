import type React from "react";
import { interpolate } from "remotion";

export const CLAMP = {
  extrapolateLeft: "clamp",
  extrapolateRight: "clamp",
} as const;

/**
 * The site's entrance, lift and unblur, driven by a 0 to 1 progress that may
 * overshoot. The blur is what makes text resolve rather than merely fade in.
 */
export const riseStyle = (
  progress: number,
  lift = 24,
  blur = 8,
): React.CSSProperties => {
  const b = Math.max(0, (1 - progress) * blur);
  return {
    opacity: interpolate(progress, [0, 1], [0, 1], CLAMP),
    transform: `translateY(${(1 - progress) * lift}px)`,
    filter: b > 0.05 ? `blur(${b}px)` : undefined,
  };
};

export const mix = (a: number, b: number, t: number) => a + (b - a) * t;
