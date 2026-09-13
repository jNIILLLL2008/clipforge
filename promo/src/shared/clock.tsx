import React from "react";

/**
 * Which frame a beat's `at` means. Beats are written in seconds from a moment
 * each video picks (the tutorial and the guide both count from their scene's
 * window opening), and the video provides the conversion. The shared
 * components read every beat time through this, so they know nothing about
 * any one video's timeline.
 */
export type BeatFrame = (seconds: number) => number;

export const BeatClock = React.createContext<BeatFrame>((seconds) => Math.round(seconds * 30));

export const useBeatFrame = () => React.useContext(BeatClock);
