# Contributing

Asset Passport is small on purpose: two games, one hub ontology, one conversion rule and four gates. The
most useful contributions extend what the border can say, and each one comes with a test that shows the
border saying it.

## Good first contributions

- **A third game.** Add `games/<key>/profile.ttl`, `items.json` and `mapping.json`, a border contract and,
  if anything gets lost on the way in, a loss contract. Then add its crossings to `tests/test_verdicts.py`.
- **A new refusal or loss.** Add a shape to a contract, and a test in which a real item trips it.
- **A new forgery.** Add it to `passport/forge.py` and pin the gate that stops it. If nothing stops it,
  that is a finding: add it next to "Lie about the item" and say so in the README.
- **Signed exports.** This is the open problem. A passport proves the paperwork follows from the
  published rules, and it cannot prove the sender told the truth about what the thing is.

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
python3 -m pytest -q tests        # needs the open-ontologies engine; see the README
python3 scripts/build_site.py     # judge every item and forgery, write site/data/verdicts.json
python3 local.py                  # http://localhost:8765
```

The tests that pack a certificate into a passport need an engine built from open-ontologies main (#266).
On the v2.0.1 release they are skipped and say why; CI runs on that release.
