import {
  AbsoluteFill,
  Easing,
  Interactive,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { CUE } from "./cues";
import { ACCENT, fontFamily, TEXT } from "./theme";

// Everything is in place by here and nothing moves again — the only thing
// still changing after this frame is the light coming off the button.
const STILL = CUE.lockupStill - CUE.endCard;

export const EndCard: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill name="End card">
      <AbsoluteFill
        name="Glow"
        style={{
          background:
            "radial-gradient(46% 40% at 50% 46%, rgba(255, 91, 34, 0.18) 0%, rgba(255, 91, 34, 0) 70%)",
          opacity: interpolate(frame, [0, STILL], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.linear,
          }),
        }}
      />

      <AbsoluteFill
        name="Lockup"
        style={{
          justifyContent: "center",
          alignItems: "center",
          gap: 76,
          paddingBottom: 60,
        }}
      >
        <Interactive.Div
          name="Logo"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 44,
            fontFamily,
            fontSize: 152,
            fontWeight: 700,
            letterSpacing: "-0.035em",
            color: TEXT,
            transformOrigin: "center",
            opacity: interpolate(frame, [0, 18], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.linear,
            }),
            scale: interpolate(frame, [0, 26], [0.94, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.bezier(0.25, 1, 0.3, 1),
              output: "perceptual-scale",
            }),
          }}
        >
          {/* A square standing on its corner, not a glyph — so it keeps the
              brand mark's exact proportions at any size. */}
          <Interactive.Div
            name="Diamond"
            style={{
              width: 86,
              height: 86,
              borderRadius: 12,
              backgroundColor: ACCENT,
              boxShadow: "0 0 50px rgba(255, 91, 34, 0.7)",
              transformOrigin: "center",
              rotate: "45deg",
            }}
          />
          ClipForge
        </Interactive.Div>

        <Interactive.Div
          name="CTA"
          style={{
            fontFamily,
            fontSize: 62,
            fontWeight: 700,
            letterSpacing: "-0.01em",
            color: ACCENT,
            backgroundColor: "rgba(255, 91, 34, 0.06)",
            border: "2px solid " + ACCENT,
            padding: "28px 76px",
            borderRadius: 999,
            transformOrigin: "center",
            // A one-second breath. Nothing in the layout moves with it, so
            // the lockup still reads as held from CUE.lockupStill onwards.
            boxShadow:
              "0 0 " +
              (12 + 12 * Math.sin((frame / 60) * Math.PI * 2)) +
              "px " +
              ACCENT,
            opacity: interpolate(frame, [8, 24], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.linear,
            }),
            scale: interpolate(frame, [8, 28], [0.94, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.bezier(0.25, 1, 0.3, 1),
              output: "perceptual-scale",
            }),
          }}
        >
          [ Start free ]
        </Interactive.Div>
      </AbsoluteFill>

      <Interactive.Div
        name="Domain"
        style={{
          position: "absolute",
          bottom: 108,
          left: 0,
          right: 0,
          textAlign: "center",
          fontFamily,
          fontSize: 52,
          fontWeight: 500,
          letterSpacing: "0.34em",
          color: "rgba(255, 255, 255, 0.74)",
          opacity: interpolate(frame, [14, STILL], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.linear,
          }),
        }}
      >
        clipforgee.app
      </Interactive.Div>
    </AbsoluteFill>
  );
};
