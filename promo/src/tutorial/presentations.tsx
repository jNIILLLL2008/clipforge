import type {
  TransitionPresentation,
  TransitionPresentationComponentProps,
} from "@remotion/transitions";
import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { CLAMP } from "./motion";

type NoProps = Record<string, never>;

/*
 * Between steps: the outgoing step drifts left and fades, the incoming one
 * slides in from the right and fades up. The fades are staggered, the old one
 * mostly gone before the new one is mostly there, so two screenshots never sit
 * on top of each other at half opacity. The backdrop sits outside the
 * transitions, so only the step itself moves.
 */
const SlideFade: React.FC<TransitionPresentationComponentProps<NoProps>> = ({
  children,
  presentationDirection,
  presentationProgress: p,
}) => {
  const entering = presentationDirection === "entering";
  const style: React.CSSProperties = entering
    ? {
        opacity: interpolate(p, [0.25, 1], [0, 1], CLAMP),
        transform: `translateX(${(1 - p) * 240}px)`,
      }
    : {
        opacity: interpolate(p, [0, 0.7], [1, 0], CLAMP),
        transform: `translateX(${-p * 160}px)`,
      };
  return <AbsoluteFill style={style}>{children}</AbsoluteFill>;
};

export const slideFade = (): TransitionPresentation<NoProps> => ({
  component: SlideFade,
  props: {},
});

/*
 * Into the outro: the last step blurs to 20px, shrinks to 0.96 and fades,
 * while the outro fades up.
 */
const BlurAway: React.FC<TransitionPresentationComponentProps<NoProps>> = ({
  children,
  presentationDirection,
  presentationProgress: p,
}) => {
  const style: React.CSSProperties =
    presentationDirection === "entering"
      ? { opacity: p }
      : {
          opacity: 1 - p,
          filter: `blur(${20 * p}px)`,
          transform: `scale(${1 - 0.04 * p})`,
        };
  return <AbsoluteFill style={style}>{children}</AbsoluteFill>;
};

export const blurAway = (): TransitionPresentation<NoProps> => ({
  component: BlurAway,
  props: {},
});
