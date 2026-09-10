import {
  AbsoluteFill,
  CanvasImage,
  Easing,
  Interactive,
  interpolate,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CUE } from "./cues";
import {
  ACCENT,
  BACKGROUND,
  BUTTON_FILL,
  BUTTON_LABEL,
  BUTTON_ORIGIN,
  BUTTON_RECT,
  fontFamily,
  PANEL_BG,
  PLANE_HEIGHT,
  PLANE_PERSPECTIVE,
  PLANE_ROLL,
  PLANE_TILT,
  PLANE_WIDTH,
  PUBLISH_BUTTON,
  STATUS_ROW,
  STATUS_ROWS,
} from "./theme";

// The scene is mounted at CUE.dashboardIn, so every cue is rebased onto its
// own clock here and nowhere else.
export const STUDIO_MOUNT = CUE.dashboardIn;

const SETTLED = CUE.dashboardSettled - STUDIO_MOUNT;
const CURSOR_IN = CUE.cursorIn - STUDIO_MOUNT;
const CLICK = CUE.click - STUDIO_MOUNT;
const PUSH = CUE.pushStart - STUDIO_MOUNT;
const PUSH_END = CUE.pushEnd - STUDIO_MOUNT;

const BUTTON_X = PUBLISH_BUTTON.x * PLANE_WIDTH;
const BUTTON_Y = PUBLISH_BUTTON.y * PLANE_HEIGHT;
const BUTTON_W = BUTTON_RECT.width * PLANE_WIDTH;
const BUTTON_H = BUTTON_RECT.height * PLANE_HEIGHT;

// The plane is laid out centred, so this is how far the button sits from the
// middle of the frame. The dive walks it to the centre of the screen on the
// way in, so the camera goes through the button and out the middle of the
// lens rather than off to one side.
const DX = Math.round(PLANE_WIDTH / 2 - BUTTON_X);
const DY = Math.round(PLANE_HEIGHT / 2 - BUTTON_Y);

const Cursor: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <Interactive.Div
      name="Cursor"
      style={{
        position: "absolute",
        width: 38,
        height: 55,
        left: interpolate(frame, [CURSOR_IN, CLICK], [1520, BUTTON_X - 6], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.bezier(0.16, 1, 0.3, 1),
        }),
        top: interpolate(frame, [CURSOR_IN, CLICK], [900, BUTTON_Y - 8], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.bezier(0.16, 1, 0.3, 1),
        }),
        // A real hand does not arrive square to the target.
        rotate: interpolate(frame, [CURSOR_IN, CLICK], ["-5deg", "0deg"], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.bezier(0.33, 1, 0.68, 1),
        }),
        opacity: interpolate(
          frame,
          [CURSOR_IN - 12, CURSOR_IN, CLICK + 80, CLICK + 96],
          [0, 1, 1, 0],
          {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.linear,
          },
        ),
        // Down to 0.85 on the click frame, held for eight frames, released.
        scale: interpolate(
          frame,
          [CLICK - 1, CLICK, CLICK + 8, CLICK + 11],
          [1, 0.85, 0.85, 1],
          {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.linear,
          },
        ),
        transformOrigin: "top left",
        filter: "drop-shadow(0 5px 12px rgba(0, 0, 0, 0.8))",
      }}
    >
      <svg width="38" height="55" viewBox="0 0 18 26" fill="none">
        <path
          d="M2.4 1.4 L2.4 20.9 L7.3 16.4 L10.4 23.9 L13.3 22.6 L10.3 15.4 L16.2 15.0 Z"
          fill="#FAFAFA"
          stroke="#0D0D0E"
          strokeWidth="1"
          strokeLinejoin="round"
        />
      </svg>
    </Interactive.Div>
  );
};

// A live Publish now button drawn over the screenshot's baked one, so it can
// physically depress under the cursor — and so the camera has something
// crisp to fly through rather than a fifty-times magnified screenshot.
const PublishButton: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <>
      {/* Hides the printed button underneath, so none of it peeks out from
          behind this one while it is depressed. */}
      <div
        style={{
          position: "absolute",
          left: BUTTON_X - BUTTON_W / 2 - 5,
          top: BUTTON_Y - BUTTON_H / 2 - 5,
          width: BUTTON_W + 10,
          height: BUTTON_H + 10,
          backgroundColor: PANEL_BG,
        }}
      />

      <Interactive.Div
        name="Publish now"
        style={{
          position: "absolute",
          left: BUTTON_X - BUTTON_W / 2,
          top: BUTTON_Y - BUTTON_H / 2,
          width: BUTTON_W,
          height: BUTTON_H,
          borderRadius: 12,
          backgroundColor: BUTTON_FILL,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily,
          fontSize: 16,
          fontWeight: 600,
          color: BUTTON_LABEL,
          boxShadow:
            "0 0 " +
            interpolate(frame, [PUSH - 20, PUSH_END], [0, 120], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.linear,
            }) +
            "px rgba(255, 91, 34, 0.9)",
          scale:
            frame < CLICK
              ? 1
              : spring({
                  frame: frame - CLICK,
                  fps,
                  config: { mass: 0.55, damping: 10, stiffness: 240 },
                  from: 0.8,
                  to: 1,
                }),
        }}
      >
        <span
          style={{
            opacity: interpolate(frame, [PUSH - 18, PUSH - 4], [1, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.linear,
            }),
          }}
        >
          Publish now
        </span>

        {/* Goes hot as the camera commits to it. */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: 12,
            backgroundColor: ACCENT,
            opacity: interpolate(frame, [PUSH - 18, PUSH], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.linear,
            }),
          }}
        />

        {/* And then opens. This is what lets the dive end on the void rather
            than on a full-frame orange card: by the time the button is big
            enough to fill the screen its middle is already #0D0D0E, so the
            camera passes through a ring of light into black. */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: 12,
            background:
              "radial-gradient(ellipse 58% 88% at 50% 50%, " +
              BACKGROUND +
              " 0%, " +
              BACKGROUND +
              " 44%, rgba(13, 13, 14, 0) 78%)",
            opacity: interpolate(frame, [PUSH + 4, PUSH + 16], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.linear,
            }),
          }}
        />
      </Interactive.Div>
    </>
  );
};

// The shockwave the click throws off. It lives inside the dashboard plane so
// it sits on the button in the plane's own 3D space.
const PublishRipple: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <Interactive.Div
      name="Ripple"
      style={{
        position: "absolute",
        left: BUTTON_X - 70,
        top: BUTTON_Y - 70,
        width: 140,
        height: 140,
        borderRadius: "50%",
        border: "3px solid " + ACCENT,
        opacity: interpolate(frame, [0, 30], [1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.bezier(0.4, 0, 1, 1),
        }),
        scale: interpolate(frame, [0, 30], [1, 14], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.bezier(0.16, 1, 0.3, 1),
          output: "perceptual-scale",
        }),
      }}
    />
  );
};

// The pipeline reporting for duty: each status row lights up in turn once the
// button has been pressed.
const StatusCascade: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <>
      {STATUS_ROWS.map((row, index) => (
        <Interactive.Div
          key={row.top}
          name={"Row " + (index + 1)}
          style={{
            position: "absolute",
            left: STATUS_ROW.left * PLANE_WIDTH,
            top: row.top * PLANE_HEIGHT,
            width: STATUS_ROW.width * PLANE_WIDTH,
            height: STATUS_ROW.height * PLANE_HEIGHT,
            borderRadius: 12,
            border: "1.5px solid " + ACCENT,
            backgroundColor: "rgba(255, 91, 34, 0.1)",
            boxShadow: "0 0 34px rgba(255, 91, 34, 0.35)",
            opacity: interpolate(
              frame,
              [index * 7, index * 7 + 8, index * 7 + 46, index * 7 + 62],
              [0, 1, 1, 0],
              {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: Easing.linear,
              },
            ),
            scale: spring({
              frame: frame - index * 7,
              fps,
              config: { mass: 0.4, damping: 11, stiffness: 180 },
              from: 0.9,
              to: 1,
            }),
          }}
        />
      ))}
    </>
  );
};

export const StudioStage: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill name="Studio stage">
      <AbsoluteFill
        name="Stage"
        style={{
          justifyContent: "center",
          alignItems: "center",
          perspective: PLANE_PERSPECTIVE,
        }}
      >
        {/* The transform origin is the Publish now button. Everything that
            happens to this element — the roll, the arrival, the fifty-times
            dive — pivots on the pixel the cursor is about to press. */}
        <Interactive.Div
          name="Plane"
          style={{
            position: "relative",
            width: PLANE_WIDTH,
            height: PLANE_HEIGHT,
            transformOrigin: BUTTON_ORIGIN,
            transformStyle: "preserve-3d",
            rotate: "z " + PLANE_ROLL,
            opacity: interpolate(frame, [PUSH_END - 6, PUSH_END], [1, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.linear,
            }),
            // Rises out of the same depth the phones are leaving through, is
            // locked off, then goes through the lens.
            translate: interpolate(
              frame,
              [0, SETTLED, PUSH, PUSH_END],
              [
                "0px 0px -1500px",
                "0px 0px 0px",
                "0px 0px 0px",
                DX + "px " + DY + "px 0px",
              ],
              {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: [
                  Easing.bezier(0.25, 1, 0.3, 1),
                  Easing.linear,
                  Easing.in(Easing.exp),
                ],
              },
            ),
            scale: interpolate(frame, [PUSH, PUSH_END], [1, 50], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.in(Easing.exp),
            }),
          }}
        >
          <Interactive.Div
            name="Tilt"
            style={{
              position: "absolute",
              inset: 0,
              transformOrigin: BUTTON_ORIGIN,
              transformStyle: "preserve-3d",
              boxShadow:
                "0 60px 160px rgba(0, 0, 0, 0.7), 0 0 90px rgba(255, 91, 34, 0.12)",
              rotate: "x " + PLANE_TILT,
            }}
          >
            {/* Dropped before the plane gets big enough to magnify a
                1460px-wide screenshot into mush. */}
            <Interactive.Div
              name="Surface"
              style={{
                position: "absolute",
                inset: 0,
                overflow: "hidden",
                opacity: interpolate(frame, [PUSH + 4, PUSH + 18], [1, 0], {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                  easing: Easing.linear,
                }),
              }}
            >
              <CanvasImage
                src={staticFile("studio.png")}
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
            </Interactive.Div>

            <Sequence
              from={CLICK + 10}
              durationInFrames={90}
              name="Status cascade"
              layout="none"
            >
              <StatusCascade />
            </Sequence>

            <PublishButton />

            <Sequence
              from={CLICK}
              durationInFrames={34}
              name="Ripple"
              layout="none"
            >
              <PublishRipple />
            </Sequence>

            <Cursor />
          </Interactive.Div>
        </Interactive.Div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
