import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { z } from "zod";
import { C, MONO, SANS, SPRING } from "../../shared/brand";
import { Backdrop } from "../../shared/components/Backdrop";
import { Lockup, lockupEntrance } from "../../shared/components/Lockup";
import { CLAMP, riseStyle } from "../../shared/motion";
import { FPS, TRANSITION, sceneFrames } from "../timeline";

export const bookendSchema = z.object({
  /** Previewed on its own: draw the backdrop, which the full video keeps outside the transitions. */
  standalone: z.boolean(),
});

/**
 * The mark draws on and the spark strikes, the wordmark and tagline resolve,
 * then the title rises in under them. The group pushes in 3% over the scene.
 */
export const GuideIntro: React.FC<z.infer<typeof bookendSchema>> = ({ standalone }) => {
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
            Set up ClipForge
          </div>
          <div style={{ marginTop: 14, fontFamily: SANS, fontWeight: 400, fontSize: 30, color: C.inkMuted, ...riseStyle(sub) }}>
            Five steps, from download to your first video.
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/**
 * The lockup returns with the same draw-on once the last scene has blurred
 * away, then the sign-off. Everything settles by about 3s in, so the last
 * second holds still.
 */
export const GuideOutro: React.FC<z.infer<typeof bookendSchema>> = ({ standalone }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const start = TRANSITION;
  const lockup = lockupEntrance(frame, fps, start);
  const line = spring({ frame: frame - (start + 40), fps, config: SPRING.text });
  const url = spring({ frame: frame - (start + 46), fps, config: SPRING.text });

  return (
    <AbsoluteFill>
      {standalone ? <Backdrop holdFrom={sceneFrames("outro") - FPS} /> : null}
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <Lockup size={112} tagline motion={lockup} />
          <div
            style={{
              marginTop: 84,
              fontFamily: SANS,
              fontWeight: 600,
              fontSize: 56,
              letterSpacing: "-0.02em",
              color: C.ink,
              ...riseStyle(line),
            }}
          >
            You’re set up.
          </div>
          <div style={{ marginTop: 16, fontFamily: MONO, fontWeight: 500, fontSize: 30, color: C.emberInk, ...riseStyle(url) }}>
            clipforgee.app
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
