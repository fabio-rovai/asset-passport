// The things a visitor does on the page, each written as a check. Elements are
// found by role, id and visible text, never by how many border gates there are.
// An inventory slot is a <button> named "Use <item>" inside a list item, so
// slots are found as buttons by that name.
// The one thing read from classes is the drag state on #battle (drop-ready,
// drop-hot), because the page exposes no ARIA state for a drag in progress.
import { check, expectPassport, passport, waitForLog } from "./lib.mjs";

export async function firstPassportAdmitted(page) {
  const now = await passport(page);
  check(now.name === "Crystal Sword", `the first passport is for ${JSON.stringify(now.name)}, not the Crystal Sword`);
  check(/^Admitted\b/.test(now.stamp), `the first passport is stamped ${JSON.stringify(now.stamp)}, not Admitted`);
}

// The line is built from the type chart: Rock against the Fire-type wild creature is x2.
export async function swordDoesDoubleDamage(page) {
  const before = await page.evaluate(() => window.__logs.battle.slice());
  check(!before.some((t) => /double damage/i.test(t)), "the battle text box said double damage before anything was clicked");
  await page.locator("#battle-inv").getByRole("button", { name: "Use Crystal Sword" }).click();
  await waitForLog(page, "battle", /Rock beats Fire: double damage\./);
}

export async function blastBlockDragIsRefused(page) {
  const block = page.locator("#craft-inv").getByRole("button", { name: "Use Blast Block" });
  const target = page.locator("#battle-canvas");
  await block.scrollIntoViewIfNeeded();
  const from = await block.boundingBox();
  const to = await target.boundingBox();
  const vh = page.viewportSize().height;
  check(from && to, "the Blast Block slot or the Pocket Battlers canvas has no box on screen");
  check(to.y + to.height / 2 > 0 && to.y + to.height / 2 < vh,
    `the Pocket Battlers canvas centre is off screen (y ${Math.round(to.y + to.height / 2)}, viewport ${vh}), so it cannot be a drop target`);
  const [x0, y0] = [from.x + from.width / 2, from.y + from.height / 2];
  const [x1, y1] = [to.x + to.width / 2, to.y + to.height / 2];
  await page.mouse.move(x0, y0);
  await page.mouse.down();
  await page.mouse.move(x0 + 12, y0 + 4, { steps: 3 });
  // The page exposes no ARIA state for a drag in progress, so the drop target's
  // state is read from the classes the page sets on #battle while dragging.
  const battleHas = (cls) => page.locator("#battle").evaluate((el, c) => el.classList.contains(c), cls);
  check(await battleHas("drop-ready"), "the drag did not start: Pocket Battlers is not marked as a drop target");
  await page.mouse.move(x1, y1, { steps: 20 });
  check(await battleHas("drop-hot"), "Pocket Battlers is not lit as the drop target with the pointer over its canvas");
  await page.mouse.up();
  await expectPassport(page, "Blast Block", /^Refused\b/);
  // A refused thing goes home: it is back in the hotbar, and the battle side never received it.
  await page.locator("#craft-inv").getByRole("button", { name: "Use Blast Block" }).waitFor();
  check(await page.locator("#battle-inv").getByRole("button", { name: "Use Blast Block" }).count() === 0,
    "the refused Blast Block appeared in Pocket Battlers");
}

export async function emberfoxSendReachesBlockcraft(page) {
  await page.locator("#battle-inv").getByRole("button", { name: "Send Emberfox to Blockcraft" }).click();
  await expectPassport(page, "Emberfox", /^Admitted\b/);
  // The move's name, Cinder Puff, is in the craft text box only once the pet has used it.
  await waitForLog(page, "craft", /\bCinder Puff\b/);
}

// The phone layout must be laid out at the phone's width. Without a working
// viewport meta tag, Chrome's mobile emulation lays the page out 980 CSS px wide
// and nothing overflows that, so the layout viewport (clientWidth) is checked
// against 390 first, and every width is then compared with 390, not with what
// the page reports. On a phone, content wider than the layout viewport also
// widens the visual viewport (innerWidth), because the browser zooms out to fit
// it, so innerWidth counts as overflow rather than as a lost layout.
export const PHONE_WIDTH = 390;

// Fails when the page, laid out at the phone's width, is wider than the phone.
async function fitsThePhone(page, when) {
  const W = PHONE_WIDTH;
  const measure = () => page.evaluate((w) => {
    // The elements past the edge that have no child past it: the ones that push
    // the page wide, rather than every ancestor they stretch.
    const past = (el) => el.getBoundingClientRect().right > w + 0.5 && getComputedStyle(el).position !== "fixed";
    const wide = [...document.querySelectorAll("body *")]
      .filter((el) => past(el) && ![...el.children].some(past))
      .slice(0, 5).map((el) => `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}.${el.className} right=${Math.round(el.getBoundingClientRect().right)}`);
    return { cw: document.documentElement.clientWidth, iw: window.innerWidth,
      sw: document.documentElement.scrollWidth, bw: document.body.scrollWidth, wide };
  }, W);
  const m = await measure();
  check(m.cw === W,
    `${when}: the page is laid out ${m.cw}px wide on a ${W}px phone, so it has lost its phone layout. Check the viewport meta tag.`);
  check(m.sw <= W && m.bw <= W && m.iw <= W,
    `${when}: the page is ${Math.max(m.sw, m.bw, m.iw)}px wide on a ${W}px phone. ` +
    (m.wide.length ? `Elements past the edge: ${m.wide.join("; ")}` : "No element box crosses the edge, so look at pseudo-elements, margins and transforms."));
}

export async function noHorizontalOverflow(page) {
  const W = PHONE_WIDTH;
  const look = (when) => fitsThePhone(page, when);
  check(page.viewportSize().width === W, `the viewport is ${page.viewportSize().width}px wide, not ${W}px`);
  await look("on load");
  // A passport with its details opened is the widest thing the desk shows. The
  // details are opened in one step rather than by clicking each summary: once
  // the first one overflows, the next summary can be pushed out of reach, and the
  // failure would be a click timeout instead of the measurement below.
  await page.locator("#battle-inv").getByRole("button", { name: "Send Emberfox to Blockcraft" }).click();
  await expectPassport(page, "Emberfox", /^Admitted\b/);
  const groups = page.locator("#passport").getByRole("group");
  const opened = await groups.evaluateAll((ds) => ds.filter((d) => d.tagName === "DETAILS").map((d) => (d.open = true)).length);
  check(opened > 0, "the Emberfox passport has no details to open, so the widest state was not measured");
  await look(`after sending Emberfox, with the passport's ${opened} details open`);
}

export async function reducedMotionIsOn(page) {
  check(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches),
    "the page does not see prefers-reduced-motion: reduce, so this suite would test nothing new");
}

// The two checks below run only at the published address (published.mjs), where
// site/config.js sends the forge to the live engine. They need the network: the
// engine is the real deployment, reached from the Pages origin, so its CORS
// answer for that origin is part of what they check.
const LIVE_WAIT = 60000; // a cold serverless start can take several seconds

export async function liveEngineFound(page) {
  const engine = page.locator("#forge-engine");
  await page.waitForFunction(() => document.getElementById("forge-engine").textContent.trim() !== "", null, { timeout: LIVE_WAIT });
  const text = (await engine.textContent()).trim();
  check(/^Live engine: open-ontologies \S+, sha256 [0-9a-f]{12}/.test(text),
    `the published page did not find the live engine: the forge says ${JSON.stringify(text)}`);
  check(await page.locator("#forge-send").isEnabled(), "the published page found the live engine but left the Send button disabled");
}

export async function liveEngineJudges(page) {
  await liveEngineFound(page);
  await page.locator("#forge-game").selectOption({ label: "Blockcraft" });
  await page.locator("#forge-kind").selectOption({ label: "Crystal Sword" });
  await page.locator("#forge-send").click();
  const status = page.locator("#forge-status");
  try {
    await page.waitForFunction(() => /^The live engine (answered|did not answer)/.test(document.getElementById("forge-status").textContent),
      null, { timeout: LIVE_WAIT });
  } catch (_) {
    throw new Error(`the live engine never answered; the forge status says ${JSON.stringify(await status.textContent())}`);
  }
  const said = (await status.textContent()).trim();
  check(/^The live engine answered in \d+ ms\.$/.test(said), `the live engine round trip failed: ${JSON.stringify(said)}`);
  const result = page.locator("#forge-result");
  check(await result.isVisible(), "the live engine answered but the forge shows no result");
  // A Crystal Sword with its catalogue stats is the first passport on the desk,
  // admitted; the live engine must say the same about it.
  const stamp = (await result.locator("b").textContent()).trim();
  check(/^Admitted\b/.test(stamp), `the live engine stamped a catalogue Crystal Sword ${JSON.stringify(stamp)}, not Admitted`);
}

// ------------------------------------------------------------ the live forge, answered by a stand-in
// These checks answer api/engine and api/judge from the test itself
// (page.route), then reload the page so it finds that "engine" at boot. They
// need no engine and no network; what they pin is how the page shows a reply.

const ENGINE_INFO = { tag: "test", binary_sha256: "0".repeat(64), oo_cert_sha256: null, oo_shacl_sha256: null };

async function standInEngine(page, judgeReply) {
  await page.route("**/api/engine", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ENGINE_INFO) }));
  await page.route("**/api/judge", judgeReply);
  await page.reload();
  await page.locator("#passport").getByRole("img", { name: /^(Admitted|Refused)\b/ }).waitFor();
  await page.waitForFunction(() => !document.getElementById("forge-send").disabled);
}

async function forgeSword(page) {
  await page.locator("#forge-game").selectOption({ label: "Blockcraft" });
  await page.locator("#forge-kind").selectOption({ label: "Crystal Sword" });
  await page.locator("#forge-send").click();
}

// The forge's status line once the request has come back, whatever it says.
async function forgeSaid(page) {
  await page.waitForFunction(() => { const t = document.getElementById("forge-status").textContent;
    return t && !/^Sending/.test(t); });
  return (await page.locator("#forge-status").textContent()).trim();
}

const gate = (page, g) => page.locator(`.gate[data-gate="${g}"]`).evaluate((li) =>
  ({ state: li.dataset.state, chip: li.querySelector(".chip").textContent, note: li.querySelector(".gd").textContent }));

// An undetermined verdict at the unpack gate (no Lean checker on the server).
// The page used to draw unpack as a pass ("Lean accepted undefined steps") and
// hold the border, which the item never reached.
export async function undeterminedHoldsItsGate(page) {
  const why = "This machine has no Lean checker (oo-cert), so the proof was not checked and nothing is claimed.";
  const verdict = { verdict: "undetermined", stage: "unpack", headline: why, refusals: [], losses: [],
    notes: [{ message: why }], evaluators: {}, item_iri: "https://tesseractsemantics.com/ns/asset-passport/craft#forged_x",
    source: "https://tesseractsemantics.com/ns/asset-passport/craft#game", target: "battle", hub_types: ["Item", "Weapon"],
    why: [], conversion: {}, proof: { status: "checker_absent_nothing_was_checked" }, signature: null,
    transcript: [{ tool: "onto_clear", args: {}, result: { ok: true } }], lane: "live" };
  await standInEngine(page, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(verdict) }));
  await forgeSword(page);
  await page.waitForFunction(() => document.querySelector('.gate[data-gate="unpack"] .chip').textContent === "held", null, { timeout: 15000 })
    .catch(async () => { throw new Error(`the unpack gate never showed held: ${JSON.stringify(await gate(page, "unpack"))}`); });
  const unpack = await gate(page, "unpack");
  check(unpack.state === "warn" && unpack.note === why, `the unpack gate is ${JSON.stringify(unpack)}, not held with the headline`);
  for (const g of ["rules", "closure", "border"]) {
    const later = await gate(page, g);
    check(later.state === "idle" && later.chip === "not reached", `the ${g} gate after an undetermined unpack is ${JSON.stringify(later)}, not "not reached"`);
  }
}

// The server explained its failure: the page says what happened once.
export async function forgeErrorIsSaidOnce(page) {
  const error = "The engine run failed, so nothing is claimed. The server log has the details.";
  await standInEngine(page, (r) => r.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ verdict: "undetermined", error }) }));
  await forgeSword(page);
  const said = await forgeSaid(page);
  check(said === `The live engine answered 502: ${error}` || said === `The live engine answered 502 Bad Gateway: ${error}`,
    `the forge said ${JSON.stringify(said)}`);
}

// A reply that is not a verdict at all (a proxy's HTML page): named by its status, once.
export async function forgeNonJsonErrorIsSaidOnce(page) {
  await standInEngine(page, (r) => r.fulfill({ status: 502, contentType: "text/html", body: "<h1>Bad Gateway</h1>" }));
  await forgeSword(page);
  const said = await forgeSaid(page);
  check(/^The live engine answered 502( Bad Gateway)?, with no verdict\.$/.test(said), `the forge said ${JSON.stringify(said)}`);
}

// Crossing the 761px breakpoint re-renders both inventories. A slot or Send
// button that had keyboard focus must keep it, not drop it on the page body.
export async function focusSurvivesAResize(page) {
  for (const [name, role] of [["Use Blast Block", "button"], ["Send Blast Block to Pocket Battlers", "button"]]) {
    await page.setViewportSize({ width: 1440, height: 1000 });
    const el = page.locator("#craft-inv").getByRole(role, { name, exact: true });
    await el.focus();
    for (const width of [700, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.waitForFunction((w) => matchMedia("(min-width: 761px)").matches === (w > 760), width);
      await page.waitForTimeout(50);
      const now = await page.evaluate(() => { const a = document.activeElement;
        return a ? (a.getAttribute("aria-label") || a.tagName) : "none"; });
      check(now === name, `after resizing to ${width}px, focus is on ${JSON.stringify(now)}, not ${JSON.stringify(name)}`);
    }
  }
}

// The forge takes names up to 40 characters. One unbroken 40-character name
// widened the passport title and the Pocket Battlers text box to 1050px on a
// 390px phone. The stand-in engine answers with the page's own verdict for the
// Crystal Sword, so the forged blade is admitted and lands in Pocket Battlers.
export async function longForgedNameFitsThePhone(page) {
  const v = await page.evaluate(async () => (await (await fetch("data/verdicts.json")).json()).transfers["craft:crystal_sword"]);
  await standInEngine(page, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(v) }));
  const name = "W".repeat(40);
  await page.locator("#forge-game").selectOption({ label: "Blockcraft" });
  await page.locator("#forge-kind").selectOption({ label: "Crystal Sword" });
  await page.locator("#forge-name").fill(name);
  await page.locator("#forge-send").click();
  await expectPassport(page, name, /^Admitted\b/);
  await waitForLog(page, "battle", new RegExp(name));
  await fitsThePhone(page, "after a forged item with a 40-character name crossed");
}

// Send in the forge was disabled while the request ran, and a disabled button
// cannot hold focus, so keyboard focus fell to the page body and stayed there.
export async function forgeKeepsKeyboardFocus(page) {
  const v = await page.evaluate(async () => (await (await fetch("data/verdicts.json")).json()).transfers["craft:crystal_sword"]);
  await standInEngine(page, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(v) }));
  await page.locator("#forge-game").selectOption({ label: "Blockcraft" });
  await page.locator("#forge-kind").selectOption({ label: "Crystal Sword" });
  await page.locator("#forge-send").focus();
  await page.keyboard.press("Enter");
  await forgeSaid(page);
  const focused = () => page.evaluate(() => { const a = document.activeElement; return a ? (a.id || a.tagName) : "none"; });
  check(await focused() === "forge-send", `right after the engine answered, focus is on ${JSON.stringify(await focused())}, not the Send button`);
  await page.waitForFunction(() => !document.body.classList.contains("acting") && !document.getElementById("forge-send").hasAttribute("aria-disabled"));
  check(await focused() === "forge-send", `after the crossing, focus is on ${JSON.stringify(await focused())}, not the Send button`);
}
