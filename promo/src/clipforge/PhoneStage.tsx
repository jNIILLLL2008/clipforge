import { Video } from "@remotion/media";
import {
  AbsoluteFill,
  Easing,
  Interactive,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";
import { CUE } from "./cues";
import { fontFamily, PHONE_BEZEL, TEXT } from "./theme";

const PHONE_WIDTH = 380;
const PHONE_HEIGHT = 760;

// The scene is mounted 15 frames early, underneath the hook's exit, so the
// pair are already growing out of the depth by the time the hook has flown
// past the lens. Nothing cross-fades; the two moves overlap in Z.
export const PHONES_MOUNT = CUE.barFull;

const HERO = CUE.phonesHero - PHONES_MOUNT;
const FLY = CUE.flyOut - PHONES_MOUNT;
const GONE = CUE.phonesGone - PHONES_MOUNT;

const Phone: React.FC<{
  src: string;
  yaw: number;
  roll: number;
  exitX: number;
}> = ({ src, yaw, roll, exitX }) => {
  const frame = useCurrentFrame();

  return (
    <Interactive.Div
      name="Phone"
      style={{
        transformStyle: "preserve-3d",
        rotate: "y " + yaw + "deg",
        // Held in place for the showcase, then thrown outwards as the camera
        // comes through between them.
        translate: interpolate(
          frame,
          [FLY, GONE],
          ["0px 0px", exitX + "px 0px"],
          {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.in(Easing.quad),
          },
        ),
      }}
    >
      <Interactive.Div
        name="Roll"
        style={{
          position: "relative",
          width: PHONE_WIDTH,
          height: PHONE_HEIGHT,
          borderRadius: 48,
          overflow: "hidden",
          backgroundColor: "#000000",
          border: "6px solid " + PHONE_BEZEL,
          boxShadow:
            "0 30px 80px rgba(0, 0, 0, 0.9), inset 0 0 15px rgba(255, 255, 255, 0.1)",
          rotate: "z " + roll + "deg",
        }}
      >
        <Video
          src={staticFile(src)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
        {/* The same inset the box-shadow above asks for, on its own layer.
            An inset shadow paints under child content, so on the container it
            would sit behind the video and never be seen. */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: 42,
            boxShadow: "inset 0 0 15px rgba(255, 255, 255, 0.1)",
          }}
        />
      </Interactive.Div>
    </Interactive.Div>
  );
};

export const PhoneStage: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill name="Phone stage">
      <AbsoluteFill
        name="Glow"
        style={{
          background:
            "radial-gradient(56% 54% at 50% 54%, rgba(255, 91, 34, 0.2) 0%, rgba(255, 91, 34, 0) 70%)",
          opacity: interpolate(frame, [0, 26, FLY, GONE], [0, 1, 1, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.linear,
          }),
        }}
      />

      <AbsoluteFill
        name="Stage"
        style={{
          justifyContent: "center",
          alignItems: "center",
          paddingTop: 80,
          perspective: 1400,
        }}
      >
        {/* One continuous run on Z: out of the depth, hold, then straight
            past the camera. The dashboard rises through the same depth on the
            same frames, so the two scenes are handed off rather than cut. */}
        <Interactive.Div
          name="Camera"
          style={{
            display: "flex",
            gap: 90,
            transformStyle: "preserve-3d",
            translate: interpolate(
              frame,
              [0, HERO, FLY, GONE],
              [
                "0px 0px -1500px",
                "0px 0px 0px",
                "0px 0px 0px",
                "0px 0px 980px",
              ],
              {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: [
                  Easing.bezier(0.25, 1, 0.3, 1),
                  Easing.linear,
                  Easing.in(Easing.quad),
                ],
              },
            ),
          }}
        >
          <Phone src="clip-left.mp4" yaw={-18} roll={2} exitX={-600} />
          <Phone src="clip-right.mp4" yaw={18} roll={-2} exitX={600} />
        </Interactive.Div>
      </AbsoluteFill>

      <Interactive.Div
        name="Pill"
        style={{
          position: "absolute",
          top: 52,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          opacity: interpolate(
            frame,
            [16, 40, FLY - 26, FLY - 2],
            [0, 1, 1, 0],
            {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.linear,
            },
          ),
          translate: interpolate(frame, [16, 46], ["0px -120px", "0px 0px"], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.25, 1, 0.3, 1),
          }),
        }}
      >
        <div
          style={{
            fontFamily,
            fontSize: 60,
            fontWeight: 600,
            letterSpacing: "-0.02em",
            color: TEXT,
            padding: "22px 56px",
            borderRadius: 999,
            background: "rgba(255, 255, 255, 0.08)",
            backdropFilter: "blur(20px)",
            border: "1px solid rgba(255, 255, 255, 0.12)",
            boxShadow:
              "0 30px 90px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.16)",
            whiteSpace: "nowrap",
          }}
        >
          Want clips like this in one click?
        </div>
      </Interactive.Div>
    </AbsoluteFill>
  );
};
