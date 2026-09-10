import { Audio } from "@remotion/media";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  Sequence,
  staticFile,
} from "remotion";
import { BackgroundTexture } from "./BackgroundTexture";
import { CUE } from "./cues";
import { EndCard } from "./EndCard";
import { BANNER_MOUNT, FeatureBanner } from "./FeatureBanner";
import { KineticHook } from "./KineticHook";
import { PHONES_MOUNT, PhoneStage } from "./PhoneStage";
import { STUDIO_MOUNT, StudioStage } from "./StudioStage";
import { BACKGROUND, fontFamily } from "./theme";

const TRACK = "Y2Mate.is - Best SaaS Product Launch Ad Video _ LangEase.mp3";

// Sat under the track rather than over it — the vocal carries the rhythm, so
// these only mark the frames the picture does something. Empty the array to
// hear the song on its own.
const SFX = [
  { src: "sfx-boom.mp3", from: CUE.find, volume: 0.4 },
  { src: "sfx-boom.mp3", from: CUE.cut, volume: 0.4 },
  { src: "sfx-boom.mp3", from: CUE.publish, volume: 0.45 },
  { src: "sfx-whoosh.mp3", from: CUE.flyOut - 8, volume: 0.38 },
  { src: "sfx-click.mp3", from: CUE.click, volume: 0.7 },
  { src: "sfx-riser.mp3", from: CUE.pushEnd - 96, volume: 0.3 },
  { src: "sfx-impact.mp3", from: CUE.pushEnd, volume: 0.5 },
];

// Order in the markup is paint order, not time order. The dashboard is
// mounted first so the phones fly out in front of it, and the hook last so it
// passes the lens in front of the phones rising up behind it. No scene
// dissolves into the next; every handover is a move in Z.
export const ClipForgeLaunchAd: React.FC = () => {
  return (
    <AbsoluteFill
      name="ClipForge launch ad"
      style={{ backgroundColor: BACKGROUND, fontFamily }}
    >
      <Audio
        src={staticFile(TRACK)}
        volume={(f) =>
          interpolate(f, [0, 10, 858, 898], [0, 1, 1, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.linear,
          })
        }
      />

      {SFX.map((sfx, index) => (
        <Audio key={index} src={staticFile(sfx.src)} from={sfx.from} volume={sfx.volume} />
      ))}

      <BackgroundTexture />

      <Sequence
        from={STUDIO_MOUNT}
        durationInFrames={450}
        name="3+5 — Studio stage"
      >
        <StudioStage />
      </Sequence>

      <Sequence
        from={PHONES_MOUNT}
        durationInFrames={315}
        name="2 — Phone stage"
      >
        <PhoneStage />
      </Sequence>

      <Sequence from={0} durationInFrames={120} name="1 — Kinetic hook">
        <KineticHook />
      </Sequence>

      <Sequence
        from={BANNER_MOUNT}
        durationInFrames={180}
        name="4 — Feature banner"
      >
        <FeatureBanner />
      </Sequence>

      <Sequence from={CUE.endCard} durationInFrames={180} name="6 — End card">
        <EndCard />
      </Sequence>

      <AbsoluteFill
        name="Vignette"
        style={{
          background:
            "radial-gradient(78% 72% at 50% 50%, rgba(0, 0, 0, 0) 40%, rgba(0, 0, 0, 0.5) 100%)",
        }}
      />
    </AbsoluteFill>
  );
};
