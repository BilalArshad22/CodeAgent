// Records a real CodeAgent run: launches the Electron app with remote debugging,
// captures the window via the DevTools screencast, clicks "Start Generation",
// and timestamps the run's milestones so build.py can cut scenes to the narration.
//
//   node video/record.mjs <rawDir>        (settings.json must already be prepared)

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
const DRY = args.includes('--dry');   // record the idle UI only; never starts a (paid) run
const OUT = path.resolve(args.find((a) => !a.startsWith('--')) || path.join(import.meta.dirname, 'raw'));
const DESKTOP = path.resolve(import.meta.dirname, '..', 'desktop');
const PORT = 9335;
const RUN_TIMEOUT_MS = 30 * 60 * 1000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const now = () => Date.now() / 1000;

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(path.join(OUT, 'frames'), { recursive: true });

const env = { ...process.env };
delete env.NODE_ENV;              // production path: load dist/index.html
delete env.CODEAGENT_DEMO;        // must be a real run
delete env.CODEAGENT_DEVTOOLS;
const app = spawn(path.join(DESKTOP, 'node_modules', '.bin', 'electron'), ['.', `--remote-debugging-port=${PORT}`],
  { cwd: DESKTOP, env, stdio: ['ignore', 'ignore', 'pipe'] });
app.stderr.on('data', (d) => fs.appendFileSync(path.join(OUT, 'electron.log'), d));

class CDP {
  constructor(url) { this.ws = new WebSocket(url); this.n = 0; this.pending = new Map(); this.handlers = {}; }
  async open() {
    await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = rej; });
    this.ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) { this.pending.get(m.id)(m); this.pending.delete(m.id); }
      else if (m.method && this.handlers[m.method]) this.handlers[m.method](m.params);
    };
  }
  send(method, params = {}) {
    const id = ++this.n;
    return new Promise((res) => { this.pending.set(id, res); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  on(method, fn) { this.handlers[method] = fn; }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    return r.result?.result?.value;
  }
}

async function connect() {
  for (let i = 0; i < 60; i++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      const page = targets.find((t) => t.type === 'page' && t.url.includes('index.html'));
      if (page) { const c = new CDP(page.webSocketDebuggerUrl); await c.open(); return c; }
    } catch { /* not up yet */ }
    await sleep(500);
  }
  throw new Error('app did not expose a debuggable page');
}

const marks = {};
const mark = (name) => { if (!(name in marks)) { marks[name] = now(); console.log(`mark ${name}`); } };
const frames = [];
let viewport = null;
let maxFps = 30;          // 30 fps for smooth parts; lowered during the long run (it is sped up anyway)
let lastSaved = 0;

const cdp = await connect();
await cdp.send('Page.enable');
cdp.on('Page.javascriptDialogOpening', async (p) => {
  console.log(`dialog: ${p.message}`);
  if (p.type === 'alert') marks.alert = p.message;
  await cdp.send('Page.handleJavaScriptDialog', { accept: true });   // e.g. "folder not empty, overwrite?"
});
cdp.on('Page.screencastFrame', async (p) => {
  if (p.metadata.timestamp - lastSaved < 1 / maxFps) {
    await cdp.send('Page.screencastFrameAck', { sessionId: p.sessionId });
    return;
  }
  lastSaved = p.metadata.timestamp;
  const file = `f${String(frames.length).padStart(6, '0')}.jpg`;
  fs.writeFileSync(path.join(OUT, 'frames', file), Buffer.from(p.data, 'base64'));
  frames.push({ file, t: p.metadata.timestamp });
  viewport ??= { width: p.metadata.deviceWidth, height: p.metadata.deviceHeight };
  await cdp.send('Page.screencastFrameAck', { sessionId: p.sessionId });
});

// Frames arrive only on repaint; build.py holds each one until the next, so static
// stretches (e.g. waiting on the model) stay correct in time.
await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 88, maxWidth: 1920, maxHeight: 1920, everyNthFrame: 1 });

const text = () => cdp.eval('document.body.innerText');
const clickButton = (label) => cdp.eval(`(() => {
  const b = [...document.querySelectorAll('button')].find(x => x.innerText.trim().startsWith(${JSON.stringify(label)}));
  if (!b) return false; b.click(); return true; })()`);

try {
  // 1. Idle app (splash finished, settings loaded)
  for (let i = 0; !(await text())?.includes('Start Generation'); i++) {
    if (i > 120) throw new Error('UI never became ready');
    await sleep(500);
  }
  await sleep(1500);
  mark('idle');
  await sleep(7000);

  if (DRY) throw Object.assign(new Error('dry run: stopped before starting generation'), { dry: true });

  // 2. Start the real run
  if (!(await clickButton('Start Generation'))) throw new Error('Start Generation button not found');
  mark('start');
  maxFps = 8;

  const deadline = Date.now() + RUN_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const t = (await text()) || '';
    if (/preprocessing/i.test(t)) mark('preprocess');
    if (/live process/i.test(t)) mark('plan');
    // Only the transcript counts: plan items such as "Write unit tests" must not trigger this.
    const log = (await cdp.eval(`document.querySelector('[data-transcript]')?.innerText || ''`)) || '';
    if (/^\s*Write\b/m.test(log)) mark('writing');
    if (/finish rejected/i.test(t)) mark('rejected');
    if (/Generation Complete|Stopped:/i.test(t)) { mark('done'); break; }
    if (marks.alert) throw new Error(`app refused to start: ${marks.alert}`);
    await sleep(500);
  }
  if (!marks.done) {
    await clickButton('Stop Generation');
    throw new Error('run timed out');
  }
  await sleep(5000);

  // 3. Recap: scroll the transcript from the top back down to the result card
  await cdp.eval(`(() => { const p = document.querySelector('[data-transcript]'); if (p) p.scrollTo({ top: 0 }); })()`);
  await sleep(1200);
  maxFps = 30;
  mark('recap_start');
  await cdp.eval(`new Promise(resolve => {
    const p = document.querySelector('[data-transcript]');
    if (!p) return resolve();
    const start = performance.now(), dur = 12000, max = p.scrollHeight - p.clientHeight;
    const step = (ts) => { const k = Math.min(1, (ts - start) / dur);
      p.scrollTop = max * (k < .5 ? 2*k*k : 1 - Math.pow(-2*k + 2, 2) / 2);
      k < 1 ? requestAnimationFrame(step) : resolve(); };
    requestAnimationFrame(step);
  })`);
  mark('recap_end');
  await sleep(2500);
} catch (e) {
  if (!e.dry) { console.error(e.message); process.exitCode = 1; } else console.log(e.message);
} finally {
  marks.end = now();
  await cdp.send('Page.stopScreencast').catch(() => {});
  fs.writeFileSync(path.join(OUT, 'recording.json'), JSON.stringify({ frames, marks, viewport }, null, 1));
  app.kill('SIGTERM');
  console.log(`saved ${frames.length} frames to ${OUT}`);
}
