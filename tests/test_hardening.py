"""Checks added after an adversarial review. Each one refuses something here.

The rules gate compares blank nodes by structure; discovery refuses two
directories for one game and malformed keys; the signature gate refuses
malformed passports; admit refuses a passport with no certificate and says
plainly when the engine cannot admit at all; the command line keeps its exit
codes; a plain build never replaces a published key.
"""

import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from _support import games_copy, needs_packs, packs_carry_certificates, signed_root

from passport import games, judge, sign
from passport.engine import GA, ROOT, Engine, EngineError, engine_binary, scratch

TONIC = {"id": "fizz_tonic", "kind": "FizzTonic", "name": "Fizz Tonic", "restoresHp": 40}
SWORD = {"id": "crystal_sword", "kind": "CrystalSword", "name": "Crystal Sword", "attack": 6, "material": "Crystal"}

# Blockcraft's Crystal and Iron axioms with their hasValue types swapped. Once
# blank-node labels are erased, the asserted lines are the same multiset.
CRYSTAL = ("owl:hasValue craft:Crystal ]\n    rdfs:subClassOf [ a owl:Restriction ; "
           "owl:onProperty ga:elementalType ; owl:hasValue ga:Rock ]")
IRON = ("owl:hasValue craft:Iron ]\n    rdfs:subClassOf [ a owl:Restriction ; "
        "owl:onProperty ga:elementalType ; owl:hasValue ga:Steel ]")


@pytest.fixture(scope="module")
def signed():
    return signed_root()


def rewired(profile_text: str) -> str:
    assert CRYSTAL in profile_text and IRON in profile_text
    return (profile_text.replace(CRYSTAL, "@@D").replace(IRON, "@@I")
            .replace("@@D", CRYSTAL.replace("ga:Rock", "ga:Steel"))
            .replace("@@I", IRON.replace("ga:Steel", "ga:Rock")))


def _admit(pack, root, target="craft", binary=None):
    return judge.admit(pack, target, scratch("t"), binary, root=root)


# ------------------------------------------------------------------ rules gate: blank nodes


def _asserted(profile_path):
    """The asserted lines a certificate holds for the hub plus this profile."""
    with Engine(scratch("tbox")) as e:
        e.call("onto_clear")
        e.load(judge.HUB)
        e.load(profile_path)
        e.call("onto_reason", profile=judge.PROFILE, certificate_dir=str(e.workdir / "cert"))
        return e.workdir / "cert" / "asserted.tsv"


def test_rewiring_two_restrictions_is_seen_by_the_rules_comparison():
    """The defect this guards against: with blank-node labels erased, the
    swapped profile and the published one are the same multiset of lines.
    Compared by structure, they differ in exactly the two swapped axioms."""
    import re
    d = scratch("rw")
    (d / "rewired.ttl").write_text(rewired((ROOT / "games" / "craft" / "profile.ttl").read_text()))
    published, swapped = _asserted(ROOT / "games" / "craft" / "profile.ttl"), _asserted(d / "rewired.ttl")
    erase = lambda p: Counter(re.sub(r"_:[A-Za-z0-9]+", "_:b", l) for l in p.read_text().splitlines() if l)
    assert erase(published) == erase(swapped)  # the old comparison saw nothing
    a, b = judge.TBox.read(published), judge.TBox.read(swapped)
    assert sum((a.statements - b.statements).values()) == 2
    assert sum((b.statements - a.statements).values()) == 2
    assert judge.TBox.read(_asserted(ROOT / "games" / "craft" / "profile.ttl")).statements == a.statements


@needs_packs
def test_a_signed_passport_under_rewired_rules_is_refused_at_rules(signed):
    """The issuer's real key, a sound proof, and rules that make a Crystal
    Sword Steel-typed. Before the structural comparison this crossed as
    typeInTarget ga:Steel."""
    root, keys = signed
    d = scratch("rw")
    doctored = d / "doctored.ttl"
    doctored.write_text(rewired((root / "craft" / "profile.ttl").read_text()))
    ex = judge.export("craft", SWORD, d, root=root, profile=doctored, key=keys["craft"])
    v = _admit(ex["pack"], root, target="battle")
    assert v["signature"]["verified"] is True and v["proof"]["status"] == "certificate_accepted"
    assert (v["verdict"], v["stage"]) == ("refused", "rules"), v.get("conversion")
    assert any("craft:Crystal" in l and "ga:Steel" in l for l in v["drift"]["added"])
    assert any("craft:Crystal" in l and "ga:Rock" in l for l in v["drift"]["removed"])


A, B, P = "<urn:a>", "<urn:b>", "<urn:p>"


def test_a_shared_blank_node_is_refused_not_compared():
    with pytest.raises(ValueError, match="object of 2 statements"):
        judge.TBox.of([(A, P, "_:x"), (B, P, "_:x"), ("_:x", P, A)])


@pytest.mark.parametrize("triples", [
    [("_:x", P, "_:y"), ("_:y", P, "_:x")],                 # a cycle that nothing points into
    [(A, P, "_:x"), ("_:x", P, "_:y"), ("_:y", P, "_:x")],  # a cycle entered from an IRI: _:x has two parents
])
def test_a_blank_node_cycle_is_refused_not_compared(triples):
    with pytest.raises(ValueError, match="cycle|object of 2"):
        judge.TBox.of(triples)


def test_identical_trees_with_different_labels_compare_equal():
    """The control: fresh labels alone are not drift."""
    one = judge.TBox.of([(A, P, "_:x"), ("_:x", P, B), ("_:r", P, "_:s"), ("_:s", P, A)])
    two = judge.TBox.of([(A, P, "_:q"), ("_:q", P, B), ("_:m", P, "_:n"), ("_:n", P, A)])
    assert one.statements == two.statements


# ------------------------------------------------------------------ discovery


def test_two_directories_that_declare_one_game_are_refused():
    """Otherwise the later one replaces the first game's published export key,
    and a forger's passport signed with the later key gets through."""
    root = games_copy()
    battle = games.get("battle", root).iri
    shutil.copytree(root / "battle", root / "zz_mod")
    sign.set_export_key(root / "zz_mod" / "profile.ttl", battle,
                        sign.public_b64(sign.generate()))
    with pytest.raises(EngineError, match="both declare the game"):
        games.discover(root)


@pytest.mark.parametrize("bad", ["abc", base64.b64encode(b"x" * 31).decode()])
def test_an_export_key_that_is_not_32_bytes_of_base64_is_refused(bad):
    root = games_copy()
    sign.set_export_key(root / "battle" / "profile.ttl", games.get("battle", root).iri, bad)
    with pytest.raises(EngineError, match="not base64 of a 32-byte"):
        games.discover(root)


def test_a_profile_with_two_export_keys_is_refused():
    root = games_copy()
    p = root / "battle" / "profile.ttl"
    iri = games.get("battle", root).iri
    k1, k2 = (sign.public_b64(sign.generate()) for _ in range(2))
    p.write_text(p.read_text() + f'\n<{iri}> <{GA}exportKey> "{k1}" .\n<{iri}> <{GA}exportKey> "{k2}" .\n')
    with pytest.raises(EngineError, match="export keys; a game has one"):
        games.discover(root)


def test_publishing_a_key_that_does_not_land_is_refused(monkeypatch):
    """publish_key reads the profile back through the engine. If the write did
    not take, it refuses rather than report a key the profile does not publish."""
    root = games_copy()
    monkeypatch.setattr(sign, "set_export_key", lambda *a, **k: None)
    with pytest.raises(EngineError, match="the engine reads its export key"):
        games.publish_key("craft", sign.public_b64(sign.generate()), root)


def test_a_publish_that_breaks_the_profile_is_undone(monkeypatch):
    """A rewrite that leaves two keys made every command that discovers games
    fail until the file was edited by hand. The profile is restored now."""
    root = games_copy()
    p = root / "craft" / "profile.ttl"
    before = p.read_bytes()
    iri = games.get("craft", root).iri
    extra = sign.public_b64(sign.generate())
    real = sign.set_export_key

    def two_keys(profile, game_iri, pub):
        real(profile, game_iri, pub)
        Path(profile).write_text(Path(profile).read_text() + f'craft:game ga:exportKey "{extra}" .\n')

    monkeypatch.setattr(sign, "set_export_key", two_keys)
    with pytest.raises(EngineError, match="export keys; a game has one"):
        games.publish_key("craft", sign.public_b64(sign.generate()), root)
    assert p.read_bytes() == before
    assert games.discover(root)["craft"].iri == iri


def test_a_contract_missing_from_a_sibling_contracts_directory_falls_back_to_the_repository():
    base = scratch("sib")
    shutil.copytree(ROOT / "games", base / "games", ignore=shutil.ignore_patterns("__pycache__"))
    (base / "contracts").mkdir()
    shutil.copy(ROOT / "contracts" / "battle-border.shacl.ttl", base / "contracts" / "battle-border.shacl.ttl")
    found = games.discover(base / "games")
    assert found["battle"].border == (base / "contracts" / "battle-border.shacl.ttl").resolve()
    assert found["craft"].border == (ROOT / "contracts" / "craft-border.shacl.ttl").resolve()
    assert found["craft"].border.exists()


def test_discovery_reads_each_games_health_through_the_engine():
    found = games.discover()
    assert (found["craft"].max_player_health, found["battle"].max_player_health) == (20, 100)


# ------------------------------------------------------------------ signature gate: malformed input


def _pack_file(obj) -> "os.PathLike":
    p = scratch("mal") / "p.pack"
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj))
    return p


PUBLISHED = {"urn:g": ("Test game", sign.public_b64(sign.generate()))}


@pytest.mark.parametrize("body,why", [
    ("[]", "a JSON list, not an object"),
    ("hello", "not well-formed JSON"),
    ({"manifest": "x", "signature": {"alg": "Ed25519", "game": "urn:g", "value": "AAAA"}}, "manifest is not an object"),
    ({"manifest": {"content_sha256": "ab"}, "signature": {"alg": "RSA", "game": "urn:g", "value": "AAAA"}},
     "only Ed25519 is accepted"),
])
def test_a_malformed_passport_is_refused_at_the_signature_gate(body, why):
    v = sign.verify(_pack_file(body), PUBLISHED)
    assert v["ok"] is False and why in v["why"], v


def test_a_passport_file_that_cannot_be_opened_is_an_error_not_a_refusal():
    with pytest.raises(OSError):
        sign.verify(scratch("mal") / "does-not-exist.pack", PUBLISHED)


def test_a_published_key_that_is_not_a_key_is_refused_by_the_signature_gate():
    """Discovery refuses such a profile first; the gate refuses it on its own too."""
    v = sign.verify(_pack_file({"manifest": {"content_sha256": "ab"},
                                "signature": {"alg": "Ed25519", "game": "urn:g", "value": "AAAA"}}),
                    {"urn:g": ("Test game", "abc")})
    assert v["ok"] is False and "not base64 of a 32-byte" in v["why"]


def test_signing_a_pack_with_no_content_digest_is_refused():
    p = _pack_file({"graph": "", "manifest": {"sha256": "00"}})
    with pytest.raises(ValueError, match="nothing to sign"):
        sign.sign_pack(p, "urn:g", sign.generate())
    assert "signature" not in json.loads(p.read_text())


# ------------------------------------------------------------------ admit: certificates and engines


@needs_packs
def test_a_signed_passport_with_no_certificate_is_refused_at_unpack(signed):
    root, keys = signed
    run = scratch("nocert")
    out = run / "export"
    out.mkdir(parents=True)
    with Engine(out) as e:
        judge._lift(e, "battle", TONIC, out, root=root)
        e.call("onto_reason", profile=judge.PROFILE)
        e.call("onto_pack", path=str(run / "p.pack"), name="x", version="0.1.0")
    assert "certificate" not in json.loads((run / "p.pack").read_text())["manifest"]
    judge.sign_existing(run / "p.pack", games.get("battle", root).iri, keys["battle"])
    v = _admit(run / "p.pack", root)
    assert v["signature"]["verified"] is True
    assert (v["verdict"], v["stage"]) == ("refused", "unpack")
    assert "carries no certificate" in v["refusals"][0]["message"]


@needs_packs
def test_a_source_game_the_receiver_has_no_profile_for_is_refused_at_rules(signed):
    """Signed by a game the receiver knows, about an item derived to come from
    a game the receiver has never heard of."""
    root, keys = signed
    ex = judge.export("craft", SWORD, scratch("t"), root=root, key=keys["battle"],
                      sign_as=games.get("battle", root).iri)
    receiver = games_copy()
    shutil.copy(root / "battle" / "profile.ttl", receiver / "battle" / "profile.ttl")
    shutil.rmtree(receiver / "craft")
    v = _admit(ex["pack"], receiver, target="battle")
    assert v["signature"]["verified"] is True
    assert (v["verdict"], v["stage"]) == ("refused", "rules")
    assert "No published profile for the source game" in v["refusals"][0]["message"]


def _engine_without_266():
    """The engine to show the #266 error on: OO_BIN_RELEASED if set, else the
    default engine when it lacks #266, else nothing."""
    rel = os.environ.get("OO_BIN_RELEASED")
    if rel:
        return rel
    return None if packs_carry_certificates() else engine_binary()


def test_admitting_on_an_engine_without_266_is_an_error_not_a_crash():
    binary = _engine_without_266()
    if not binary:
        pytest.skip("this engine has #266; set OO_BIN_RELEASED to a v2.0.1 binary to run this test here")
    pack = ROOT / "site" / "passports" / "battle-fizz_tonic.pack"
    with pytest.raises(EngineError, match="#266"):
        judge.admit(pack, "craft", scratch("t"), binary)
    rc, out, _ = cli("admit", str(pack), "--into", "craft", env={"OO_BIN": binary})
    assert rc == 2 and "#266" in out["error"]


# ------------------------------------------------------------------ the command line


def cli(*args, env=None, pre=""):
    code = f"import sys; {pre}from passport.__main__ import main; sys.exit(main(sys.argv[1:]))"
    p = subprocess.run([sys.executable, "-c", code, *args], cwd=ROOT, capture_output=True,
                       text=True, timeout=300, env={**os.environ, **(env or {})})
    lines = p.stdout.strip().splitlines()
    return p.returncode, json.loads(lines[-1]) if lines else None, p.stderr


def test_cli_a_missing_passport_file_exits_2():
    rc, out, err = cli("admit", str(scratch("t") / "does-not-exist.pack"), "--into", "craft")
    assert rc == 2 and "no passport file" in out["error"], err


@needs_packs
@pytest.mark.parametrize("body,why", [("[]", "JSON list"), ("hello", "not well-formed JSON")])
def test_cli_a_malformed_passport_is_refused_with_exit_1(body, why):
    p = _pack_file(body)
    rc, out, err = cli("admit", str(p), "--into", "craft")
    assert (rc, out["verdict"], out["stage"]) == (1, "refused", "signature"), err
    assert any(why in m for m in out["refusals"])


def test_cli_an_unexpected_exception_exits_2_not_1():
    rc, out, _ = cli("judge", "--from", "craft", "--into", "battle", "--item", "blast_block",
                     pre="import passport.judge as j; j.judge_direct = lambda *a, **k: [][0]; "
                         "import passport.__main__ as m; m.judge_direct = j.judge_direct; ")
    assert rc == 2 and out["type"] == "IndexError"


def test_cli_judge_runs_without_the_cryptography_package():
    """The direct lane signs nothing, so it must not need cryptography."""
    rc, out, err = cli("judge", "--from", "battle", "--into", "craft", "--item", "fizz_tonic",
                       pre="sys.modules['cryptography'] = None; ")
    assert (rc, out["verdict"]) == (0, "converted"), err


@needs_packs
def test_cli_unsigned_export_never_opens_a_key_file():
    """A key file that cannot be parsed sits where battle's key would be. An
    unsigned export succeeds, so it never read it; a signed export fails on it."""
    keys = scratch("garbage") / "k"
    keys.mkdir()
    battle = games.get("battle")
    (keys / sign.key_path(battle).name).write_text("not a key")
    env = {"ASSET_PASSPORT_KEYS": str(keys)}
    d = scratch("cli")
    rc, out, err = cli("export", "--from", "battle", "--item", "fizz_tonic", "--out", str(d / "u.pack"),
                       "--unsigned", env=env)
    assert rc == 0 and out["signature"] is None, err
    rc, out, _ = cli("export", "--from", "battle", "--item", "fizz_tonic", "--out", str(d / "s.pack"), env=env)
    assert rc == 2


def test_cli_keys_for_another_game_in_a_same_named_directory_makes_a_new_key():
    """The reviewer's case: a directory called craft that declares another game."""
    keys = scratch("keys") / "k"
    env = {"ASSET_PASSPORT_KEYS": str(keys)}
    real = games_copy()
    rc, first, err = cli("keys", "--game", "craft", "--write", "--games", str(real), env=env)
    assert rc == 0, err
    other = games_copy()
    p = other / "craft" / "profile.ttl"
    p.write_text(p.read_text().replace("craft:game a ga:Game", "<https://example.org/mycraft#game> a ga:Game"))
    rc, second, err = cli("keys", "--game", "craft", "--write", "--games", str(other), env=env)
    assert rc == 0, err
    assert second["game"] == "https://example.org/mycraft#game"
    assert second["generated"] is True and second["public_key"] != first["public_key"]


# ------------------------------------------------------------------ the build


def _build_module():
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_a_plain_build_never_replaces_a_published_key(monkeypatch):
    """No private key here (tests have an empty keys directory): the build
    stops, and every profile is byte for byte what it was."""
    root = games_copy()
    monkeypatch.setenv("ASSET_PASSPORT_GAMES", str(root))
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(scratch("keys") / "k"))
    before = {k: (root / k / "profile.ttl").read_bytes() for k in ("craft", "battle")}
    b = _build_module()
    with pytest.raises(SystemExit, match="does not replace them on its own"):
        b.real_keys(games.discover(root), engine_binary(), new_keys=False)
    assert {k: (root / k / "profile.ttl").read_bytes() for k in before} == before
    keys = b.real_keys(games.discover(root), engine_binary(), new_keys=True)  # the opt-in does
    for k, priv in keys.items():
        assert games.discover(root)[k].export_key == sign.public_b64(priv)
        assert (root / k / "profile.ttl").read_bytes() != before[k]
    # A private key that is not the published one: a plain build refuses, and
    # does not "fix" the profile to match the key on this machine.
    games.publish_key("craft", sign.public_b64(sign.generate()), root)
    published = (root / "craft" / "profile.ttl").read_bytes()
    with pytest.raises(SystemExit, match="is not the export key"):
        b.real_keys(games.discover(root), engine_binary(), new_keys=False)
    assert (root / "craft" / "profile.ttl").read_bytes() == published


def test_the_build_stops_on_a_third_game_before_writing_anything(monkeypatch):
    root = games_copy()
    (root / "puzzle").mkdir()
    (root / "puzzle" / "profile.ttl").write_text(
        "@prefix ga: <https://tesseractsemantics.com/ns/asset-passport/ga#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        '<https://example.org/puzzle#game> a ga:Game ; rdfs:label "Tile Puzzle" .\n')
    monkeypatch.setenv("ASSET_PASSPORT_GAMES", str(root))
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(scratch("keys") / "k"))
    before = {p: p.read_bytes() for p in root.glob("*/profile.ttl")}
    with pytest.raises(SystemExit, match="two games side by side"):
        _build_module().main(["--new-keys"])
    assert {p: p.read_bytes() for p in root.glob("*/profile.ttl")} == before
    assert not sign.keys_dir().exists()


# ------------------------------------------------------------------ a second review: the gates


from passport import forge  # noqa: E402

GOLD = {"id": "gold_sword", "kind": "CrystalSword", "name": "Gold Sword", "attack": 7, "material": "Gold"}
ORB = {"id": "capture_orb", "kind": "CaptureOrb", "name": "Capture Orb", "catchRate": 40}
RDF_TYPE_IRI = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
OWL = "http://www.w3.org/2002/07/owl#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"


def _signed_pack(root, keys, game, rec, edit=None):
    """An honest export, optionally edited, re-digested and signed again with
    the game's own test key: what a dishonest issuer can do."""
    run = scratch("t")
    ex = judge.export(game, rec, run, root=root, key=keys[game])
    if edit is None:
        return ex["pack"], ex["item_iri"]
    pack = forge.read(ex["pack"])
    edit(pack, ex["item_iri"])
    forge.redigest(pack)
    p = forge.write(pack, run / "edited.pack")
    judge.sign_existing(p, games.get(game, root).iri, keys[game])
    return p, ex["item_iri"]


def _add_graph(lines):
    def edit(pack, item):
        pack["graph"] = pack["graph"].rstrip("\n") + "\n" + "\n".join(l.format(item=item) for l in lines) + "\n"
    return edit


FIRE_RULE = [  # Gold placed on the Fire type, in the graph only
    f"_:m <{RDF_TYPE_IRI[1:-1]}> <{OWL}Restriction> .",
    f"_:m <{OWL}onProperty> <{GA}madeOf> .",
    f"_:m <{OWL}hasValue> <https://tesseractsemantics.com/ns/asset-passport/craft#Gold> .",
    f"_:m <{RDFS}subClassOf> _:t .",
    f"_:t <{RDF_TYPE_IRI[1:-1]}> <{OWL}Restriction> .",
    f"_:t <{OWL}onProperty> <{GA}elementalType> .",
    f"_:t <{OWL}hasValue> <{GA}Fire> .",
]
FIRE_FACT = [f"<{{item}}> <{GA}elementalType> <{GA}Fire> ."]


@needs_packs
def test_the_honest_gold_sword_is_refused_for_having_no_type(signed):
    """The control for the injections below: Gold is on no type scale."""
    root, keys = signed
    pack, _ = _signed_pack(root, keys, "craft", GOLD)
    v = _admit(pack, root, target="battle")
    assert (v["verdict"], v["stage"]) == ("refused", "border")
    assert any("has a type" in r["message"] for r in v["refusals"])


@needs_packs
@pytest.mark.parametrize("lines,stage", [
    (FIRE_RULE + FIRE_FACT, "closure"),   # a rule the certificate does not carry, and its conclusion
    (FIRE_FACT, "closure"),               # the conclusion alone, in the graph only
])
def test_graph_only_additions_are_not_reasoned_with(signed, lines, stage):
    """The rules gate compares the certificate's statements; the receiver used
    to reason over the pack's graph, which may carry more. A sword the honest
    profile leaves untyped was admitted as Fire-typed. Now the receiver reasons
    only over its own hub, its own copy of the profile and the item's own
    fields, and a hub fact the passport claims without grounds is refused."""
    root, keys = signed
    pack, _ = _signed_pack(root, keys, "craft", GOLD, _add_graph(lines))
    v = _admit(pack, root, target="battle")
    assert v["signature"]["verified"] is True and v["proof"]["status"] == "certificate_accepted"
    assert (v["verdict"], v["stage"]) == ("refused", stage), (v["verdict"], v["conversion"])
    assert "ga:elementalType ga:Fire" in v["refusals"][0]["message"]


@needs_packs
def test_a_graph_only_rule_with_no_claim_changes_nothing(signed):
    """The rule alone used to make the receiver derive Fire and then refuse for
    the omission. The receiver no longer loads it, so the verdict is the
    honest sword's."""
    root, keys = signed
    pack, _ = _signed_pack(root, keys, "craft", GOLD, _add_graph(FIRE_RULE))
    v = _admit(pack, root, target="battle")
    assert (v["verdict"], v["stage"]) == ("refused", "border")
    assert "typeInTarget" not in v["conversion"]


@needs_packs
def test_a_graph_only_game_parameter_is_not_used(signed):
    """The target's health, stated in the passport's graph, used to change the
    converted damage tenfold (with the earlier sword's attack of 7, 35 became
    350). The receiver uses its own copy."""
    root, keys = signed
    battle = games.get("battle", root).iri
    pack, _ = _signed_pack(root, keys, "craft", SWORD,
                           _add_graph([f"<{battle}> <{GA}maxPlayerHealth> \"1000\"^^<http://www.w3.org/2001/XMLSchema#integer> ."]))
    v = _admit(pack, root, target="battle")
    assert (v["verdict"], v["conversion"]) == ("converted", {"damageInTarget": 30, "typeInTarget": "ga:Rock"})


@needs_packs
def test_a_hub_fact_the_certificate_asserts_about_the_item_is_refused_at_rules(signed):
    """The same Fire claim put in the graph AND the certificate's asserted
    statements, so the two agree. An item may assert only its own game's
    fields; every hub fact about it must be derived."""
    root, keys = signed

    def edit(pack, item):
        line = f"<{item}>\t<{GA}elementalType>\t<{GA}Fire>"
        pack["graph"] = pack["graph"].rstrip("\n") + "\n" + FIRE_FACT[0].format(item=item) + "\n"
        cert = pack["manifest"]["certificate"]
        cert["files"]["asserted.tsv"] = cert["files"]["asserted.tsv"].rstrip("\n") + "\n" + line + "\n"
        cert["asserted"] += 1

    pack, _ = _signed_pack(root, keys, "craft", GOLD, edit)
    v = _admit(pack, root, target="battle")
    assert v["proof"]["status"] == "certificate_accepted"
    assert (v["verdict"], v["stage"]) == ("refused", "rules"), v["refusals"]
    assert "ga:elementalType ga:Fire" in v["refusals"][0]["message"]


@needs_packs
def test_an_item_named_in_another_games_namespace_is_refused(signed):
    """Pocket Battlers signs its tonic under the IRI craft#sunfruit. The
    signer is the derived source game, so the old checks passed and Blockcraft
    admitted it; the item's name was Blockcraft's."""
    root, keys = signed
    battle_ns = "https://tesseractsemantics.com/ns/asset-passport/battle#"
    craft_ns = "https://tesseractsemantics.com/ns/asset-passport/craft#"

    def edit(pack, item):
        text = json.dumps(pack).replace(item, craft_ns + "sunfruit")
        pack.clear()
        pack.update(json.loads(text))

    honest, item = _signed_pack(root, keys, "battle", TONIC)
    assert item == battle_ns + "fizz_tonic"
    assert _admit(honest, root)["verdict"] == "converted"
    pack, _ = _signed_pack(root, keys, "battle", TONIC, edit)
    v = _admit(pack, root)
    assert v["signature"]["verified"] is True and v["proof"]["status"] == "certificate_accepted"
    assert (v["verdict"], v["stage"]) == ("refused", "rules")
    assert "namespace" in v["refusals"][0]["message"]


def _unsigned_lie(root):
    run = scratch("t")
    return judge.export("battle", forge.LIE, run, root=root)["pack"]


@needs_packs
def test_a_passport_swapped_after_the_signature_check_is_not_what_gets_unpacked(signed, monkeypatch):
    """The reviewers' race, made deterministic: the real signature check runs,
    then the file at the user's path is replaced by an unsigned forgery before
    the engine reads it. It used to be admitted as a healing item with
    'signature verified: True'. admit() now reads the file once, into its run
    directory, and both gates read that copy."""
    root, keys = signed
    honest, _ = _signed_pack(root, keys, "battle", ORB)
    lie = _unsigned_lie(root)
    inbox = scratch("t") / "inbox.pack"
    shutil.copy(honest, inbox)
    real = sign.verify

    def verify_then_swap(path, published):
        out = real(path, published)
        shutil.copy(lie, inbox)
        return out

    monkeypatch.setattr(sign, "verify", verify_then_swap)
    v = _admit(inbox, root)
    assert (v["verdict"], v["stage"], v["hub_types"]) == ("refused", "border", ["CaptureDevice", "Item"])
    assert inbox.read_bytes() == lie.read_bytes()  # the swap did happen


@needs_packs
def test_content_the_signature_does_not_cover_is_refused_at_unpack(signed, monkeypatch):
    """Belt and braces: hand the engine a different pack from the one the
    signature gate verified. The digest the engine reports for what it
    unpacked must be the digest that was signed."""
    root, keys = signed
    honest, _ = _signed_pack(root, keys, "battle", ORB)
    lie = _unsigned_lie(root)
    real = Engine.call

    def call(self, tool, **args):
        if tool == "onto_unpack":
            shutil.copy(lie, args["path"])
        return real(self, tool, **args)

    monkeypatch.setattr(Engine, "call", call)
    v = _admit(honest, root)
    assert (v["verdict"], v["stage"]) == ("refused", "unpack")
    assert "not the content the signature covers" in v["refusals"][0]["message"]


# ------------------------------------------------------------------ temporary directories and the build


def test_discovery_and_rule_pinning_leave_no_directories(monkeypatch):
    import tempfile
    root = games_copy()
    p = root / "craft" / "profile.ttl"
    p.write_text(p.read_text() + "\n# a new byte, so the rules are pinned again\n")
    fresh = scratch("empty")
    monkeypatch.setattr(tempfile, "tempdir", str(fresh))
    games.discover(root)
    judge.published_tbox("craft", root=root)
    assert sorted(os.listdir(fresh)) == []


def test_the_build_resolves_an_engine_named_on_the_path(monkeypatch):
    """OO_BIN=open-ontologies (a command name) used to crash the build after it
    had replaced site/passports, when it hashed the binary as a path."""
    b = _build_module()
    real = shutil.which(engine_binary()) or engine_binary()
    monkeypatch.setenv("PATH", os.path.dirname(real) + os.pathsep + os.environ.get("PATH", ""))
    resolved = b.resolve_binary(os.path.basename(real))
    assert os.path.isabs(resolved) and b.sha256(resolved) == b.sha256(real)
    with pytest.raises(SystemExit, match="no engine binary"):
        b.resolve_binary("no-such-engine-anywhere")


def test_the_build_swaps_passports_and_verdicts_together(monkeypatch):
    b = _build_module()
    site = scratch("site")
    monkeypatch.setattr(b, "DATA", site / "data")
    monkeypatch.setattr(b, "PASSPORTS", site / "passports")
    (site / "passports").mkdir(parents=True)
    (site / "passports" / "old.pack").write_text("old")
    packs = scratch("packs")
    (packs / "new.pack").write_text("new")
    b.publish(packs, '{"v": 2}')
    assert sorted(os.listdir(site / "passports")) == ["new.pack"]
    assert (site / "data" / "verdicts.json").read_text() == '{"v": 2}'
    assert sorted(os.listdir(site)) == ["data", "passports"]
    assert sorted(os.listdir(site / "data")) == ["verdicts.json"]


def test_a_build_that_fails_late_leaves_site_as_it_was(monkeypatch):
    """The build computes every value before it touches site/. Make the last
    computation fail (hashing the engine) and nothing under site/ changes."""
    b = _build_module()
    site = scratch("site")
    monkeypatch.setattr(b, "DATA", site / "data")
    monkeypatch.setattr(b, "PASSPORTS", site / "passports")
    calls = []

    def fail(*a, **k):
        calls.append(a)
        raise RuntimeError("engine hash failed")

    monkeypatch.setattr(b, "publish", fail)
    real_sha = b.sha256

    def sha_then_fail(path):
        if calls == [] and os.path.basename(str(path)).startswith("open-ontologies"):
            raise FileNotFoundError(path)
        return real_sha(path)

    monkeypatch.setattr(b, "sha256", sha_then_fail)
    root, keys = signed_root()
    monkeypatch.setenv("ASSET_PASSPORT_GAMES", str(root))
    monkeypatch.setattr(b, "real_keys", lambda known, binary, new_keys: keys)
    if not packs_carry_certificates():
        # The released job allows only skips whose reason names #266, so this
        # one says it in the same words as needs_packs; it used to say it its own
        # way, and the job's skip check would have refused it.
        pytest.skip("this engine cannot carry a certificate in a pack (open-ontologies #266, after v2.0.1), "
                    "and the build needs one")
    with pytest.raises(FileNotFoundError):
        b.main([])
    assert not site.joinpath("passports").exists() and not site.joinpath("data").exists()
    assert calls == []
