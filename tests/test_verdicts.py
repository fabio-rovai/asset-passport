"""Every verdict, number and gate the page shows, pinned against the real engine.

Each gate is also shown ABLE TO FAIL: a check that has never refused anything
proves nothing (see the forgery tests).
"""

import pytest

from passport import forge
from passport.engine import scratch
from passport.judge import admit, export, game_dir, item_record, judge_direct

EXPECTED = {
    # item                     target    verdict                conversion
    ("blocky", "diamond_sword"):   ("souls",  "converted",
                                    {"damageInTarget": 350, "lengthInTarget": 100,
                                     "staminaCostInTarget": 18, "staminaCostDefaulted": True}),
    ("blocky", "iron_chestplate"): ("souls",  "converted", {"armourInTarget": 24}),
    ("blocky", "bed"):             ("souls",  "refused", {}),
    ("souls", "greatsword"):       ("blocky", "converted_with_loss",
                                    {"damageInTarget": 8, "lengthInTarget": 1.8}),
    ("souls", "ember_flask"):      ("blocky", "converted_with_loss", {"healInTarget": 8}),
    ("souls", "knight_armour"):    ("blocky", "converted", {"armourInTarget": 8}),
}


@pytest.mark.parametrize("game,item", list(EXPECTED))
def test_passport_lane(game, item):
    target, verdict, conversion = EXPECTED[(game, item)]
    run = scratch("t")
    ex = export(game, item_record(game, item), run)
    v = admit(ex["pack"], target, run)
    assert v["proof"]["status"] == "certificate_accepted"
    assert v["verdict"] == verdict, v["refusals"]
    assert v["conversion"] == conversion
    assert v["evaluators"] == {"verified": verdict != "refused", "default": verdict != "refused"}


@pytest.mark.parametrize("game,item", list(EXPECTED))
def test_direct_lane_agrees(game, item):
    target, verdict, conversion = EXPECTED[(game, item)]
    v = judge_direct(game, item_record(game, item), target, scratch("t"))
    assert (v["verdict"], v["conversion"]) == (verdict, conversion)


def test_conversion_arithmetic_is_left_associative():
    """7/20*1000 must be 350. Oxigraph's parser reads it as 7/(20*1000); the
    rule parenthesises every chain. Unparenthesise one and this fails."""
    v = judge_direct("blocky", item_record("blocky", "diamond_sword"), "souls", scratch("t"))
    assert v["conversion"]["damageInTarget"] == 350


def test_losses_are_named():
    v = judge_direct("souls", item_record("souls", "greatsword"), "blocky", scratch("t"))
    msgs = " ".join(l["message"] for l in v["losses"])
    assert "poise" in msgs and "stamina" in msgs


@pytest.mark.parametrize("game,rec,target,why", [
    ("blocky", {"id": "big", "kind": "DiamondSword", "name": "x", "attack": 13, "size": 1.0},
     "souls", "60%"),                      # 13/20 of 1,000 = 650 > 600
    ("blocky", {"id": "plate", "kind": "IronChestplate", "name": "x", "armorPoints": 20},
     "souls", "60%"),                      # 20/20 * 0.8 = 80% absorption > 60%
    ("souls", {"id": "zwei", "kind": "Greatsword", "name": "x", "attackRating": 420,
               "bladeLengthCm": 250, "poiseDamage": 60, "stamina": 32},
     "blocky", "2 blocks"),                # 2.5 blocks > 2
])
def test_border_refuses_out_of_range(game, rec, target, why):
    v = judge_direct(game, rec, target, scratch("t"))
    assert v["verdict"] == "refused" and v["stage"] == "border"
    assert any(why in r["message"] for r in v["refusals"])


@pytest.fixture(scope="module")
def bed_passport():
    run = scratch("forge")
    return run, export("blocky", item_record("blocky", "bed"), run)


@pytest.mark.parametrize("attack,stage,status", [
    (forge.tamper, "unpack", "pack_refused_before_the_checker"),
    (forge.unhook, "closure", "certificate_accepted"),
    (forge.false_step, "unpack", "certificate_refused"),
])
def test_forgery_is_refused_at_its_gate(bed_passport, attack, stage, status):
    run, ex = bed_passport
    r = scratch(attack.__name__)
    pack = forge.write(attack(forge.read(ex["pack"]), ex["item_iri"]), r / "f.pack")
    v = admit(pack, "souls", r)
    assert (v["verdict"], v["stage"], v["proof"]["status"]) == ("refused", stage, status)


def test_doctored_rules_are_refused_with_the_diff():
    r = scratch("own")
    doctored = r / "p.ttl"
    doctored.write_text((game_dir("blocky") / "profile.ttl").read_text().replace(
        "blocky:Bed a owl:Class ; rdfs:subClassOf ga:RespawnAnchor",
        "blocky:Bed a owl:Class ; rdfs:subClassOf ga:MeleeWeapon"))
    ex = export("blocky", item_record("blocky", "bed"), r, profile=doctored)
    v = admit(ex["pack"], "souls", r)
    assert (v["verdict"], v["stage"]) == ("refused", "rules")
    assert v["proof"]["status"] == "certificate_accepted"  # the proof IS sound
    assert v["drift"] == {"added": ["blocky:Bed rdfs:subClassOf ga:MeleeWeapon"],
                          "removed": ["blocky:Bed rdfs:subClassOf ga:RespawnAnchor"]}


def test_a_lie_about_the_item_gets_through():
    """Where the guarantee ends. If this starts failing, the page is wrong."""
    r = scratch("lie")
    lie = {"id": "bed", "kind": "DiamondSword", "name": "Bed", "attack": 3, "size": 1.0}
    v = admit(export("blocky", lie, r)["pack"], "souls", r)
    assert v["verdict"] == "converted"


def test_vacuous_border_is_not_a_pass():
    """An empty store conforms vacuously on the verified evaluator. The border
    must not read that as an admission."""
    from passport.judge import decide
    v = decide({"status": "certificate_accepted"}, {}, {"conforms": True},
               {"conforms": None, "error": "the border saw no focus node"}, None)
    assert v["verdict"] == "undetermined"
