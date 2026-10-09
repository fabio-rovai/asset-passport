# Asset Passport

![Dragging Blocky's bed into Ashen: the border refuses it at gate 4. Dragging Ashen's greatsword into Blocky: admitted, with the lost poise and stamina named. The imported diamond sword then fells Ashen's husk.](docs/assets/demo.gif)

<sub>Drag an item from one game into the other. Every verdict in this recording is the engine's own output. Full quality: [docs/assets/demo.mp4](docs/assets/demo.mp4).</sub>

Two small browser games, Blocky and Ashen, with a border between them. Blocky measures in metres and gives a player 20 hit points. Ashen measures in centimetres, gives a player 1,000, and charges stamina for every swing. When an item crosses from one to the other, [Open Ontologies](https://github.com/fabio-rovai/open-ontologies) works out what the item is, the receiving game converts its numbers under a rule it declared, and a Lean checker on the receiving side re-checks the proof before the game's own contract decides.

The point is the AI game-merge trend of autumn 2026, where people had Claude rewrite two games until they ran together. Those merges have no step that checks a sword is still a sword on the other side. This repository is that step, on two games small enough to read in an afternoon.

## What happens at the border

An item leaves its game as a passport: the item's graph, the game's published profile, and a derivation certificate, packed by `onto_pack`. The receiving game runs four gates in order, and the first one that fails decides.

1. **Digest and proof.** `onto_unpack` checks both SHA-256 digests and runs this machine's `oo-cert` over the certificate.
2. **Published rules.** The rules inside the passport must equal the source game's published profile. A proof over doctored rules still checks, so this gate compares them line by line.
3. **Closure.** The receiving game reasons over the item itself and refuses a passport that left a conclusion out. A proof can show that what it says follows; it cannot show that the sender said everything that follows.
4. **Border contract.** The receiving game's SHACL shapes run on two evaluators, the SPARQL-compiling one and the verified `oo-shacl`. The item crosses only when both agree. Warnings in a separate loss contract name what the item loses on the way in.

## What the engine said

The table is written by `scripts/build_site.py` from the engine's own output. Do not edit it by hand.

<!-- verdicts:start -->
| Item | Into | Verdict | Converted values | Proof steps (Lean) |
|---|---|---|---|---|
| Blocky `diamond_sword` | Ashen | converted | staminaCostInTarget 18, lengthInTarget 100, damageInTarget 350 | 18 |
| Blocky `iron_chestplate` | Ashen | converted | armourInTarget 24 | 17 |
| Blocky `bed` | Ashen | refused | none | 15 |
| Ashen `greatsword` | Blocky | converted_with_loss | lengthInTarget 1.8, damageInTarget 8 | 23 |
| Ashen `ember_flask` | Blocky | converted_with_loss | healInTarget 8 | 20 |
| Ashen `knight_armour` | Blocky | converted | armourInTarget 8 | 19 |

| Forgery on the bed | Result | Stopped at |
|---|---|---|
| Edit the passport | refused | unpack |
| Edit it, then fix the digests | refused | closure |
| Forge the proof | refused | unpack |
| Bring your own rules | refused | rules |
| Lie about the item | converted | gets through |
<!-- verdicts:end -->

## Where the guarantee ends

A forger who lies about the item itself gets through. Export Blocky's bed with its `kind` field set to `DiamondSword`, under Blocky's real profile, and every step after that is honest, so the bed crosses as a sword. A passport proves the paperwork follows from the published rules. It cannot prove what the sender says the item is. That needs the source game to sign its exports, which this demo does not do yet. `tests/test_verdicts.py::test_a_lie_about_the_item_gets_through` pins the gap, so the page cannot quietly stop saying so.

## Run it

You need Python 3.10+ and an Open Ontologies build. The scripts look for `../open-ontologies/target/release/open-ontologies` and its Lean checkers in `../open-ontologies/lean/.lake/build/bin/`. Set `OO_BIN`, `OO_CERT` and `OO_SHACL` to point elsewhere.

```sh
python3 -m pytest -q tests        # every verdict, gate and forgery, against the real engine
python3 scripts/build_site.py     # judge every item and forgery, write site/data/verdicts.json
python3 local.py                  # http://localhost:8765: drag items between the games, and use the live forge
```

Passports that carry a certificate need an engine with open-ontologies #266, which landed after v2.0.1. The live forge uses the "direct" lane, which runs on the v2.0.1 release: one store, `oo-cert` run by `passport/judge.py`, the same border.

## Deploy

`vercel.json` serves `site/` and runs `api/index.py`. `build.sh` downloads the pinned release (`OO_ENGINE_TAG`, default `v2.0.1`) with `oo-cert` and `oo-shacl`, and checks each file against the release's `SHASUMS.txt` before use.

## Layout

| Path | What it is |
|---|---|
| `ontology/ga-core.ttl` | The Game Asset hub every game maps into |
| `games/*/profile.ttl` | Each game's units, health scale and mapping into the hub |
| `games/*/items.json`, `mapping.json` | Each game's own item data, and how `onto_ingest` reads it |
| `rules/convert.rq` | The declared conversion policy, as a SPARQL CONSTRUCT |
| `contracts/*-border.shacl.ttl` | What each game refuses |
| `contracts/blocky-loss.shacl.ttl` | What an item loses on the way into Blocky |
| `passport/` | The MCP client, the four gates, the forger, the live API |
| `site/` | The page and both games, plain canvas, no framework |

Every arithmetic chain in `rules/convert.rq` is fully parenthesised on purpose. The comment at the top of that file explains why.
