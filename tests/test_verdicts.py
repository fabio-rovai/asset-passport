"""Every verdict, number and gate the page shows, pinned against the real engine.

Each gate is also shown ABLE TO FAIL: a check that has never refused anything
proves nothing (see the forgery tests).
"""

import pytest

from passport import forge
from passport.engine import scratch
from passport.judge import admit, decide, export, game_dir, item_record, judge_direct

EXPECTED = {
    ("craft", "diamond_sword"): ("battle", "converted", {"damageInTarget": 35, "typeInTarget": "ga:Rock"}),
    ("craft", "tnt"):           ("battle", "refused", {"damageInTarget": 120}),
    ("craft", "golden_apple"):  ("battle", "converted_with_loss", {"healInTarget": 40}),
    ("battle", "emberfox"):     ("craft", "converted_with_loss", {"damageInTarget": 8, "hitPointsInTarget": 20}),
    ("battle", "capture_orb"):  ("craft", "refused", {}),
    ("battle", "super_potion"): ("craft", "converted", {"healInTarget": 10}),
}


@pytest.mark.parametrize("game,item", list(EXPECTED))
def test_passport_lane(game, item):
    target, verdict, conversion = EXPECTED[(game, item)]
    run = scratch("t")
    v = admit(export(game, item_record(game, item), run)["pack"], target, run)
    assert v["proof"]["status"] == "certificate_accepted"
    assert v["verdict"] == verdict, v["refusals"]
    assert v["conversion"] == conversion
    assert v["evaluators"] == {"verified": verdict != "refused", "default": verdict != "refused"}


@pytest.mark.parametrize("game,item", list(EXPECTED))
def test_direct_lane_agrees(game, item):
    target, verdict, conversion = EXPECTED[(game, item)]
    v = judge_direct(game, item_record(game, item), target, scratch("t"))
    assert (v["verdict"], v["conversion"]) == (verdict, conversion)


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
def orb_passport():
    run = scratch("forge")
    return run, export("battle", item_record("battle", "capture_orb"), run)


@pytest.mark.parametrize("attack,stage,status", [
    (forge.tamper, "unpack", "pack_refused_before_the_checker"),
    (forge.unhook, "closure", "certificate_accepted"),
    (forge.false_step, "unpack", "certificate_refused"),
])
def test_forgery_is_refused_at_its_gate(orb_passport, attack, stage, status):
    run, ex = orb_passport
    r = scratch(attack.__name__)
    pack = forge.write(attack(forge.read(ex["pack"]), ex["item_iri"]), r / "f.pack")
    v = admit(pack, "craft", r)
    assert (v["verdict"], v["stage"], v["proof"]["status"]) == ("refused", stage, status)


def test_doctored_rules_are_refused_with_the_diff():
    r = scratch("own")
    doctored = r / "p.ttl"
    doctored.write_text((game_dir("battle") / "profile.ttl").read_text().replace(
        "battle:CaptureOrb a owl:Class ; rdfs:subClassOf ga:CaptureDevice",
        "battle:CaptureOrb a owl:Class ; rdfs:subClassOf ga:HealingConsumable"))
    ex = export("battle", item_record("battle", "capture_orb"), r, profile=doctored)
    v = admit(ex["pack"], "craft", r)
    assert (v["verdict"], v["stage"]) == ("refused", "rules")
    assert v["proof"]["status"] == "certificate_accepted"  # the proof IS sound
    assert v["drift"] == {"added": ["battle:CaptureOrb rdfs:subClassOf ga:HealingConsumable"],
                          "removed": ["battle:CaptureOrb rdfs:subClassOf ga:CaptureDevice"]}


def test_a_lie_about_the_item_gets_through():
    """Where the guarantee ends. If this starts failing, the page is wrong."""
    r = scratch("lie")
    lie = {"id": "capture_orb", "kind": "SuperPotion", "name": "Capture Orb", "restoresHp": 10}
    v = admit(export("battle", lie, r)["pack"], "craft", r)
    assert v["verdict"] == "converted"


def test_vacuous_border_is_not_a_pass():
    v = decide({"status": "certificate_accepted"}, {}, {"conforms": True},
               {"conforms": None, "error": "the border saw no focus node"}, None)
    assert v["verdict"] == "undetermined"
