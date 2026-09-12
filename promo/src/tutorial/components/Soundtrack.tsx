import { Audio } from "@remotion/media";
import React from "react";
import { Sequence, staticFile } from "remotion";
import { LINES, MUSIC, VOICEOVER, VOICE_VOLUME, clipOf, musicVolume, spanOf } from "../soundtrack";

/**
 * The bed under the whole video, and each narration line in its scene. Lives
 * at the top of the main composition, outside the TransitionSeries, so the
 * frames here are the video's own. Everything it plays is set in
 * soundtrack.ts.
 */
export const Soundtrack: React.FC = () => {
  return (
    <>
      <Sequence name="Music" layout="none">
        <Audio src={staticFile(MUSIC)} volume={musicVolume} />
      </Sequence>
      {LINES.map((line) => {
        const { start, end } = spanOf(line);
        const { trimBefore, trimAfter } = clipOf(line);
        return (
          <Sequence
            key={line.scene}
            name={`Voice: ${line.scene}`}
            from={start}
            durationInFrames={end - start}
            layout="none"
          >
            <Audio
              src={staticFile(VOICEOVER)}
              trimBefore={trimBefore}
              trimAfter={trimAfter}
              volume={VOICE_VOLUME}
            />
          </Sequence>
        );
      })}
    </>
  );
};
