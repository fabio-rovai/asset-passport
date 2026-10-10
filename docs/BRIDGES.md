# Bridge checker: units, axes and health

Two-game mods run one game inside another: Minecraft inside Skyrim, Garry's Mod inside Red Dead
Redemption 2. Universal Modder's note on bridge contracts
([rehan-remade/universal-modder](https://github.com/rehan-remade/universal-modder), MIT,
`knowledge/techniques/bridge-contracts-ownership-units-and-lifecycle.md` at commit
`2131b2cc9e06dac51ebcd202745c03cf3b988ee8`) asks every such bridge to write down its "Units and axes" as a
function both sides share, and its table "Unit mappings" lists what bridges have declared. Four of that
table's nine rows link a public project: NewVegasCraft, Faith Runner, Killcraft and the 2010 Rust Rewrite
Mashup. For SkyCraft, LibertyCraft, Minecraft × Half-Life and Garry's Redemption, the `um-` files take
the link from the note's ownership table. The Minecraft × GTA V example links nothing anywhere.

This checker takes one of those declarations and asks the Open Ontologies engine whether it agrees with
the two games' own documented facts. It answers per check: **holds**, **refused**, **undetermined** (a
fact it needs has no source we could open), or not declared.

```sh
python3 -m passport.bridge check examples/bridges/um-skycraft.ttl
python3 scripts/bridges_report.py     # rewrite the generated sections of this file
```

Exit status: 0 when every declared check holds, 1 when any check is refused, 2 when nothing is refused
but something is undetermined (or the run failed). The output is JSON, one verdict per check, with the
derived values and, for an undetermined check, the fact that is missing.

## What it checks

A game states, with a source for each statement, how long its unit is and which of its signed axes points
east, north and up (`ontology/ga-space.ttl`). A bridge names a host (the game whose world you see) and a
guest, and declares any of the following. The four checks are:

1. **The axis map.** Each guest axis is declared as a signed host axis (`ga:guestZFrom "-y"` means guest
   z is host minus y). `rules/bridge.rq` derives, from the two games' east, north and up, which host axis
   each guest axis must be, and the contract refuses any declared axis that differs. A partly known basis
   still refutes: if the guest's north is known for both games, a wrong guest axis along north is refused
   even when up is unknown.
2. **Handedness.** The rule computes the determinant of the declared map taken through both games' bases
   (a signed permutation's determinant is the sign of the permutation times the product of the signs). A
   map must keep handedness unless the bridge declares `ga:mirrored true`, and a bridge that declares a
   mirror must actually mirror. A map that sends two guest axes to one host axis has determinant 0 and is
   refused. A declared mirror names the world direction it flips (`ga:mirrorDirection ga:North`), and the
   axis check then derives the mirrored map, flipping the sign of the guest axis along that direction, so
   a declared and named mirror can hold (`syn-declared-mirror.ttl`). A mirror declared without a direction
   leaves the axis check undetermined, because more than one mirrored map exists; handedness is still
   checked.
3. **The unit ratio.** A bridge may say how many host units make a guest unit, how many host units make a
   metre, how long a guest or host unit is in metres, or give a span ("72 units ≈ 1.8 m", from which the
   engine computes the ratio). The rule computes what the games' sourced unit lengths imply, and the
   contract allows **2 percent** of relative error. When a game's sources give more than one scale (Valve
   documents three), the rule computes the best and the worst error over every combination of scales:
   best over 2 percent is a refusal, worst over it with the best inside is undetermined. A source may
   give a range ("2-3 centimeters"), and a ratio inside it has error 0 against that scale. Only the
   host-units-per-guest-unit form compares the two games; the other forms involve one game's unit only,
   and the output says which (`"checks"`). "1 metre per block", for instance, is a claim about Minecraft's
   block and holds whatever the host is.
4. **Health.** A declared multiplier (guest hit points times it are host hit points) must equal the
   proportional policy that Asset Passport already uses for items, the host's maximum health over the
   guest's, to within 0.001 either way. The tolerance is absolute, not relative: against a policy of 5,
   a declared 5.001 holds and 5.0011 is refused. A bridge may instead declare health native (it crosses
   unconverted, by policy), but not both.
   Native health is reported as **not checked**, not as holding: there is no number to compare.

Two more checks guard the declaration: **declaration** (well-formed axes, one host and one guest that the
facts declare as games, a bridge that is not also a game, positive numbers, a mirror direction only with
a mirror) and **facts** (every game fact has a source page and the source's own words, is an IRI, a range
has both ends, and a game's east, north and up are three different axes).

### What a bridge file may say

Before anything else runs, engine queries check the inputs, each on a store that holds that input
alone. `rules/bridge-input.rq` refuses a bridge file that says anything except its bridges' host, guest,
axis map, mirror, unit ratio, health policy and provenance: it cannot add a game fact, type a node as a
game, or state anything the rule derives (`ga:handedness`, `ga:unitCheckOf`, `ga:bestRelativeError` and
the rest), and its declared numbers must be `xsd:integer` or `xsd:decimal`. A second query on the same
store (`BRIDGE_NODE_GUARD` in `passport/bridge.py`) refuses a bridge that is a blank node (the checker
reads each bridge by its name), a bridge minted on an IRI in the game or fact namespace (so a bridge
file cannot add to a game or a fact), and a declared number the engine cannot read: an integer past 64
bits, or a decimal with more than 18 digits after the point. The engine has no value for such a number,
and the two SHACL evaluators then disagree, so the run could only have ended undetermined. A game the
facts declare under another IRI (this repository's own two games) and typed a bridge is refused by the
contract instead, on the declaration check. `rules/facts-input.rq` refuses a facts file,
`ontology/ga-space.ttl` included, that states a bridge or a derived predicate, or a number the engine
cannot read. Any of these refusals stops the run with exit 1 before the rule runs. Game facts therefore
come only from `ontology/ga-space.ttl`. Tests that need a made-up game (a broken basis, an unsourced fact)
pass it with `--facts examples/bridges/facts/<name>.ttl`, and the output then says
`"synthetic_facts": true`.

### How the engine decides

After the input guards, `passport/bridge.py` loads `ontology/ga-space.ttl` and the bridge file into one
store, applies `rules/bridge.rq` (a SPARQL CONSTRUCT) until it adds nothing new, then runs
`contracts/bridge.shacl.ttl` on both of the engine's SHACL evaluators, the default one and the
Lean-verified `oo-shacl`. A check is refused only when the contract refuses it, and both evaluators must
return exactly the same refusals (focus node and path) or nothing is claimed. A contract that saw no
focus node claims nothing either, because the verified evaluator conforms vacuously on an empty store.
The rule reads only facts that carry `ga:source`, so an unsourced fact can never decide a check; it can
only be refused.

A check whose facts are all sourced, but for which the engine returned no value, is **refused**, not
undetermined: a declaration the engine could not evaluate is not admitted. This holds for all four
checks. An axis is refused when both games source the direction along it and no host axis was derived,
and handedness when the map is complete, both bases are complete, and no determinant came back. The
unit check is refused when a sourced length fact got no metres per unit, when the rule joined fewer
scale combinations than the games' length facts give, or when a combination came back without an error,
so a value dropped for one scale cannot hide behind the minimum over the others or vanish from the
count. Health is refused when both maxima are sourced and no policy came back.

The contract compares derived values with `sh:in`, `sh:class`, `sh:minInclusive` and `sh:maxInclusive`.
It does not use `sh:equals`, which the default evaluator does not implement (it skips the constraint and
withholds its verdict), or `sh:pattern` with a character class, which the verified evaluator does not
parse. Its numeric bounds compare decimals only, because the verified evaluator does not order an
`xsd:double` at all, not even against another double. All of this was measured while building it.

## Results

The checker's own result for every row is a **derived comparison**: it compares a declaration with facts
from elsewhere. The Evidence column is the level of the declaration itself, in Universal Modder's
vocabulary: a table row restates what its creators report (**creator report**), a `src-` file was read
from the project's code at a pinned commit (**source inspection**), and the `syn-` and `wrong-` files are
**synthetic tests**. Every number below is written by `scripts/bridges_report.py` from the engine's
output; `tests/test_bridges.py` pins them and fails if this section goes stale.

<!-- bridges:results:start -->
#### Universal Modder's table, as written

| File | Row | Evidence | Axes | Handedness | Units | Health | Verdict | Exit |
|---|---|---|---|---|---|---|---|---|
| `um-2010-rust-rewrite-mashup.ttl` | 2010 Rust Rewrite Mashup (table row) | creator report |  |  | undetermined |  | undetermined | 2 |
| `um-faith-runner-skyrim.ttl` | Faith Runner in Skyrim (table row) | creator report |  |  | holds |  | holds | 0 |
| `um-garrys-redemption.ttl` | Garry's Redemption (table row) | creator report |  |  | undetermined |  | undetermined | 2 |
| `um-gta-v-example.ttl` | Minecraft x GTA V example (table row) | creator report | undetermined | undetermined | undetermined |  | undetermined | 2 |
| `um-killcraft.ttl` | Killcraft (table row) | creator report |  |  | undetermined |  | undetermined | 2 |
| `um-libertycraft.ttl` | LibertyCraft (table row) | creator report |  |  | holds |  | holds | 0 |
| `um-minecraft-x-half-life.ttl` | Minecraft x Half-Life (table row) | creator report |  |  | undetermined | holds | undetermined | 2 |
| `um-newvegascraft.ttl` | NewVegasCraft (table row) | creator report | undetermined | undetermined | holds |  | undetermined | 2 |
| `um-skycraft.ttl` | SkyCraft (table row) | creator report |  |  | holds |  | holds | 0 |

- **2010 Rust Rewrite Mashup (table row)** (Modern Warfare 2 (IW4L Rust rewrite) hosting Minecraft (Java Edition)). Units: 36 host units per guest unit; undetermined: Modern Warfare 2 (IW4L Rust rewrite) has no sourced unit length.
- **Faith Runner in Skyrim (table row)** (The Elder Scrolls V: Skyrim hosting Mirror's Edge). Units: 70 host units per metre (this checks the host's own unit length only; the guest's unit is not involved); the sourced unit lengths imply 69.9913, off by 0.0125%; holds.
- **Garry's Redemption (table row)** (Red Dead Redemption 2 hosting Garry's Mod (Source)). Units: 0.01905 m per guest unit (this checks the guest's own unit length only; the host's unit is not involved); the sourced unit lengths imply 0.01905 to 0.03 across 3 combinations of sourced scales, off by 0% to 25%; undetermined.
- **Minecraft x GTA V example (table row)** (Grand Theft Auto V hosting Minecraft (Java Edition)). Axes: declares guest x = host +x, y = host +z, z = host -y; the sourced directions give nothing; undetermined: Grand Theft Auto V has no sourced East axis; Grand Theft Auto V has no sourced Up axis; Grand Theft Auto V has no sourced North axis. Handedness: undetermined: Grand Theft Auto V has no sourced East, North, Up axis. Units: 1 host units per guest unit; undetermined: Grand Theft Auto V has no sourced unit length. Units: 1 m per guest unit (this checks the guest's own unit length only; the host's unit is not involved); the sourced unit lengths imply 1, off by 0%; holds.
- **Killcraft (table row)** (ULTRAKILL hosting Minecraft (Java Edition)). Units: 2 host units per guest unit; undetermined: ULTRAKILL has no sourced unit length.
- **LibertyCraft (table row)** (Grand Theft Auto IV hosting Minecraft (Java Edition)). Units: 1 m per guest unit (this checks the guest's own unit length only; the host's unit is not involved); the sourced unit lengths imply 1, off by 0%; holds.
- **Minecraft x Half-Life (table row)** (Half-Life (GoldSrc) hosting Minecraft (Java Edition)). Units: 40 host units per guest unit; the sourced unit lengths imply 33.3333 to 52.4934 across 3 combinations of sourced scales, off by 0% to 23.8%; undetermined. Units: 72 host units in 1.8 m (40 host units per metre, from a stated span) (this checks the host's own unit length only; the guest's unit is not involved); the sourced unit lengths imply 33.3333 to 52.4934 across 3 combinations of sourced scales, off by 0% to 23.8%; undetermined. Health: declares times 5; the proportional policy (host maximum over guest maximum) is 5; holds.
- **NewVegasCraft (table row)** (Fallout: New Vegas hosting Minecraft (Java Edition)). Axes: declares guest x = host +x, y = host +z, z = host -y; the sourced directions give x = host +x, z = host -y; undetermined: Fallout: New Vegas has no sourced Up axis. Handedness: undetermined: Fallout: New Vegas has no sourced Up axis. Units: 70 host units per guest unit; the sourced unit lengths imply 69.9913, off by 0.0125%; holds.
- **SkyCraft (table row)** (The Elder Scrolls V: Skyrim hosting Minecraft (Java Edition)). Units: 70 host units per guest unit; the sourced unit lengths imply 69.9913, off by 0.0125%; holds.

#### The same projects, read from their own source

| File | Row | Evidence | Axes | Handedness | Units | Health | Verdict | Exit |
|---|---|---|---|---|---|---|---|---|
| `src-2010-rust-rewrite-mashup.ttl` | 2010 Rust Rewrite Mashup (voxel collision) | source inspection | undetermined | undetermined | undetermined |  | undetermined | 2 |
| `src-garrys-redemption.ttl` | Garry's Redemption (units header) | source inspection | undetermined | undetermined | undetermined |  | undetermined | 2 |
| `src-minecraft-x-half-life.ttl` | Minecraft x Half-Life (link code) | source inspection | undetermined | undetermined | undetermined |  | undetermined | 2 |
| `src-skycraft.ttl` | SkyCraft (design notes) | source inspection | holds | holds | holds |  | holds | 0 |

- **2010 Rust Rewrite Mashup (voxel collision)** (Modern Warfare 2 (IW4L Rust rewrite) hosting Minecraft (Java Edition)). Axes: declares guest x = host +x, y = host +z, z = host -y; the sourced directions give nothing; undetermined: Modern Warfare 2 (IW4L Rust rewrite) has no sourced East axis; Modern Warfare 2 (IW4L Rust rewrite) has no sourced Up axis; Modern Warfare 2 (IW4L Rust rewrite) has no sourced North axis. Handedness: undetermined: Modern Warfare 2 (IW4L Rust rewrite) has no sourced East, North, Up axis. Units: 36 host units per guest unit; undetermined: Modern Warfare 2 (IW4L Rust rewrite) has no sourced unit length.
- **Garry's Redemption (units header)** (Red Dead Redemption 2 hosting Garry's Mod (Source)). Axes: declares guest x = host +x, y = host +y, z = host +z; the sourced directions give nothing; undetermined: Red Dead Redemption 2 has no sourced East axis; Red Dead Redemption 2 has no sourced North axis; Red Dead Redemption 2 has no sourced Up axis. Handedness: undetermined: Red Dead Redemption 2 has no sourced East, North, Up axis. Units: 0.01905 m per guest unit (this checks the guest's own unit length only; the host's unit is not involved); the sourced unit lengths imply 0.01905 to 0.03 across 3 combinations of sourced scales, off by 0% to 25%; undetermined.
- **Minecraft x Half-Life (link code)** (Half-Life (GoldSrc) hosting Minecraft (Java Edition)). Axes: declares guest x = host +x, y = host +z, z = host -y; the sourced directions give nothing; undetermined: Half-Life (GoldSrc) has no sourced East axis; Half-Life (GoldSrc) has no sourced Up axis; Half-Life (GoldSrc) has no sourced North axis. Handedness: undetermined: Half-Life (GoldSrc) has no sourced East, North, Up axis. Units: 40 host units per guest unit; the sourced unit lengths imply 33.3333 to 52.4934 across 3 combinations of sourced scales, off by 0% to 23.8%; undetermined.
- **SkyCraft (design notes)** (The Elder Scrolls V: Skyrim hosting Minecraft (Java Edition)). Axes: declares guest x = host +x, y = host +z, z = host -y; the sourced directions give x = host +x, y = host +z, z = host -y; holds. Handedness: the map's determinant through both bases is 1, and the bridge declares 1; holds. Units: 70 host units per guest unit; the sourced unit lengths imply 69.9913, off by 0.0125%; holds.

#### This repository's own games

| File | Row | Evidence | Axes | Handedness | Units | Health | Verdict | Exit |
|---|---|---|---|---|---|---|---|---|
| `syn-asset-passport-health.ttl` | Blockcraft into Pocket Battlers (health) | synthetic test |  |  |  | holds | holds | 0 |
| `syn-declared-mirror.ttl` | Declared north-south mirror | synthetic test | holds | holds | holds |  | holds | 0 |

- **Blockcraft into Pocket Battlers (health)** (Pocket Battlers hosting Blockcraft). Health: declares times 5; the proportional policy (host maximum over guest maximum) is 5; holds.
- **Declared north-south mirror** (The Elder Scrolls V: Skyrim hosting Minecraft (Java Edition)). Axes: declares guest x = host +x, y = host +z, z = host +y, mirroring North; the sourced directions give x = host +x, y = host +z, z = host +y; holds. Handedness: the map's determinant through both bases is -1, and the bridge declares -1; holds. Units: 70 host units per guest unit; the sourced unit lengths imply 69.9913, off by 0.0125%; holds.

#### Wrong on purpose

| File | Row | Evidence | Axes | Handedness | Units | Health | Verdict | Exit |
|---|---|---|---|---|---|---|---|---|
| `wrong-broken-basis.ttl` | Map into a broken basis | synthetic test | **refused** | **refused** |  |  | **refused** | 1 |
| `wrong-degenerate-map.ttl` | Two axes onto one | synthetic test | **refused** | **refused** | holds |  | **refused** | 1 |
| `wrong-false-mirror-claim.ttl` | Mirror claimed, not done | synthetic test | undetermined | **refused** | holds |  | **refused** | 1 |
| `wrong-health-multiplier.ttl` | Health times 4 | synthetic test |  |  |  | **refused** | **refused** | 1 |
| `wrong-health-native-and-multiplier.ttl` | Native and multiplied | synthetic test |  |  |  | **refused** | **refused** | 1 |
| `wrong-malformed-axis.ttl` | Not an axis | synthetic test | **refused** | **refused** |  |  | **refused** | 1 |
| `wrong-mirror-declared.ttl` | Mirror declared along the wrong direction | synthetic test | **refused** | holds | holds |  | **refused** | 1 |
| `wrong-mirrored.ttl` | Undeclared mirror | synthetic test | **refused** | **refused** | holds |  | **refused** | 1 |
| `wrong-naive-xyz.ttl` | Naive x/y/z copy | synthetic test | **refused** | holds | holds |  | **refused** | 1 |
| `wrong-unit-ratio.ttl` | 64 units per block | synthetic test |  |  | **refused** |  | **refused** | 1 |
| `wrong-unit-ratio-large.ttl` | 1000 units per block | synthetic test |  |  | **refused** |  | **refused** | 1 |
| `wrong-unsourced-fact.ttl` | Unsourced host unit | synthetic test |  |  | undetermined |  | **refused** | 1 |

- **Map into a broken basis** (A game whose east and north are one axis hosting Minecraft (Java Edition)). Axes: declares guest x = host +x, y = host +z, z = host -y; the sourced directions give x = host +x, y = host +z, z = host -x; refused. Handedness: the map's determinant through both bases is 0, and the bridge declares 1; refused. Facts: refused: A game's east, north and up must be three different axes. Read with `--facts examples/bridges/facts/wrong-broken-basis.ttl`, a synthetic facts file.
- **Two axes onto one** (The Elder Scrolls V: Skyrim hosting Minecraft (Java Edition)). Axes: declares guest x = host +x, y = host +x, z = host -y; the sourced directions give x = host +x, y = host +z, z = host -y; refused. Handedness: the map's determinant through both bases is 0, and the bridge declares 1; refused. Units: 70 host units per guest unit; the sourced unit lengths imply 69.9913, off by 0.0125%; holds.
- **Mirror claimed, not done** (The Elder Scrolls V: Skyrim hosting Minecraft (Java Edition)). Axes: declares guest x = host +x, y = host +z, z = host -y; the sourced directions give nothing; undetermined: the bridge declares a mirror without naming the world direction it flips (ga:mirrorDirection), so no single map can be derived. Handedness: the map's determinant through both bases is 1, and the bridge declares -1; refused. Units: 70 host units per guest unit; the sourced unit lengths imply 69.9913, off by 0.0125%; holds.
- **Health times 4** (Half-Life (GoldSrc) hosting Minecraft (Java Edition)). Health: declares times 4; the proportional policy (host maximum over guest maximum) is 5; refused.
- **Native and multiplied** (Half-Life (GoldSrc) hosting Minecraft (Java Edition)). Health: declares native and times 5; the proportional policy (host maximum over guest maximum) is 5; refused.
- **Not an axis** (The Elder Scrolls V: Skyrim hosting Minecraft (Java Edition)). Axes: declares guest x = host +w, y = host +z, z = host -y; the sourced directions give x = host +x, y = host +z, z = host -y; refused. Handedness: the map's determinant through both bases is 0, and the bridge declares 1; refused. Declaration: refused: The guest's x must be read off one signed host axis: +x, -x, +y, -y, +z or -z.
- **Mirror declared along the wrong direction** (The Elder Scrolls V: Skyrim hosting Minecraft (Java Edition)). Axes: declares guest x = host +x, y = host +z, z = host +y, mirroring East; the sourced directions give x = host -x, y = host +z, z = host -y; refused. Handedness: the map's determinant through both bases is -1, and the bridge declares -1; holds. Units: 70 host units per guest unit; the sourced unit lengths imply 69.9913, off by 0.0125%; holds.
- **Undeclared mirror** (The Elder Scrolls V: Skyrim hosting Minecraft (Java Edition)). Axes: declares guest x = host +x, y = host +z, z = host +y; the sourced directions give x = host +x, y = host +z, z = host -y; refused. Handedness: the map's determinant through both bases is -1, and the bridge declares 1; refused. Units: 70 host units per guest unit; the sourced unit lengths imply 69.9913, off by 0.0125%; holds.
- **Naive x/y/z copy** (The Elder Scrolls V: Skyrim hosting Minecraft (Java Edition)). Axes: declares guest x = host +x, y = host +y, z = host +z; the sourced directions give x = host +x, y = host +z, z = host -y; refused. Handedness: the map's determinant through both bases is 1, and the bridge declares 1; holds. Units: 70 host units per guest unit; the sourced unit lengths imply 69.9913, off by 0.0125%; holds.
- **64 units per block** (The Elder Scrolls V: Skyrim hosting Minecraft (Java Edition)). Units: 64 host units per guest unit; the sourced unit lengths imply 69.9913, off by 8.56%; refused.
- **1000 units per block** (The Elder Scrolls V: Skyrim hosting Minecraft (Java Edition)). Units: 1000 host units per guest unit; the sourced unit lengths imply 69.9913, off by 1329%; refused.
- **Unsourced host unit** (A game with an unsourced unit hosting Minecraft (Java Edition)). Units: 1 host units per guest unit; undetermined: A game with an unsourced unit has no sourced unit length. Facts: refused: A unit length is admitted only with the source's own words. A unit length is admitted only with the page it was read from. Read with `--facts examples/bridges/facts/wrong-unsourced-fact.ttl`, a synthetic facts file.

Refused by the input guard (`rules/bridge-input.rq`) before the rule runs:

| File | Predicates refused | Reason | Exit |
|---|---|---|---|
| `wrong-double-ratio.ttl` | `declaredHostUnitsPerGuestUnit` | A declared number is written as an xsd:integer or xsd:decimal, not a double, a string or an IRI. | 1 |
| `wrong-forged-derived.ttl` | `axisXAgrees`, `axisYAgrees`, `axisZAgrees`, `declaredHandedness`, `derivedGuestXFrom`, `derivedGuestYFrom`, `derivedGuestZFrom`, `handedness`, `handednessAgreement`, `healthMultiplierError`, `healthPolicyMultiplier` | A bridge may state only its host, guest, axis map, mirror, unit ratio, health policy and provenance; everything else is a game fact or derived by the engine. | 1 |
| `wrong-injected-fact.ttl` | `lengthEvidence`, `metres`, `quote`, `source`, `units` | A bridge file states things only about the bridges it declares; game facts come from ontology/ga-space.ttl. | 1 |
<!-- bridges:results:end -->

### What the table rows show

No published row is refused. A row holds when the facts it needs are sourced and agree on one value;
every other row is undetermined, and the checker names the missing or unsettled fact.

**The two Valve rows rest on different Valve scales, and neither says which.** The Valve Developer
Community's Unit page says a unit is "usually loosely analogous to roughly 1 inch, 0.75 inches, or 2-3
centimeters", and the checker encodes all three, the last as a range. For Source it takes 0.75 inch and
the range from that page and 1 inch from the Source Dimensions page. Minecraft × Half-Life's 40 units
per block (and its "72 units ≈ 1.8 m") falls inside the 2-3 cm range, sits close to the 1-inch scale,
and is well off the 0.75-inch one. The project's own code says the same
40 (`kUnitsPerBlock = 40.0` in `link/bsp_collision.h`), and its comment puts Gordon's 72-unit hull at
1.8 blocks rather than 1.8 metres, which with Minecraft's 1-metre block is the same ratio. Garry's
Redemption's 0.01905 m per Source unit is exactly the Unit page's 0.75 inch, 4.75 percent below its 2-3
cm range, and 25 percent off the Source Dimensions page's "1 Hammer unit (HU) ≈ 1 inch". That page also
says some props and map architecture "may be scaled ⅓ (~33%) larger than their real-world counterparts
(16 units for props, vs. 12 units for human characters)", which fits 0.75 inch for those objects, but it
states that as an enlargement, not as the unit's length, so the checker does not encode it. Each row
fits some Valve scale, neither says which one it means, and the checker reports both as undetermined,
with the errors above. A contract that writes "Source unit" without naming the scale has left the most
important fact out. Neither page is specific to the game it is applied to here: the Unit page is about
"Id Software and Valve engines" in general, and the Dimensions page was written for Half-Life 2 and
Counter-Strike: Source.

**Two rows are gameplay scales, and the table does not say so.** Killcraft's README says its 2 units per
block are there because "2 makes the Minecraft player about V1's height", and the 2010 Rust Rewrite Mashup's
`voxel.rs` picks 36 so the 70-unit soldier is "about two blocks tall" and a block is "below the 39-unit
jump". Neither is a measurement, and the table lists them next to measured ones. We found no source for
either host's unit length, so both are undetermined here. A contract should mark a gameplay rescale as
one; this vocabulary has no term for it yet (see below).

**The Bethesda rows are consistent.** The Creation Kit wiki gives Skyrim "128 world units is equal to 6
feet". The official GECK wiki's Exterior Cells page gives "4096 units by 4096 units or 192 feet by 192
feet", the same unit. That page names no game (the only one it mentions is Fallout 3, through FO3Edit),
and the GECK wiki serves both Fallout 3 and New Vegas, so applying it to New Vegas is our inference and
is labelled a derived comparison; so are New Vegas's east and north, read off a GetAngle page that
describes GECK 1.1.0.36, names only Fallout 3's Wasteland worldspace, and says other exterior
worldspaces "have not been tested". SkyCraft's and NewVegasCraft's 70 per block, and Faith Runner's 70
per metre, all hold. SkyCraft's own design notes give the axis map (`mc.z = -sky.y / 70`), and it is
exactly the one the checker derives from the two wikis. NewVegasCraft's map agrees on east and north; no
GECK page we could open says which axis points up, so its axis and handedness checks stay undetermined.
The row itself states "host x-east/y-north/z-up", but a creator's statement about a game is not a game
fact here.

**The Faith Runner row does not match its link.** The linked repository (at
`9470d755b6aa4e4fa9257fc1326abcfc3ad4b028`) is a Bevy rewrite of Mirror's Edge movement and does not
mention Skyrim; its tuning file works in Unreal units ("1 uu = 1 cm"). The row's number is consistent
with Skyrim's unit, so it holds as written, but we could not find where it comes from.

**The health row is a damage constant.** "health MC 20 → HL 100 (×5)" matches the proportional policy
(Half-Life's player spawns with 100, from `dlls/player.cpp` in Valve's Half-Life SDK; Minecraft's has
20), so it holds. In the project's code, though, the constant is `kMcToHlDamage`, it scales Minecraft
hits into Half-Life damage, and Minecraft keeps ownership of the player's health
(`MinecraftOwnsHealth()` in `link/mclink_server.cpp`). The ratio is right; the row's word for it is not.

**Two rows hold only against Minecraft's block.** "1 metre per block" is a claim about the guest's unit,
and Minecraft's wiki confirms it whatever the host is, so it says nothing about GTA's unit. LibertyCraft's
row gives only that, and its README (at `3ae53066a33cbbdb4543d14d37f2d85546f7b8d9`) states no scale, so
it holds, with the output marking it as a check of the guest's unit alone. The GTA V example says "1 GTA
metre = 1 block" and maps GTA's x, y and z into Minecraft without scaling, which also makes it one GTA
unit per block. The checker models both readings: the first holds against Minecraft's block, and the
second needs GTA V's own unit, which we found no source for, so it is undetermined, and so are the
example's axes.

## Game facts and their sources

Every fact below was read on the page linked, on 10 October 2026. The Creation Kit, GECK and Valve wikis
refuse automated readers, so the copy actually opened is an Internet Archive snapshot, linked next to the
page. Facts marked **derived comparison** are our inference from the quoted words, and each carries a
note saying what was inferred. For Skyrim, the wiki states north and the heading convention, and east
follows from its own conversion to a trigonometric angle, whose 0 the same page puts on the x-axis. For
New Vegas, every fact comes from a GECK wiki page that never names the game: the toolkit is shared with
Fallout 3, and the angle page quotes Fallout 3's worldspace. Games named in the
table with no fact here (GTA V, GTA IV, Red Dead Redemption 2,
ULTRAKILL, the IW4 rewrite, Mirror's Edge) have none because we found no source we could open, and every
check that needs one says undetermined.

<!-- bridges:facts:start -->
| Game | Fact | Engine derives | Evidence | Source | Quote |
|---|---|---|---|---|---|
| Blockcraft | maximum health 20 |  | source inspection | [page](https://github.com/fabio-rovai/asset-passport/blob/6095567a94c2192ffd0f99433f857880815f05a8/games/craft/profile.ttl#L13) | craft:game a ga:Game ; rdfs:label "Blockcraft" ; ga:maxPlayerHealth 20 ; ga:wholeNumbersOnly true . |
| Fallout: New Vegas | East is +x | basis incomplete | derived comparison | [page](http://geck.bethsoft.com/index.php?title=GetAngle), [copy opened](https://web.archive.org/web/20191114162229/http://geck.bethsoft.com:80/index.php?title=GetAngle) | They increase clockwise, from 0 at the north to 90 in the east. These are not the same as the standard mathematical/trigonometric "angles", which increase counterclockwise, from 0 at the east to 90 at the north. *(Our reading: The quote puts a trigonometric angle of 0 at the east. This page does not say which axis that angle lies on; +x is the standard convention, which the Creation Kit's GetAngleZ page states ("standard mathematical notation has 0 starting on the x-axis"). The page describes GECK version 1.1.0.36, names only Fallout 3's Wasteland worldspace and never names New Vegas, so applying it to New Vegas is our inference.)* |
| Fallout: New Vegas | North is +y | basis incomplete | derived comparison | [page](http://geck.bethsoft.com/index.php?title=GetAngle), [copy opened](https://web.archive.org/web/20191114162229/http://geck.bethsoft.com:80/index.php?title=GetAngle) | Z angle is measured with the positive y-axis as 0 and increasing clockwise from there. In the Wasteland worldspace, this is North, however, the same is not true of interiors (other exterior worldspaces have not been tested) *(Our reading: The page describes GECK version 1.1.0.36 and names only the Wasteland, which is Fallout 3's worldspace. It never names New Vegas, and it says other exterior worldspaces have not been tested, so reading +y as north in New Vegas is our inference.)* |
| Fallout: New Vegas | 4096 units = 192 ft | 0.0142875 m per unit | derived comparison | [page](http://geck.bethsoft.com/index.php?title=Exterior_Cells), [copy opened](https://web.archive.org/web/20191223030354/http://geck.bethsoft.com:80/index.php?title=Exterior_Cells) | Each exterior cell is 4096 units by 4096 units or 192 feet by 192 feet or 58.5 meters by 58.5 meters. *(Our reading: The page names no game; the only game it mentions is Fallout 3, through the FO3Edit tool. The GECK wiki is shared by Fallout 3 and New Vegas, so reading this as New Vegas's unit is our inference.)* |
| Garry's Mod (Source) | East is +x | basis determinant 1 | documentation | [page](https://developer.valvesoftware.com/wiki/Coordinates), [copy opened](https://web.archive.org/web/20260109211752/https://developer.valvesoftware.com/wiki/Coordinates) | Coordinates in Source are (X,Y,Z), where X is forward/East, Y is left/North, and Z is up. |
| Garry's Mod (Source) | North is +y | basis determinant 1 | documentation | [page](https://developer.valvesoftware.com/wiki/Coordinates), [copy opened](https://web.archive.org/web/20260109211752/https://developer.valvesoftware.com/wiki/Coordinates) | Coordinates in Source are (X,Y,Z), where X is forward/East, Y is left/North, and Z is up. |
| Garry's Mod (Source) | Up is +z | basis determinant 1 | documentation | [page](https://developer.valvesoftware.com/wiki/Coordinates), [copy opened](https://web.archive.org/web/20260109211752/https://developer.valvesoftware.com/wiki/Coordinates) | Coordinates in Source are (X,Y,Z), where X is forward/East, Y is left/North, and Z is up. |
| Garry's Mod (Source) | 1 unit = 2 to 3 cm | 0.02 to 0.03 m per unit | documentation | [page](https://developer.valvesoftware.com/wiki/Unit), [copy opened](https://web.archive.org/web/20260701213934/https://developer.valvesoftware.com/wiki/Unit) | Units in Id Software and Valve engines are referred to as quake units (qu) or hammer units (hu), and are usually loosely analogous to roughly 1 inch, 0.75 inches, or 2-3 centimeters |
| Garry's Mod (Source) | 1 unit = 1 in | 0.0254 m per unit | documentation | [page](https://developer.valvesoftware.com/wiki/Dimensions_(Half-Life_2_and_Counter-Strike:_Source)), [copy opened](https://web.archive.org/web/20260918191618/https://developer.valvesoftware.com/wiki/Dimensions_(Half-Life_2_and_Counter-Strike:_Source)) | Objects in the Source engine are scaled based on Hammer units. 1 Hammer unit (HU) ≈ 1 inch (or 2.54 centimeters). |
| Garry's Mod (Source) | 1 unit = 0.75 in | 0.01905 m per unit | documentation | [page](https://developer.valvesoftware.com/wiki/Unit), [copy opened](https://web.archive.org/web/20260701213934/https://developer.valvesoftware.com/wiki/Unit) | Units in Id Software and Valve engines are referred to as quake units (qu) or hammer units (hu), and are usually loosely analogous to roughly 1 inch, 0.75 inches, or 2-3 centimeters |
| Half-Life (GoldSrc) | maximum health 100 |  | source inspection | [page](https://github.com/ValveSoftware/halflife/blob/b1b5cf5892918535619b2937bb927e46cb097ba1/dlls/player.cpp#L3000-L3005) | pev->health = 100; ... pev->max_health = pev->health; |
| Half-Life (GoldSrc) | 1 unit = 2 to 3 cm | 0.02 to 0.03 m per unit | documentation | [page](https://developer.valvesoftware.com/wiki/Unit), [copy opened](https://web.archive.org/web/20260701213934/https://developer.valvesoftware.com/wiki/Unit) | Units in Id Software and Valve engines are referred to as quake units (qu) or hammer units (hu), and are usually loosely analogous to roughly 1 inch, 0.75 inches, or 2-3 centimeters |
| Half-Life (GoldSrc) | 1 unit = 1 in | 0.0254 m per unit | documentation | [page](https://developer.valvesoftware.com/wiki/Unit), [copy opened](https://web.archive.org/web/20260701213934/https://developer.valvesoftware.com/wiki/Unit) | Units in Id Software and Valve engines are referred to as quake units (qu) or hammer units (hu), and are usually loosely analogous to roughly 1 inch, 0.75 inches, or 2-3 centimeters |
| Half-Life (GoldSrc) | 1 unit = 0.75 in | 0.01905 m per unit | documentation | [page](https://developer.valvesoftware.com/wiki/Unit), [copy opened](https://web.archive.org/web/20260701213934/https://developer.valvesoftware.com/wiki/Unit) | Units in Id Software and Valve engines are referred to as quake units (qu) or hammer units (hu), and are usually loosely analogous to roughly 1 inch, 0.75 inches, or 2-3 centimeters |
| Minecraft (Java Edition) | East is +x | basis determinant 1 | documentation | [page](https://minecraft.wiki/w/Coordinates) | The x-axis indicates the player's distance east (positive) or west (negative) of the origin point |
| Minecraft (Java Edition) | North is -z | basis determinant 1 | documentation | [page](https://minecraft.wiki/w/Coordinates) | The z-axis indicates the player's distance south (positive) or north (negative) of the origin point |
| Minecraft (Java Edition) | Up is +y | basis determinant 1 | documentation | [page](https://minecraft.wiki/w/Coordinates) | As the player's elevation rises, the y-axis number increases |
| Minecraft (Java Edition) | maximum health 20 |  | documentation | [page](https://minecraft.wiki/w/Health) | the player normally has 20 maximum health points |
| Minecraft (Java Edition) | 1 unit = 1 m | 1 m per unit | documentation | [page](https://minecraft.wiki/w/Coordinates) | The unit length of the three axes equals the side of one block. And, in terms of real-world measurement, one block equals 1 cubic meter. |
| Pocket Battlers | maximum health 100 |  | source inspection | [page](https://github.com/fabio-rovai/asset-passport/blob/6095567a94c2192ffd0f99433f857880815f05a8/games/battle/profile.ttl#L12) | battle:game a ga:Game ; rdfs:label "Pocket Battlers" ; ga:maxPlayerHealth 100 ; |
| The Elder Scrolls V: Skyrim | East is +x | basis determinant 1 | derived comparison | [page](https://ck.uesp.net/wiki/GetAngleZ_-_ObjectReference), [copy opened](https://web.archive.org/web/20250731204421/https://ck.uesp.net/wiki/GetAngleZ_-_ObjectReference) | Note that standard mathematical notation has 0 starting on the x-axis, rather than the y-axis, and increases counter-clockwise, not clockwise. ... if ( GameAngleZ < 90 ) TrigAngleZ = 90 - GameAngleZ else TrigAngleZ = 450 - GameAngleZ endif *(Our reading: A heading of 90 is east (clockwise from north). It takes the page's else branch, 450 - 90 = 360, which is the same angle as 0, and the page puts 0 on the x-axis, so east is +x.)* |
| The Elder Scrolls V: Skyrim | North is +y | basis determinant 1 | documentation | [page](https://ck.uesp.net/wiki/GetAngleZ_-_ObjectReference), [copy opened](https://web.archive.org/web/20250731204421/https://ck.uesp.net/wiki/GetAngleZ_-_ObjectReference) | Z angle is measured with the positive y-axis as 0 and increasing clockwise from there. ... In the Tamriel worldspace, a Z angle of 0 is North |
| The Elder Scrolls V: Skyrim | Up is +z | basis determinant 1 | documentation | [page](https://ck.uesp.net/wiki/GetPositionZ_-_ObjectReference), [copy opened](https://web.archive.org/web/20241229073314/https://ck.uesp.net/wiki/GetPositionZ_-_ObjectReference) | The higher you are in the game (i.e. on a mountain, hill, ...), the more positive the value of the Z position will be. |
| The Elder Scrolls V: Skyrim | 128 units = 6 ft | 0.0142875 m per unit | documentation | [page](https://ck.uesp.net/wiki/Unit), [copy opened](https://web.archive.org/web/20250917163955/https://ck.uesp.net/wiki/Unit) | The game's measurement system is scaled so that 128 world units is equal to 6 feet. |
<!-- bridges:facts:end -->

## What it cannot check

- **Offsets, angles and origins.** `yOffset`, the "exterior yOffset fixed at −34", "yaw = 180 − heading",
  rotation order and a floating origin are outside it. It checks the linear part of the map: axes,
  signs and scale.
- **The running code.** A table row or a `src-` file is a declaration. The checker compares it with game
  facts; it does not run either game, and a `src-` file was transcribed by hand from the commit it names.
- **A deliberate rescale.** A gameplay scale (Killcraft, the 2010 mashup) can only hold, be refused or be
  undetermined against a metric unit. There is no term yet for "this ratio is a design choice, not a
  measurement", and adding one needs a check that can refuse it.
- **More than the wiki says.** A fact is as good as its page. The GoldSrc unit scales, and Source's
  0.75-inch and 2-3 cm scales, come from a page about "Id Software and Valve engines" in general; the
  other Source facts come from pages written for Half-Life 2 and Counter-Strike: Source and are applied
  to Garry's Mod; the GECK wiki is
  shared by Fallout 3 and New Vegas, its cited pages never name New Vegas, and the angle page quotes
  Fallout 3's worldspace.
- **The tolerances.** Two percent on a unit ratio and 0.001 on a health multiplier are choices. Every
  error is printed, so a reader can apply another.
- **A deliberate rotation.** The axis check admits exactly the map the two games' directions imply, or
  that map with one named direction mirrored. A bridge that turns the world on purpose is refused; there
  is no term for a declared rotation yet.
- **Ownership, channels, protocol and lifecycle**, the other rows of Universal Modder's contract template.

## An engine fault found on the way

Decimal arithmetic in the engine (Oxigraph's `oxsdatatypes` `Decimal`, an i128 holding 18 fractional
digits; the code below is in the registry's `oxsdatatypes` 0.2.3) returns no value, with no error, in two
cases it treats as overflow. Both were measured on the v2.0.1 release and on main.

- `checked_mul` strips the trailing zeros from both operands' scaled values and returns nothing when the
  two counts add up to fewer than 18. So `0.0 * 0.5` and `(1 / 3) * 0.5` are unbound, while
  `(1 / 3) * 2` is fine.
- `checked_div` multiplies the dividend by 10 for as long as it still fits in an i128 (its headroom),
  strips the trailing zeros from the divisor, and returns nothing when the two counts add up to fewer
  than 18. A zero dividend has no headroom, so `0.0 / 0.5` and `0 / 0.01905` are unbound while
  `0.0 / 2.0` is fine. Against a divisor that uses all 18 fractional digits, any dividend larger than
  i128::MAX / 10^36 (about 170.14) is unbound: `171 / 69.991251093613298337` has no value, while
  `170 / 69.991251093613298337` is 2.428875 and `1000 / 70` is fine.

The first version of this checker described only the trailing-zero case and computed its relative errors
in decimals. A declared ratio of about 171 or more against Skyrim's implied 69.99... units per block then
came back with no error and was reported undetermined, not refused, however wrong it was. The rule now
computes its errors in `xsd:double` and casts them back to decimals for the contract, and the checker
refuses a declaration whose error the engine drops (`wrong-unit-ratio-large.ttl`). The same fault could
drop a unit length before the unit check ever saw it: a sourced length of 0.333333333333333333 inch
has no value in decimals, its scale never joined the check, and a ratio that fits only the other scale
was reported as holding with exit 0. Metres per unit is now computed in decimals where the engine can
(so 0.75 inch stays exactly 0.01905 m) and in doubles where it cannot, and the checker refuses a unit
check that is missing any sourced length fact.
`tests/test_bridges.py` pins every expression above against the engine, so a release that fixes the
fault fails that test and this description gets updated. The fault is separate from the right-grouping
of arithmetic chains described in `rules/convert.rq`, and it is not yet reported upstream.

## Adding a game or a bridge

A game fact goes in `ontology/ga-space.ttl` as an IRI evidence node with `ga:source`, `ga:quote` and
`ga:evidenceLevel`: `ga:units` with `ga:metres`, `ga:feet` or `ga:inches` for a length, or with
`ga:centimetresFrom` and `ga:centimetresTo` for a range; `ga:direction`
(`ga:East`, `ga:North`, `ga:Up`) with `ga:axis` for a direction; `ga:maxHealth` for health. If you cannot
source it, leave it out.

A bridge is a small Turtle file that states only its bridges; see `examples/bridges/`. Add it to
`EXPECTED` in `tests/test_bridges.py`, and run `python3 scripts/bridges_report.py` to update this page. A
made-up game for a test goes in `examples/bridges/facts/<name>.ttl`, which the tests and this page pass
with `--facts`.
