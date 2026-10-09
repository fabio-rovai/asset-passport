# Contributing

Asset Passport is small on purpose: two games, one hub ontology, one conversion rule and five gates. The
most useful contributions extend what the border can say, and each one comes with a test that shows the
border saying it.

## Good first contributions

- **A third game.** Add `games/<key>/profile.ttl`, `items.json` and `mapping.json`, a border contract
  `contracts/<key>-border.shacl.ttl` and, if anything gets lost on the way in, a loss contract. The game is
  discovered from its directory; nothing in the code lists games. Run `python3 -m passport keys --game <key> --write`
  to give it an export key, then add its crossings to `tests/test_verdicts.py`.
- **A new refusal or loss.** Add a shape to a contract, and a test in which a real item trips it.
- **A new forgery.** Add it to `ATTEMPTS` in `passport/forge.py` and pin the gate that stops it in
  `STOPS` in `tests/test_verdicts.py`. If nothing stops it, that is a finding: add it next to "The issuer
  lies about the item" and say so in the README.
- **The dishonest issuer.** This is the open problem now. Passports are signed, so a receiving game knows
  who issued one and that nobody changed it since, and the gates check that the paperwork follows from the
  issuer's published rules. Nothing checks that the issuer told the truth about what the thing is: Pocket
  Battlers can sign a capture orb described as a potion, and it gets through. Closing that needs evidence
  the issuer does not control, for example a catalogue the issuer publishes ahead of time and the receiver
  checks items against, or a second, independent party that attests to the item. A contribution here should
  turn `test_a_lie_by_the_issuer_gets_through` red for a reason a reader can check, not by refusing potions.
- **Key rotation and revocation.** A game replaces its key by rewriting its profile, and that is all there
  is. There is no way yet to say which passports were signed under an old key, or to revoke one.

## Rules the page depends on

1. **Every number on the page comes from the engine.** Do not type a verdict, a converted value or a count
   into the page or the README. `scripts/build_site.py` writes them from the engine's output.
2. **A check has to be shown to fail.** A new gate or shape lands with a test where it refuses something.
3. **Parenthesise every arithmetic chain in SPARQL.** The engine's parser groups `a/b*c` as `a/(b*c)`.
   See the comment at the top of `rules/convert.rq`.
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
On the v2.0.1 release they are skipped and say why; CI runs on that release. No test reads your real
export keys: tests that sign copy `games/` to a temporary directory and publish keys they make on the spot.
`scripts/build_site.py` does use the real keys in `~/.asset-passport/keys`, and makes them if they are
missing, which rewrites the games' profiles; commit those profiles, never the keys.
