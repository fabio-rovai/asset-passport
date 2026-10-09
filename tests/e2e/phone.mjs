// A 390x844 phone. The games stack in one column and crossings use the Send buttons.
import { suite } from "./lib.mjs";
import * as f from "./flows.mjs";

const phone = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true };
await suite("phone, 390x844", phone, [
  ["the page loads with no page errors and the first passport is admitted", f.firstPassportAdmitted],
  ["there is no horizontal overflow", f.noHorizontalOverflow],
  ["clicking the Diamond Sword in Pocket Battlers is super effective", f.swordIsSuperEffective],
  ["sending Emberfox to Blockcraft makes Blockcraft mention Ember", f.emberfoxSendReachesBlockcraft],
]);
