import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { z } from "zod";
import { C, SANS, SPRING } from "../brand";
import { Backdrop } from "../components/Backdrop";
import { Lockup, lockupEntrance } from "../components/Lockup";
import { CLAMP, riseStyle } from "../motion";
import { sceneFrames } from "../timeline";

export const bookendSchema = z.object({
  /** Previewed on its own: draw the backdrop, which the full video keeps outside the transitions. */
  standalone: z.boolean(),
});

/**
 * The mark draws on and the spark strikes, the wordmark and tagline resolve,
 * then the title rises in under them. The whole group pushes in 3% over the
 * scene so it never sits dead still.
 */
export const Intro: React.FC<z.infer<typeof bookendSchema>> = ({ standalone }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const lockup = lockupEntrance(frame, fps, 5);
  const title = spring({ frame: frame - 46, fps, config: SPRING.text });
  const sub = spring({ frame: frame - 52, fps, config: SPRING.text });

  return (
    <AbsoluteFill>
      {standalone ? <Backdrop /> : null}
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            transform: `scale(${interpolate(frame, [0, sceneFrames("intro")], [1, 1.03], CLAMP)})`,
          }}
        >
          <Lockup size={132} tagline motion={lockup} />
          <div
            style={{
              marginTop: 92,
              fontFamily: SANS,
              fontWeight: 600,
              fontSize: 64,
              letterSpacing: "-0.02em",
              color: C.ink,
              ...riseStyle(title),
            }}
          >
            Connect your YouTube channel
          </div>
          <div
            style={{
              marginTop: 14,
              fontFamily: SANS,
              fontWeight: 400,
              fontSize: 30,
              color: C.inkMuted,
              ...riseStyle(sub),
            }}
          >
            Seven steps, about five minutes, done once.
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
