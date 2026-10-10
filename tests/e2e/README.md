# Browser tests

These tests load the real static page from `site/` and drive it in Chromium with real pointer events. They build no engine: the page reads `site/data/verdicts.json`, which `scripts/build_site.py` wrote from the engine's output, and CI checks that file against the engine separately (see `ci/` below). One suite, `published.mjs`, also talks to the live engine API, so it needs the network.

```sh
cd tests/e2e
npm ci
npm test                    # all four suites
node desktop.mjs            # one suite: desktop.mjs, reduced-motion.mjs, phone.mjs or published.mjs
```

Three suites serve `site/` with `python3 -m http.server` on a free loopback port. On that host `site/config.js` gives the forge no engine, which is what a copy of the page without a server should do, but it is not what a visitor to GitHub Pages gets. So `published.mjs` loads the page at its published address, `https://fabio-rovai.github.io/asset-passport/`: the browser asks for that address and every request to the Pages host is answered from `site/` on disk, so the real Pages site is never fetched, while the request to the engine API goes out to the deployment `site/config.js` names, from the Pages origin, as a visitor's would. Every suite prints one `ok` or `not ok` line per check and exits non-zero when any check fails.

On a Mac the tests use the installed Google Chrome. Set `E2E_CHROME` to another executable, or to `bundled` for Playwright's own Chromium (install it with `npx playwright install chromium`). When `CI` is set, the bundled Chromium is the default.

What they check:

- The page loads with no page errors, no console errors and no failed requests for its own files, and the first passport on the desk is the Crystal Sword, admitted. The one console line allowed is Chrome's own note that the static page's probe of `api/engine` got a 404 on a loopback host. (All four suites.)
- Clicking the Crystal Sword in Pocket Battlers makes the battle text box say "Rock beats Fire: double damage.", a line the page builds from its type chart. (Desktop, reduced motion and phone.)
- Dragging the Blast Block from Blockcraft's hotbar onto the Pocket Battlers canvas produces a refused stamp, and the Blast Block goes back to the hotbar. (Desktop and reduced motion only: below 761px the page turns touch drag off and offers Send buttons instead, so the phone suite has no drag to test.)
- Sending Emberfox to Blockcraft with its Send button stamps its passport admitted and makes the Blockcraft text box mention its move, Cinder Puff. (Desktop, reduced motion and phone.)
- With the engine replies answered by the test itself (no engine, no network): an undetermined verdict holds the gate it stopped at and leaves the later gates not reached; an error the engine explains, and a reply that is not a verdict at all, are each described once in the forge's status line; and a slot or Send button that has keyboard focus keeps it when the layout crosses the 761px breakpoint and both inventories are drawn again. (Desktop only.)
- The reduced-motion suite first checks that the page really sees `prefers-reduced-motion: reduce`.
- On the 390x844 phone the page is laid out 390px wide (a lost viewport meta tag would lay it out 980px wide), and nothing is wider than 390px, both on load and with a passport's details open.
- At the published address, the page finds the live engine (the forge names its version and the Send button is enabled), and a Crystal Sword forged with its catalogue stats goes to the live engine and comes back stamped admitted. A broken `site/config.js`, a host that is not the engine, or an engine that refuses the Pages origin under CORS all fail here. (`published.mjs` only.)

Elements are found by role, id and visible text, never by how many border gates there are. Two exceptions: inventory slots are `<button>` elements named "Use <item>" inside list items, so they are found as buttons by that name; and the page exposes no ARIA state for a drag in progress, so the drag check reads the `drop-ready` and `drop-hot` classes the page sets on `#battle`.

## Every check can fail

```sh
npm run mutants             # or: node mutants.mjs <part of a mutant title>
```

`mutants.mjs` copies `site/` to a scratch folder, plants one fault there (a refused Crystal Sword or Emberfox, an admitted Blast Block, a thrown error, a logged error, a missing stylesheet, no "double damage" line, no move name, a drag that never starts, no viewport meta tag, a pseudo-element or opened details wider than the phone, a page blind to reduced motion, a `config.js` that names a host that is not the engine or a Pages host that is not the published one, a forge that posts to a path the engine does not serve, an undetermined verdict drawn as a pass at its gate, a forge error said twice, a reply that is not a verdict described without its status, a resize that drops keyboard focus), and runs the one check that should catch it against the copy. It exits non-zero unless every mutant fails its target check with the expected message. `site/` itself is never edited. CI runs it after the tests.

Two variables exist for this: `E2E_SITE` serves another folder in place of `site/`, and `E2E_ONLY` runs only the check with that exact name.

## In CI

`.github/workflows/e2e.yml` runs `npm test` and then `npm run mutants` with Playwright's bundled Chromium on Node 22, on pull requests and on pushes to main that do not touch only the page. `pages.yml` calls the same workflow, and `tests.yml`, and deploys the page only when both pass and `scripts/check_live.py` passes against the URL in `site/config.js`.

## The CI checks in `ci/`

Two small Python scripts that `.github/workflows/tests.yml` runs after pytest, with their own tests in `ci/test_ci_checks.py` (part of the ordinary `python3 -m pytest tests` run, no engine needed):

- `ci/skips.py report.xml [--allow TEXT]` reads the JUnit report pytest wrote and fails when a test skipped for a reason the job does not allow. On the v2.0.1 release only the tests that need a certificate in a pack (#266) may skip; on the engine built from main nothing may.
- `ci/engine_matches_page.py` runs `scripts/build_site.py --check`, which judges every item and forgery with the engine, writes nothing, and fails with a diff unless `site/data/verdicts.json` gives what the engine says in every field the page renders (the engine's own replies in the transcripts are compared only when the check runs the binary that built the file). It then also checks the same target, verdict and converted values for every transfer, and the same verdict, deciding gate and outcome, in the same order, for every forgery. It needs an engine with #266.
