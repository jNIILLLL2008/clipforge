import { Composition, Folder } from "remotion";
import "./index.css";
import { ClipForgeLaunchAd } from "./clipforge/ClipForgeLaunchAd";
import { EndCard } from "./clipforge/EndCard";
import { FeatureBanner } from "./clipforge/FeatureBanner";
import { KineticHook } from "./clipforge/KineticHook";
import { PhoneStage } from "./clipforge/PhoneStage";
import { StudioStage } from "./clipforge/StudioStage";
import { Intro, bookendSchema } from "./tutorial/scenes/Intro";
import { Outro } from "./tutorial/scenes/Outro";
import { StepScene, stepSceneSchema } from "./tutorial/scenes/StepScene";
import { TOTAL_FRAMES, sceneFrames } from "./tutorial/timeline";
import { YouTubeSetupTutorial, tutorialSchema } from "./tutorial/YouTubeSetupTutorial";

// The tutorial is 60s at 30fps. If a retime in timeline.ts stops adding up,
// fail here rather than render a video that ends early or runs long.
if (TOTAL_FRAMES !== 1800) {
  throw new Error(`YouTubeSetupTutorial should be 1800 frames, timeline.ts adds up to ${TOTAL_FRAMES}.`);
}

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="ClipForgeLaunchAd"
        component={ClipForgeLaunchAd}
        durationInFrames={900}
        fps={60}
        width={1920}
        height={1080}
      />

      {/* Each scene is registered on its own too, so double-clicking a
          sequence in the timeline jumps straight into it. */}
      <Folder name="Scenes">
        <Composition
          id="Scene1-KineticHook"
          component={KineticHook}
          durationInFrames={120}
          fps={60}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene2-PhoneStage"
          component={PhoneStage}
          durationInFrames={315}
          fps={60}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene3-StudioStage"
          component={StudioStage}
          durationInFrames={450}
          fps={60}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene4-FeatureBanner"
          component={FeatureBanner}
          durationInFrames={180}
          fps={60}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene6-EndCard"
          component={EndCard}
          durationInFrames={180}
          fps={60}
          width={1920}
          height={1080}
        />
      </Folder>

      <Composition
        id="YouTubeSetupTutorial"
        component={YouTubeSetupTutorial}
        durationInFrames={1800}
        fps={30}
        width={1920}
        height={1080}
        schema={tutorialSchema}
        defaultProps={{ showGuides: false }}
      />

      {/* The tutorial's scenes on their own, with their backdrop, for tuning.
          Same components as in the full video, so double-clicking a sequence
          there jumps here. */}
      <Folder name="Tutorial-Scenes">
        <Composition
          id="Tutorial-Intro"
          component={Intro}
          durationInFrames={sceneFrames("intro")}
          fps={30}
          width={1920}
          height={1080}
          schema={bookendSchema}
          defaultProps={{ standalone: true }}
        />
        <Composition
          id="Tutorial-Step1"
          component={StepScene}
          durationInFrames={sceneFrames("step1")}
          fps={30}
          width={1920}
          height={1080}
          schema={stepSceneSchema}
          defaultProps={{ step: 1, standalone: true, showGuides: false }}
        />
        <Composition
          id="Tutorial-Step2"
          component={StepScene}
          durationInFrames={sceneFrames("step2")}
          fps={30}
          width={1920}
          height={1080}
          schema={stepSceneSchema}
          defaultProps={{ step: 2, standalone: true, showGuides: false }}
        />
        <Composition
          id="Tutorial-Step3"
          component={StepScene}
          durationInFrames={sceneFrames("step3")}
          fps={30}
          width={1920}
          height={1080}
          schema={stepSceneSchema}
          defaultProps={{ step: 3, standalone: true, showGuides: false }}
        />
        <Composition
          id="Tutorial-Step4"
          component={StepScene}
          durationInFrames={sceneFrames("step4")}
          fps={30}
          width={1920}
          height={1080}
          schema={stepSceneSchema}
          defaultProps={{ step: 4, standalone: true, showGuides: false }}
        />
        <Composition
          id="Tutorial-Step5"
          component={StepScene}
          durationInFrames={sceneFrames("step5")}
          fps={30}
          width={1920}
          height={1080}
          schema={stepSceneSchema}
          defaultProps={{ step: 5, standalone: true, showGuides: false }}
        />
        <Composition
          id="Tutorial-Step6"
          component={StepScene}
          durationInFrames={sceneFrames("step6")}
          fps={30}
          width={1920}
          height={1080}
          schema={stepSceneSchema}
          defaultProps={{ step: 6, standalone: true, showGuides: false }}
        />
        <Composition
          id="Tutorial-Step7"
          component={StepScene}
          durationInFrames={sceneFrames("step7")}
          fps={30}
          width={1920}
          height={1080}
          schema={stepSceneSchema}
          defaultProps={{ step: 7, standalone: true, showGuides: false }}
        />
        <Composition
          id="Tutorial-Outro"
          component={Outro}
          durationInFrames={sceneFrames("outro")}
          fps={30}
          width={1920}
          height={1080}
          schema={bookendSchema}
          defaultProps={{ standalone: true }}
        />
      </Folder>
    </>
  );
};
