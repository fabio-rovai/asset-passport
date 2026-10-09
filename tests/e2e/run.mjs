// Runs every suite in its own node process and exits non-zero if any failed.
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const suites = ["desktop.mjs", "reduced-motion.mjs", "phone.mjs"];
let failed = [];
for (const s of suites) {
  const r = spawnSync(process.execPath, [path.join(here, s)], { stdio: "inherit" });
  if (r.status !== 0) failed.push(s);
}
console.log(failed.length ? `FAILED: ${failed.join(", ")}` : `all ${suites.length} suites passed`);
process.exit(failed.length ? 1 : 0);
