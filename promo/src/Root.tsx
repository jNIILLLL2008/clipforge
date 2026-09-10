import { Composition, Folder } from "remotion";
import "./index.css";
import { ClipForgeLaunchAd } from "./clipforge/ClipForgeLaunchAd";
import { EndCard } from "./clipforge/EndCard";
import { FeatureBanner } from "./clipforge/FeatureBanner";
import { KineticHook } from "./clipforge/KineticHook";
import { PhoneStage } from "./clipforge/PhoneStage";
import { StudioStage } from "./clipforge/StudioStage";

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
    </>
  );
};
