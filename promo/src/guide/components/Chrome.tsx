import React from "react";
import { interpolate, interpolateColors, spring, useVideoConfig } from "remotion";
import { C, MONO, SANS, SPRING } from "../../shared/brand";
import { Lockup } from "../../shared/components/Lockup";
import { CLAMP, mix } from "../../shared/motion";
import type { ChecklistItem, StepSceneId } from "../guide";
import { CHECKLIST_ITEMS, PUBLISHED_AT, RAIL_STEPS, SCENES } from "../guide";
import { CHECKLIST, CHROME_Y, LOCKUP_X, RAIL_X } from "../layout";
import { TRANSITION, cutFrame, sec } from "../timeline";

/*
 * What stays on screen across scenes: the small lockup, the five-step rail
 * and, through the settings scenes, the checklist. It sits outside the
 * TransitionSeries so it holds still while scenes slide under it, and it is
 * drawn from the video's own frame, passed in, so a scene previewed on its
 * own shows exactly the chrome it has in the full video.
 */

const HALF = TRANSITION / 2;

/** Where each rail step begins: the cut into its first scene. */
const STEP_STARTS: readonly StepSceneId[] = ["agent", "ffmpeg", "pair", "niche", "youtube"];

// ---------------------------------------------------------------- rail --
const CHIP_W = 118;
const CHIP_H = 40;
const CHIP_GAP = 10;
const slot = (i: number) => i * (CHIP_W + CHIP_GAP);

const Tick: React.FC<{ size: number; colour: string; progress?: number }> = ({ size, colour, progress = 1 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" style={{ flex: "none" }}>
    <path
      d="M3 8.5 L6.5 12 L13 4.5"
      fill="none"
      stroke={colour}
      strokeWidth={2.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      pathLength={1}
      strokeDasharray="1 1"
      strokeDashoffset={1 - progress}
    />
  </svg>
);

/**
 * Five chips; the current one sits under an ember pill that stretches across
 * to the next chip when the step changes, leading edge first. A chip the
 * pill covers takes the on-ember ink; a finished one takes a tick.
 */
const Rail: React.FC<{ frame: number }> = ({ frame }) => {
  const { fps } = useVideoConfig();
  let lead = 0;
  let trail = 0;
  for (let i = 1; i < STEP_STARTS.length; i++) {
    const cut = cutFrame(STEP_STARTS[i]);
    lead += spring({ frame: frame - (cut - 4), fps, config: { damping: 200, stiffness: 220 } });
    trail += spring({ frame: frame - (cut + 1), fps, config: { damping: 200, stiffness: 150 } });
  }
  const pillLeft = slot(Math.min(lead, trail));
  const pillRight = slot(Math.max(lead, trail)) + CHIP_W;
  // A beat's global frame is its scene's cut plus its seconds.
  const published = cutFrame("publish") + sec(PUBLISHED_AT);

  return (
    <div style={{ position: "relative", width: slot(RAIL_STEPS.length - 1) + CHIP_W, height: CHIP_H }}>
      <div
        style={{
          position: "absolute",
          left: pillLeft,
          top: 0,
          width: pillRight - pillLeft,
          height: CHIP_H,
          borderRadius: 999,
          backgroundColor: C.ember,
          boxShadow: "0 8px 24px rgba(226, 96, 58, 0.3)",
        }}
      />
      {RAIL_STEPS.map((label, i) => {
        const left = slot(i);
        const covered = Math.max(0, Math.min(pillRight, left + CHIP_W) - Math.max(pillLeft, left)) / CHIP_W;
        const next = i + 1 < STEP_STARTS.length ? cutFrame(STEP_STARTS[i + 1]) : published;
        const done = spring({ frame: frame - (next + 2), fps, config: SPRING.pop });
        return (
          <div
            key={label}
            style={{
              position: "absolute",
              left,
              top: 0,
              width: CHIP_W,
              height: CHIP_H,
              boxSizing: "border-box",
              borderRadius: 999,
              boxShadow: `inset 0 0 0 1px ${C.hairlineFirm}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 7,
              fontFamily: SANS,
              fontWeight: 600,
              fontSize: 17,
              color: interpolateColors(covered, [0, 1], [done > 0.5 ? C.inkMuted : C.inkSubtle, C.onEmber]),
            }}
          >
            {done > 0.01 ? (
              <div style={{ width: 14 * Math.min(1, done), overflow: "hidden", display: "flex" }}>
                <Tick size={14} colour={covered > 0.5 ? C.onEmber : C.emberInk} progress={done} />
              </div>
            ) : null}
            {label}
          </div>
        );
      })}
    </div>
  );
};

// ----------------------------------------------------------- checklist --
/** Every tick in the settings scenes, as a global frame. */
const tickFrames = (): Record<ChecklistItem, number> => {
  const out = {} as Record<ChecklistItem, number>;
  for (const [id, scene] of Object.entries(SCENES) as [StepSceneId, (typeof SCENES)[StepSceneId]][]) {
    for (const tick of scene.ticks ?? []) out[tick.item] = cutFrame(id) + sec(tick.at);
  }
  return out;
};
const TICKS = tickFrames();

const Checklist: React.FC<{ frame: number }> = ({ frame }) => {
  const { fps } = useVideoConfig();
  return (
    <div
      style={{
        boxSizing: "border-box",
        width: CHECKLIST.width,
        padding: "26px 30px 22px",
        borderRadius: 16,
        backgroundColor: "rgba(19, 19, 22, 0.72)",
        backdropFilter: "blur(18px)",
        WebkitBackdropFilter: "blur(18px)",
        boxShadow: "inset 0 0 0 1px rgba(255, 255, 255, 0.06), 0 30px 80px rgba(0, 0, 0, 0.45)",
      }}
    >
      <div style={{ fontFamily: MONO, fontWeight: 500, fontSize: 16, letterSpacing: "0.14em", color: C.emberInk }}>
        SETTINGS THAT MATTER
      </div>
      <div style={{ marginTop: 14 }}>
        {CHECKLIST_ITEMS.map((item) => {
          const at = TICKS[item] ?? Infinity;
          const ticked = spring({ frame: frame - at, fps, config: SPRING.pop });
          return (
            <div key={item} style={{ display: "flex", alignItems: "center", gap: 14, height: 44 }}>
              <div
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: 999,
                  display: "grid",
                  placeItems: "center",
                  boxShadow: `inset 0 0 0 1.5px ${interpolateColors(ticked, [0, 1], [C.hairlineFirm, C.ember])}`,
                  backgroundColor: `rgba(226, 96, 58, ${interpolate(ticked, [0, 1], [0, 1], CLAMP)})`,
                  transform: `scale(${mix(1, 1.08, Math.sin(Math.min(1, ticked) * Math.PI))})`,
                }}
              >
                {ticked > 0.01 ? <Tick size={15} colour={C.onEmber} progress={Math.min(1, ticked)} /> : null}
              </div>
              <div
                style={{
                  fontFamily: SANS,
                  fontWeight: 500,
                  fontSize: 22,
                  color: interpolateColors(ticked, [0, 1], [C.inkMuted, C.ink]),
                }}
              >
                {item}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------- all --
export const GuideChrome: React.FC<{ frame: number }> = ({ frame }) => {
  const first = cutFrame("agent");
  const out = cutFrame("outro");
  const opacity = interpolate(frame, [first - HALF, first + HALF, out - HALF, out + HALF], [0, 1, 1, 0], CLAMP);
  const settingsIn = cutFrame("niche");
  const settingsOut = cutFrame("youtube");
  const checklist = interpolate(
    frame,
    [settingsIn - HALF, settingsIn + HALF, settingsOut - HALF, settingsOut + HALF],
    [0, 1, 1, 0],
    CLAMP,
  );
  if (opacity <= 0) return null;

  return (
    <>
      <div style={{ position: "absolute", left: LOCKUP_X, top: CHROME_Y, transform: "translateY(-50%)", opacity: opacity * 0.7 }}>
        <Lockup size={26} tone="ink" />
      </div>
      <div style={{ position: "absolute", left: RAIL_X, top: CHROME_Y, transform: "translate(-50%, -50%)", opacity }}>
        <Rail frame={frame} />
      </div>
      {checklist > 0 ? (
        <div
          style={{
            position: "absolute",
            left: CHECKLIST.left,
            top: CHECKLIST.top,
            opacity: checklist,
            transform: `translateX(${(1 - checklist) * -24}px)`,
          }}
        >
          <Checklist frame={frame} />
        </div>
      ) : null}
    </>
  );
};
