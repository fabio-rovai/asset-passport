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

What they check:

- The page loads with no page errors, no console errors and no failed requests for its own files, and the first passport on the desk is the Diamond Sword, admitted. The one console line allowed is Chrome's own note that the static page's probe of `api/engine` got a 404. (All three suites.)
- Clicking the Diamond Sword in Pocket Battlers makes the battle text box say it is super effective. (All three suites.)
- Dragging TNT from Blockcraft's hotbar onto the Pocket Battlers canvas produces a refused stamp, and the TNT goes back to the hotbar. (Desktop and reduced motion only: below 761px the page turns touch drag off and offers Send buttons instead, so the phone suite has no drag to test.)
- Sending Emberfox to Blockcraft with its Send button stamps its passport admitted and makes the Blockcraft text box mention its move, Ember. (All three suites.)
- The reduced-motion suite first checks that the page really sees `prefers-reduced-motion: reduce`.
- On the 390x844 phone the page is laid out 390px wide (a lost viewport meta tag would lay it out 980px wide), and nothing is wider than 390px, both on load and with a passport's details open.

Elements are found by role, id and visible text, never by how many border gates there are. Two exceptions: inventory slots are `<button>` elements that the page gives `role="listitem"`, so they are found as list items named "Use <item>"; and the page exposes no ARIA state for a drag in progress, so the drag check reads the `drop-ready` and `drop-hot` classes the page sets on `#battle`.

## Every check can fail

```sh
npm run mutants             # or: node mutants.mjs <part of a mutant title>
```

`mutants.mjs` copies `site/` to a scratch folder, plants one fault there (a refused Diamond Sword or Emberfox, an admitted TNT, a thrown error, a logged error, a missing stylesheet, no "super effective" line, no move name, a drag that never starts, no viewport meta tag, a pseudo-element or opened details wider than the phone, a page blind to reduced motion), and runs the one check that should catch it against the copy. It exits non-zero unless every mutant fails its target check with the expected message. `site/` itself is never edited. CI runs it after the tests.

Two variables exist for this: `E2E_SITE` serves another folder in place of `site/`, and `E2E_ONLY` runs only the check with that exact name.

## In CI

`.github/workflows/e2e.yml` runs `npm test` and then `npm run mutants` with Playwright's bundled Chromium on Node 22, on pushes to main and on pull requests. `pages.yml` calls the same workflow and deploys the page only when it passes.
