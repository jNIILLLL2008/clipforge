import React from "react";
import { Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, MONO, SANS, SPRING } from "../../shared/brand";
import { useBeatFrame } from "../../shared/clock";
import { CLAMP, mix } from "../../shared/motion";
import { CAPTURES } from "../captures";
import { PAIR } from "../guide";
import { BOXES, TERMINAL_BOX, planeFor } from "../layout";

/*
 * The agent's own window, rebuilt rather than screenshotted: a capture of the
 * real one carries the Windows user name in its title bar and its first log
 * line. The text is what agent/main.py and agent/pairing.py print, with the
 * path's user folder as "you" and the account as the guide's own.
 *
 * Beside it, the line that joins its code to the code in the browser's dialog.
 */

const FONT = 15;
const LINE = 22;
const CHAR = FONT * 0.6; // Geist Mono advances 0.6em
const TITLE = 40;
const PAD_X = 22;
const PAD_Y = 18;
const RULE = "=".repeat(58);

type Line = { text: string; after?: "paired" };

const LINES: readonly Line[] = [
  { text: "2026-09-13 00:53:44 | INFO | agent | Using ffmpeg at" },
  { text: "    C:\\Users\\you\\Downloads\\ClipForgeAgent\\ffmpeg\\ffmpeg.exe" },
  { text: "" },
  { text: RULE },
  { text: "  Your browser should have opened. If it did not, go to:" },
  { text: `    https://clipforgee.app/pair?code=${PAIR.code}` },
  { text: "" },
  { text: `  It will ask you to confirm this code:   ${PAIR.code}` },
  { text: "" },
  { text: "  Waiting for you to approve it..." },
  { text: RULE },
  { text: "", after: "paired" },
  { text: `  Paired with ${PAIR.email}.`, after: "paired" },
  { text: "", after: "paired" },
  { text: "2026-09-13 00:54:02 | INFO | agent | Working for", after: "paired" },
  { text: "    https://clipforgee.app. Ctrl+C to stop.", after: "paired" },
];

const CODE_LINE = LINES.findIndex((l) => l.text.startsWith("  It will ask"));
const WAITING_LINE = LINES.findIndex((l) => l.text.includes("Waiting for you"));
const PAIRED_LINE = LINES.findIndex((l) => l.text.includes("Paired with"));

/** The terminal's code, in frame px. */
export const terminalCode = () => {
  const col = LINES[CODE_LINE].text.indexOf(PAIR.code);
  return {
    x: TERMINAL_BOX.left + PAD_X + col * CHAR,
    y: TERMINAL_BOX.top + TITLE + PAD_Y + CODE_LINE * LINE,
    w: PAIR.code.length * CHAR,
    h: LINE,
  };
};

/** A target of the pairing dialog, in frame px, once its plane has settled. */
const dialogRect = (key: keyof (typeof CAPTURES)["pair-dialog"]["targets"]) => {
  const capture = CAPTURES["pair-dialog"];
  const plane = planeFor(capture, BOXES.pair);
  const [l, t, w, h] = capture.targets[key].rect;
  return { x: plane.left + l * plane.W, y: plane.top + t * plane.H, w: w * plane.W, h: h * plane.H };
};

const Controls = () => (
  <div style={{ marginLeft: "auto", display: "flex", color: "#D6D6D6", fontFamily: SANS, fontSize: 15 }}>
    {["—", "☐", "✕"].map((c) => (
      <span key={c} style={{ width: 46, height: TITLE, display: "grid", placeItems: "center" }}>
        {c}
      </span>
    ))}
  </div>
);

export const PairTerminal: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const at = useBeatFrame();
  const enter = spring({ frame, fps, config: SPRING.plane });
  const printFrom = at(PAIR.printAt);
  const paired = at(PAIR.pairedAt);
  const match = at(PAIR.matchAt);
  const unmatch = at(PAIR.unmatchAt);

  // Program output arrives a line every two frames; the paired lines when the
  // agent hears back.
  const before = LINES.filter((l) => !l.after).length;
  const shown =
    frame >= paired
      ? before + Math.min(LINES.length - before, Math.floor((frame - paired) / 2) + 1)
      : Math.max(0, Math.min(before, Math.floor((frame - printFrom) / 2) + 1));
  const waiting = frame >= printFrom + WAITING_LINE * 2 && frame < paired;
  const blink = Math.floor(frame / 16) % 2 === 0;
  const pairedGlow = interpolate(frame, [paired + 2, paired + 10, paired + 40], [0, 1, 0.55], CLAMP);

  const code = terminalCode();
  const ringDraw = interpolate(frame, [match, match + 14], [0, 1], { ...CLAMP, easing: Easing.bezier(0.65, 0, 0.35, 1) });
  const ringOut = interpolate(frame, [unmatch, unmatch + 8], [1, 0], CLAMP);

  return (
    <div
      style={{
        position: "absolute",
        left: TERMINAL_BOX.left,
        top: TERMINAL_BOX.top,
        width: TERMINAL_BOX.width,
        height: TERMINAL_BOX.height,
        opacity: interpolate(enter, [0, 0.6], [0, 1], CLAMP),
        transformOrigin: "50% 50%",
        transform: `perspective(1600px) rotateX(${14 * (1 - enter)}deg) rotateY(${8 * (1 - enter)}deg) translateY(${50 * (1 - enter)}px) scale(${0.94 + 0.06 * enter})`,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: 10,
          overflow: "hidden",
          backgroundColor: "#0C0C0C",
          boxShadow: "inset 0 0 0 1px #3A3A3A, 0 40px 120px rgba(0, 0, 0, 0.6)",
        }}
      >
        <div style={{ height: TITLE, backgroundColor: "#1F1F1F", display: "flex", alignItems: "flex-end" }}>
          <div
            style={{
              marginLeft: 8,
              height: TITLE - 6,
              width: 300,
              borderRadius: "8px 8px 0 0",
              backgroundColor: "#0C0C0C",
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "0 12px",
              boxSizing: "border-box",
              fontFamily: SANS,
              fontSize: 15,
              color: "#E8E8E8",
            }}
          >
            <span
              style={{
                fontFamily: MONO,
                fontSize: 11,
                padding: "1px 4px",
                borderRadius: 3,
                boxShadow: "inset 0 0 0 1px #6A6A6A",
                color: "#CFCFCF",
              }}
            >
              &gt;_
            </span>
            ClipForgeAgent.exe
            <span style={{ marginLeft: "auto", color: "#BDBDBD" }}>✕</span>
          </div>
          <span style={{ margin: "0 0 9px 14px", color: "#BDBDBD", fontFamily: SANS, fontSize: 18 }}>+</span>
          <Controls />
        </div>
        <div style={{ padding: `${PAD_Y}px ${PAD_X}px`, fontFamily: MONO, fontSize: FONT, lineHeight: `${LINE}px`, color: "#CCCCCC" }}>
          {LINES.slice(0, shown).map((line, i) => (
            <div key={i} style={{ height: LINE, whiteSpace: "pre", position: "relative" }}>
              <span style={i === PAIRED_LINE ? { color: C.emberInk, textShadow: `0 0 18px rgba(255, 138, 99, ${0.6 * pairedGlow})` } : undefined}>
                {line.text}
              </span>
              {i === WAITING_LINE && waiting && blink ? (
                <span style={{ display: "inline-block", width: CHAR, height: FONT, marginLeft: CHAR, verticalAlign: "-2px", backgroundColor: "#CCCCCC" }} />
              ) : null}
            </div>
          ))}
        </div>
      </div>
      {frame >= match && frame < unmatch + 8 ? (
        <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, overflow: "visible", opacity: ringOut }}>
          <rect
            x={code.x - TERMINAL_BOX.left - 6}
            y={code.y - TERMINAL_BOX.top - 2}
            width={code.w + 12}
            height={code.h + 4}
            rx={6}
            fill="none"
            stroke={C.ember}
            strokeWidth={2.5}
            pathLength={1}
            strokeDasharray={ringDraw >= 1 ? undefined : "1 1"}
            strokeDashoffset={ringDraw >= 1 ? undefined : 1 - ringDraw}
            style={{ filter: "drop-shadow(0 0 10px rgba(226, 96, 58, 0.6))" }}
          />
        </svg>
      ) : null}
    </div>
  );
};

/** The ember line from the terminal's code to the dialog's, and its label. */
export const MatchConnector: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const at = useBeatFrame();
  const start = at(PAIR.matchAt) + 6;
  const end = at(PAIR.unmatchAt);
  if (frame < start || frame > end + 10) return null;

  // The dialog's code sits at the right of its card, so a straight line would
  // run across the card's labels. This one curves out of the terminal, runs
  // along the empty band between the code row and the buttons, and turns up
  // into the code from below.
  const a = terminalCode();
  const code = dialogRect("code");
  const card = dialogRect("card");
  const button = dialogRect("pairIt");
  const x1 = a.x + a.w + 10;
  const y1 = a.y + a.h / 2;
  const band = (code.y + code.h + button.y) / 2;
  const x2 = code.x + code.w / 2;
  const y2 = code.y + code.h + 6;
  const into = card.x + 30;
  const path = [
    `M ${x1} ${y1}`,
    `C ${x1 + 150} ${y1}, ${into - 150} ${band}, ${into} ${band}`,
    `L ${x2 - 24} ${band}`,
    `Q ${x2} ${band}, ${x2} ${y2}`,
  ].join(" ");
  const drawn = interpolate(frame, [start, start + 20], [0, 1], { ...CLAMP, easing: Easing.bezier(0.65, 0, 0.35, 1) });
  const out = interpolate(frame, [end, end + 10], [1, 0], CLAMP);
  const label = spring({ frame: frame - (start + 14), fps, config: SPRING.pop });
  // The label sits over the curve's middle, in the gap between the windows.
  const mx = (x1 + into) / 2;
  const my = (y1 + band) / 2;

  return (
    <div style={{ position: "absolute", inset: 0, opacity: out }}>
      <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <path
          d={path}
          fill="none"
          stroke={C.ember}
          strokeWidth={3}
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray="1 1"
          strokeDashoffset={1 - drawn}
          style={{ filter: "drop-shadow(0 0 8px rgba(226, 96, 58, 0.55))" }}
        />
        <circle cx={x1} cy={y1} r={5} fill={C.ember} opacity={drawn > 0 ? 1 : 0} />
        <circle cx={x2} cy={y2} r={5} fill={C.ember} opacity={drawn >= 1 ? 1 : 0} />
      </svg>
      <div
        style={{
          position: "absolute",
          left: mx,
          top: my - 46,
          transform: `translate(-50%, 0) scale(${mix(0.7, 1, label)})`,
          opacity: interpolate(label, [0, 0.6], [0, 1], CLAMP),
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 16px",
          borderRadius: 999,
          backgroundColor: C.ember,
          color: C.onEmber,
          fontFamily: SANS,
          fontWeight: 600,
          fontSize: 20,
          whiteSpace: "nowrap",
          boxShadow: "0 12px 30px rgba(226, 96, 58, 0.35)",
        }}
      >
        <svg width={16} height={16} viewBox="0 0 16 16">
          <path d="M3 8.5 L6.5 12 L13 4.5" fill="none" stroke={C.onEmber} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        They match
      </div>
    </div>
  );
};
