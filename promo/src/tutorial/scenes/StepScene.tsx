import React from "react";
import { AbsoluteFill } from "remotion";
import { z } from "zod";
import { Backdrop } from "../components/Backdrop";
import { Caption } from "../components/Caption";
import { StaticChrome } from "../components/Chrome";
import { ScreenshotPlane } from "../components/ScreenshotPlane";
import { planeLayout } from "../layout";
import { STEPS } from "../steps";

export const stepSceneSchema = z.object({
  step: z.number().int().min(1).max(7),
  /** Previewed on its own: draw the backdrop and the chrome, which the full video keeps outside the transitions. */
  standalone: z.boolean(),
  showGuides: z.boolean(),
});

/** One step of the walkthrough, entirely driven by its entry in steps.ts. */
export const StepScene: React.FC<z.infer<typeof stepSceneSchema>> = ({
  step,
  standalone,
  showGuides,
}) => {
  const config = STEPS[step - 1];
  const plane = planeLayout(config);

  return (
    <AbsoluteFill>
      {standalone ? <Backdrop /> : null}
      {standalone ? <StaticChrome index={step - 1} /> : null}
      <ScreenshotPlane step={config} plane={plane} showGuides={showGuides} />
      <Caption step={config} left={plane.captionLeft} />
    </AbsoluteFill>
  );
};
