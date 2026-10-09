// Desktop width with normal motion: the page as most visitors first see it.
import { suite } from "./lib.mjs";
import * as f from "./flows.mjs";

await suite("desktop, 1440x1000", { viewport: { width: 1440, height: 1000 } }, [
  ["the page loads with no page errors and the first passport is admitted", f.firstPassportAdmitted],
  ["clicking the Diamond Sword in Pocket Battlers is super effective", f.swordIsSuperEffective],
  ["dragging TNT onto the Pocket Battlers canvas is refused", f.tntDragIsRefused],
  ["sending Emberfox to Blockcraft makes Blockcraft mention Ember", f.emberfoxSendReachesBlockcraft],
]);
