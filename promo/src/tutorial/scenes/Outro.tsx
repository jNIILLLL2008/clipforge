import React from "react";
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { z } from "zod";
import { C, MONO, SANS, SPRING } from "../../shared/brand";
import { Backdrop } from "../../shared/components/Backdrop";
import { Lockup, lockupEntrance } from "../../shared/components/Lockup";
import { riseStyle } from "../../shared/motion";
import { FPS, TRANSITION, sceneFrames } from "../timeline";
import type { bookendSchema } from "./Intro";

/**
 * The lockup returns with the same draw-on once the last step has blurred
 * away, then the sign-off. Everything has settled by about 3s in, so the last
 * second holds still.
 */
export const Outro: React.FC<z.infer<typeof bookendSchema>> = ({ standalone }) => {
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
            You’re ready to publish.
          </div>
          <div
            style={{
              marginTop: 16,
              fontFamily: MONO,
              fontWeight: 500,
              fontSize: 30,
              color: C.emberInk,
              ...riseStyle(url),
            }}
          >
            clipforgee.app
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
