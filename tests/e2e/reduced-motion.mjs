// The same flows with prefers-reduced-motion: reduce. Every pause in the page
// drops to zero, so text boxes change at once; the flows must still finish.
import { suite } from "./lib.mjs";
import * as f from "./flows.mjs";

await suite("desktop, 1440x1000, reduced motion", { viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" }, [
  ["the page sees reduced motion", f.reducedMotionIsOn],
  ["the page loads with no page errors and the first passport is admitted", f.firstPassportAdmitted],
  ["clicking the Crystal Sword in Pocket Battlers does double damage", f.swordDoesDoubleDamage],
  ["dragging the Blast Block onto the Pocket Battlers canvas is refused", f.blastBlockDragIsRefused],
  ["sending Emberfox to Blockcraft makes Blockcraft mention Cinder Puff", f.emberfoxSendReachesBlockcraft],
]);
