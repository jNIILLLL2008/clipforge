import React from "react";
import { MONO } from "../brand";
import type { PlaneLayout } from "../layout";
import { rectPx } from "../layout";
import type { Step } from "../steps";
import { zoomFoci } from "./Camera";

/*
 * A tuning overlay, off by default: a 10% grid labelled in percent, every
 * target's rect with its key, and every zoom's focus as a crosshair. Read a
 * position off the grid and type it into steps.ts.
 */
const LINE = "rgba(255, 255, 255, 0.28)";
const LABEL = "rgba(255, 255, 255, 0.85)";

export const Guides: React.FC<{ step: Step; plane: PlaneLayout }> = ({ step, plane }) => {
  const ticks: number[] = [];
  for (let i = 1; i < 10; i++) ticks.push(i / 10);
  const label: React.CSSProperties = {
    position: "absolute",
    fontFamily: MONO,
    fontSize: 12,
    color: LABEL,
    backgroundColor: "rgba(0, 0, 0, 0.6)",
    padding: "1px 4px",
    borderRadius: 3,
    whiteSpace: "nowrap",
  };

  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
      {ticks.map((t) => (
        <React.Fragment key={t}>
          <div style={{ position: "absolute", left: t * plane.W, top: 0, bottom: 0, width: 1, backgroundColor: LINE }} />
          <div style={{ position: "absolute", top: t * plane.H, left: 0, right: 0, height: 1, backgroundColor: LINE }} />
          <div style={{ ...label, left: t * plane.W + 3, top: 3 }}>{Math.round(t * 100)}</div>
          <div style={{ ...label, left: 3, top: t * plane.H + 3 }}>{Math.round(t * 100)}</div>
        </React.Fragment>
      ))}
      {Object.keys(step.targets).map((key) => {
        const box = rectPx(plane, step.targets[key].rect);
        return (
          <React.Fragment key={key}>
            <div
              style={{
                position: "absolute",
                left: box.x,
                top: box.y,
                width: box.w,
                height: box.h,
                outline: `1px dashed ${LABEL}`,
              }}
            />
            <div style={{ ...label, left: box.x, top: box.y + box.h + 3 }}>{key}</div>
          </React.Fragment>
        );
      })}
      {zoomFoci(step).map((focus, i) => (
        <React.Fragment key={i}>
          <div style={{ position: "absolute", left: focus.x * plane.W - 14, top: focus.y * plane.H, width: 28, height: 1, backgroundColor: LABEL }} />
          <div style={{ position: "absolute", left: focus.x * plane.W, top: focus.y * plane.H - 14, width: 1, height: 28, backgroundColor: LABEL }} />
          <div style={{ ...label, left: focus.x * plane.W + 8, top: focus.y * plane.H + 8 }}>
            zoom {focus.scale} @ {focus.x.toFixed(2)}, {focus.y.toFixed(2)}
          </div>
        </React.Fragment>
      ))}
    </div>
  );
};
