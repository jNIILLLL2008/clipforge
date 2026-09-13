import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { z } from "zod";
import { BeatClock, useBeatFrame } from "../../shared/clock";
import { Backdrop } from "../../shared/components/Backdrop";
import { Caption } from "../../shared/components/Caption";
import { ScreenshotPlane } from "../../shared/components/ScreenshotPlane";
import { CLAMP } from "../../shared/motion";
import { CAPTURES } from "../captures";
import { GuideChrome } from "../components/Chrome";
import { InsetView } from "../components/Inset";
import { MatchConnector, PairTerminal } from "../components/PairTerminal";
import { WhyCard } from "../components/WhyCard";
import type { Segment, StepSceneId } from "../guide";
import { CAPTION_EXIT_LEAD, SCENES, shotOf } from "../guide";
import { BOXES, CAPTION, PLANE_RADIUS, planeFor } from "../layout";
import { TRANSITION, cutFrame, windowFrame, windowSeconds } from "../timeline";

const STEP_SCENES = Object.keys(SCENES) as [StepSceneId, ...StepSceneId[]];

export const guideSceneSchema = z.object({
  scene: z.enum(STEP_SCENES),
  /** Previewed on its own: draw the backdrop and the chrome, which the full video keeps outside the transitions. */
  standalone: z.boolean(),
  showGuides: z.boolean(),
});

/** How long one screenshot takes to replace another within a scene. */
const SWAP_FRAMES = 12;

/**
 * One screenshot of a scene. A second one takes over at its `at`: scrolling
 * up from below, or fading in on top while this one stays put underneath, so
 * the frame never shows two half-transparent screenshots.
 */
const SegmentView: React.FC<{
  segment: Segment;
  next?: Segment;
  first: boolean;
  showGuides: boolean;
}> = ({ segment, next, first, showGuides }) => {
  const frame = useCurrentFrame();
  const at = useBeatFrame();
  const inAt = first ? -Infinity : at(segment.at);
  const outAt = next ? at(next.at) : Infinity;
  if (frame < inAt || frame >= outAt + SWAP_FRAMES) return null;

  const ease = { ...CLAMP, easing: Easing.bezier(0.2, 0.8, 0.2, 1) };
  let style: React.CSSProperties = {};
  if (!first) {
    const p = interpolate(frame, [inAt, inAt + SWAP_FRAMES], [0, 1], ease);
    style = segment.swap === "scroll" ? { opacity: p, transform: `translateY(${(1 - p) * 180}px)` } : { opacity: p };
  }
  if (next && frame >= outAt && next.swap === "scroll") {
    const q = interpolate(frame, [outAt, outAt + SWAP_FRAMES], [0, 1], ease);
    style = { opacity: 1 - q, transform: `translateY(${-q * 140}px)` };
  }

  const capture = CAPTURES[segment.capture];
  const plane = planeFor(capture, BOXES[segment.box]);
  // Explorer is a window with its own 8px corners; the app captures are the
  // whole viewport, so their frame gets the plane's radius.
  const radius = segment.box === "explorer" ? 8 * plane.k : PLANE_RADIUS;

  return (
    <AbsoluteFill style={style}>
      <ScreenshotPlane
        shot={shotOf(segment)}
        plane={plane}
        showGuides={showGuides}
        radius={radius}
        enter={first ? (segment.enter ?? "tilt") : "none"}
      />
    </AbsoluteFill>
  );
};

/** One scene of the guide, entirely driven by its entry in guide.ts. */
export const GuideScene: React.FC<z.infer<typeof guideSceneSchema>> = ({ scene, standalone, showGuides }) => {
  const frame = useCurrentFrame();
  const spec = SCENES[scene];

  return (
    <AbsoluteFill>
      {standalone ? <Backdrop /> : null}
      {standalone ? <GuideChrome frame={cutFrame(scene) - TRANSITION / 2 + frame} /> : null}
      {/* A beat's seconds count from this scene's window opening. */}
      <BeatClock.Provider value={(seconds) => windowFrame(scene, seconds)}>
        {spec.segments.map((segment, i) => (
          <SegmentView
            key={i}
            segment={segment}
            next={spec.segments[i + 1]}
            first={i === 0}
            showGuides={showGuides}
          />
        ))}
        {scene === "ffmpeg" ? <WhyCard /> : null}
        {(spec.insets ?? []).map((inset, i) => (
          <InsetView key={i} inset={inset} />
        ))}
        {scene === "pair" ? (
          <>
            <PairTerminal />
            <MatchConnector />
          </>
        ) : null}
        <Caption
          left={CAPTION.left}
          bottom={CAPTION.bottom}
          width={CAPTION.width}
          eyebrow={`STEP ${spec.step} OF 5`}
          headline={spec.headline}
          sub={spec.sub}
          exitAt={spec.captionExit ? windowSeconds(scene) - CAPTION_EXIT_LEAD : undefined}
        />
      </BeatClock.Provider>
    </AbsoluteFill>
  );
};
