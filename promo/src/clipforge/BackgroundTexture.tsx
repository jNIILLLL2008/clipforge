import { AbsoluteFill, useCurrentFrame } from "remotion";
import { BACKGROUND, BACKGROUND_CORE } from "./theme";

// feTurbulence is seeded, so the same noise renders every frame. Left alone
// that reads as a dirty lens rather than grain, so the tile is walked around
// on a cheap pseudo-random offset instead of being regenerated.
const GRAIN =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220">' +
      '<filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="3" stitchTiles="stitch"/></filter>' +
      '<rect width="220" height="220" filter="url(#n)"/>' +
      "</svg>",
  );

export const BackgroundTexture: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill name="Backdrop">
      <AbsoluteFill
        name="Field"
        style={{
          background:
            "radial-gradient(62% 58% at 50% 46%, " +
            BACKGROUND_CORE +
            " 0%, " +
            BACKGROUND +
            " 72%)",
        }}
      />
      <AbsoluteFill
        name="Grain"
        style={{
          backgroundImage: "url(" + GRAIN + ")",
          backgroundRepeat: "repeat",
          backgroundPosition:
            ((frame * 71) % 220) + "px " + ((frame * 37) % 220) + "px",
          opacity: 0.03,
          mixBlendMode: "overlay",
        }}
      />
    </AbsoluteFill>
  );
};
