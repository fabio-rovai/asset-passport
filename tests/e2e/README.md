# Browser tests

These tests load the real static page from `site/` and drive it in Chromium with real pointer events. They need no engine: the page reads `site/data/verdicts.json`, which `scripts/build_site.py` wrote from the engine's output.

```sh
cd tests/e2e
npm ci
npm test                    # all three suites
node desktop.mjs            # one suite: desktop.mjs, reduced-motion.mjs or phone.mjs
```

Each suite serves `site/` with `python3 -m http.server` on a free loopback port, prints one `ok` or `not ok` line per check, and exits non-zero when any check fails.

On a Mac the tests use the installed Google Chrome. Set `E2E_CHROME` to another executable, or to `bundled` for Playwright's own Chromium (install it with `npx playwright install chromium`). When `CI` is set, the bundled Chromium is the default.

What they check, in desktop, reduced-motion and 390x844 phone layouts:

- The page loads with no page errors and no failed requests for its own files, and the first passport on the desk is admitted.
- Clicking the Diamond Sword in Pocket Battlers makes the battle text box say it is super effective.
- Dragging TNT from Blockcraft's hotbar onto the Pocket Battlers canvas produces a refused stamp, and the TNT goes back to the hotbar.
- Sending Emberfox to Blockcraft with its Send button makes the Blockcraft text box mention its move, Ember.
- At 390x844 nothing is wider than the viewport, before and after a passport with its details open.

Elements are found by role, id and visible text, never by how many border gates there are.
