import { TransitionSeries, springTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import React from "react";
import { AbsoluteFill } from "remotion";
import { z } from "zod";
import { C } from "../shared/brand";
import { Backdrop } from "../shared/components/Backdrop";
import { blurAway, slideFade } from "../shared/presentations";
import { StepChrome } from "./components/Chrome";
import { Soundtrack } from "./components/Soundtrack";
import { Intro } from "./scenes/Intro";
import { Outro } from "./scenes/Outro";
import { StepScene } from "./scenes/StepScene";
import { FPS, TOTAL_FRAMES, TRANSITION, sceneFrames } from "./timeline";

export const tutorialSchema = z.object({
  /** A 10% grid, every target rect and every zoom focus over the screenshots. */
  showGuides: z.boolean(),
});

const timing = springTiming({ config: { damping: 200 }, durationInFrames: TRANSITION });

/*
 * The 60-second walkthrough of connecting a YouTube channel.
 *
 * The backdrop and the chrome (small lockup, stepper) sit outside the
 * TransitionSeries, so they hold still while the scenes slide and fade over
 * them, and so does the soundtrack. Every duration comes from timeline.ts,
 * and every sound from soundtrack.ts.
 */
export const YouTubeSetupTutorial: React.FC<z.infer<typeof tutorialSchema>> = ({
  showGuides,
}) => {
  return (
    <AbsoluteFill style={{ backgroundColor: C.canvas }}>
      <Backdrop holdFrom={TOTAL_FRAMES - FPS} />
      <TransitionSeries>
        <TransitionSeries.Sequence name="Intro" durationInFrames={sceneFrames("intro")}>
          <Intro standalone={false} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade({ shouldFadeOutExitingScene: true })}
          timing={timing}
        />
        <TransitionSeries.Sequence name="Step 1" durationInFrames={sceneFrames("step1")}>
          <StepScene step={1} standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slideFade()} timing={timing} />
        <TransitionSeries.Sequence name="Step 2" durationInFrames={sceneFrames("step2")}>
          <StepScene step={2} standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slideFade()} timing={timing} />
        <TransitionSeries.Sequence name="Step 3" durationInFrames={sceneFrames("step3")}>
          <StepScene step={3} standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slideFade()} timing={timing} />
        <TransitionSeries.Sequence name="Step 4" durationInFrames={sceneFrames("step4")}>
          <StepScene step={4} standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slideFade()} timing={timing} />
        <TransitionSeries.Sequence name="Step 5" durationInFrames={sceneFrames("step5")}>
          <StepScene step={5} standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slideFade()} timing={timing} />
        <TransitionSeries.Sequence name="Step 6" durationInFrames={sceneFrames("step6")}>
          <StepScene step={6} standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slideFade()} timing={timing} />
        <TransitionSeries.Sequence name="Step 7" durationInFrames={sceneFrames("step7")}>
          <StepScene step={7} standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={blurAway()} timing={timing} />
        <TransitionSeries.Sequence name="Outro" durationInFrames={sceneFrames("outro")}>
          <Outro standalone={false} />
        </TransitionSeries.Sequence>
      </TransitionSeries>
      <StepChrome />
      <Soundtrack />
    </AbsoluteFill>
  );
};
