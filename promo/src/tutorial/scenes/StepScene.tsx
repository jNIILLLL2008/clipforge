import React from "react";
import { AbsoluteFill } from "remotion";
import { z } from "zod";
import { BeatClock } from "../../shared/clock";
import { Backdrop } from "../../shared/components/Backdrop";
import { Caption } from "../../shared/components/Caption";
import { ScreenshotPlane } from "../../shared/components/ScreenshotPlane";
import { StaticChrome } from "../components/Chrome";
import { CAPTION_BOTTOM, CAPTION_WIDTH, planeLayout } from "../layout";
import { CARD_CSS_RADIUS, STEPS, TOTAL_STEPS } from "../steps";
import { windowFrame } from "../timeline";

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
      {/* A beat's seconds count from this step's window opening. */}
      <BeatClock.Provider value={(seconds) => windowFrame(config.id, seconds)}>
        <ScreenshotPlane
          shot={config}
          plane={plane}
          showGuides={showGuides}
          radius={CARD_CSS_RADIUS * plane.k}
        />
        <Caption
          left={plane.captionLeft}
          bottom={CAPTION_BOTTOM}
          width={CAPTION_WIDTH}
          eyebrow={
            <>
              STEP {config.n} OF {TOTAL_STEPS}
            </>
          }
          headline={config.headline}
          sub={config.sub}
          subLater={config.subLater}
          callout={config.callout}
        />
      </BeatClock.Provider>
    </AbsoluteFill>
  );
};
