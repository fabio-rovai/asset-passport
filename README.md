# Asset Passport

[![Play it in your browser](https://img.shields.io/badge/%E2%96%B6%20PLAY%20IT%20IN%20YOUR%20BROWSER-2747a8?style=for-the-badge)](https://fabio-rovai.github.io/asset-passport/)
[![Tests](https://img.shields.io/github/actions/workflow/status/fabio-rovai/asset-passport/tests.yml?branch=main&style=for-the-badge&label=tests)](https://github.com/fabio-rovai/asset-passport/actions/workflows/tests.yml)
[![MIT](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)

[![Using a Crystal Sword that crossed from Blockcraft: a Rock-type move that does double damage to a Fire creature. Dragging a Blast Block into Pocket Battlers: refused at the border. Dragging Emberfox into Blockcraft: it becomes a pet that attacks the zombie. Dragging a Sunfruit into Pocket Battlers: admitted, and its passport names the extra hearts that had nowhere to go. The border desk checks each crossing gate by gate, starting with the signature.](docs/assets/demo.gif)](https://fabio-rovai.github.io/asset-passport/)

<sub>Click the recording to play it at [fabio-rovai.github.io/asset-passport](https://fabio-rovai.github.io/asset-passport/). Drag an item from one game into the other. Every verdict is the engine's own output. Full quality: [docs/assets/demo.mp4](docs/assets/demo.mp4).</sub>

Two small browser games with a border between them. Blockcraft is a block-building game with no elemental types. Pocket Battlers is a creature battler in which every move has a type, and the two games count health on different scales. Drag a thing from one game into the other. [Open Ontologies](https://github.com/fabio-rovai/open-ontologies) works out what it is, the sending game signs the result, the receiving game checks the signature against the key the sender publishes, a Lean checker on the receiving side re-checks the proof, the receiving game converts the thing under a rule it declared, and its own contract decides. Then the thing shows what it does.

<!-- example:start -->
A Crystal Sword deals 6 of a player's 20 HP in Blockcraft. In Pocket Battlers it becomes a move with power 30 of 100, and its type is Rock. Nobody typed that type. Blockcraft's profile says "anything made of crystal is Rock-typed", and the engine derives the rest, so the sword is strong against a Fire creature. A Blast Block is refused, because 22 of 20 HP becomes 110 of 100, which would knock out a full-health creature in one turn. A Capture Orb is refused by Blockcraft, where nothing can own a mob.
<!-- example:end -->

The point is the AI game-merge trend of autumn 2026, where people had Claude rewrite two games until they ran together. Those merges have no step that checks what a sword should become on the other side. This repository is that step, on two games small enough to read in an afternoon. Both games, their creatures and their art are original.

## What happens at the border

An item leaves its game as a passport: the item's graph, the game's published profile, and a derivation certificate, packed by `onto_pack` and signed with the game's Ed25519 export key. The receiving game runs the gates below in order, and the first one that fails decides.

1. **Signature.** The passport names the game that issued it. The receiving game looks that game up in its own copy of the published profiles and verifies the signature against the `ga:exportKey` published there. A key that arrives inside a passport is never used. The signature covers the engine's `content_sha256`, the digest over the graph and the certificate together.
2. **Digest and proof.** `onto_unpack` checks that the graph and the certificate are the content that digest names, which is what ties the signature to the content, and runs this machine's `oo-cert` over the certificate.
3. **Published rules.** The rules inside the passport must equal the source game's published profile, statement by statement, because a proof over doctored rules still checks. Anonymous parts of a rule (the `[ ... ]` restrictions in a profile) are compared by their whole structure, not by position, so swapping the values inside two restrictions is a change this gate sees. A passport whose rules share an anonymous node between two statements, or loop through one, is refused here rather than compared. The game the item is derived to come from (`ga:fromGame`, a conclusion in the certificate, not an assertion) must also be the game that signed, so one game cannot vouch for another game's items.
4. **Closure.** The receiving game reasons over the item itself and refuses a passport that left a conclusion out. A proof can show that what it says follows; it cannot show that the sender said everything that follows.
5. **Border contract.** The receiving game's SHACL shapes run on two evaluators, the SPARQL-compiling one and the verified `oo-shacl`. The item crosses only when both agree. Warnings in a separate loss contract name what the item loses on the way in.

The live forge on the page uses a second lane, the direct lane: one engine, one store, no passport in transit, so nothing to sign. It runs on the released engine and goes through the same border.

## What the engine said

The table is written by `scripts/build_site.py` from the engine's own output. Do not edit it by hand.

<!-- verdicts:start -->
| Item | Into | Verdict | Converted values | Proof steps (Lean) |
|---|---|---|---|---|
| Pocket Battlers `emberfox` | Blockcraft | converted_with_loss | hitPointsInTarget 20, damageInTarget 9 | 14 |
| Pocket Battlers `capture_orb` | Blockcraft | refused | none | 8 |
| Pocket Battlers `fizz_tonic` | Blockcraft | converted | healInTarget 8 | 9 |
| Blockcraft `crystal_sword` | Pocket Battlers | converted | typeInTarget ga:Rock, damageInTarget 30 | 14 |
| Blockcraft `blast_block` | Pocket Battlers | refused | damageInTarget 110 | 9 |
| Blockcraft `sunfruit` | Pocket Battlers | converted_with_loss | healInTarget 30 | 10 |

| Forgery on the Capture Orb | Result | Stopped at |
|---|---|---|
| Edit the passport | refused | gate 2, unpack |
| Edit it, then fix the digests | refused | gate 1, signature |
| Forge the proof | refused | gate 1, signature |
| Lie, and sign it yourself | refused | gate 1, signature |
| The issuer leaves a line out | refused | gate 4, closure |
| The issuer bends its own rules | refused | gate 3, rules |
| The issuer lies about the item | converted | gets through |
<!-- verdicts:end -->

## Where the guarantee ends

A dishonest issuer gets through. If Pocket Battlers itself exports the Capture Orb with its `kind` field set to `FizzTonic`, under its real profile, and signs the passport with its real key, every gate passes and the orb crosses as a tonic. A signed passport proves who issued it, that nobody changed it since, and that the paperwork follows from the issuer's published rules. It cannot prove the issuer told the truth about what the thing is. What the receiving game gains is that it knows whom to hold to account. `tests/test_verdicts.py::test_a_lie_by_the_issuer_gets_through` pins the gap, so the page cannot quietly stop saying so.

The forgers who do not hold the key are stopped earlier. The table above lists every attempt and the gate that stopped it; the page shows the engine's own words for each.

A passport is a bearer document. The signature covers the issuing game and the content, and nothing in the passport names the game it is meant for, a time after which it expires, or a single use. Whoever holds a passport can present it again, and to any game whose border lets it in, and it is admitted every time; a receiving game that must not take the same thing twice has to keep its own record of what it has admitted.

Smaller limits are worth knowing too. The signature and rules gates both trust the receiving game's own copy of the issuer's profile, so whoever can edit that copy decides which key and which rules are trusted. The signature covers the graph and the certificate (`content_sha256`), not the manifest's name, version or the sender's free-text evidence, so those are informational. Key rotation is manual: a game that replaces its key rewrites its profile, and a passport signed with the old key stops verifying everywhere the new profile is published.

## Use it on your own games

**Games are discovered, not listed in code.** Every directory under the games root that holds a `profile.ttl` is a game, and its key is the directory's name. Its IRI, label, health scale and export key are read by the engine from the profile's `?g a ga:Game ; rdfs:label ?label` (with `ga:maxPlayerHealth` and `ga:exportKey`). Two directories that declare the same game IRI are refused, because either could otherwise replace the other's published key, and so is an export key that is not base64 of 32 bytes. The games root is `games/` unless `ASSET_PASSPORT_GAMES` or `--games` says otherwise. Contracts are looked up as `<key>-border.shacl.ttl` and, if present, `<key>-loss.shacl.ttl`, file by file: first in a `contracts/` directory next to the games root, then in this repository's `contracts/` (`ASSET_PASSPORT_CONTRACTS` replaces both). A game needs `profile.ttl`, `items.json` and `mapping.json`; see `games/craft/` for a small one.

The judging code and the command line take any number of games. The page and `scripts/build_site.py` show exactly two side by side, and the build stops, before it writes anything, on any other count.

**The command line** prints one line of JSON and exits 0 when the item is admitted, 1 when it is refused, and 2 when nothing can be claimed or the run failed. A passport file that cannot be opened is a failed run (2); one that opens but is not a well-formed signed passport is refused (1).

```sh
python3 -m passport keys   --game battle --write          # make battle's keypair; publish the public key in its profile
python3 -m passport export --from battle --item capture_orb --out orb.pack   # a signed passport
python3 -m passport admit  orb.pack --into craft           # every gate, as the receiving game
python3 -m passport judge  --from craft --into battle --item blast_block     # the direct lane, no passport
python3 -m passport judge  --from craft --into battle --item my_sword.json   # an item from a file
```

**Keys.** A game's private key lives outside the repository, in `~/.asset-passport/keys/` (`ASSET_PASSPORT_KEYS` overrides), as an unencrypted PKCS#8 PEM file readable only by its owner. The file is named after the game's IRI as well as its directory, `<key>.<first 16 hex digits of sha256(IRI)>.ed25519`, so a directory called `craft` in another games root that declares a different game gets a key of its own, never Blockcraft's. The code refuses to write a key inside the repository, and `.gitignore` covers `*.ed25519` anyway. The public half goes into the game's `profile.ttl` as `ga:exportKey`, and that profile is what other games trust. Admitting a passport needs no private key at all, and `judge` runs without the `cryptography` package.

**The published keys are trust anchors, so the build never replaces them by default.** `python3 scripts/build_site.py` signs with the private keys on this machine, and stops with an explanation if a key is missing or is not the one the profile publishes. `--check` judges every item and forgery with throwaway keys in a scratch copy of the games and writes nothing. `--new-keys` makes missing keys and rewrites the profiles to publish them, and prints each change; only the games' maintainer should run it.

## Run it

You need Python 3.10+, the `cryptography` package (`pip install -r requirements.txt`) and an Open Ontologies build. The scripts look for `../open-ontologies/target/release/open-ontologies` and its Lean checkers in `../open-ontologies/lean/.lake/build/bin/`. Set `OO_BIN`, `OO_CERT` and `OO_SHACL` to point elsewhere.

```sh
python3 -m pytest -q tests        # every verdict, gate and forgery, against the real engine
python3 scripts/build_site.py     # judge every item and forgery, write site/data/verdicts.json (needs the games' keys)
python3 scripts/build_site.py --check   # the same with throwaway keys; writes nothing
python3 local.py                  # http://localhost:8765: drag items between the games, and use the live forge
```

Passports that carry a certificate need an engine with open-ontologies #266, which landed after v2.0.1, so exporting and admitting a passport need an engine built from main. The live forge and `python3 -m passport judge` use the "direct" lane, which runs on the v2.0.1 release: one store, `oo-cert` run by `passport/judge.py`, the same border.

## Check a two-game bridge

Mods that run one game inside another, Minecraft inside Skyrim for instance, have to agree on units, axes and health. Universal Modder's [note on bridge contracts](https://github.com/rehan-remade/universal-modder/blob/2131b2cc9e06dac51ebcd202745c03cf3b988ee8/knowledge/techniques/bridge-contracts-ownership-units-and-lifecycle.md) asks each bridge to write those down. `python3 -m passport.bridge` takes one such declaration and asks the engine whether it agrees with the two games' own documented facts, each with its source, in `ontology/ga-space.ttl`. It checks the axis map, handedness, the unit ratio and the health multiplier, and runs its contract on both SHACL evaluators, which must agree. [docs/BRIDGES.md](docs/BRIDGES.md) explains every check and lists the engine's verdict on every example.

```sh
python3 -m passport.bridge check examples/bridges/um-skycraft.ttl
python3 scripts/bridges_report.py --check   # are the results in docs/BRIDGES.md current?
```

It prints JSON, one verdict per check, and exits 0 when every declared check holds, 1 when any check is refused, and 2 when nothing is refused but some check is undetermined, or when the run failed. A check is undetermined when, for example, a fact it needs has no source that could be opened.

## Deploy

The page is static, and GitHub Pages serves `site/` on every push that changes it (`.github/workflows/pages.yml`). Pages has no engine server of its own. The copy at fabio-rovai.github.io sends its live forge to the engine API named by `VERCEL_API` in `site/config.js`, and that API lets only this origin (and the local server) read its answers (`passport/cors.py`). While `VERCEL_API` is empty, and on any other static host, the forge is off and says so.

For the engine API, `vercel.json` serves `site/` and runs `api/index.py`. `build.sh` downloads the pinned release (`OO_ENGINE_TAG`, default `v2.0.1`) with `oo-cert` and `oo-shacl`. Each file must match both the release's `SHASUMS.txt` and the checksum written into `build.sh`, and a tag with no checksums in `build.sh` is refused. `.vercelignore` keeps tests, docs and any local `api/_bin` out of the upload. The API has no login and no rate limit of its own: anyone can call it, and each call runs the engine once.

## Layout

| Path | What it is |
|---|---|
| `ontology/ga-core.ttl` | The Game Asset hub every game maps into |
| `games/*/profile.ttl` | Each game's health scale, the mapping of its own words (kinds, materials, type names) into the hub, and its published export key |
| `games/*/items.json`, `mapping.json` | Each game's own item data, and how `onto_ingest` reads it |
| `rules/convert.rq` | The declared conversion policy, as a SPARQL CONSTRUCT |
| `contracts/*-border.shacl.ttl` | What each game refuses |
| `contracts/*-loss.shacl.ttl` | What a thing loses on the way in, as warnings |
| `passport/` | The MCP client, game discovery, signing, the gates, the forgers, the command line, the live API |
| `site/` | The page and both games, plain canvas, no framework |
| `scripts/build_site.py` | Judges every item and forgery with the engine and writes `site/data/`, `site/passports/` and the generated parts of this README |
| `api/index.py`, `build.sh`, `vercel.json` | The engine API behind the live forge, on Vercel, with the pinned engine release |
| `scripts/check_live.py` | Checks a deployed engine API the way the GitHub Pages copy calls it |
| `tests/`, `tests/e2e/` | The engine tests, and browser tests that drive the page in Chrome |
| `ontology/ga-space.ttl` | Sourced facts about real games for the bridge checker: unit lengths, which axis points east, north and up, health |
| `rules/bridge.rq` | What a bridge's axis map, handedness, unit ratio and health multiplier must be, derived from those facts |
| `rules/bridge-input.rq`, `rules/facts-input.rq` | What a bridge file and a facts file may say; anything else stops the run before the rule |
| `contracts/bridge.shacl.ttl` | What the bridge checker refuses |
| `examples/bridges/` | Bridge declarations: Universal Modder's table as written (`um-`), the same projects read from their source (`src-`), this repository's games (`syn-`) and wrong ones on purpose (`wrong-`) |
| `scripts/bridges_report.py` | Writes the results in `docs/BRIDGES.md` from the engine's output; `--check` says whether they are stale |

Every arithmetic chain in `rules/convert.rq` is fully parenthesised on purpose. The comment at the top of that file explains why.

## Contributing and licence

A third game, a new refusal, a new forgery, a new bridge, or a way past the dishonest-issuer limit: see [CONTRIBUTING.md](CONTRIBUTING.md). Every
number on the page has to come from the engine, and every new check lands with a test where it fails.

MIT, like [Open Ontologies](https://github.com/fabio-rovai/open-ontologies). Both games, their creatures and
their art are original to this project.
