import { fitText } from "@remotion/layout-utils";
import {
  AbsoluteFill,
  Easing,
  Interactive,
  interpolate,
  Sequence,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CUE } from "./cues";
import { ACCENT, displayFont, TEXT } from "./theme";

// Every word is sized to fill the same 80% of the frame, so the three of them
// punch through one window instead of being three different widths.
const TARGET_WIDTH = 1920 * 0.8;
const TRACKING = "-0.04em";

const Word: React.FC<{ text: string; stroked?: boolean }> = ({
  text,
  stroked,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const { fontSize } = fitText({
    text,
    withinWidth: TARGET_WIDTH,
    fontFamily: displayFont,
    fontWeight: 900,
    letterSpacing: TRACKING,
  });

  return (
    <div style={{ transformOrigin: "center" }}>
      <Interactive.Div
        name={text}
        style={{
          fontFamily: displayFont,
          fontSize,
          fontWeight: 900,
          letterSpacing: TRACKING,
          lineHeight: 1,
          color: TEXT,
          whiteSpace: "nowrap",
          transformOrigin: "center",
          WebkitTextStroke: stroked ? "2px " + ACCENT : undefined,
          textShadow: stroked
            ? "0 0 70px rgba(255, 91, 34, 0.6)"
            : "0 0 90px rgba(255, 91, 34, 0.16)",
          // No fade in either direction. The word is at full strength on the
          // frame it mounts and gone on the frame it unmounts; the spring is
          // the only easing in the scene.
          scale: spring({
            frame,
            fps,
            config: { stiffness: 200, damping: 12 },
            from: 0.8,
            to: 1,
          }),
        }}
      >
        {text}
      </Interactive.Div>
    </div>
  );
};

export const KineticHook: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill name="Kinetic hook" style={{ perspective: 1400 }}>
      {/* The hook does not dissolve into the next scene, it leaves through
          the camera: the whole group accelerates past the lens on Z while the
          phones are arriving out of the depth behind it. */}
      <Interactive.Div
        name="Camera"
        style={{
          position: "absolute",
          inset: 0,
          transformStyle: "preserve-3d",
          transformOrigin: "center",
          translate: interpolate(
            frame,
            [CUE.barFull, CUE.hookOut],
            ["0px 0px 0px", "0px 0px 900px"],
            {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.in(Easing.quad),
            },
          ),
        }}
      >
        <AbsoluteFill
          name="Words"
          style={{ justifyContent: "center", alignItems: "center" }}
        >
          <Sequence
            from={CUE.find}
            durationInFrames={CUE.cut - CUE.find}
            name="FIND."
            layout="none"
          >
            <Word text="FIND." />
          </Sequence>
          <Sequence
            from={CUE.cut}
            durationInFrames={CUE.publish - CUE.cut}
            name="CUT."
            layout="none"
          >
            <Word text="CUT." stroked />
          </Sequence>
          {/* Held to the end of the scene rather than to frame 105, so the
              camera has something to fly past on the way out. */}
          <Sequence
            from={CUE.publish}
            durationInFrames={CUE.hookOut - CUE.publish}
            name="PUBLISH."
            layout="none"
          >
            <Word text="PUBLISH." />
          </Sequence>
        </AbsoluteFill>

        <Interactive.Div
          name="Progress"
          style={{
            position: "absolute",
            bottom: 150,
            left: "50%",
            width: 1152,
            marginLeft: -576,
            height: 4,
            borderRadius: 2,
            backgroundColor: "rgba(255, 255, 255, 0.08)",
            overflow: "hidden",
          }}
        >
          <Interactive.Div
            name="Fill"
            style={{
              height: "100%",
              borderRadius: 2,
              backgroundColor: ACCENT,
              boxShadow: "0 0 28px rgba(255, 91, 34, 0.8)",
              width: interpolate(
                frame,
                [CUE.find, CUE.barFull],
                ["0%", "100%"],
                {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                  easing: Easing.linear,
                },
              ),
            }}
          />
        </Interactive.Div>
      </Interactive.Div>
    </AbsoluteFill>
  );
};
