// Captures every screen in the ClipForge setup guide, and measures its targets.
//
//   node promo/tools/capture_guide.mjs
//
// The app screens are the real frontend (frontend/index.html, styles.css,
// app.js) rendered in Remotion's own headless Chrome at 2x. Its API calls are
// answered with what the real backend returns for a fresh, throwaway account
// (guide_payloads.py makes those in-process), so every pixel is the app's own
// and none of it is anybody's: the account is you@example.com, the computer is
// "Your PC", the channel is "Your channel".
//
// File Explorer isn't part of the app, so it is a small HTML mock of the
// Windows 11 window, captured the same way, with no sidebar entry that could
// carry a name.
//
// Writes promo/public/guide/*.png and promo/src/guide/captures.ts, which holds
// each capture's size and the rect of every target in it, as fractions of the
// capture, measured off the DOM.
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PROMO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO = path.resolve(PROMO, "..");
const FRONTEND = path.join(REPO, "frontend");
const OUT = path.join(PROMO, "public", "guide");
const CAPTURES_TS = path.join(PROMO, "src", "guide", "captures.ts");
const CDP_PORT = 9334;
const VIEW = { width: 1600, height: 900, scale: 2 };
const PAIR_CODE = "DA6H-SVSG";

// ------------------------------------------------------------ payloads --
const python = process.platform === "win32"
  ? path.join(REPO, ".venv", "Scripts", "python.exe")
  : path.join(REPO, ".venv", "bin", "python");
const payloadFile = path.join(os.tmpdir(), `guide-payloads-${process.pid}.json`);
const made = spawnSync(python, [path.join(PROMO, "tools", "guide_payloads.py"), payloadFile], {
  cwd: REPO,
  encoding: "utf8",
});
if (made.status !== 0) {
  console.error(made.stderr);
  console.error("guide_payloads.py failed.");
  process.exit(1);
}
const P = JSON.parse(fs.readFileSync(payloadFile, "utf8"));
fs.rmSync(payloadFile, { force: true });

// -------------------------------------------------------------- server --
const TYPES = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml", ".webp": "image/webp" };
const world = { ready: false };

const readBody = (req) =>
  new Promise((resolve) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => resolve(body));
  });

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  const p = url.pathname;
  const send = (code, type, body) => {
    res.writeHead(code, { "content-type": type });
    res.end(body);
  };
  const json = (value) => send(200, "application/json", JSON.stringify(value));

  if (p === "/" || p === "/app" || p === "/pair") {
    return send(200, "text/html", fs.readFileSync(path.join(FRONTEND, "index.html")));
  }
  // Its placeholders are only filled in by the real server; with nothing in
  // them it would put a cookie banner over every capture.
  if (p === "/static/consent.js") return send(200, "text/javascript", "");
  if (p.startsWith("/static/")) {
    const file = path.join(FRONTEND, decodeURIComponent(p.slice(8)));
    if (fs.existsSync(file) && fs.statSync(file).isFile()) {
      return send(200, TYPES[path.extname(file)] || "application/octet-stream", fs.readFileSync(file));
    }
    return send(404, "text/plain", "");
  }
  if (p.startsWith("/mock/explorer/")) return send(200, "text/html", explorer(p.split("/").pop()));

  const body = await readBody(req);
  switch (p) {
    case "/api/me":
      return json(P.me);
    case "/api/studio":
      return json(world.ready ? P.studio_ready : P.studio_setup);
    case "/api/studio/settings":
      return json(P.settings);
    case "/api/studio/review":
      return json(P.review);
    case "/api/studio/preview": {
      const cfg = (JSON.parse(body || "{}").settings) || {};
      const png = cfg.banner_line2 === "FORMULA 1" ? P.preview_after : P.preview_before;
      return send(200, "image/png", Buffer.from(png, "base64"));
    }
    case "/api/agent/status":
      return json(P.agent);
    case "/api/agent/pair/lookup":
      return json({ found: true, approved: false, code: PAIR_CODE, label: "Your PC", already_paired: false });
    case "/api/agent/pair/approve":
      return json({ ok: true });
    default:
      return json({});
  }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const ORIGIN = `http://127.0.0.1:${server.address().port}`;

// ------------------------------------------------------------- explorer --
const ICON = {
  folder: `<svg viewBox="0 0 20 16" width="18" height="15"><path d="M1 3a2 2 0 0 1 2-2h4.2l2 2H17a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2z" fill="#E8B34A"/><path d="M1 6h18v7a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2z" fill="#F6C75A"/></svg>`,
  text: `<svg viewBox="0 0 16 20" width="14" height="17"><path d="M1 2a1 1 0 0 1 1-1h8l5 5v12a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1z" fill="#F2F2F2"/><path d="M10 1v5h5" fill="#CFCFCF"/><path d="M4 10h8M4 13h8M4 16h5" stroke="#8A8A8A" stroke-width="1.2"/></svg>`,
  app: `<svg viewBox="0 0 20 18" width="17" height="15"><rect x="1" y="1" width="18" height="16" rx="2" fill="#2B2B30" stroke="#6C6C74"/><rect x="1" y="1" width="18" height="4" rx="2" fill="#4F8FDB"/><rect x="4" y="8" width="7" height="2" rx="1" fill="#9AA0AA"/><rect x="4" y="12" width="11" height="2" rx="1" fill="#9AA0AA"/></svg>`,
  file: `<svg viewBox="0 0 16 20" width="14" height="17"><path d="M1 2a1 1 0 0 1 1-1h8l5 5v12a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1z" fill="#E6E6E6"/><path d="M10 1v5h5" fill="#C4C4C4"/></svg>`,
};
const SIDEBAR = ["Home", "Gallery", "", "Desktop", "Downloads", "Documents", "Pictures", "Music", "Videos"];
const DIRS = {
  root: {
    tab: "ClipForgeAgent-windows",
    crumbs: ["This PC", "Downloads", "ClipForgeAgent-windows"],
    groups: [
      ["Today", [["ffmpeg", "13/09/2026 00:52", "File folder", "", "folder"]]],
      ["Last week", [
        ["READ ME FIRST", "02/09/2026 20:11", "Text Document", "1 KB", "text"],
        ["ClipForgeAgent", "02/09/2026 20:11", "Application", "24,387 KB", "app"],
      ]],
    ],
  },
  ffmpeg: {
    tab: "ffmpeg",
    crumbs: ["This PC", "Downloads", "ClipForgeAgent-windows", "ffmpeg"],
    groups: [
      ["Last month", [
        ["ffmpeg", "29/08/2026 17:41", "Application", "100,446 KB", "app"],
        ["ffprobe", "29/08/2026 17:41", "Application", "100,247 KB", "app"],
        ["LICENSE", "29/08/2026 17:41", "File", "35 KB", "file"],
        ["README", "29/08/2026 17:41", "Text Document", "41 KB", "text"],
      ]],
    ],
  },
};

function explorer(dir) {
  const d = DIRS[dir] || DIRS.root;
  const count = d.groups.reduce((n, [, rows]) => n + rows.length, 0);
  const rows = d.groups.map(([label, items]) => `
      <div class="group"><span class="chev">&#8964;</span>${label}</div>
      ${items.map(([name, date, type, size, icon]) => `
      <div class="row" data-row="${name}">
        <span class="name">${ICON[icon]}<span>${name}</span></span>
        <span>${date}</span><span>${type}</span><span class="size">${size}</span>
      </div>`).join("")}`).join("");
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    html, body { margin: 0; background: transparent; }
    body { font: 13px "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; color: #EDEDED; padding: 40px; }
    #window { width: 1180px; height: 620px; background: #191919; border: 1px solid #3B3B3B; border-radius: 8px; overflow: hidden; display: grid; grid-template-rows: 44px 48px 46px 1fr 28px; }
    .tabs { background: #202020; display: flex; align-items: flex-end; padding: 0 0 0 10px; position: relative; }
    .tab { background: #2C2C2C; height: 36px; border-radius: 8px 8px 0 0; display: flex; align-items: center; gap: 10px; padding: 0 12px; width: 220px; box-sizing: border-box; }
    .tab .x { margin-left: auto; color: #BDBDBD; }
    .plus { color: #BDBDBD; margin: 0 0 9px 14px; font-size: 18px; }
    .win { position: absolute; right: 0; top: 0; display: flex; }
    .win span { width: 46px; height: 32px; display: grid; place-items: center; color: #D6D6D6; font-size: 13px; }
    .nav { background: #2C2C2C; display: flex; align-items: center; gap: 18px; padding: 0 14px; color: #D0D0D0; font-size: 15px; }
    .address { flex: 1; height: 32px; border-radius: 4px; background: #202020; display: flex; align-items: center; gap: 10px; padding: 0 12px; color: #EDEDED; }
    .address .sep { color: #9A9A9A; }
    .search { width: 230px; height: 32px; border-radius: 4px; background: #202020; display: flex; align-items: center; padding: 0 12px; color: #9A9A9A; }
    .tools { background: #2C2C2C; border-bottom: 1px solid #3B3B3B; display: flex; align-items: center; gap: 22px; padding: 0 16px; color: #DADADA; }
    .tools .spacer { flex: 1; }
    .body { display: grid; grid-template-columns: 170px 1fr; min-height: 0; }
    .side { border-right: 1px solid #333; padding: 10px 0; }
    .side div { height: 30px; display: flex; align-items: center; padding: 0 18px; color: #E4E4E4; }
    .side div.on { background: #2D2D2D; border-radius: 4px; margin: 0 6px; padding-left: 12px; }
    .side hr { border: 0; border-top: 1px solid #333; margin: 8px 14px; }
    .list { padding: 6px 12px; }
    .head, .row { display: grid; grid-template-columns: 1fr 170px 150px 110px; align-items: center; }
    .head { height: 30px; color: #CFCFCF; border-bottom: 1px solid #333; padding: 0 10px; }
    .head span + span { border-left: 1px solid #333; padding-left: 8px; }
    .group { height: 30px; display: flex; align-items: center; gap: 8px; padding: 0 6px; color: #EDEDED; font-size: 14px; }
    .chev { color: #BDBDBD; transform: translateY(-3px); }
    .row { height: 30px; padding: 0 10px; border-radius: 4px; color: #D2D2D2; }
    .row .name { display: flex; align-items: center; gap: 10px; color: #EDEDED; }
    .row .size { text-align: right; padding-right: 20px; }
    .status { background: #191919; border-top: 1px solid #2E2E2E; display: flex; align-items: center; padding: 0 14px; color: #CFCFCF; font-size: 12px; }
  </style></head><body><div id="window">
    <div class="tabs"><div class="tab">${ICON.folder}<span>${d.tab}</span><span class="x">&#10005;</span></div><span class="plus">+</span>
      <div class="win"><span>&#8212;</span><span>&#9744;</span><span>&#10005;</span></div></div>
    <div class="nav"><span>&#8592;</span><span style="color:#777">&#8594;</span><span>&#8593;</span><span>&#8635;</span>
      <div class="address">${d.crumbs.map((c) => `<span>${c}</span>`).join('<span class="sep">&#8250;</span>')}<span class="sep">&#8250;</span></div>
      <div class="search">Search ${d.tab}</div></div>
    <div class="tools"><span>&#8853; New &#709;</span><span>&#9986;</span><span>&#10697;</span><span>&#9636;</span><span>&#9998;</span><span>&#8599;</span><span>&#128465;</span><span>&#8645; Sort &#709;</span><span>&#8801; View &#709;</span><span>&#183;&#183;&#183;</span><span class="spacer"></span><span>Details</span></div>
    <div class="body">
      <div class="side">${SIDEBAR.map((s) => (s ? `<div class="${s === "Downloads" ? "on" : ""}">${s}</div>` : "<hr>")).join("")}</div>
      <div class="list"><div class="head"><span>Name</span><span>Date modified</span><span>Type</span><span>Size</span></div>${rows}</div>
    </div>
    <div class="status">${count} items</div>
  </div></body></html>`;
}

// ---------------------------------------------------------------- chrome --
const findChrome = (dir) => {
  if (!fs.existsSync(dir)) return null;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      const found = findChrome(full);
      if (found) return found;
    } else if (/^chrome-headless-shell(\.exe)?$/.test(entry.name)) {
      return full;
    }
  }
  return null;
};
const CHROME = findChrome(path.join(PROMO, "node_modules/.remotion/chrome-headless-shell"));
if (!CHROME) {
  console.error("No chrome-headless-shell under promo/node_modules/.remotion. Render any still once so Remotion downloads it.");
  process.exit(1);
}
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "cf-guide-"));
const chrome = spawn(CHROME, [
  `--remote-debugging-port=${CDP_PORT}`,
  `--user-data-dir=${profile}`,
  "--no-first-run",
  "--no-default-browser-check",
  "--hide-scrollbars",
  "--force-color-profile=srgb",
  "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let targets = [];
for (let i = 0; i < 50 && !targets.some((t) => t.type === "page"); i++) {
  try {
    targets = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
  } catch {
    await sleep(200);
  }
}
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let nextId = 1;
const pending = new Map();
ws.addEventListener("message", (e) => {
  const msg = JSON.parse(e.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
});
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, (msg) => (msg.error ? reject(new Error(`${method}: ${msg.error.message}`)) : resolve(msg.result)));
    ws.send(JSON.stringify({ id, method, params }));
  });
const evaluate = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
};
const until = async (expression, label, timeout = 15000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (await evaluate(`Boolean(${expression})`).catch(() => false)) return;
    await sleep(100);
  }
  throw new Error(`Timed out waiting for ${label}`);
};

// Measured in the page: each target's rect as fractions of the clip, its
// corner radius in CSS px, and for a field, how text sits in it.
const MEASURE = `(clip, spec) => {
  const out = {};
  for (const [key, want] of Object.entries(spec)) {
    let el = document.querySelector(want.sel);
    if (!el) throw new Error('No element for ' + key + ': ' + want.sel);
    if (want.row) el = el.closest('.row');
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const t = {
      rect: [(r.left - clip.x) / clip.width, (r.top - clip.y) / clip.height, r.width / clip.width, r.height / clip.height].map((v) => +v.toFixed(4)),
      radius: want.radius ?? (parseFloat(cs.borderTopLeftRadius) || 0),
    };
    if (want.field) {
      const px = (v) => parseFloat(v) || 0;
      // A text input on a settings row is transparent and shows the row
      // through it; a fill has to cover the value with what you actually see.
      let background = cs.backgroundColor;
      for (let up = el.parentElement; /rgba\\(0, 0, 0, 0\\)|transparent/.test(background) && up; up = up.parentElement) {
        background = getComputedStyle(up).backgroundColor;
      }
      t.field = {
        inset: px(cs.paddingLeft) + px(cs.borderLeftWidth),
        insetRight: px(cs.paddingRight) + px(cs.borderRightWidth),
        padTop: px(cs.paddingTop) + px(cs.borderTopWidth),
        fontSize: px(cs.fontSize),
        lineHeight: cs.lineHeight === 'normal' ? +(px(cs.fontSize) * 1.25).toFixed(2) : px(cs.lineHeight),
        weight: px(cs.fontWeight) || 400,
        color: cs.color,
        background,
        align: cs.textAlign === 'right' || cs.textAlign === 'end' ? 'right' : 'left',
        valign: el.tagName === 'TEXTAREA' ? 'top' : 'center',
        font: 'sans',
      };
    }
    out[key] = t;
  }
  return out;
}`;

const captures = {};

/**
 * Screenshot a clip (viewport CSS px) and record its targets under `name`.
 * Full-screen captures go out as JPEG: at 3200x1800 a PNG of the app is 2-3MB,
 * and at quality 92 the JPEG is a fifth of that and can't be told apart once
 * it is scaled into the video. Everything smaller stays PNG.
 */
async function capture(name, clip, spec, { jpeg = false } = {}) {
  await evaluate(`document.activeElement && document.activeElement.blur(), document.fonts.ready.then(() => true)`);
  await evaluate(`new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))`);
  const scroll = await evaluate(`({ x: scrollX, y: scrollY })`);
  const measured = await evaluate(`(${MEASURE})(${JSON.stringify(clip)}, ${JSON.stringify(spec)})`);
  const shot = await send("Page.captureScreenshot", {
    format: jpeg ? "jpeg" : "png",
    ...(jpeg ? { quality: 92 } : {}),
    fromSurface: true,
    // The clip is in document coordinates; the measurements are in the viewport's.
    clip: { x: clip.x + scroll.x, y: clip.y + scroll.y, width: clip.width, height: clip.height, scale: 1 },
  });
  const file = `${name}.${jpeg ? "jpg" : "png"}`;
  fs.writeFileSync(path.join(OUT, file), Buffer.from(shot.data, "base64"));
  captures[name] = {
    image: `guide/${file}`,
    width: Math.round(clip.width * VIEW.scale),
    height: Math.round(clip.height * VIEW.scale),
    cssWidth: +clip.width.toFixed(2),
    targets: measured,
  };
  console.log(`wrote public/guide/${file}, ${captures[name].width}x${captures[name].height}, ${Object.keys(measured).length} targets`);
}

/** Screenshot one element on its own, with no targets. */
async function captureElement(name, selector, pad = 0) {
  const r = await evaluate(`(() => { const b = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect(); return { x: b.left - ${pad}, y: b.top - ${pad}, width: b.width + ${2 * pad}, height: b.height + ${2 * pad} }; })()`);
  await capture(name, r, {});
}

const VIEWPORT = { x: 0, y: 0, width: VIEW.width, height: VIEW.height };
const go = async (url) => {
  await send("Page.navigate", { url: ORIGIN + url });
  await until("document.readyState === 'complete'", `${url} to load`);
  await evaluate("document.fonts.ready.then(() => true)");
};
const hideCarets = () =>
  evaluate(`(() => { const s = document.createElement('style'); s.textContent = '*, *::before, *::after { transition: none !important; animation: none !important; caret-color: transparent !important; } #toast, .toast { display: none !important; }'; document.head.appendChild(s); return true; })()`);
const scrollToGroup = (id, gap = 16) =>
  evaluate(`(() => { const h = document.getElementById('g-${id}'); const top = h.closest('section').getBoundingClientRect().top + scrollY - ${gap}; scrollTo(0, top); return scrollY; })()`);

try {
  fs.mkdirSync(OUT, { recursive: true });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: VIEW.width, height: VIEW.height, deviceScaleFactor: VIEW.scale, mobile: false });
  // The site's own backdrop has a light variant; headless Chrome reports a
  // light system theme unless told otherwise, and the brand default is dark.
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "dark" }] });

  // ------------------------------------------------------------ Home --
  await go("/app");
  await hideCarets();
  await until("document.getElementById('hero-title').textContent.includes('Not ready')", "Home, not ready");
  await until("document.getElementById('agent-download')", "the agent panel");
  await capture("home-top", VIEWPORT, {
    hero: { sel: "#hero" },
    publish: { sel: "#publish" },
    youtubeRow: { sel: "#connect-youtube", row: true, radius: 12 },
    setUpPublishing: { sel: "#connect-youtube", radius: 4 },
    agentStatus: { sel: "#agent-rows .row", radius: 12 },
  }, { jpeg: true });
  await evaluate("scrollTo(0, document.documentElement.scrollHeight), true");
  await capture("home-agent", VIEWPORT, {
    agentStatus: { sel: "#agent-rows .row", radius: 12 },
    agentPanel: { sel: "#agent-token" },
    // An <a> styled as a button: its radius is the button class's, not its own.
    download: { sel: "#agent-download", radius: 12 },
    ffmpegLine: { sel: "#agent-token li:nth-child(2)", radius: 6 },
    agentNote: { sel: "#agent-note", radius: 6 },
  }, { jpeg: true });

  // --------------------------------------------------------- Pairing --
  await go(`/pair?code=${PAIR_CODE}`);
  await hideCarets();
  await until("document.getElementById('pair-yes')", "the pair dialog");
  const card = await evaluate(`(() => { const b = document.querySelector('#pair .pair-card').getBoundingClientRect(); return { x: b.left - 70, y: b.top - 60, width: b.width + 140, height: b.height + 120 }; })()`);
  await capture("pair-dialog", card, {
    card: { sel: "#pair .pair-card" },
    computer: { sel: "#pair-rows .row:first-child .row-value", radius: 4 },
    code: { sel: ".pair-code", radius: 6 },
    pairIt: { sel: "#pair-yes" },
  });
  await evaluate("document.getElementById('pair-yes').click(), true");
  await until("document.getElementById('pair-close')", "the paired state");
  await capture("paired", card, {
    card: { sel: "#pair .pair-card" },
    lead: { sel: "#pair-lead", radius: 6 },
    done: { sel: "#pair-close" },
  });

  // -------------------------------------------------------- Settings --
  await go("/app");
  await hideCarets();
  await until("document.getElementById('hero-title').textContent.includes('Not ready')", "Home");
  await evaluate("showTab('settings'), true");
  await until("document.getElementById('preview-img').naturalWidth > 0 && document.querySelector('#review-list .finding')", "the preview and its findings");
  await captureElement("preview-before", "#preview-img");
  await captureElement("preview-warning", "#review-list .finding");
  await evaluate("window.__src = document.getElementById('preview-img').src, state.settings.banner_line2 = 'FORMULA 1', refreshPreview(), true");
  await until("document.getElementById('preview-img').src !== window.__src && document.getElementById('preview-img').complete", "the edited preview");
  await captureElement("preview-after", "#preview-img");
  await evaluate("state.settings.banner_line2 = 'YOUR SHOW', true");

  const SAVE = { save: { sel: "#settings-save" } };
  await scrollToGroup("subject");
  await capture("settings-subject", VIEWPORT, {
    description: { sel: "[data-key=description]", field: true },
    searchTerms: { sel: "[data-key=search_terms]", field: true },
    sources: { sel: "[data-key=sources]", field: true },
    playlists: { sel: "[data-key=source_playlists]", field: true },
    channels: { sel: "[data-key=source_channels]", field: true },
    line1: { sel: "[data-key=banner_line1]", row: true, radius: 12 },
    line2: { sel: "[data-key=banner_line2]", row: true, radius: 12 },
    line2Field: { sel: "[data-key=banner_line2]", field: true },
    ...SAVE,
  }, { jpeg: true });
  await scrollToGroup("gate");
  await capture("settings-showfilter", VIEWPORT, {
    showMatch: { sel: "[data-key=require_show_match]", row: true, radius: 12 },
    showName: { sel: "[data-key=show_name]", row: true, radius: 12 },
    showNameField: { sel: "[data-key=show_name]", field: true },
    showTerms: { sel: "[data-key=show_terms]", field: true },
    regulars: { sel: "[data-key=show_people]", field: true },
    ...SAVE,
  }, { jpeg: true });
  await scrollToGroup("cut");
  await capture("settings-cut", VIEWPORT, {
    clips: { sel: "[data-key=clips]", row: true, radius: 12 },
    length: { sel: "[data-key=target_seconds]", row: true, radius: 12 },
    listen: { sel: "[data-key=moment_audio_scan]", row: true, radius: 12 },
    aiPicks: { sel: "[data-key=ai_moment_ranking]", row: true, radius: 12 },
    ...SAVE,
  }, { jpeg: true });

  // ------------------------------------------------------- Home, ready --
  world.ready = true;
  await go("/app");
  await hideCarets();
  await until("document.getElementById('hero-title').textContent.trim() === 'Ready'", "Home, ready");
  await capture("home-ready", VIEWPORT, {
    hero: { sel: "#hero" },
    publish: { sel: "#publish" },
    youtubeRow: { sel: "#status-rows .row:nth-child(2)", radius: 12 },
  }, { jpeg: true });

  // ------------------------------------------------------ File Explorer --
  for (const dir of ["root", "ffmpeg"]) {
    await go(`/mock/explorer/${dir}`);
    const win = await evaluate(`(() => { const b = document.getElementById('window').getBoundingClientRect(); return { x: b.left, y: b.top, width: b.width, height: b.height }; })()`);
    const rows = dir === "root"
      ? { ffmpeg: { sel: '[data-row="ffmpeg"]' }, readMe: { sel: '[data-row="READ ME FIRST"]' }, agent: { sel: '[data-row="ClipForgeAgent"]' } }
      : { ffmpegExe: { sel: '[data-row="ffmpeg"]' }, ffprobeExe: { sel: '[data-row="ffprobe"]' } };
    await capture(`explorer-${dir}`, win, rows);
  }

  const banner = `/*
 * Generated by promo/tools/capture_guide.mjs. Don't edit it by hand: rerun
 *
 *   node promo/tools/capture_guide.mjs
 *
 * which rewrites this file and the PNGs in public/guide/. Rects are
 * [left, top, width, height] as fractions of each capture, measured off the
 * DOM. Radii and field metrics are in the page's CSS px; cssWidth is the
 * capture's width in those px.
 */
`;
  fs.mkdirSync(path.dirname(CAPTURES_TS), { recursive: true });
  fs.writeFileSync(CAPTURES_TS, `${banner}\nexport const CAPTURES = ${JSON.stringify(captures, null, 2)} as const;\n`);
  console.log(`wrote ${path.relative(REPO, CAPTURES_TS)}`);
} finally {
  ws.close();
  chrome.kill();
  server.close();
}
