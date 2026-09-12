import { loadFont } from "@remotion/fonts";
import { loadFont as loadGeist } from "@remotion/google-fonts/Geist";
import { loadFont as loadGeistMono } from "@remotion/google-fonts/GeistMono";
import type React from "react";
import { spring, staticFile } from "remotion";

/*
 * The live site's tokens, from frontend/landing.css and DESIGN.md. Ember is
 * the only chromatic hue: no blue, no green, no red, no second accent. White
 * text never sits on an ember fill; that's what onEmber is for.
 */
export const C = {
  canvas: "#0B0B0D",
  surface: "#131316",
  surface2: "#191920",
  hairline: "#25252C",
  hairlineFirm: "#34343D",
  ink: "#F4F2EF",
  inkMuted: "#B7B4AE",
  inkSubtle: "#8A8781",
  ember: "#E2603A",
  emberInk: "#FF8A63",
  emberWash: "rgba(226, 96, 58, 0.10)",
  emberEdge: "rgba(226, 96, 58, 0.28)",
  onEmber: "#12100E",
} as const;

/** The mark's gradient, from the favicon. The logo only, nothing else. */
export const MARK_STOPS = [
  { offset: 0, color: "#F25C1E" },
  { offset: 0.52, color: "#FF8A3C" },
  { offset: 1, color: "#E8B54A" },
] as const;

export const TAGLINE_COLOR = "#FF8A3C";

export const RADIUS = { pill: 999, control: 12, panel: 16 } as const;

export const { fontFamily: SANS } = loadGeist("normal", {
  weights: ["400", "500", "600", "700"],
  subsets: ["latin"],
});

export const { fontFamily: MONO } = loadGeistMono("normal", {
  weights: ["400", "500"],
  subsets: ["latin"],
});

/*
 * The wordmark is Archivo at wdth 92 / wght 880, the brand kit's wordmark
 * instance. Google's loader only hands out fixed weights at normal width, so
 * the variable file is loaded directly and both axes are set on the text.
 * loadFont() holds the render until the file is in, so no frame goes out in a
 * fallback face.
 */
export const WORDMARK_FAMILY = "ClipForge Wordmark";
loadFont({
  family: WORDMARK_FAMILY,
  url: staticFile("fonts/Archivo-Variable.ttf"),
  weight: "100 900",
  stretch: "62% 125%",
});

export const WORDMARK_TYPE: React.CSSProperties = {
  fontFamily: WORDMARK_FAMILY,
  fontWeight: 880,
  fontStretch: "92%",
  fontVariationSettings: "'wdth' 92, 'wght' 880",
  textTransform: "uppercase",
  letterSpacing: "-0.035em",
  lineHeight: 0.82,
  whiteSpace: "nowrap",
};

type SpringConfig = NonNullable<Parameters<typeof spring>[0]["config"]>;

export const SPRING = {
  // The screenshot plane: settles without a bounce.
  plane: { damping: 200 },
  // Caption lines: snappy, with a touch of overshoot.
  text: { damping: 16, stiffness: 150 },
  cursor: { damping: 22, stiffness: 120 },
  // Slower than the plane, so a zoom reads as a camera move. About 0.8s.
  camera: { damping: 200, stiffness: 50 },
  // The spotlight gliding from one target to the next.
  spotlight: { damping: 200, stiffness: 120 },
  // Chips, badges and the spark: a visible overshoot.
  pop: { damping: 12, stiffness: 170 },
} satisfies Record<string, SpringConfig>;
