// Records the README's demo from the page in site/, as a visitor would see it:
// the Crystal Sword used as a move in Pocket Battlers, the Blast Block dragged
// into Pocket Battlers and refused, Emberfox dragged into Blockcraft, and the
// Sunfruit dragged into Pocket Battlers and admitted with its losses named.
//
//   (cd tests/e2e && npm ci) && node scripts/record_demo.mjs
//
// It uses Playwright from tests/e2e/node_modules and the system Chrome
// (E2E_CHROME names another executable), serves site/ on a loopback port the
// way the browser tests do, records the tab with Chrome's own screencast as
// lossless PNG frames, and writes docs/assets/demo.mp4, docs/assets/demo.gif
// and docs/assets/still.png with ffmpeg. Nothing on screen is staged: every
// verdict comes from site/data/verdicts.json, and the page is not modified.
// The one addition is a dot that shows where the pointer is.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../tests/e2e/node_modules/playwright/index.mjs";
import { serve } from "../tests/e2e/lib.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(ROOT, "docs", "assets");
const W = 1440, H = 810;                 // the viewport, and the size of each frame
const GIF_W = 840, GIF_FPS = 8, GIF_COLOURS = 128, GIF_LIMIT = 6 * 1024 * 1024;
const MP4_FPS = 25;
const CHROME = process.env.E2E_CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

function run(cmd, args) {
  const r = spawnSync(cmd, args, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (r.status !== 0) throw new Error(`${cmd} ${args.join(" ")} exited ${r.status}:\n${r.stderr}`);
  return r;
}

// A dot that follows the mouse, so a viewer sees where each click and drag
// starts. It is added by this recording (an init script), never by site/, and
// it takes no pointer events, so the page's own hit tests never see it.
const POINTER = () => {
  addEventListener("DOMContentLoaded", () => {
    const dot = document.createElement("div");
    dot.setAttribute("aria-hidden", "true");
    dot.style.cssText = "position:fixed;left:-40px;top:-40px;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;" +
      "background:rgba(39,71,168,0.35);border:2px solid #2747a8;pointer-events:none;z-index:99999;transition:transform 120ms;";
    document.body.append(dot);
    addEventListener("pointermove", (e) => { dot.style.left = e.clientX + "px"; dot.style.top = e.clientY + "px"; }, true);
    addEventListener("pointerdown", () => { dot.style.transform = "scale(0.7)"; }, true);
    addEventListener("pointerup", () => { dot.style.transform = ""; }, true);
  });
};

async function centre(locator) {
  await locator.scrollIntoViewIfNeeded();
  const b = await locator.boundingBox();
  if (!b) throw new Error(`no box on screen for ${locator}`);
  return [b.x + b.width / 2, b.y + b.height / 2];
}

// The page holds one lock for a turn and for a crossing, and marks it with the
// "acting" class on <body>; this waits until the lock is free.
const idle = (page) => page.waitForFunction(() => !document.body.classList.contains("acting"), null, { timeout: 60000 });

async function stamped(page, name, stamp) {
  await page.locator("#passport").getByRole("article")
    .filter({ has: page.getByRole("heading", { name, exact: true }) })
    .getByRole("img", { name: stamp }).waitFor({ timeout: 60000 });
}

async function drag(page, from, to) {
  const a = await centre(from);
  const b = await centre(to);
  await page.mouse.move(a[0], a[1], { steps: 25 });
  await page.waitForTimeout(250);
  await page.mouse.down();
  await page.mouse.move(a[0] + 12, a[1] + 4, { steps: 4 });
  await page.mouse.move(b[0], b[1], { steps: 40 });
  await page.waitForTimeout(250);
  await page.mouse.up();
}

// Chrome's screencast sends a frame each time the tab repaints, with the time
// it was painted. Each frame is written to disk as it arrives.
async function screencast(context, page, dir) {
  const cdp = await context.newCDPSession(page);
  const frames = [];
  let writing = Promise.resolve();
  cdp.on("Page.screencastFrame", (f) => {
    const file = path.join(dir, `f${String(frames.length).padStart(5, "0")}.png`);
    frames.push({ file, t: f.metadata.timestamp });
    writing = writing.then(() => writeFileSync(file, Buffer.from(f.data, "base64")));
    cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
  });
  await cdp.send("Page.startScreencast", { format: "png", maxWidth: W, maxHeight: H, everyNthFrame: 1 });
  return async () => {
    await cdp.send("Page.stopScreencast");
    await writing;
    return frames;
  };
}

async function record(dir) {
  const browser = await chromium.launch({ headless: true, executablePath: existsSync(CHROME) ? CHROME : undefined });
  const server = await serve();
  try {
    const context = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
    await context.addInitScript(POINTER);
    const page = await context.newPage();
    page.setDefaultTimeout(30000);
    await page.goto(server.url);
    await stamped(page, "Crystal Sword", /^Admitted\b/);
    await page.evaluate(() => document.fonts.ready);
    const stop = await screencast(context, page, dir);
    await page.waitForTimeout(1800);
    // From the masthead down to the stage: both games and the desk.
    await page.locator("#craft").evaluate((el) => window.scrollTo({ top: el.getBoundingClientRect().top + scrollY - 12, behavior: "smooth" }));
    await page.waitForTimeout(1200);

    // 1. The Crystal Sword came over from Blockcraft when the page opened. Use it as a move.
    const [sx, sy] = await centre(page.locator("#battle-inv").getByRole("button", { name: "Use Crystal Sword" }));
    await page.mouse.move(sx, sy, { steps: 30 });
    await page.waitForTimeout(300);
    await page.mouse.click(sx, sy);
    await page.waitForTimeout(200);
    await idle(page);
    await page.waitForTimeout(800);

    // 2. The Blast Block into Pocket Battlers: refused at the border.
    await drag(page, page.locator("#craft-inv").getByRole("button", { name: "Use Blast Block" }), page.locator("#battle-canvas"));
    await stamped(page, "Blast Block", /^Refused\b/);
    await idle(page);
    await page.waitForTimeout(2200);

    // 3. Emberfox into Blockcraft: a pet that uses its move on the zombie.
    await drag(page, page.locator("#battle-inv").getByRole("button", { name: "Use Emberfox" }), page.locator("#craft-canvas"));
    await stamped(page, "Emberfox", /^Admitted\b/);
    await idle(page);
    await page.waitForTimeout(2000);

    // 4. The Sunfruit into Pocket Battlers: admitted, and its passport names the extra hearts as a loss.
    await drag(page, page.locator("#craft-inv").getByRole("button", { name: "Use Sunfruit" }), page.locator("#battle-canvas"));
    await stamped(page, "Sunfruit", /^Admitted\b/);
    await idle(page);
    await page.mouse.move(W - 40, H - 40, { steps: 20 });
    await page.waitForTimeout(2500);
    const still = path.join(dir, "still-page.png");
    await page.screenshot({ path: still });
    const frames = await stop();
    await context.close();
    return { frames, still };
  } finally {
    await browser.close();
    server.stop();
  }
}

function size(file) {
  const r = run("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", file]);
  const [w, h] = r.stdout.trim().split(",").map(Number);
  return { w, h };
}

// Rows at the bottom of a frame that the screencast never painted. A frame is
// read as raw RGB, and a bottom row counts as unpainted when every pixel in it
// has the colour of the bottom-left pixel. The page never paints a flat row
// there by itself: its background is a guilloche pattern. The band kept is the
// smallest found in any sampled frame, so nothing painted is ever cropped.
function unpaintedBottom(files) {
  let band = Infinity;
  for (const file of files) {
    const { w, h } = size(file);
    const r = spawnSync("ffmpeg", ["-v", "error", "-i", file, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], { maxBuffer: w * h * 3 + 1024 });
    if (r.status !== 0) throw new Error(`ffmpeg could not read ${file}: ${r.stderr}`);
    const px = r.stdout;
    const at = (x, y, c) => px[(y * w + x) * 3 + c];
    const same = (x, y) => [0, 1, 2].every((c) => at(x, y, c) === at(0, h - 1, c));
    let rows = 0;
    for (let y = h - 1; y >= 0; y--) {
      let flat = true;
      for (let x = 0; x < w; x++) if (!same(x, y)) { flat = false; break; }
      if (!flat) break;
      rows++;
    }
    console.log(`${path.basename(file)}: ${w}x${h}, ${rows} unpainted row(s) at the bottom (rgb ${at(0, h - 1, 0)}, ${at(0, h - 1, 1)}, ${at(0, h - 1, 2)})`);
    band = Math.min(band, rows);
  }
  return band;
}

const dir = mkdtempSync(path.join(tmpdir(), "ap-demo-"));
try {
  const framesDir = path.join(dir, "frames");
  mkdirSync(framesDir);
  const { frames, still } = await record(framesDir);
  if (frames.length < 10) throw new Error(`the screencast sent only ${frames.length} frames`);
  const secs = frames[frames.length - 1].t - frames[0].t;
  const { w, h } = size(frames[0].file);
  // Each frame is shown until the next one arrives; the last one is held for a second.
  const list = frames.map((f, i) => `file '${f.file}'\nduration ${(i + 1 < frames.length ? frames[i + 1].t - f.t : 1).toFixed(4)}`);
  writeFileSync(path.join(dir, "frames.txt"), `ffconcat version 1.0\n${list.join("\n")}\nfile '${frames[frames.length - 1].file}'\n`);
  const sample = [0, 0.2, 0.4, 0.6, 0.8, 1].map((k) => frames[Math.min(frames.length - 1, Math.round(k * (frames.length - 1)))].file);
  const band = unpaintedBottom(sample);
  const keep = (h - band) - ((h - band) % 2);   // H.264 wants an even height
  console.log(`${frames.length} frames over ${secs.toFixed(1)} s at ${w}x${h}; unpainted rows at the bottom: ${band}; keeping ${w}x${keep}`);
  const crop = `crop=${w}:${keep}:0:0`;
  const input = ["-f", "concat", "-safe", "0", "-i", path.join(dir, "frames.txt")];
  run("ffmpeg", ["-y", "-v", "error", ...input, "-vf", `${crop},fps=${MP4_FPS}`, "-c:v", "libx264", "-pix_fmt", "yuv420p",
    "-crf", "20", "-preset", "slow", "-movflags", "+faststart", "-an", path.join(OUT, "demo.mp4")]);
  const palette = path.join(dir, "palette.png");
  const scale = `${crop},fps=${GIF_FPS},scale=${GIF_W}:-2:flags=lanczos`;
  run("ffmpeg", ["-y", "-v", "error", ...input, "-vf", `${scale},palettegen=max_colors=${GIF_COLOURS}:stats_mode=diff`, palette]);
  run("ffmpeg", ["-y", "-v", "error", ...input, "-i", palette, "-lavfi",
    `${scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle`, path.join(OUT, "demo.gif")]);
  run("ffmpeg", ["-y", "-v", "error", "-i", still, "-vf", crop, path.join(OUT, "still.png")]);
  for (const f of ["demo.mp4", "demo.gif", "still.png"]) {
    const s = size(path.join(OUT, f));
    console.log(`wrote docs/assets/${f}: ${s.w}x${s.h}, ${statSync(path.join(OUT, f)).size} bytes`);
  }
  const gif = statSync(path.join(OUT, "demo.gif")).size;
  if (gif > GIF_LIMIT) throw new Error(`demo.gif is ${gif} bytes, over the ${GIF_LIMIT}-byte limit; lower GIF_FPS or GIF_COLOURS`);
} finally {
  rmSync(dir, { recursive: true, force: true });
}
