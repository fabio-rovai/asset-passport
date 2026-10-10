// A 390x844 phone. The games stack in one column and crossings use the Send buttons.
import { suite } from "./lib.mjs";
import * as f from "./flows.mjs";

const phone = { viewport: { width: f.PHONE_WIDTH, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true };
await suite("phone, 390x844", phone, [
  ["the page loads with no page errors and the first passport is admitted", f.firstPassportAdmitted],
  ["there is no horizontal overflow", f.noHorizontalOverflow],
  ["clicking the Crystal Sword in Pocket Battlers does double damage", f.swordDoesDoubleDamage],
  ["sending Emberfox to Blockcraft makes Blockcraft mention Cinder Puff", f.emberfoxSendReachesBlockcraft],
]);
