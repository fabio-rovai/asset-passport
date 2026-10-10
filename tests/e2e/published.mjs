// The page at its published address, https://fabio-rovai.github.io/asset-passport/,
// with the files from site/ and the live engine API that site/config.js names.
// This is the only suite that runs the configuration Pages visitors get, and the
// only one that needs the network.
import { suite } from "./lib.mjs";
import * as f from "./flows.mjs";

await suite("published address, live engine, 1440x1000", { viewport: { width: 1440, height: 1000 } }, [
  ["the page loads with no page errors and the first passport is admitted", f.firstPassportAdmitted],
  ["the published page finds the live engine", f.liveEngineFound],
  ["a Crystal Sword forged on the published page is judged by the live engine", f.liveEngineJudges],
], { at: "pages" });
