import React from "react";
import { Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, MONO, SANS, SPRING } from "../../shared/brand";
import { useBeatFrame } from "../../shared/clock";
import { CLAMP, riseStyle } from "../../shared/motion";
import { WHY } from "../guide";

/*
 * Why the agent needs ffmpeg, in one picture: your clips go through ffmpeg
 * and come out a finished video, and the three things it does on the way
 * pop in underneath as the narration names them. The footer says what to do
 * if ffmpeg is already there.
 * Sits over the empty lower right of the Explorer window.
 */
// Inside the window's empty lower right, below the last file row of either
// folder and clear of the ring round ClipForgeAgent, the root folder's last.
const CARD = { left: 1000, top: 570, width: 780 };
const NODE = 92;

const Node: React.FC<{ progress: number; label: string; hot?: boolean; children: React.ReactNode }> = ({
  progress,
  label,
  hot,
  children,
}) => (
  <div style={{ width: 170, display: "flex", flexDirection: "column", alignItems: "center", ...riseStyle(progress, 16, 5) }}>
    <div
      style={{
        width: NODE,
        height: NODE,
        borderRadius: 22,
        display: "grid",
        placeItems: "center",
        backgroundColor: hot ? C.ember : C.surface2,
        boxShadow: hot ? "0 14px 36px rgba(226, 96, 58, 0.38)" : `inset 0 0 0 1px ${C.hairlineFirm}`,
      }}
    >
      {children}
    </div>
    <div style={{ marginTop: 12, fontFamily: SANS, fontWeight: 500, fontSize: 20, color: C.ink, whiteSpace: "nowrap" }}>{label}</div>
  </div>
);

const Arrow: React.FC<{ drawn: number }> = ({ drawn }) => (
  <svg width={90} height={NODE} viewBox={`0 0 90 ${NODE}`} style={{ flex: "none", alignSelf: "flex-start" }}>
    <path
      d={`M 6 ${NODE / 2} L 78 ${NODE / 2} M 68 ${NODE / 2 - 9} L 80 ${NODE / 2} L 68 ${NODE / 2 + 9}`}
      fill="none"
      stroke={C.ember}
      strokeWidth={3}
      strokeLinecap="round"
      strokeLinejoin="round"
      pathLength={1}
      strokeDasharray="1 1"
      strokeDashoffset={1 - drawn}
    />
  </svg>
);

export const WhyCard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const at = useBeatFrame();
  const start = at(WHY.at);
  if (frame < start) return null;

  const card = spring({ frame: frame - start, fps, config: SPRING.plane });
  const node = (i: number) => spring({ frame: frame - (start + 4 + i * 5), fps, config: SPRING.text });
  const draw = (from: number) =>
    interpolate(frame, [start + from, start + from + 14], [0, 1], { ...CLAMP, easing: Easing.bezier(0.65, 0, 0.35, 1) });
  const verb = (i: number) => spring({ frame: frame - at(WHY.verbs[i]), fps, config: SPRING.pop });
  const winget = spring({ frame: frame - at(WHY.wingetAt), fps, config: SPRING.text });

  return (
    <div
      style={{
        position: "absolute",
        left: CARD.left,
        top: CARD.top,
        width: CARD.width,
        boxSizing: "border-box",
        padding: "26px 32px 26px",
        borderRadius: 18,
        backgroundColor: "rgba(19, 19, 22, 0.86)",
        backdropFilter: "blur(18px)",
        WebkitBackdropFilter: "blur(18px)",
        boxShadow: "inset 0 0 0 1px rgba(255, 255, 255, 0.07), 0 30px 80px rgba(0, 0, 0, 0.5)",
        opacity: interpolate(card, [0, 1], [0, 1], CLAMP),
        transform: `translateY(${(1 - card) * 20}px)`,
      }}
    >
      <div style={{ fontFamily: MONO, fontWeight: 500, fontSize: 17, letterSpacing: "0.14em", color: C.emberInk }}>WHY FFMPEG</div>
      <div style={{ marginTop: 20, display: "flex", alignItems: "flex-start", justifyContent: "center" }}>
        <Node progress={node(0)} label="Your clips">
          <svg width={44} height={44} viewBox="0 0 24 24" fill="none" stroke={C.inkMuted} strokeWidth={1.6} strokeLinejoin="round">
            <rect x={3} y={5} width={18} height={14} rx={2} />
            <path d="M3 9h18M3 15h18M7 5v4M12 5v4M17 5v4M7 15v4M12 15v4M17 15v4" />
          </svg>
        </Node>
        <Arrow drawn={draw(12)} />
        <Node progress={node(1)} label="ffmpeg" hot>
          <span style={{ fontFamily: MONO, fontWeight: 500, fontSize: 19, color: C.onEmber }}>ffmpeg</span>
        </Node>
        <Arrow drawn={draw(20)} />
        <Node progress={node(2)} label="Finished video">
          <svg width={44} height={44} viewBox="0 0 24 24" fill="none" stroke={C.inkMuted} strokeWidth={1.6} strokeLinejoin="round">
            <rect x={6} y={2.5} width={12} height={19} rx={2.5} />
            <path d="M10.5 9.5v5l4-2.5z" fill={C.inkMuted} />
          </svg>
        </Node>
      </div>
      <div style={{ marginTop: 16, display: "flex", justifyContent: "center", gap: 10 }}>
        {["cuts", "captions", "encodes"].map((word, i) => (
          <span
            key={word}
            style={{
              padding: "6px 14px",
              borderRadius: 999,
              backgroundColor: C.emberWash,
              boxShadow: `inset 0 0 0 1px ${C.emberEdge}`,
              fontFamily: MONO,
              fontWeight: 500,
              fontSize: 16,
              color: C.emberInk,
              transform: `scale(${0.7 + 0.3 * verb(i)})`,
              opacity: interpolate(verb(i), [0, 0.6], [0, 1], CLAMP),
            }}
          >
            {word}
          </span>
        ))}
      </div>
      <div
        style={{
          marginTop: 22,
          paddingTop: 16,
          borderTop: `1px solid ${C.hairline}`,
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontFamily: SANS,
          fontSize: 19,
          color: C.inkMuted,
          ...riseStyle(winget, 12, 5),
        }}
      >
        Already have ffmpeg?
        <span
          style={{
            fontFamily: MONO,
            fontSize: 17,
            color: C.ink,
            padding: "4px 10px",
            borderRadius: 8,
            backgroundColor: C.surface2,
            boxShadow: `inset 0 0 0 1px ${C.hairlineFirm}`,
          }}
        >
          winget install Gyan.FFmpeg
        </span>
        works too.
      </div>
    </div>
  );
};
