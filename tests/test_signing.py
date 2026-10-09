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


def test_a_private_key_is_never_written_inside_the_repository(monkeypatch):
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(ROOT / "keys-must-not-land-here"))
    with pytest.raises(ValueError, match="inside the repository"):
        sign.write_private("craft", sign.generate())
    assert not (ROOT / "keys-must-not-land-here").exists()


def test_a_private_key_is_written_owner_only(monkeypatch):
    d = scratch("keys")
    monkeypatch.setenv("ASSET_PASSPORT_KEYS", str(d / "k"))
    k = sign.generate()
    p = sign.write_private("craft", k)
    assert oct(os.stat(p).st_mode & 0o777) == "0o600"
    assert sign.public_b64(sign.load_private("craft")) == sign.public_b64(k)
    with pytest.raises(FileExistsError):
        sign.write_private("craft", sign.generate())


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
