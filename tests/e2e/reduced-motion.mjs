// The same flows with prefers-reduced-motion: reduce. Every pause in the page
// drops to zero, so text boxes change at once; the flows must still finish.
import { suite } from "./lib.mjs";
import * as f from "./flows.mjs";

await suite("desktop, 1440x1000, reduced motion", { viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" }, [
  ["the page sees reduced motion", f.reducedMotionIsOn],
  ["the page loads with no page errors and the first passport is admitted", f.firstPassportAdmitted],
  ["clicking the Diamond Sword in Pocket Battlers is super effective", f.swordIsSuperEffective],
  ["dragging TNT onto the Pocket Battlers canvas is refused", f.tntDragIsRefused],
  ["sending Emberfox to Blockcraft makes Blockcraft mention Ember", f.emberfoxSendReachesBlockcraft],
]);
