import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C } from "../../shared/brand";
import { Lockup } from "../../shared/components/Lockup";
import { CLAMP } from "../../shared/motion";
import { CAPTION_LEFT, CHROME_Y, STEPPER_X } from "../layout";
import { TOTAL_STEPS } from "../steps";
import { TRANSITION, cutFrame } from "../timeline";
import type { SceneId } from "../timeline";

/*
 * The modal's own stepper, scaled up: small dots, and the current one an
 * elongated ember pill. On each change the pill's leading edge runs to the
 * next dot first and the trailing edge follows, so it stretches across rather
 * than jumping.
 *
 * `lead` and `trail` are slot positions (0 is the first dot), fractional while
 * the pill is moving.
 */
const DOT = 10;
const GAP = 14;
const PILL_PAD = 8;

const Stepper: React.FC<{ lead: number; trail: number }> = ({ lead, trail }) => {
  const slot = (i: number) => i * (DOT + GAP);
  const left = Math.min(slot(lead), slot(trail)) - PILL_PAD;
  const right = Math.max(slot(lead), slot(trail)) + DOT + PILL_PAD;
  const dots: number[] = [];
  for (let i = 0; i < TOTAL_STEPS; i++) dots.push(i);

  return (
    <div style={{ position: "relative", width: slot(TOTAL_STEPS - 1) + DOT, height: DOT }}>
      {dots.map((i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: slot(i),
            top: 0,
            width: DOT,
            height: DOT,
            borderRadius: 999,
            backgroundColor: C.inkSubtle,
            opacity: 0.4,
          }}
        />
      ))}
      <div
        style={{
          position: "absolute",
          left,
          top: 0,
          width: right - left,
          height: DOT,
          borderRadius: 999,
          backgroundColor: C.ember,
        }}
      />
    </div>
  );
};

const ChromeLayout: React.FC<{ lead: number; trail: number; opacity: number }> = ({
  lead,
  trail,
  opacity,
}) => (
  <>
    <div
      style={{
        position: "absolute",
        left: CAPTION_LEFT,
        top: CHROME_Y,
        transform: "translateY(-50%)",
        opacity: opacity * 0.7,
      }}
    >
      <Lockup size={26} tone="ink" />
    </div>
    <div
      style={{
        position: "absolute",
        left: STEPPER_X,
        top: CHROME_Y,
        transform: "translate(-50%, -50%)",
        opacity,
      }}
    >
      <Stepper lead={lead} trail={trail} />
    </div>
  </>
);

/** For a step previewed on its own: the chrome at rest on that step. */
export const StaticChrome: React.FC<{ index: number }> = ({ index }) => (
  <ChromeLayout lead={index} trail={index} opacity={1} />
);

const STEP_IDS: readonly SceneId[] = ["step1", "step2", "step3", "step4", "step5", "step6", "step7"];

/**
 * For the full video: sits above every scene, so it stays put through the
 * transitions instead of sliding with them. Fades in at the cut into step 1,
 * out at the cut into the outro.
 */
export const StepChrome: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const half = TRANSITION / 2;
  const first = cutFrame("step1");
  const out = cutFrame("outro");

  const opacity = interpolate(
    frame,
    [first - half, first + half, out - half, out + half],
    [0, 1, 1, 0],
    CLAMP,
  );
  if (opacity <= 0) {
    return null;
  }

  let lead = 0;
  let trail = 0;
  for (let i = 1; i < STEP_IDS.length; i++) {
    const cut = cutFrame(STEP_IDS[i]);
    lead += spring({ frame: frame - (cut - 4), fps, config: { damping: 200, stiffness: 220 } });
    trail += spring({ frame: frame - (cut + 1), fps, config: { damping: 200, stiffness: 150 } });
  }

  return <ChromeLayout lead={lead} trail={trail} opacity={opacity} />;
};
