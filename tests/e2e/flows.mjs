// The things a visitor does on the page, each written as a check. Elements are
// found by role, id and visible text, never by how many border gates there are.
// An inventory slot is a <button> that the page gives role="listitem" and an
// accessible name "Use <item>", so slots are found as list items by that name.
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
  check(await page.locator("#battle.drop-ready").count() === 1, "the drag did not start: Pocket Battlers is not marked as a drop target");
  await page.mouse.move(x1, y1, { steps: 20 });
  check(await page.locator("#battle.drop-hot").count() === 1, "Pocket Battlers is not lit as the drop target with the pointer over its canvas");
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

export async function noHorizontalOverflow(page) {
  const measure = () => page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const wide = [...document.querySelectorAll("body *")]
      .filter((el) => el.getBoundingClientRect().right > vw + 0.5 && getComputedStyle(el).position !== "fixed")
      .slice(0, 5).map((el) => `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}.${el.className} right=${Math.round(el.getBoundingClientRect().right)}`);
    return { vw, sw: document.documentElement.scrollWidth, bw: document.body.scrollWidth, wide };
  });
  const look = async (when) => {
    const m = await measure();
    check(m.sw <= m.vw && m.bw <= m.vw,
      `${when}: the page is ${Math.max(m.sw, m.bw)}px wide in a ${m.vw}px viewport. ` +
      (m.wide.length ? `Elements past the edge: ${m.wide.join("; ")}` : "No element box crosses the edge, so look at pseudo-elements, margins and transforms."));
  };
  check(page.viewportSize().width === 390, `the viewport is ${page.viewportSize().width}px wide, not 390px`);
  await look("on load");
  // A passport with its details opened is the widest thing the desk shows.
  await page.locator("#battle-inv").getByRole("button", { name: "Send Emberfox to Blockcraft" }).click();
  await expectPassport(page, "Emberfox", /^Admitted\b/);
  for (const d of await page.locator("#passport details").all()) await d.locator("summary").click();
  await look("after sending Emberfox, with the passport's details open");
}

export async function reducedMotionIsOn(page) {
  check(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches),
    "the page does not see prefers-reduced-motion: reduce, so this suite would test nothing new");
}
