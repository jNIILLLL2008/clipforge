import { TransitionSeries, springTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { z } from "zod";
import { C } from "../shared/brand";
import { Backdrop } from "../shared/components/Backdrop";
import { blurAway, scroll, slideFade } from "../shared/presentations";
import { GuideChrome } from "./components/Chrome";
import { Soundtrack } from "./components/Soundtrack";
import { GuideIntro, GuideOutro } from "./scenes/Bookends";
import { GuideScene } from "./scenes/GuideScene";
import { FPS, TOTAL_FRAMES, TRANSITION, sceneFrames } from "./timeline";

export const guideSchema = z.object({
  /** A 10% grid, every target rect and every zoom focus over the screenshots. */
  showGuides: z.boolean(),
});

const timing = springTiming({ config: { damping: 200 }, durationInFrames: TRANSITION });

/*
 * The two-minute setup guide: the render agent, ffmpeg, pairing, the settings
 * that matter, then connect and publish.
 *
 * The backdrop and the chrome (small lockup, step rail, settings checklist)
 * sit outside the TransitionSeries, so they hold still while the scenes move
 * under them. Between scenes: a slide for a new place, a scroll between parts
 * of the Settings page, and a dissolve between scenes on one screenshot, which
 * guide.ts keeps identical across the cut so only the caption changes. Every
 * duration comes from timeline.ts, every beat from guide.ts.
 */
export const ClipForgeSetupGuide: React.FC<z.infer<typeof guideSchema>> = ({ showGuides }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: C.canvas }}>
      <Backdrop holdFrom={TOTAL_FRAMES - FPS} />
      <TransitionSeries>
        <TransitionSeries.Sequence name="Intro" durationInFrames={sceneFrames("intro")}>
          <GuideIntro standalone={false} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade({ shouldFadeOutExitingScene: true })} timing={timing} />
        <TransitionSeries.Sequence name="Agent" durationInFrames={sceneFrames("agent")}>
          <GuideScene scene="agent" standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slideFade()} timing={timing} />
        <TransitionSeries.Sequence name="ffmpeg" durationInFrames={sceneFrames("ffmpeg")}>
          <GuideScene scene="ffmpeg" standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slideFade()} timing={timing} />
        <TransitionSeries.Sequence name="Pair" durationInFrames={sceneFrames("pair")}>
          <GuideScene scene="pair" standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slideFade()} timing={timing} />
        <TransitionSeries.Sequence name="Niche" durationInFrames={sceneFrames("niche")}>
          <GuideScene scene="niche" standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={timing} />
        <TransitionSeries.Sequence name="Banner" durationInFrames={sceneFrames("banner")}>
          <GuideScene scene="banner" standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={timing} />
        <TransitionSeries.Sequence name="Sources" durationInFrames={sceneFrames("sources")}>
          <GuideScene scene="sources" standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={scroll("down")} timing={timing} />
        <TransitionSeries.Sequence name="Long form" durationInFrames={sceneFrames("longform")}>
          <GuideScene scene="longform" standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={scroll("up")} timing={timing} />
        <TransitionSeries.Sequence name="Show filter" durationInFrames={sceneFrames("showfilter")}>
          <GuideScene scene="showfilter" standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slideFade()} timing={timing} />
        <TransitionSeries.Sequence name="YouTube" durationInFrames={sceneFrames("youtube")}>
          <GuideScene scene="youtube" standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={timing} />
        <TransitionSeries.Sequence name="Publish" durationInFrames={sceneFrames("publish")}>
          <GuideScene scene="publish" standalone={false} showGuides={showGuides} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={blurAway()} timing={timing} />
        <TransitionSeries.Sequence name="Outro" durationInFrames={sceneFrames("outro")}>
          <GuideOutro standalone={false} />
        </TransitionSeries.Sequence>
      </TransitionSeries>
      <GuideChrome frame={frame} />
      <Soundtrack />
    </AbsoluteFill>
  );
};
