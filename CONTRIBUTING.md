# Contributing

Asset Passport is small on purpose: two games, one hub ontology with its conversion rule, the gates a passport
passes at the border, and a checker for the units, axes and health of two-game bridges ([docs/BRIDGES.md](docs/BRIDGES.md)).
The most useful contributions extend what the border can say, and each one comes with a test that shows the
border saying it.

## Good first contributions

- **A third game, for the command line.** Add `games/<key>/profile.ttl`, `items.json` and `mapping.json`, a
  border contract `contracts/<key>-border.shacl.ttl` and, if anything gets lost on the way in, a loss
  contract. The judging code and `python3 -m passport` discover the game from its directory; nothing there
  lists games. Run `python3 -m passport keys --game <key> --write` to give it an export key, and add tests
  for its crossings. The page and `scripts/build_site.py` are another matter: they show exactly two games side
  by side (`site/app.js` names `craft` and `battle`), and the build stops on any other count. A page that
  shows any number of games is a contribution of its own.
- **A new refusal or loss.** Add a shape to a contract, and a test in which a real item trips it.
- **A new forgery.** Add it to `ATTEMPTS` in `passport/forge.py` and pin the gate that stops it in
  `STOPS` in `tests/test_verdicts.py`. If nothing stops it, that is a finding: add it next to "The issuer
  lies about the item" and say so in the README.
- **The dishonest issuer.** This is the open problem now. Passports are signed, so a receiving game knows
  who issued one and that nobody changed it since, and the gates check that the paperwork follows from the
  issuer's published rules. Nothing checks that the issuer told the truth about what the thing is: Pocket
  Battlers can sign a capture orb described as a tonic, and it gets through. Closing that needs evidence
  the issuer does not control, for example a catalogue the issuer publishes ahead of time and the receiver
  checks items against, or a second, independent party that attests to the item. A contribution here should
  turn `test_a_lie_by_the_issuer_gets_through` red for a reason a reader can check, not by refusing tonics.
- **A bridge.** Declare a two-game bridge in `examples/bridges/<name>.ttl`, and add any game fact it needs to
  `ontology/ga-space.ttl` with its source page and the source's own words. Pin the engine's verdict in
  `EXPECTED` in `tests/test_bridges.py`, which fails while an example is unpinned, and run
  `python3 scripts/bridges_report.py` to rewrite the results in `docs/BRIDGES.md`.
- **Single use and audience.** A passport names who issued it, not which game it is for, when it expires or
  that it may be used once, so the same passport is admitted every time it is presented. Binding a
  passport to a receiver, or recording what a game has already admitted, is open.
- **Key rotation and revocation.** A game replaces its key by rewriting its profile, and that is all there
  is. There is no way yet to say which passports were signed under an old key, or to revoke one.

## Rules the page depends on

1. **Every number on the page comes from the engine.** Do not type a verdict, a converted value or a count
   into the page or the README. `scripts/build_site.py` writes them from the engine's output, and
   `scripts/bridges_report.py` does the same for `docs/BRIDGES.md`.
2. **A check has to be shown to fail.** A new gate or shape lands with a test where it refuses something.
3. **Parenthesise every arithmetic chain in SPARQL.** The engine's parser groups a chain of `+` and `-`,
   or of `*` and `/`, to the right: `a/b*c` as `a/(b*c)` and `a-b-c` as `a-(b-c)`. See the comment at the
   top of `rules/convert.rq`.
4. **Original names and art only.** Both games, their creatures and their items are our own. Please do not
   add other companies' characters, names or sprites.

## Running it

```sh
pip install -r requirements.txt   # cryptography, for the Ed25519 signatures
python3 -m pytest -q tests        # needs the open-ontologies engine; see the README
python3 scripts/build_site.py     # judge every item and forgery, write site/data/verdicts.json
python3 local.py                  # http://localhost:8765
```

The tests that pack a certificate into a passport need an engine built from open-ontologies main (#266).
On the v2.0.1 release they are skipped and say why. CI runs the suite twice: once on the v2.0.1 release,
where only those tests may skip, and once on the engine built from a pinned main commit, where no test may
skip and `scripts/build_site.py --check` must find that the engine still gives every verdict, message and
number the page shows in `site/data/verdicts.json`. No test reads your real
export keys: `tests/conftest.py` points every test, and every command a test runs, at an empty keys
directory of its own, and tests that sign copy `games/` to a temporary directory and publish keys they make
on the spot.

**Do not change a game's `ga:exportKey` in a pull request.** The published keys are what every receiving
game trusts, and only the maintainer holds the private halves. `python3 scripts/build_site.py` stops if the
keys on your machine do not match the published ones; run `python3 scripts/build_site.py --check` instead,
which judges every item and forgery with throwaway keys in a scratch copy and writes nothing. The
maintainer regenerates `site/data/` and `site/passports/` after merging. `--new-keys` exists for the
maintainer, to make or replace keys on purpose.
