"""Every verdict, number and gate the page shows, pinned against the real engine.

Each gate is also shown ABLE TO FAIL: a check that has never refused anything
proves nothing (see the forgery tests, and tests/test_signing.py for the rest
of the signature and rules gates).
"""

import pytest
from _support import needs_packs, signed_root

from passport import forge, sign
from passport.engine import scratch
from passport.judge import GATES, admit, decide, export, item_record, judge_direct


@pytest.fixture(scope="module")
def signed():
    return signed_root()

EXPECTED = {
    ("craft", "diamond_sword"): ("battle", "converted", {"damageInTarget": 35, "typeInTarget": "ga:Rock"}),
    ("craft", "tnt"):           ("battle", "refused", {"damageInTarget": 120}),
    ("craft", "golden_apple"):  ("battle", "converted_with_loss", {"healInTarget": 40}),
    ("battle", "emberfox"):     ("craft", "converted_with_loss", {"damageInTarget": 8, "hitPointsInTarget": 20}),
    ("battle", "capture_orb"):  ("craft", "refused", {}),
    ("battle", "super_potion"): ("craft", "converted", {"healInTarget": 10}),
}


@needs_packs
@pytest.mark.parametrize("game,item", list(EXPECTED))
def test_passport_lane(signed, game, item):
    root, keys = signed
    target, verdict, conversion = EXPECTED[(game, item)]
    run = scratch("t")
    v = admit(export(game, item_record(game, item, root), run, root=root, key=keys[game])["pack"],
              target, run, root=root)
    assert v["signature"]["verified"] is True
    assert v["signature"]["public_key_sha256"] == sign.key_sha256(sign.public_b64(keys[game]))
    assert v["proof"]["status"] == "certificate_accepted"
    assert v["verdict"] == verdict, v["refusals"]
    assert v["conversion"] == conversion
    assert v["evaluators"] == {"verified": verdict != "refused", "default": verdict != "refused"}


@pytest.mark.parametrize("game,item", list(EXPECTED))
def test_direct_lane_agrees(game, item):
    target, verdict, conversion = EXPECTED[(game, item)]
    v = judge_direct(game, item_record(game, item), target, scratch("t"))
    assert (v["verdict"], v["conversion"]) == (verdict, conversion)
    assert v["signature"] is None  # one store, one trust domain: nothing to sign


def test_the_type_is_derived_from_the_material():
    """Diamond is placed on the Rock type by one axiom in Blockcraft's profile;
    the sword's type is a conclusion, and the certificate holds the step."""
    v = judge_direct("craft", item_record("craft", "diamond_sword"), "battle", scratch("t"))
    assert v["conversion"]["typeInTarget"] == "ga:Rock"
    assert any(s["rule"] == "cls-hv1" and s["conclusion"].endswith("ga:elementalType ga:Rock") for s in v["why"])


def test_an_unplaced_material_has_no_type_and_is_refused():
    rec = {"id": "gold", "kind": "DiamondSword", "name": "Gold Sword", "attack": 4, "material": "Gold"}
    v = judge_direct("craft", rec, "battle", scratch("t"))
    assert v["verdict"] == "refused" and any("has a type" in r["message"] for r in v["refusals"])


def test_conversion_arithmetic_is_left_associative():
    """7/20*100 must be 35. Oxigraph reads it as 7/(20*100); the rule
    parenthesises every chain. Unparenthesise one and this fails."""
    v = judge_direct("craft", item_record("craft", "diamond_sword"), "battle", scratch("t"))
    assert v["conversion"]["damageInTarget"] == 35


@pytest.mark.parametrize("game,rec,target,why", [
    ("craft", {"id": "big", "kind": "DiamondSword", "name": "x", "attack": 20, "material": "Diamond"},
     "battle", "one turn"),                # 20/20 of 100 = 100, not below 100
    ("battle", {"id": "fox", "kind": "Emberfox", "name": "x", "hp": 100, "movePower": 100,
                "moveName": "Inferno", "type": "Fire"}, "craft", "one hit"),   # 100/100 of 20 = 20
])
def test_border_refuses_out_of_range(game, rec, target, why):
    v = judge_direct(game, rec, target, scratch("t"))
    assert v["verdict"] == "refused" and v["stage"] == "border"
    assert any(why in r["message"] for r in v["refusals"])


@pytest.fixture(scope="module")
def forgeries(signed):
    root, keys = signed
    run = scratch("forge")
    return run, root, forge.forge_all(run, keys[forge.SOURCE], root=root)


# Where each forgery must stop, and what the proof status must be when it does.
# None for the proof: the gate fired before the pack was opened.
STOPS = {
    "tamper":       ("refused", "unpack", "pack_refused_before_the_checker"),
    "unhook":       ("refused", "signature", None),
    "false_step":   ("refused", "signature", None),
    "forger_lie":   ("refused", "signature", None),
    "source_omits": ("refused", "closure", "certificate_accepted"),
    "source_rules": ("refused", "rules", "certificate_accepted"),
    "source_lies":  ("converted", "border", "certificate_accepted"),
    "honest":       ("refused", "border", "certificate_accepted"),
}


def test_every_attempt_is_pinned():
    assert [a[0] for a in forge.ATTEMPTS] == [k for k in STOPS if k != "honest"]


@needs_packs
@pytest.mark.parametrize("name", list(STOPS))
def test_forgery_stops_at_its_gate(forgeries, name):
    run, root, packs = forgeries
    r = scratch(name)
    v = admit(packs[name], forge.TARGET, r, root=root)
    assert (v["verdict"], v["stage"], v["proof"].get("status")) == STOPS[name], v["refusals"]


@needs_packs
def test_the_tampered_passport_still_carries_a_valid_signature(forgeries):
    """tamper is stopped by the digest, not the signature: the signature covers
    content_sha256, which the forger left alone. The engine's refusal names the
    pack's graph checksum (manifest.sha256), which the content digest also
    covers. Were the digest check gone, the closure gate would still catch this
    edit: source_omits is the same edit, re-digested and signed, and it stops there."""
    run, root, packs = forgeries
    v = admit(packs["tamper"], forge.TARGET, scratch("t"), root=root)
    assert v["signature"]["verified"] is True
    assert "checksum mismatch" in v["refusals"][0]["message"]


@needs_packs
def test_doctored_rules_are_refused_with_the_diff(forgeries):
    run, root, packs = forgeries
    v = admit(packs["source_rules"], forge.TARGET, scratch("t"), root=root)
    assert v["signature"]["verified"] is True  # the issuer really signed it
    assert v["drift"] == {"added": ["battle:CaptureOrb rdfs:subClassOf ga:HealingConsumable"],
                          "removed": ["battle:CaptureOrb rdfs:subClassOf ga:CaptureDevice"]}


@needs_packs
def test_a_lie_by_the_issuer_gets_through(forgeries):
    """Where the guarantee ends. If this starts failing, the page is wrong."""
    run, root, packs = forgeries
    v = admit(packs["source_lies"], forge.TARGET, scratch("t"), root=root)
    assert v["verdict"] == "converted" and v["signature"]["verified"] is True
    assert v["conversion"] == {"healInTarget": 2}


@needs_packs
def test_lean_still_refuses_a_forged_step_the_issuer_signed(forgeries, signed):
    """With a valid signature on it, a forged derivation reaches the unpack
    gate, and this machine's Lean checker refuses it there."""
    run, root, packs = forgeries
    _, keys = signed
    r = scratch("t")
    p = forge.write(forge.read(packs["false_step"]), r / "f.pack")
    from passport.judge import sign_existing
    from passport import games
    sign_existing(p, games.get("battle", root).iri, keys["battle"])
    v = admit(p, forge.TARGET, r, root=root)
    assert (v["verdict"], v["stage"], v["proof"]["status"]) == ("refused", "unpack", "certificate_refused")


def test_gate_order():
    assert GATES == ("signature", "unpack", "rules", "closure", "border")


def test_vacuous_border_is_not_a_pass():
    v = decide({"status": "certificate_accepted"}, {}, {"conforms": True},
               {"conforms": None, "error": "the border saw no focus node"}, None)
    assert v["verdict"] == "undetermined"


# ------------------------------------------------------------------ a proof nobody checked


def _checker(tmp, body: str):
    p = tmp / "oo-cert"
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(0o755)
    return str(p)


def test_no_checker_is_undetermined_not_refused(monkeypatch):
    """A missing Lean checker used to give 'refused' at the border with the
    headline 'The passport's proof did not check.' Nothing was checked, so
    nothing is claimed. The control: with the checker the item is converted."""
    from passport import judge
    rec = item_record("battle", "super_potion")
    assert judge_direct("battle", rec, "craft", scratch("t"))["verdict"] == "converted"
    monkeypatch.setattr(judge, "find_oo_cert", lambda explicit=None: None)
    v = judge_direct("battle", rec, "craft", scratch("t"))
    assert (v["verdict"], v["stage"], v["proof"]["status"]) == \
        ("undetermined", "unpack", "checker_absent_nothing_was_checked")
    assert v["refusals"] == [] and "no Lean checker" in v["headline"]


@pytest.mark.parametrize("body,status", [
    ("kill -SEGV $$", "checker_failed"),   # a crash
    ("exit 2", "checker_failed"),          # oo-cert's code for a file it could not read
    ("exit 1", "checker_failed"),          # oo-cert's code for a step it rejects, but no verdict printed
    ("echo '{\"ok\":false}'; exit 1", "certificate_refused"),  # a rejection, with oo-cert's own verdict
])
def test_a_checker_that_crashes_is_not_a_checker_that_refused(body, status):
    from passport.judge import run_oo_cert
    tmp = scratch("chk")
    assert run_oo_cert(tmp, _checker(tmp, body))["status"] == status


def test_decide_holds_an_unchecked_proof():
    for status in ("checker_absent_nothing_was_checked", "checker_failed", None):
        v = decide({"status": status}, {}, {"conforms": True}, {"conforms": True, "focus_nodes": 1}, None)
        assert v["verdict"] == "undetermined", status
    v = decide({"status": "certificate_refused"}, {}, {"conforms": True}, {"conforms": True}, None)
    assert v["verdict"] == "refused" and "passport" not in v["headline"]


# ------------------------------------------------------------------ what a verdict reports


def test_a_field_with_two_converted_values_shows_both_and_claims_nothing():
    """A sword with an attack and a blast damage gets two damage values in
    Pocket Battlers. The verdict used to keep whichever came last (35) and
    admit it. Both are shown now, and the verdict is held."""
    rec = {"id": "x", "kind": "DiamondSword", "name": "x", "attack": 7, "blastDamage": 2, "material": "Diamond"}
    v = judge_direct("craft", rec, "battle", scratch("t"))
    assert v["conversion"]["damageInTarget"] == [10, 35]
    assert v["verdict"] == "undetermined" and "damageInTarget 2 values" in v["headline"]


def test_the_why_list_is_in_a_fixed_order(tmp_path):
    from passport.judge import derivation_steps
    item = "https://tesseractsemantics.com/ns/asset-passport/craft#s"
    lines = [f"rdfs9\t<{item}>\t<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>\t<urn:{c}>" for c in "cab"]
    (tmp_path / "derivations.tsv").write_text("\n".join(lines))
    first = derivation_steps(tmp_path, item)
    (tmp_path / "derivations.tsv").write_text("\n".join(reversed(lines)))
    assert derivation_steps(tmp_path, item) == first
    assert [s["conclusion"][-1] for s in first] == ["a", "b", "c"]


def test_a_verdict_names_the_engine_binary_not_the_mcp_library():
    import hashlib
    import os
    import shutil
    from passport.engine import engine_binary
    v = judge_direct("craft", item_record("craft", "tnt"), "battle", scratch("t"))
    binary = shutil.which(engine_binary()) or engine_binary()
    assert v["engine"]["binary_sha256"] == hashlib.sha256(open(binary, "rb").read()).hexdigest()
    assert v["engine"]["binary"] == os.path.basename(binary)
    assert "name" not in v["engine"]  # the MCP serverInfo is kept, under its own name
