"""Signed exports. Each check in the signature gate, and the rules gate's
provenance checks, refuses something here. Keys are made by the test; the real
private keys in ~/.asset-passport/keys are never read."""

import json
import os
import shutil

import pytest
from _support import games_copy, needs_packs, signed_root

from passport import forge, games, judge, sign
from passport.engine import GA, ROOT, Engine, scratch

ORB = {"id": "capture_orb", "kind": "CaptureOrb", "name": "Capture Orb", "catchRate": 40}
POTION = {"id": "super_potion", "kind": "SuperPotion", "name": "Super Potion", "restoresHp": 50}


@pytest.fixture(scope="module")
def signed():
    return signed_root()


def _admit(pack, root, target="craft"):
    return judge.admit(pack, target, scratch("t"), root=root)


# ------------------------------------------------------------------ the pack format


@pytest.mark.parametrize("with_certificate", [False, True])
def test_onto_unpack_loads_a_pack_that_carries_a_signature_field(with_certificate):
    """The signature is a top-level field the engine does not know. The engine's
    Pack struct has no deny_unknown_fields, so it should load, and this pins it:
    if a future engine starts refusing unknown fields, every signed passport
    would stop loading, and this test is the one that says why."""
    d = scratch("extra")
    with Engine(d) as e:
        if with_certificate and not e.accepts("onto_pack", "certificate_dir"):
            pytest.skip("this engine cannot carry a certificate in a pack (open-ontologies #266, after v2.0.1)")
        e.call("onto_clear")
        e.load(judge.HUB)
        args = {}
        if with_certificate:
            e.call("onto_reason", profile=judge.PROFILE, certificate_dir=str(d / "cert"))
            args = {"certificate_dir": str(d / "cert"), "profile": judge.PROFILE}
        e.call("onto_pack", path=str(d / "plain.pack"), name="x", version="0.1.0", **args)
        pack = json.loads((d / "plain.pack").read_text())
        assert "signature" not in pack
        pack["signature"] = {"alg": "Ed25519", "game": "urn:x", "public_key_sha256": "00", "value": "AAAA"}
        (d / "signed.pack").write_text(json.dumps(pack))
        e.call("onto_clear")
        u = e.call("onto_unpack", path=str(d / "signed.pack"))
        assert u.get("loaded") is True, u
        assert u["triples_loaded"] == pack["manifest"]["triples"]


# ------------------------------------------------------------------ the signature gate


@needs_packs
def test_an_unsigned_passport_is_refused(signed):
    root, _ = signed
    run = scratch("t")
    v = _admit(judge.export("battle", POTION, run, root=root)["pack"], root)
    assert (v["verdict"], v["stage"]) == ("refused", "signature")
    assert "not signed" in v["refusals"][0]["message"]


@needs_packs
def test_the_same_passport_signed_is_admitted(signed):
    """The control for the test above: signing is the only difference."""
    root, keys = signed
    run = scratch("t")
    v = _admit(judge.export("battle", POTION, run, root=root, key=keys["battle"])["pack"], root)
    assert v["verdict"] == "converted" and v["signature"]["verified"] is True
    assert v["signature"]["label"] == "Pocket Battlers"


@needs_packs
def test_a_signer_the_receiver_does_not_know_is_refused(signed):
    root, _ = signed
    run = scratch("t")
    ex = judge.export("battle", POTION, run, root=root, key=sign.generate(), sign_as="https://example.org/elsewhere#game")
    v = _admit(ex["pack"], root)
    assert (v["verdict"], v["stage"]) == ("refused", "signature")
    assert "not a game this receiver knows" in v["refusals"][0]["message"]


@needs_packs
def test_a_game_that_publishes_no_key_cannot_be_trusted(signed):
    """Pocket Battlers really signed it, but the RECEIVER's copy of Pocket
    Battlers' profile publishes no key, so there is nothing to verify against."""
    root, keys = signed
    run = scratch("t")
    pack = judge.export("battle", POTION, run, root=root, key=keys["battle"])["pack"]
    keyless = games_copy(strip_keys=("battle",))
    shutil.copy(root / "craft" / "profile.ttl", keyless / "craft" / "profile.ttl")
    v = _admit(pack, keyless)
    assert (v["verdict"], v["stage"]) == ("refused", "signature")
    assert "publishes no export key" in v["refusals"][0]["message"]


@needs_packs
def test_the_key_comes_from_the_receivers_profile_not_the_pack(signed):
    """A receiver whose copy of the profile holds a DIFFERENT key refuses a
    passport that the sender's key really signed."""
    root, keys = signed
    run = scratch("t")
    pack = judge.export("battle", POTION, run, root=root, key=keys["battle"])["pack"]
    other = games_copy()
    for k in ("craft", "battle"):
        shutil.copy(root / k / "profile.ttl", other / k / "profile.ttl")
    games.publish_key("battle", sign.public_b64(sign.generate()), other)
    v = _admit(pack, other)
    assert (v["verdict"], v["stage"]) == ("refused", "signature")


@needs_packs
def test_a_duplicated_json_key_is_refused(signed):
    """Two parsers that resolve a duplicate key differently would be checking
    two different passports. The signature gate refuses duplicates outright."""
    root, keys = signed
    run = scratch("t")
    pack = judge.export("battle", POTION, run, root=root, key=keys["battle"])["pack"]
    text = pack.read_text()
    digest = json.loads(text)["manifest"]["content_sha256"]
    needle = f'"content_sha256": "{digest}"'
    assert text.count(needle) == 1
    pack.write_text(text.replace(needle, f'"content_sha256": "{"0" * 64}", {needle}'))
    v = _admit(pack, root)
    assert (v["verdict"], v["stage"]) == ("refused", "signature")
    assert "duplicate JSON key 'content_sha256'" in v["refusals"][0]["message"]


@needs_packs
def test_a_pack_with_no_content_digest_binds_the_signature_to_nothing(signed):
    root, keys = signed
    run = scratch("t")
    pack = judge.export("battle", POTION, run, root=root, key=keys["battle"])["pack"]
    p = json.loads(pack.read_text())
    del p["manifest"]["content_sha256"]
    pack.write_text(json.dumps(p))
    v = _admit(pack, root)
    assert (v["verdict"], v["stage"]) == ("refused", "signature")
    assert "no content digest" in v["refusals"][0]["message"]


# ------------------------------------------------------------------ the rules gate: provenance


@needs_packs
def test_one_game_cannot_sign_another_games_item(signed):
    """Blockcraft's real key, Blockcraft's real IRI, a genuine signature, on a
    Pocket Battlers item. Every check in the signature gate passes."""
    root, keys = signed
    run = scratch("t")
    ex = judge.export("battle", POTION, run, root=root, key=keys["craft"],
                      sign_as=games.get("craft", root).iri)
    v = _admit(ex["pack"], root, target="craft")
    assert v["signature"]["verified"] is True
    assert (v["verdict"], v["stage"]) == ("refused", "rules")
    assert "cannot vouch for another game's items" in v["refusals"][0]["message"]


def _pack_with_extra_facts(root, key, turtle_for_item):
    """The sender's side of export(), with facts about the item added before
    reasoning: a sender is free to assert whatever it likes."""
    run = scratch("extra")
    out = run / "export"
    out.mkdir(parents=True)
    with Engine(out) as e:
        item = judge._lift(e, "battle", POTION, out, root=root)
        e.call("onto_load", turtle=turtle_for_item(item))
        e.call("onto_reason", profile=judge.PROFILE, certificate_dir=str(out / "cert"))
        e.call("onto_pack", path=str(run / "p.pack"), name="x", version="0.1.0",
               certificate_dir=str(out / "cert"), profile=judge.PROFILE)
    judge.sign_existing(run / "p.pack", games.get("battle", root).iri, key)
    return run / "p.pack"


@needs_packs
def test_a_source_game_that_is_asserted_not_derived_is_refused(signed):
    """The item's game must FOLLOW from the published rules. Asserting it
    directly means nothing derived it, and no proof covers it."""
    root, keys = signed
    battle = games.get("battle", root).iri
    pack = _pack_with_extra_facts(root, keys["battle"], lambda i: f"<{i}> <{GA}fromGame> <{battle}> .")
    v = _admit(pack, root)
    assert v["signature"]["verified"] is True
    assert (v["verdict"], v["stage"]) == ("refused", "rules")
    assert "instead of deriving it" in v["refusals"][0]["message"]


@needs_packs
def test_an_item_from_two_games_is_refused(signed):
    root, keys = signed
    craft = games.get("craft", root).iri
    pack = _pack_with_extra_facts(root, keys["battle"], lambda i: f"<{i}> <{GA}fromGame> <{craft}> .")
    v = _admit(pack, root)
    assert (v["verdict"], v["stage"]) == ("refused", "rules")
    assert "one item from one game" in v["refusals"][0]["message"]


# ------------------------------------------------------------------ keys


CRAFT = ("craft", "https://tesseractsemantics.com/ns/asset-passport/craft#game")


def test_no_test_can_reach_the_real_keys():
    """tests/conftest.py points every test at an empty keys directory of its own."""
    real = (os.path.expanduser("~") + "/.asset-passport/keys").rstrip("/")
    assert str(sign.keys_dir()).rstrip("/") != real
    assert "asset-passport-test-keys-" in str(sign.keys_dir())


def test_a_private_key_is_never_written_inside_the_repository(monkeypatch):
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(ROOT / "keys-must-not-land-here"))
    with pytest.raises(ValueError, match="inside the repository"):
        sign.write_private(CRAFT, sign.generate())
    assert not (ROOT / "keys-must-not-land-here").exists()


def test_a_private_key_is_written_owner_only(monkeypatch):
    d = scratch("keys")
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(d / "k"))
    k = sign.generate()
    p = sign.write_private(CRAFT, k)
    assert oct(os.stat(p).st_mode & 0o777) == "0o600"
    assert sign.public_b64(sign.load_private(CRAFT)) == sign.public_b64(k)
    with pytest.raises(FileExistsError):
        sign.write_private(CRAFT, sign.generate())


def test_a_key_belongs_to_a_game_iri_not_a_directory_name(monkeypatch):
    """Another games root with a directory called craft that declares a
    different game must not get Blockcraft's key."""
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(scratch("keys") / "k"))
    sign.write_private(CRAFT, sign.generate())
    assert sign.load_private(CRAFT) is not None
    assert sign.load_private(("craft", "https://example.org/mycraft#game")) is None
    assert sign.key_path(CRAFT) != sign.key_path(("craft", "https://example.org/mycraft#game"))


def _pem(k) -> bytes:
    return k.private_bytes(sign.serialization.Encoding.PEM, sign.serialization.PrivateFormat.PKCS8,
                           sign.serialization.NoEncryption())


def test_a_directory_named_key_file_is_never_adopted(monkeypatch):
    """Keys made before they were bound to an IRI sat at <dir>.ed25519. Such a
    file is never read, even by a game whose profile publishes its public half:
    a public key is public, so a match proves nothing."""
    from types import SimpleNamespace
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(scratch("keys") / "k"))
    k = sign.generate()
    sign.keys_dir().mkdir(parents=True)
    old = sign.keys_dir() / "craft.ed25519"
    old.write_bytes(_pem(k))
    old.chmod(0o600)
    owner = SimpleNamespace(key="craft", iri=CRAFT[1], export_key=sign.public_b64(k))
    assert sign.load_private(owner) is None
    assert old.read_bytes() == _pem(k) and not sign.key_path(owner).exists()


def test_a_directory_named_after_another_games_key_file_cannot_take_it(monkeypatch):
    """The reviewer's case: a directory called craft.<Blockcraft's IRI tag>
    publishes Blockcraft's public key, copied from Blockcraft's profile. Its
    old-style key path was exactly Blockcraft's key file, and the public halves
    matched, so it took the file. Now discovery refuses the directory name, and
    the key loader never reads any file but the game's own IRI-bound one."""
    from types import SimpleNamespace
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(scratch("keys") / "k"))
    victim_key = sign.generate()
    victim = sign.write_private(CRAFT, victim_key)
    before = victim.read_bytes()
    name = victim.name[:-len(".ed25519")]  # craft.<16 hex>
    impostor = SimpleNamespace(key=name, iri="https://example.org/mods#game",
                               export_key=sign.public_b64(victim_key))
    assert sign.load_private(impostor) is None
    assert victim.read_bytes() == before
    assert sorted(p.name for p in sign.keys_dir().iterdir()) == [victim.name]
    root = games_copy()
    (root / name).mkdir()
    (root / name / "profile.ttl").write_text(
        f"@prefix ga: <{GA}> .\n@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        f'<https://example.org/mods#game> a ga:Game ; rdfs:label "Mods" ; '
        f'ga:exportKey "{sign.public_b64(victim_key)}" .\n')
    from passport.engine import EngineError
    with pytest.raises(EngineError, match="directory name must be lower-case letters"):
        games.discover(root)


def test_two_games_that_publish_one_export_key_are_refused():
    """A key vouches for one game. Two profiles with one key are refused, and
    the check can fail: the same two games with two keys are discovered."""
    root = games_copy()
    shared = sign.public_b64(sign.generate())
    games.publish_key("craft", sign.public_b64(sign.generate()), root)
    games.publish_key("battle", shared, root)
    assert sorted(games.discover(root)) == ["battle", "craft"]
    sign.set_export_key(root / "craft" / "profile.ttl", games.get("craft", root).iri, shared)
    from passport.engine import EngineError
    with pytest.raises(EngineError, match="publish the same export key"):
        games.discover(root)


def test_replacing_a_key_moves_the_old_one_aside_and_the_new_one_is_owner_only(monkeypatch):
    """write_private(force=True) used to open the old file and keep its mode,
    so a 0644 key stayed 0644. Now the old key is moved aside, untouched, and
    the new file is created owner-only."""
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(scratch("keys") / "k"))
    first = sign.write_private(CRAFT, sign.generate())
    first.chmod(0o644)
    old_bytes = first.read_bytes()
    second = sign.generate()
    p = sign.write_private(CRAFT, second, force=True)
    assert oct(os.stat(p).st_mode & 0o777) == "0o600"
    aside = [q for q in sign.keys_dir().iterdir() if ".replaced-" in q.name]
    assert len(aside) == 1 and aside[0].read_bytes() == old_bytes
    assert sign.public_b64(sign.load_private(CRAFT)) == sign.public_b64(second)


def test_a_key_other_users_can_read_is_refused(monkeypatch):
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(scratch("keys") / "k"))
    p = sign.write_private(CRAFT, sign.generate())
    assert sign.load_private(CRAFT) is not None
    p.chmod(0o644)
    with pytest.raises(ValueError, match="readable by its owner only"):
        sign.load_private(CRAFT)


def test_a_key_file_that_is_a_symbolic_link_is_neither_read_nor_written_through(monkeypatch):
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(scratch("keys") / "k"))
    elsewhere = scratch("keys") / "elsewhere.pem"
    elsewhere.write_bytes(_pem(sign.generate()))
    elsewhere.chmod(0o600)
    sign.keys_dir().mkdir(parents=True)
    sign.key_path(CRAFT).symlink_to(elsewhere)
    with pytest.raises(OSError):
        sign.load_private(CRAFT)
    with pytest.raises(FileExistsError):
        sign.write_private(CRAFT, sign.generate())


def test_the_keys_directory_is_made_owner_only_but_an_existing_one_keeps_its_mode(monkeypatch):
    made = scratch("keys") / "new"
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(made))
    sign.write_private(CRAFT, sign.generate())
    assert oct(os.stat(made).st_mode & 0o777) == "0o700"
    shared = scratch("keys") / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(shared))
    sign.write_private(CRAFT, sign.generate())
    assert oct(os.stat(shared).st_mode & 0o777) == "0o755"


def test_publishing_a_key_is_read_back_by_the_engine():
    root = games_copy()
    pub = sign.public_b64(sign.generate())
    g = games.publish_key("craft", pub, root)
    assert g.export_key == pub
    again = sign.public_b64(sign.generate())
    assert games.publish_key("craft", again, root).export_key == again  # replaced, not added
    assert (root / "craft" / "profile.ttl").read_text().count("exportKey") == 1


def test_a_signature_over_a_different_message_does_not_verify():
    """The message binds the game IRI as well as the digest: the same digest
    signed for one game does not verify for another."""
    k = sign.generate()
    sig = k.sign(sign.message("urn:game:a", "ab" * 32))
    k.public_key().verify(sig, sign.message("urn:game:a", "ab" * 32))
    from cryptography.exceptions import InvalidSignature
    with pytest.raises(InvalidSignature):
        k.public_key().verify(sig, sign.message("urn:game:b", "ab" * 32))
