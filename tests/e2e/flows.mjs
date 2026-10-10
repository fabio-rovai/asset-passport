// The things a visitor does on the page, each written as a check. Elements are
// found by role, id and visible text, never by how many border gates there are.
// An inventory slot is a <button> that the page gives role="listitem" and an
// accessible name "Use <item>", so slots are found as list items by that name.
// The one thing read from classes is the drag state on #battle (drop-ready,
// drop-hot), because the page exposes no ARIA state for a drag in progress.
import { check, expectPassport, passport, waitForLog } from "./lib.mjs";

export async function firstPassportAdmitted(page) {
  const now = await passport(page);
  check(now.name === "Diamond Sword", `the first passport is for ${JSON.stringify(now.name)}, not the Diamond Sword`);
  check(/^Admitted\b/.test(now.stamp), `the first passport is stamped ${JSON.stringify(now.stamp)}, not Admitted`);
}

export async function swordIsSuperEffective(page) {
  const before = await page.evaluate(() => window.__logs.battle.slice());
  check(!before.some((t) => /super effective/i.test(t)), "the battle text box said super effective before anything was clicked");
  await page.locator("#battle-inv").getByRole("listitem", { name: "Use Diamond Sword" }).click();
  await waitForLog(page, "battle", /super effective/i);
}

export async function tntDragIsRefused(page) {
  const tnt = page.locator("#craft-inv").getByRole("listitem", { name: "Use TNT" });
  const target = page.locator("#battle-canvas");
  await tnt.scrollIntoViewIfNeeded();
  const from = await tnt.boundingBox();
  const to = await target.boundingBox();
  const vh = page.viewportSize().height;
  check(from && to, "the TNT slot or the Pocket Battlers canvas has no box on screen");
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
  await expectPassport(page, "TNT", /^Refused\b/);
  // A refused thing goes home: it is back in the hotbar, and the battle side never received it.
  await page.locator("#craft-inv").getByRole("listitem", { name: "Use TNT" }).waitFor();
  check(await page.locator("#battle-inv").getByRole("listitem", { name: "Use TNT" }).count() === 0,
    "the refused TNT appeared in Pocket Battlers");
}

export async function emberfoxSendReachesBlockcraft(page) {
  await page.locator("#battle-inv").getByRole("button", { name: "Send Emberfox to Blockcraft" }).click();
  await expectPassport(page, "Emberfox", /^Admitted\b/);
  // "Ember" as a word, so the creature's own name (Emberfox) does not count: the move has to be used.
  await waitForLog(page, "craft", /\bEmber\b/);
}

// The phone layout must be laid out at the phone's width. Without a working
// viewport meta tag, Chrome's mobile emulation lays the page out 980 CSS px wide
// and nothing overflows that, so the layout viewport (clientWidth) is checked
// against 390 first, and every width is then compared with 390, not with what
// the page reports. On a phone, content wider than the layout viewport also
// widens the visual viewport (innerWidth), because the browser zooms out to fit
// it, so innerWidth counts as overflow rather than as a lost layout.
export const PHONE_WIDTH = 390;

export async function noHorizontalOverflow(page) {
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
  const look = async (when) => {
    const m = await measure();
    check(m.cw === W,
      `${when}: the page is laid out ${m.cw}px wide on a ${W}px phone, so it has lost its phone layout. Check the viewport meta tag.`);
    check(m.sw <= W && m.bw <= W && m.iw <= W,
      `${when}: the page is ${Math.max(m.sw, m.bw, m.iw)}px wide on a ${W}px phone. ` +
      (m.wide.length ? `Elements past the edge: ${m.wide.join("; ")}` : "No element box crosses the edge, so look at pseudo-elements, margins and transforms."));
  };
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
  await page.locator("#forge-kind").selectOption({ label: "Diamond Sword" });
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
  // A Diamond Sword with its catalogue stats is the first passport on the desk,
  // admitted; the live engine must say the same about it.
  const stamp = (await result.locator("b").textContent()).trim();
  check(/^Admitted\b/.test(stamp), `the live engine stamped a catalogue Diamond Sword ${JSON.stringify(stamp)}, not Admitted`);
}
