// Shows that every check can fail. Each mutant copies site/ to a scratch folder,
// plants one fault there, runs one suite against the copy (E2E_SITE) and expects
// that suite to exit non-zero with a named check failing for the stated reason.
// A mutant that the suite passes, or that fails a different check or for a
// different reason, makes this script exit non-zero. site/ itself is never edited.
import { spawnSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SITE = path.resolve(HERE, "..", "..", "site");

// Replaces `from` with `to` in a file of the copy. The original text must be
// there, so a mutant cannot silently plant nothing after the page changes.
const replace = (file, from, to) => (dir) => {
  const p = path.join(dir, file);
  const s = readFileSync(p, "utf8");
  if (!s.includes(from)) throw new Error(`${file} no longer contains ${JSON.stringify(from)}; update this mutant`);
  writeFileSync(p, s.replace(from, to));
};
const append = (file, text) => (dir) => writeFileSync(path.join(dir, file), readFileSync(path.join(dir, file), "utf8") + text);
const verdict = (key, v) => (dir) => {
  const p = path.join(dir, "data", "verdicts.json");
  const d = JSON.parse(readFileSync(p, "utf8"));
  if (!d.transfers[key]) throw new Error(`verdicts.json has no transfer ${key}; update this mutant`);
  d.transfers[key].verdict = v;
  writeFileSync(p, JSON.stringify(d));
};
const remove = (file) => (dir) => rmSync(path.join(dir, file));
// Gives a `const NAME = "...";` line in a file of the copy another string value,
// whatever its value is now, so the mutant still plants after the value changes.
const setConst = (file, name, value) => (dir) => {
  const p = path.join(dir, file);
  const s = readFileSync(p, "utf8");
  const re = new RegExp(`const ${name} = "[^"]*";`);
  if (!re.test(s)) throw new Error(`${file} no longer has a line const ${name} = "..."; update this mutant`);
  writeFileSync(p, s.replace(re, `const ${name} = ${JSON.stringify(value)};`));
};

const LOAD = "the page loads with no page errors and the first passport is admitted";
const SWORD = "clicking the Diamond Sword in Pocket Battlers is super effective";
const TNT = "dragging TNT onto the Pocket Battlers canvas is refused";
const EMBER = "sending Emberfox to Blockcraft makes Blockcraft mention Ember";
const OVERFLOW = "there is no horizontal overflow";
const MOTION = "the page sees reduced motion";
const LIVE = "the published page finds the live engine";
const JUDGE = "a Diamond Sword forged on the published page is judged by the live engine";

const MUTANTS = [
  ["the Diamond Sword is refused at the border", "desktop.mjs", LOAD, /stamped "Refused, [^"]*", not Admitted/,
    verdict("craft:diamond_sword", "refused")],
  ["an uncaught error is thrown after load", "desktop.mjs", LOAD, /^ +page error: planted by mutants\.mjs$/m,
    append("sprites.js", "\nsetTimeout(() => { throw new Error(\"planted by mutants.mjs\"); }, 0);\n")],
  ["the page logs an error it caught", "desktop.mjs", LOAD, /^ +console error: planted by mutants\.mjs/m,
    replace("app.js", "  boot();", "  console.error(\"planted by mutants.mjs\");\n  boot();")],
  ["the stylesheet is missing", "desktop.mjs", LOAD, /HTTP 404 for \S+\/style\.css/,
    remove("style.css")],
  ["the battle never says super effective", "reduced-motion.mjs", SWORD, /the battle text box never matched \/super effective\/i/,
    replace("battle.js", "It's super effective!", "It hits hard!")],
  ["the TNT is admitted at the border", "desktop.mjs", TNT, /expected the TNT passport stamped .*"stamp":"Admitted/,
    verdict("craft:tnt", "converted")],
  ["a drag never starts", "desktop.mjs", TNT, /the drag did not start/,
    replace("app.js", "if (e.button !== 0) return;", "return;")],
  ["Emberfox is refused at the border", "desktop.mjs", EMBER, /expected the Emberfox passport stamped .*"stamp":"Refused/,
    verdict("battle:emberfox", "refused")],
  ["the pet never names its move in Blockcraft", "desktop.mjs", EMBER, /the craft text box never matched \/\\bEmber\\b\//,
    replace("craft.js", "uses ${s.move || \"an attack\"}", "uses an attack")],
  ["the viewport meta tag is gone", "phone.mjs", OVERFLOW, /on load: the page is laid out 980px wide on a 390px phone/,
    replace("index.html", "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">", "")],
  ["a pseudo-element is wider than the phone", "phone.mjs", OVERFLOW, /on load: the page is \d+px wide on a 390px phone/,
    append("style.css", "\nbody::after { content: \"\"; display: block; width: 500px; height: 1px; }\n")],
  ["opened passport details are wider than the phone", "phone.mjs", OVERFLOW, /details open: the page is \d+px wide on a 390px phone/,
    append("style.css", "\n.pp details ol li { white-space: nowrap; overflow-wrap: normal; }\n")],
  ["the page cannot see reduced motion", "reduced-motion.mjs", MOTION, /does not see prefers-reduced-motion: reduce/,
    replace("index.html", "<script src=\"sprites.js\"></script>",
      "<script>{ const mm = window.matchMedia.bind(window); window.matchMedia = (q) => /reduced-motion/.test(q) ? " +
      "{ matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} } : mm(q); }</script>\n" +
      "<script src=\"sprites.js\"></script>")],
  // site/config.js decides where the published copy sends the forge. Both faults
  // pass every suite that loads the page from 127.0.0.1; only the suite at the
  // published address sees the forge go dark. Neither mutant needs the network:
  // .invalid never resolves, and the wrong host sends the probe to the Pages host.
  ["config.js names a host that is not the engine", "published.mjs", LIVE,
    /did not find the live engine: the forge says "This copy of the page has no engine server/,
    setConst("config.js", "VERCEL_API", "https://engine.invalid")],
  ["config.js sends the engine to some other Pages host", "published.mjs", LIVE,
    /did not find the live engine: the forge says "This copy of the page has no engine server/,
    setConst("config.js", "PAGES_HOST", "github.com")],
  // The engine is found but the forge asks it for a path it does not serve. This
  // one does reach the live engine, as the suite it targets always does.
  ["the forge posts to a path the engine does not serve", "published.mjs", JUDGE,
    /the live engine round trip failed: "The live engine did not answer/,
    replace("app.js", "`${API_BASE}api/judge`", "`${API_BASE}api/no-such-judge`")],
];

const only = process.argv.slice(2);
let bad = 0;
for (const [title, suite, check, reason, plant] of MUTANTS) {
  if (only.length && !only.some((o) => title.includes(o))) continue;
  const dir = mkdtempSync(path.join(tmpdir(), "ap-mutant-"));
  try {
    cpSync(SITE, dir, { recursive: true });
    plant(dir);
    const r = spawnSync(process.execPath, [path.join(HERE, suite)], { env: { ...process.env, E2E_SITE: dir, E2E_ONLY: check }, encoding: "utf8" });
    const out = r.stdout + r.stderr;
    // The failing check's own block: its "not ok" line and the indented message under it.
    const lines = out.split("\n");
    const at = lines.findIndex((l) => l === `not ok - ${check}`);
    const block = at < 0 ? null : [lines[at], ...lines.slice(at + 1).filter((l, k, xs) => xs.slice(0, k + 1).every((y) => y.startsWith("    ")))];
    const killed = r.status !== 0 && block && reason.test(block.join("\n"));
    if (killed) {
      console.log(`killed - ${title} (${suite}, exit ${r.status})\n    ${block.slice(0, 3).join("\n    ")}`);
    } else {
      bad++;
      console.log(`SURVIVED - ${title} (${suite}, exit ${r.status}): expected "not ok - ${check}" matching ${reason}\n    ${out.trim().split("\n").join("\n    ")}`);
    }
  } catch (err) {
    bad++;
    console.log(`BROKEN - ${title}: ${err.message}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
console.log(bad ? `# ${bad} mutant(s) not killed as expected` : "# every mutant was killed by the check it targets");
process.exit(bad ? 1 : 0);
