import {
  AbsoluteFill,
  Easing,
  Interactive,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { CUE } from "./cues";
import { ACCENT, fontFamily, TEXT } from "./theme";

export const BANNER_MOUNT = CUE.cursorIn;

const IN = CUE.banner - BANNER_MOUNT;
const OUT = CUE.bannerOut - BANNER_MOUNT;

export const FeatureBanner: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill name="Feature banner" style={{ perspective: 1400 }}>
      <Interactive.Div
        name="Banner"
        style={{
          position: "absolute",
          top: 78,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          transformStyle: "preserve-3d",
          transformOrigin: "center top",
          opacity: interpolate(frame, [IN, IN + 10, OUT, OUT + 16], [0, 1, 1, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.linear,
          }),
          // Swings down out of the ceiling of the frame rather than fading up.
          translate: interpolate(
            frame,
            [IN, IN + 26, OUT, OUT + 16],
            ["0px -190px", "0px 0px", "0px 0px", "0px -150px"],
            {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: [
                Easing.bezier(0.16, 1, 0.3, 1),
                Easing.linear,
                Easing.in(Easing.quad),
              ],
            },
          ),
          rotate: interpolate(
            frame,
            [IN, IN + 26],
            ["x -34deg", "x 0deg"],
            {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.bezier(0.16, 1, 0.3, 1),
            },
          ),
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 26,
            fontFamily,
            fontSize: 76,
            fontWeight: 700,
            letterSpacing: "-0.03em",
            padding: "30px 72px",
            borderRadius: 26,
            background: "rgba(13, 13, 14, 0.85)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
            backdropFilter: "blur(14px)",
            boxShadow: "0 40px 110px rgba(0, 0, 0, 0.75)",
            whiteSpace: "nowrap",
          }}
        >
          <span style={{ color: TEXT }}>Any source.</span>
          <span style={{ color: ACCENT }}>Fully automated.</span>
        </div>
      </Interactive.Div>
    </AbsoluteFill>
  );
};
