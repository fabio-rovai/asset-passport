// Shared harness for the browser tests. It serves site/ exactly as GitHub Pages
// would (static files only, no engine, no /api), opens it in Chromium and drives
// it with real pointer events. There is no test framework: a suite prints one
// line per check and exits non-zero when any check fails.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const SITE = path.resolve(HERE, "..", "..", "site");
const SYSTEM_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

// Which browser to drive. E2E_CHROME may name an executable, or say "bundled"
// for Playwright's own Chromium. Without it, CI uses the bundled Chromium and a
// local run uses the system Chrome when it is installed.
function browserOptions() {
  const env = process.env.E2E_CHROME;
  if (env && env !== "bundled") return { executablePath: env, label: env };
  if (env === "bundled" || process.env.CI) return { label: "bundled chromium" };
  if (existsSync(SYSTEM_CHROME)) return { executablePath: SYSTEM_CHROME, label: "system Chrome" };
  return { label: "bundled chromium" };
}

// python3 -m http.server on a free port, bound to loopback. Resolves with the base URL.
export function serve() {
  return new Promise((resolve, reject) => {
    const proc = spawn("python3", ["-u", "-m", "http.server", "0", "--bind", "127.0.0.1", "--directory", SITE],
      { stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    const timer = setTimeout(() => { proc.kill(); reject(new Error(`http.server did not start: ${out}`)); }, 15000);
    const onData = (buf) => {
      out += buf.toString();
      const m = out.match(/port (\d+)/);
      if (m) { clearTimeout(timer); resolve({ url: `http://127.0.0.1:${m[1]}/`, stop: () => proc.kill() }); }
    };
    proc.stdout.on("data", onData);
    proc.stderr.on("data", (b) => { out += b.toString(); });
    proc.on("exit", (code) => { clearTimeout(timer); reject(new Error(`http.server exited with ${code}: ${out}`)); });
  });
}

// Records every value the two game text boxes take. The battle text box moves on
// within a second (and at once under reduced motion), so polling its current text
// would miss lines; a MutationObserver sees each one.
const RECORDER = () => {
  window.__logs = { craft: [], battle: [] };
  document.addEventListener("DOMContentLoaded", () => {
    for (const game of ["craft", "battle"]) {
      const el = document.getElementById(`${game}-log`);
      if (!el) continue;
      new MutationObserver(() => window.__logs[game].push(el.textContent))
        .observe(el, { childList: true, characterData: true, subtree: true });
    }
  });
};

// Opens a fresh page, collects page errors and failed same-origin requests, and
// waits for the first passport to be on the desk.
export async function openPage(browser, base, contextOptions) {
  const context = await browser.newContext(contextOptions);
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const problems = [];
  page.on("pageerror", (err) => problems.push(`page error: ${err.message}`));
  page.on("response", (r) => {
    const u = r.url();
    // The static page has no engine server: the probe of api/engine is expected to 404.
    if (u.startsWith(base) && !u.startsWith(base + "api/") && r.status() >= 400) problems.push(`HTTP ${r.status()} for ${u}`);
  });
  page.on("requestfailed", (r) => { if (r.url().startsWith(base)) problems.push(`request failed: ${r.url()}`); });
  await page.addInitScript(RECORDER);
  await page.goto(base);
  await page.locator("#passport .stamp").waitFor();
  return { page, context, problems };
}

// Waits until one of the lines a game text box showed matches the pattern.
export async function waitForLog(page, game, pattern, timeout = 15000) {
  try {
    await page.waitForFunction(([g, src, flags]) => window.__logs[g].some((t) => new RegExp(src, flags).test(t)),
      [game, pattern.source, pattern.flags], { timeout });
  } catch (_) {
    const seen = await page.evaluate((g) => window.__logs[g], game);
    throw new Error(`the ${game} text box never matched ${pattern}. It showed:\n    ${seen.map((s) => JSON.stringify(s)).join("\n    ")}`);
  }
}

// The passport currently on the desk: its name and the stamp's accessible name.
export async function passport(page) {
  const pp = page.locator("#passport .pp");
  return {
    name: (await pp.locator(".pp-name").textContent()).trim(),
    stamp: await pp.getByRole("img").getAttribute("aria-label"),
  };
}

// Waits for a passport for `name` whose stamp's accessible name matches `stamp`.
export async function expectPassport(page, name, stamp) {
  const pp = page.locator("#passport .pp").filter({ has: page.locator(".pp-name", { hasText: name }) });
  try {
    await pp.getByRole("img", { name: stamp }).waitFor();
  } catch (_) {
    const now = await passport(page).catch(() => null);
    throw new Error(`expected the ${name} passport stamped ${stamp}; the desk shows ${JSON.stringify(now)}`);
  }
}

export function check(cond, message) { if (!cond) throw new Error(message); }

// Runs a list of named checks, each on a fresh page in a fresh context.
export async function suite(title, contextOptions, tests) {
  const opts = browserOptions();
  const server = await serve();
  const browser = await chromium.launch({ headless: true, executablePath: opts.executablePath });
  console.log(`# ${title} (${opts.label} ${browser.version()}, ${server.url})`);
  let failed = 0;
  for (const [name, fn] of tests) {
    let opened = null;
    try {
      opened = await openPage(browser, server.url, contextOptions);
      await fn(opened.page);
      check(opened.problems.length === 0, opened.problems.join("\n"));
      console.log(`ok - ${name}`);
    } catch (err) {
      failed++;
      console.log(`not ok - ${name}\n    ${String(err.message || err).split("\n").join("\n    ")}`);
    } finally {
      if (opened) await opened.context.close();
    }
  }
  await browser.close();
  server.stop();
  console.log(`# ${tests.length - failed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
}
