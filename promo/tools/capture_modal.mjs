// Captures the seven "Connect your channel" modal screens for the YouTube
// setup tutorial, and measures every target in them.
//
//   node promo/tools/capture_modal.mjs
//
// Serves frontend/ statically, opens the app in Remotion's own headless
// Chrome at 2x, steps the modal through renderPublishing(), and writes
// promo/public/step1.png to step7.png with a transparent page behind the card,
// so its rounded corners come through. The backend isn't needed: without it
// the app falls through to its sign-in gate, which is hidden for the capture.
//
// It then prints every ring, button and field as [left, top, width, height]
// fractions of its screenshot: SVG rings by their geometry (the centre of the
// stroke), HTML controls by their bounding boxes. Those are the numbers that
// go into src/tutorial/steps.ts.
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PROMO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FRONTEND = path.resolve(PROMO, "../frontend");
const OUT = path.join(PROMO, "public");
const CDP_PORT = 9333;
const REDIRECT_URI = "https://clipforgee.app/api/youtube/callback";

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

const TYPES = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml" };
const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  let file = null;
  if (url.pathname === "/" || url.pathname === "/app") file = path.join(FRONTEND, "index.html");
  else if (url.pathname.startsWith("/static/")) file = path.join(FRONTEND, url.pathname.slice(8));
  if (!file || !fs.existsSync(file)) {
    res.writeHead(404, { "content-type": "application/json" });
    res.end("{}");
    return;
  }
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const PAGE = `http://127.0.0.1:${server.address().port}/`;

const profile = fs.mkdtempSync(path.join(os.tmpdir(), "cf-capture-"));
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

try {
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1100, height: 1100, deviceScaleFactor: 2, mobile: false });
  await send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } });
  await send("Page.navigate", { url: PAGE });
  for (let i = 0; i < 100 && (await evaluate("document.readyState")) !== "complete"; i++) await sleep(100);
  await evaluate("document.fonts.ready.then(() => true)");
  await sleep(800); // boot() asks for /api/me, gets a 404 and shows the gate

  await evaluate(`(() => {
    const st = document.createElement('style');
    st.textContent = \`
      html, body { background: transparent !important; }
      html::before, html::after, body::before, body::after { display: none !important; }
      body * { visibility: hidden !important; }
      #pub, #pub * { visibility: visible !important; }
      #pub { background: transparent !important; backdrop-filter: none !important; -webkit-backdrop-filter: none !important; }
      #pub .guide-card { box-shadow: none !important; }
      #pub .hidden { display: none !important; }
      *, *::before, *::after { transition: none !important; animation: none !important; caret-color: transparent !important; }\`;
    document.head.appendChild(st);
    state.pubApp = { redirect_uri: '${REDIRECT_URI}', client_id: '', has_secret: false };
    document.getElementById('pub').classList.remove('hidden');
    return true;
  })()`);

  const report = [];
  for (let i = 0; i < 7; i++) {
    const info = await evaluate(`(async () => {
      pubAt = ${i}; renderPublishing();
      document.activeElement && document.activeElement.blur();
      await document.fonts.ready;
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      const card = document.querySelector('#pub .guide-card').getBoundingClientRect();
      const f = (l, t, w, h) => [l - card.left, t - card.top, w, h].map((v, k) => +(v / (k % 2 ? card.height : card.width)).toFixed(4));
      const box = (el) => { const r = el.getBoundingClientRect(); return f(r.left, r.top, r.width, r.height); };
      const geo = (el) => {
        const m = el.getScreenCTM();
        const x = +el.getAttribute('x'), y = +el.getAttribute('y'), w = +el.getAttribute('width'), h = +el.getAttribute('height');
        return f(m.e + m.a * x, m.f + m.d * y, m.a * w, m.d * h);
      };
      const q = (s) => { const el = document.querySelector(s); return el && el.offsetParent !== null ? box(el) : undefined; };
      return {
        step: ${i + 1},
        rings: [...document.querySelectorAll('#pub .pub-svg rect[fill="none"]')].map(geo),
        accentFields: [...document.querySelectorAll('#pub .pub-svg rect[stroke="var(--accent)"]:not([fill="none"])')].map(geo),
        next: q('#pub-next'),
        copyRow: q('#pub .pub-copy'),
        copyButton: q('#pub-copy-btn'),
        warning: q('#pub .hint.warn'),
        clientId: q('#pub [data-field=client_id]'),
        clientSecret: q('#pub [data-field=client_secret]'),
        clip: { x: card.left, y: card.top, width: card.width, height: card.height },
      };
    })()`);
    const shot = await send("Page.captureScreenshot", { format: "png", clip: { ...info.clip, scale: 1 }, fromSurface: true });
    const png = Buffer.from(shot.data, "base64");
    fs.writeFileSync(path.join(OUT, `step${i + 1}.png`), png);
    delete info.clip;
    info.size = [png.readUInt32BE(16), png.readUInt32BE(20)];
    report.push(info);
    console.error(`wrote public/step${i + 1}.png, ${info.size[0]}x${info.size[1]}`);
  }
  console.log(JSON.stringify(report, null, 2));
} finally {
  ws.close();
  chrome.kill();
  server.close();
}
