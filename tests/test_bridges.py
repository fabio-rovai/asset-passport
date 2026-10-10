"""The bridge checker, pinned against the real engine.

Every row of Universal Modder's "Unit mappings" table that we model has its
verdicts pinned here, and every check is shown refusing something: each shape
in contracts/bridge.shacl.ttl, each input guard in rules/*-input.rq, each
derived predicate a bridge file might forge, and the fail-closed path for a
value the engine drops. A check that has never refused anything proves nothing.
"""

import json
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

from passport.bridge import ENGINE_DROPPED, ROOT, _refusals, check
from passport.engine import Engine, scratch

EX = ROOT / "examples" / "bridges"
H, R, U, N, NC = "holds", "refused", "undetermined", "not_declared", "not_checked"


def facts_for(name: str) -> list:
    """A wrong- example that needs a made-up game reads it from
    examples/bridges/facts/<name>.ttl, through the explicit --facts path."""
    f = EX / "facts" / f"{name}.ttl"
    return [f] if f.exists() else []


@lru_cache(maxsize=None)
def run(name: str) -> dict:
    return check(EX / f"{name}.ttl", facts=facts_for(name))


def checks(name: str) -> dict:
    (b,) = run(name)["bridges"]
    return b["checks"]


def verdicts(name: str) -> dict:
    return {k: c["verdict"] for k, c in checks(name).items()}


# file -> (overall, axes, handedness, units, health); declaration and facts hold
# unless a row says otherwise below.
EXPECTED = {
    # the table's rows, as the table states them
    "um-gta-v-example":            (U, U, U, U, N),
    "um-libertycraft":             (H, N, N, H, N),
    "um-newvegascraft":            (U, U, U, H, N),
    "um-minecraft-x-half-life":    (U, N, N, U, H),
    "um-faith-runner-skyrim":      (H, N, N, H, N),
    "um-killcraft":                (U, N, N, U, N),
    "um-garrys-redemption":        (U, N, N, U, N),
    "um-skycraft":                 (H, N, N, H, N),
    "um-2010-rust-rewrite-mashup": (U, N, N, U, N),
    # the same projects, read from their own source
    "src-skycraft":                (H, H, H, H, N),
    "src-minecraft-x-half-life":   (U, U, U, N, N),
    "src-garrys-redemption":       (U, U, U, U, N),
    "src-2010-rust-rewrite-mashup": (U, U, U, U, N),
    # this repository's own two games
    "syn-asset-passport-health":   (H, N, N, N, H),
    "syn-declared-mirror":         (H, H, H, H, N),
    # wrong on purpose
    "wrong-naive-xyz":             (R, R, H, H, N),
    "wrong-mirrored":              (R, R, R, H, N),
    "wrong-mirror-declared":       (R, R, H, H, N),
    "wrong-false-mirror-claim":    (R, U, R, H, N),
    "wrong-degenerate-map":        (R, R, R, H, N),
    "wrong-unit-ratio":            (R, N, N, R, N),
    "wrong-unit-ratio-large":      (R, N, N, R, N),
    "wrong-health-multiplier":     (R, N, N, N, R),
    "wrong-health-native-and-multiplier": (R, N, N, N, R),
    "wrong-unsourced-fact":        (R, N, N, U, N),
    "wrong-malformed-axis":        (R, R, R, N, N),
    "wrong-broken-basis":          (R, R, R, N, N),
}
DECLARATION_REFUSED = {"wrong-malformed-axis"}
FACTS_REFUSED = {"wrong-unsourced-fact", "wrong-broken-basis"}
# Refused by rules/bridge-input.rq before the rule runs: file -> predicates named.
INPUT_REFUSED = {
    "wrong-forged-derived": {"derivedGuestXFrom", "derivedGuestYFrom", "derivedGuestZFrom",
                             "axisXAgrees", "axisYAgrees", "axisZAgrees", "handedness",
                             "declaredHandedness", "handednessAgreement",
                             "healthPolicyMultiplier", "healthMultiplierError"},
    "wrong-injected-fact": {"lengthEvidence", "units", "metres", "source", "quote"},
    "wrong-double-ratio": {"declaredHostUnitsPerGuestUnit"},
}


def test_every_example_is_pinned():
    assert {p.stem for p in EX.glob("*.ttl")} == set(EXPECTED) | set(INPUT_REFUSED)
    assert {p.stem for p in (EX / "facts").glob("*.ttl")} <= set(EXPECTED)


@pytest.mark.parametrize("name", list(INPUT_REFUSED))
def test_input_guard_refuses_the_whole_file(name):
    r = run(name)
    assert (r["verdict"], r["exit"], r["bridges"]) == (R, 1, [])
    assert r["input"]["verdict"] == R
    assert {x["predicate"] for x in r["input"]["refusals"]} == INPUT_REFUSED[name]


@pytest.mark.parametrize("name", list(EXPECTED))
def test_verdicts(name):
    overall, axes, hand, units, health = EXPECTED[name]
    r = run(name)
    assert r["input"]["verdict"] == H, r["input"]["refusals"]
    assert r["input"]["synthetic_facts"] == bool(facts_for(name))
    assert r["evaluators"]["agree"], r["evaluators"]["problems"]
    assert r["unattributed_refusals"] == []
    assert verdicts(name) == {
        "declaration": R if name in DECLARATION_REFUSED else H,
        "facts": R if name in FACTS_REFUSED else H,
        "axes": axes, "handedness": hand, "units": units, "health": health,
    }
    assert r["verdict"] == overall
    assert r["exit"] == {H: 0, R: 1, U: 2}[overall]


# ------------------------------------------------------------------ the table's numbers


def _units(name):
    return {d["form"]: d for d in checks(name)["units"]["declarations"]}


def test_skyrim_unit_is_derived_from_six_feet_per_128_units():
    """0.3048 * 6 / 128 = 0.0142875 m, so a metre is 69.99125... Skyrim units
    and SkyCraft's 70 per block is 0.0125 percent out."""
    c = checks("um-skycraft")
    assert c["facts"]["host"]["metres_per_unit"] == [0.0142875]
    d = _units("um-skycraft")["declaredHostUnitsPerGuestUnit"]
    assert d["implied_low"] == d["implied_high"] == pytest.approx(69.99125109361329, rel=1e-12)
    # The error is computed in doubles and cast back to a decimal.
    assert d["best_relative_error"] == d["worst_relative_error"] == pytest.approx(0.000125, rel=1e-9)


def test_faith_runner_seventy_per_metre_is_skyrims_unit():
    d = _units("um-faith-runner-skyrim")["declaredHostUnitsPerMetre"]
    assert d["best_relative_error"] == pytest.approx(0.000125, rel=1e-9)
    assert d["checks"].startswith("the host's own unit length only")


def test_new_vegas_uses_the_same_scale_from_the_geck():
    """4096 units = 192 feet on the GECK wiki is the same 0.0142875 m."""
    c = checks("um-newvegascraft")
    assert c["facts"]["host"]["metres_per_unit"] == [0.0142875]
    assert _units("um-newvegascraft")["declaredHostUnitsPerGuestUnit"]["verdict"] == H


def test_new_vegas_axes_hold_where_sourced_and_wait_for_up():
    """East and north are sourced for New Vegas, up is not: the two derivable
    axes agree and the check stays undetermined rather than guessing."""
    a = checks("um-newvegascraft")["axes"]
    assert a["derived"] == {"x": "+x", "z": "-y"}
    assert a["missing"] == ["Fallout: New Vegas has no sourced Up axis"]


def test_half_life_forty_per_block_fits_two_of_valves_three_scales():
    """Valve gives a unit as roughly 1 inch, 0.75 inches, or 2-3 centimetres.
    40 per block is 2.5 cm a unit: inside the 2-3 cm range (error 0), 1.6
    percent from 1 inch, and 23.8 percent from 0.75 inches."""
    u = _units("um-minecraft-x-half-life")
    for form in ("declaredHostUnitsPerGuestUnit", "declaredSpanHostUnits"):
        d = u[form]
        assert d["best_relative_error"] == 0
        assert d["worst_relative_error"] == pytest.approx(0.238, rel=1e-9)
        assert d["scale_combinations"] == 3
        assert d["implied_low"] == pytest.approx(100 / 3)
        assert d["implied_high"] == pytest.approx(52.493438320209975)
        assert d["verdict"] == U and d["unsettled"]
    # 72 units ~ 1.8 m is the same ratio, computed by the engine from the pair
    assert u["declaredSpanHostUnits"]["ratio_as_declared"] == 40
    assert checks("um-minecraft-x-half-life")["facts"]["host"]["metres_per_unit"] == [[0.02, 0.03], 0.01905, 0.0254]


def test_the_two_to_three_centimetre_range_is_what_admits_forty(monkeypatch, tmp_path):
    """Take the 2-3 cm fact out of the facts file and 40 per block is 1.6
    percent from its nearest scale: the range, not the 1-inch scale, is what
    makes the best error 0."""
    import passport.bridge as pb
    text = pb.SPACE.read_text()
    start = text.index("fact:goldsrc-length-centimetres ga:units 1")
    end = text.index("fact:half-life-health ga:maxHealth 100")
    space = tmp_path / "ga-space.ttl"
    space.write_text(text[:start].replace(", fact:goldsrc-length-centimetres", "") + text[end:])
    monkeypatch.setattr(pb, "SPACE", space)
    d = {x["form"]: x for x in check(EX / "um-minecraft-x-half-life.ttl")["bridges"][0]
         ["checks"]["units"]["declarations"]}["declaredHostUnitsPerGuestUnit"]
    assert d["scale_combinations"] == 2
    assert d["best_relative_error"] == pytest.approx(0.016, rel=1e-9)


def test_garrys_redemption_matches_valves_prop_scale_exactly():
    """0.01905 m is 0.75 inch: the Source dimensions page's props scale (16
    units against 12 for characters), and 25 percent from its "1 HU ~ 1 inch".
    The metres-per-guest-unit form checks Garry's Mod's own unit only."""
    d = _units("um-garrys-redemption")["declaredMetresPerGuestUnit"]
    assert d["best_relative_error"] == 0
    assert d["worst_relative_error"] == pytest.approx(0.25, rel=1e-9)
    assert (d["implied_low"], d["implied_high"]) == (0.01905, 0.0254)
    assert d["checks"].startswith("the guest's own unit length only")


def test_gta_v_example_needs_gta_vs_unit():
    """'1 GTA metre = 1 block' as written checks only Minecraft's block; read
    off the row's unscaled coordinate map it is 1 GTA unit per block, which
    needs GTA V's unit, and that is unsourced."""
    u = _units("um-gta-v-example")
    assert u["declaredMetresPerGuestUnit"]["verdict"] == H
    assert u["declaredMetresPerGuestUnit"]["checks"].startswith("the guest's own unit length only")
    assert u["declaredHostUnitsPerGuestUnit"]["verdict"] == U
    assert u["declaredHostUnitsPerGuestUnit"]["missing"] == ["Grand Theft Auto V has no sourced unit length"]
    assert checks("um-gta-v-example")["units"]["verdict"] == U


def test_libertycraft_holds_only_against_minecrafts_block():
    (d,) = checks("um-libertycraft")["units"]["declarations"]
    assert d["form"] == "declaredMetresPerGuestUnit" and d["verdict"] == H
    assert d["checks"] == "the guest's own unit length only; the host's unit is not involved"


@pytest.mark.parametrize("name,game", [("um-killcraft", "ULTRAKILL"),
                                       ("um-2010-rust-rewrite-mashup", "Modern Warfare 2 (IW4L Rust rewrite)")])
def test_an_unsourced_unit_is_undetermined_not_guessed(name, game):
    (d,) = checks(name)["units"]["declarations"]
    assert d["verdict"] == U and d["missing"] == [f"{game} has no sourced unit length"]
    assert d.get("best_relative_error") is None


def test_skycraft_design_notes_map_is_the_derived_one():
    c = checks("src-skycraft")
    assert c["axes"]["declared"] == c["axes"]["derived"] == {"x": "+x", "y": "+z", "z": "-y"}
    h = c["handedness"]
    assert (h["handedness"], h["host_basis_determinant"], h["guest_basis_determinant"]) == (1, 1, 1)


# ------------------------------------------------------------------ each check refuses something


def _refusal(name, check_name):
    return checks(name)[check_name]["refusals"]


def test_axis_check_refuses_the_naive_copy_and_names_the_axes():
    msgs = _refusal("wrong-naive-xyz", "axes")
    assert sorted(m.split("'s ")[1][0] for m in msgs) == ["y", "z"]
    assert checks("wrong-naive-xyz")["axes"]["derived"] == {"x": "+x", "y": "+z", "z": "-y"}


def test_handedness_refuses_an_undeclared_mirror():
    h = checks("wrong-mirrored")["handedness"]
    assert (h["handedness"], h["declared_handedness"]) == (-1, 1) and h["refusals"]


def test_a_declared_and_named_mirror_holds():
    """Spec (b): handedness is kept unless a mirror is declared. A declared
    mirror that names the direction it flips is derived and holds."""
    c = checks("syn-declared-mirror")
    assert c["axes"]["derived"] == {"x": "+x", "y": "+z", "z": "+y"}
    assert c["handedness"]["handedness"] == -1 and c["handedness"]["declared_handedness"] == -1


def test_a_mirror_along_the_wrong_direction_is_refused_on_axes():
    c = checks("wrong-mirror-declared")
    assert c["handedness"]["verdict"] == H and c["handedness"]["handedness"] == -1
    assert c["axes"]["derived"] == {"x": "-x", "y": "+z", "z": "-y"}
    assert sorted(m.split("'s ")[1][0] for m in c["axes"]["refusals"]) == ["x", "z"]


def test_handedness_refuses_a_mirror_claimed_but_not_done():
    c = checks("wrong-false-mirror-claim")
    h = c["handedness"]
    assert (h["handedness"], h["declared_handedness"]) == (1, -1) and h["refusals"]
    assert c["axes"]["missing"] == ["the bridge declares a mirror without naming the world direction it "
                                    "flips (ga:mirrorDirection), so no single map can be derived"]


def test_handedness_refuses_two_axes_onto_one():
    assert checks("wrong-degenerate-map")["handedness"]["handedness"] == 0


def test_unit_check_refuses_a_wrong_ratio():
    d = _units("wrong-unit-ratio")["declaredHostUnitsPerGuestUnit"]
    assert d["best_relative_error"] == pytest.approx(0.0856, rel=1e-9) and d["refusals"]


@pytest.mark.parametrize("ratio,error", [(171, 1.4431625), (200, 1.8575), (1000, 13.2875)])
def test_unit_check_refuses_large_ratios(ratio, error, tmp_path):
    """In decimals the engine returns no value for any of these divided by
    Skyrim's implied 69.99... ratio, and the check used to say undetermined."""
    f = tmp_path / "t.ttl"
    f.write_text(PREFIXES + f"b:t a ga:Bridge ; {SKY} ; ga:declaredHostUnitsPerGuestUnit {ratio} .\n")
    r = check(f)
    (d,) = r["bridges"][0]["checks"]["units"]["declarations"]
    assert d["verdict"] == R and d["best_relative_error"] == pytest.approx(error, rel=1e-9)
    assert r["exit"] == 1


def test_health_check_refuses_a_wrong_multiplier():
    h = checks("wrong-health-multiplier")["health"]
    assert (h["policy_multiplier"], h["error"]) == (5, 1) and h["refusals"]


def test_health_check_refuses_native_and_multiplied():
    assert any("natively" in m for m in _refusal("wrong-health-native-and-multiplier", "health"))


def test_native_health_is_reported_as_not_checked(tmp_path):
    f = tmp_path / "t.ttl"
    f.write_text(PREFIXES + "b:t a ga:Bridge ; ga:host game:half-life ; ga:guest game:minecraft ; "
                            "ga:healthNative true .\n")
    r = check(f)
    h = r["bridges"][0]["checks"]["health"]
    assert h["verdict"] == NC and "nothing is compared" in h["note"]
    # nothing was checked, so nothing holds
    assert (r["verdict"], r["exit"]) == (U, 2)


def test_facts_check_refuses_an_unsourced_fact_and_the_rule_ignores_it():
    msgs = _refusal("wrong-unsourced-fact", "facts")
    assert any("page it was read from" in m for m in msgs)
    assert any("own words" in m for m in msgs)
    (d,) = checks("wrong-unsourced-fact")["units"]["declarations"]
    assert d["verdict"] == U


def test_facts_check_refuses_a_basis_with_two_directions_on_one_axis():
    assert any("three different axes" in m for m in _refusal("wrong-broken-basis", "facts"))


def test_declaration_check_refuses_something_that_is_not_an_axis():
    assert any("signed host axis" in m for m in _refusal("wrong-malformed-axis", "declaration"))


PREFIXES = """@prefix ga: <https://tesseractsemantics.com/ns/asset-passport/ga#> .
@prefix game: <https://tesseractsemantics.com/ns/asset-passport/game/> .
@prefix fact: <https://tesseractsemantics.com/ns/asset-passport/fact/> .
@prefix b: <https://tesseractsemantics.com/ns/asset-passport/bridge/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
"""
SKY = "ga:host game:skyrim ; ga:guest game:minecraft"
T = "b:t a ga:Bridge ; ga:host game:t ; ga:guest game:minecraft"

# One small case per remaining shape: (synthetic facts, bridge, message). Each
# must be refused with that shape's message. Facts go through --facts.
SNIPPETS = {
    "two hosts": ("", "b:t a ga:Bridge ; ga:host game:skyrim , game:fallout-new-vegas ; ga:guest game:minecraft .",
                  "A bridge names exactly one host game."),
    "no guest": ("", "b:t a ga:Bridge ; ga:host game:skyrim .", "A bridge names exactly one guest game."),
    "host not a game": ("", "b:t a ga:Bridge ; ga:host fact:minecraft-length ; ga:guest game:minecraft ; "
                            "ga:declaredHostUnitsPerGuestUnit 1 .",
                        "A bridge's host must be a game that a facts file declares."),
    "guest not a game": ("", "b:t a ga:Bridge ; ga:host game:skyrim ; ga:guest game:nowhere ; "
                             "ga:declaredHostUnitsPerGuestUnit 1 .",
                         "A bridge's guest must be a game that a facts file declares."),
    "mirrored yes": ("", f'b:t a ga:Bridge ; {SKY} ; ga:mirrored "yes" .',
                     "A bridge says once, true or false, whether it mirrors the world."),
    "mirror direction not a direction": ("", f"b:t a ga:Bridge ; {SKY} ; ga:mirrored true ; ga:mirrorDirection ga:Sideways .",
                                         "A mirror flips one world direction: ga:East, ga:North or ga:Up."),
    "mirror direction without a mirror": ("", f"b:t a ga:Bridge ; {SKY} ; ga:mirrorDirection ga:North .",
                                          "A bridge names a mirror direction only when it declares ga:mirrored true."),
    "negative ratio": ("", f"b:t a ga:Bridge ; {SKY} ; ga:declaredHostUnitsPerGuestUnit -70 .",
                       "A unit ratio is one positive number."),
    "two ratios": ("", f"b:t a ga:Bridge ; {SKY} ; ga:declaredHostUnitsPerGuestUnit 70 , 64 .",
                   "A unit ratio is one positive number."),
    "zero span": ("", "b:t a ga:Bridge ; ga:host game:half-life ; ga:guest game:minecraft ; "
                      "ga:declaredSpanHostUnits 72 ; ga:declaredSpanMetres 0 .",
                  "A span is one positive number of host units and one positive length in metres."),
    "zero length": ("", f"b:t a ga:Bridge ; {SKY} ; ga:declaredMetresPerGuestUnit 0 .",
                    "A unit length is one positive number."),
    "two multipliers": ("", "b:t a ga:Bridge ; ga:host game:half-life ; ga:guest game:minecraft ; "
                            "ga:declaredHealthMultiplier 5 , 6 .", "A health multiplier is one positive number."),
    "native false": ("", "b:t a ga:Bridge ; ga:host game:half-life ; ga:guest game:minecraft ; ga:healthNative false .",
                     "ga:healthNative is only ever stated as true; a bridge that converts health declares a multiplier instead."),
    "guest y and z": ("", f'b:t a ga:Bridge ; {SKY} ; ga:guestXFrom "+x" ; ga:guestYFrom "+w" ; ga:guestZFrom "up" .',
                      "The guest's y must be read off one signed host axis: +x, -x, +y, -y, +z or -z."),
    "guest z": ("", f'b:t a ga:Bridge ; {SKY} ; ga:guestXFrom "+x" ; ga:guestYFrom "+z" ; ga:guestZFrom "down" .',
                "The guest's z must be read off one signed host axis: +x, -x, +y, -y, +z or -z."),
    "zero units": ("game:t a ga:Game ; ga:lengthEvidence fact:t . fact:t ga:units 0 ; ga:metres 1 ; "
                   "ga:source <https://example.org/s> ; ga:quote \"q\" .",
                   f"{T} ; ga:declaredHostUnitsPerGuestUnit 1 .",
                   "A length statement is about a positive number of units."),
    "half a range": ("game:t a ga:Game ; ga:lengthEvidence fact:t . fact:t ga:units 1 ; ga:centimetresFrom 2 ; "
                     "ga:source <https://example.org/s> ; ga:quote \"q\" .",
                     f"{T} ; ga:declaredHostUnitsPerGuestUnit 1 .",
                     "A length range gives exactly one lower and one upper end."),
    "bad direction": ("game:t a ga:Game ; ga:axisEvidence fact:t . fact:t ga:direction ga:East ; ga:axis \"+q\" ; "
                      "ga:source <https://example.org/s> ; ga:quote \"q\" .",
                      f'{T} ; ga:guestXFrom "+x" .',
                      "A direction is one signed axis: +x, -x, +y, -y, +z or -z."),
    "unsourced axis": ("game:t a ga:Game ; ga:axisEvidence fact:t . fact:t ga:direction ga:East ; ga:axis \"+x\" .",
                       f'{T} ; ga:guestXFrom "+x" .',
                       "An axis direction is admitted only with the page it was read from."),
    "unquoted axis": ("game:t a ga:Game ; ga:axisEvidence fact:t . fact:t ga:direction ga:East ; ga:axis \"+x\" ; "
                      "ga:source <https://example.org/s> .",
                      f'{T} ; ga:guestXFrom "+x" .',
                      "An axis direction is admitted only with the source's own words."),
    "blank-node fact": ("game:t a ga:Game ; ga:lengthEvidence [ ga:units 1 ; ga:metres 1 ; "
                        "ga:source <https://example.org/s> ; ga:quote \"q\" ] .",
                        f"{T} ; ga:declaredHostUnitsPerGuestUnit 1 .",
                        "A unit length must be an IRI, not a blank node: the rule writes its metres per unit onto it."),
    "unsourced health": ("game:t a ga:Game ; ga:healthEvidence fact:t . fact:t ga:maxHealth 50 ; ga:quote \"q\" .",
                         f"{T} ; ga:declaredHealthMultiplier 2.5 .",
                         "A health maximum is admitted only with the page it was read from."),
    "unquoted health": ("game:t a ga:Game ; ga:healthEvidence fact:t . fact:t ga:maxHealth 50 ; "
                        "ga:source <https://example.org/s> .",
                        f"{T} ; ga:declaredHealthMultiplier 2.5 .",
                        "A health maximum is admitted only with the source's own words."),
}


def run_snippet(tmp_path, bridge: str, facts: str = "") -> dict:
    f = tmp_path / "t.ttl"
    f.write_text(PREFIXES + bridge + "\n")
    extra = []
    if facts:
        extra = [tmp_path / "facts.ttl"]
        extra[0].write_text(PREFIXES + facts + "\n")
    return check(f, facts=extra)


@pytest.mark.parametrize("case", list(SNIPPETS))
def test_each_remaining_shape_refuses(case, tmp_path):
    facts, body, message = SNIPPETS[case]
    r = run_snippet(tmp_path, body, facts)
    assert r["input"]["verdict"] == H, r["input"]["refusals"]
    assert r["evaluators"]["agree"], r["evaluators"]["problems"]
    (b,) = r["bridges"]
    msgs = [m for c in b["checks"].values() for m in (c.get("refusals") or [])]
    assert message in msgs, msgs
    assert r["verdict"] == R and r["exit"] == 1


# ------------------------------------------------------------------ the input guards


def _derived_predicates() -> list[str]:
    """Every predicate rules/bridge.rq writes, read off its CONSTRUCT template
    and the VALUES table that names the per-axis ones."""
    rule = (ROOT / "rules" / "bridge.rq").read_text()
    template = rule[rule.index("CONSTRUCT {"):rule.index("WHERE {")]
    names = set(re.findall(r"ga:(\w+)", template))
    for row in re.findall(r'\("[xyz]" ga:\w+ ga:(\w+) ga:(\w+)\)', rule):
        names.update(row)
    return sorted(names)


def test_the_derived_predicate_list_is_complete():
    assert _derived_predicates() == sorted([
        "metresPerUnit", "metresPerUnitLow", "metresPerUnitHigh", "basisDeterminant",
        "derivedGuestXFrom", "derivedGuestYFrom", "derivedGuestZFrom",
        "axisXAgrees", "axisYAgrees", "axisZAgrees",
        "handedness", "declaredHandedness", "handednessAgreement",
        "unitCheckOf", "declarationForm", "declaredValue", "impliedLow", "impliedHigh",
        "bestRelativeError", "worstRelativeError", "scaleCombinations", "scaleCombinationsEvaluated",
        "healthPolicyMultiplier", "healthMultiplierError"])


@pytest.mark.parametrize("pred", _derived_predicates())
def test_a_bridge_file_cannot_state_a_derived_predicate(pred, tmp_path):
    r = run_snippet(tmp_path, f"b:t a ga:Bridge ; ga:host game:gta-v ; ga:guest game:minecraft ; "
                              f"ga:declaredHostUnitsPerGuestUnit 1234 ; ga:{pred} 1 .")
    assert (r["verdict"], r["exit"], r["bridges"]) == (R, 1, [])
    assert [x["predicate"] for x in r["input"]["refusals"]] == [pred]


@pytest.mark.parametrize("pred", _derived_predicates())
def test_a_facts_file_cannot_state_a_derived_predicate(pred, tmp_path):
    r = run_snippet(tmp_path, f"b:t a ga:Bridge ; {SKY} ; ga:declaredHostUnitsPerGuestUnit 70 .",
                    f"fact:x ga:{pred} 1 .")
    assert (r["verdict"], r["exit"]) == (R, 1)
    (x,) = r["input"]["refusals"]
    assert x["predicate"] == pred and x["file"].endswith("facts.ttl")


@pytest.mark.parametrize("triple", [
    "game:gta-v ga:lengthEvidence fact:skyrim-length .",
    "fact:skyrim-length ga:units 64 .",
    "fact:skyrim-length ga:feet 5 .",
    "fact:x ga:axis \"+x\" .",
    "fact:x ga:direction ga:East .",
    "fact:minecraft-health ga:maxHealth 40 .",
    "fact:x ga:source <https://example.org/s> .",
    "game:new a ga:Game .",
    "game:gta-v rdfs:label \"The Elder Scrolls V: Skyrim\" .",
])
def test_a_bridge_file_cannot_state_a_game_fact(triple, tmp_path):
    r = run_snippet(tmp_path, f"b:t a ga:Bridge ; {SKY} ; ga:declaredHostUnitsPerGuestUnit 64 . {triple}")
    assert (r["verdict"], r["exit"], r["bridges"]) == (R, 1, [])
    assert any("only about the bridges it declares" in x["reason"] for x in r["input"]["refusals"])


@pytest.mark.parametrize("pred", ["lengthEvidence", "units", "axis", "maxHealth", "source", "quote"])
def test_a_bridge_may_not_carry_fact_predicates_itself(pred, tmp_path):
    r = run_snippet(tmp_path, f"b:t a ga:Bridge ; {SKY} ; ga:declaredHostUnitsPerGuestUnit 64 ; ga:{pred} 1 .")
    want = [] if pred == "quote" else [pred]
    # ga:quote is provenance a bridge may carry (a src- file quotes its code)
    assert [x["predicate"] for x in r["input"]["refusals"]] == want


@pytest.mark.parametrize("value", ["6.4e1", '"64"', '"64"^^<http://www.w3.org/2001/XMLSchema#double>', "<urn:x>"])
def test_a_declared_number_must_be_an_integer_or_decimal(value, tmp_path):
    r = run_snippet(tmp_path, f"b:t a ga:Bridge ; {SKY} ; ga:declaredHostUnitsPerGuestUnit {value} .")
    (x,) = r["input"]["refusals"]
    assert "xsd:integer or xsd:decimal" in x["reason"] and r["exit"] == 1


def test_a_bridge_file_may_not_type_a_node_as_anything_but_a_bridge(tmp_path):
    r = run_snippet(tmp_path, f"b:t a ga:Bridge , ga:Game ; {SKY} ; ga:declaredHostUnitsPerGuestUnit 70 .")
    (x,) = r["input"]["refusals"]
    assert x["predicate"] == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type" and x["object"].endswith("#Game")


def test_a_facts_file_may_not_declare_a_bridge(tmp_path):
    r = run_snippet(tmp_path, f"b:t a ga:Bridge ; {SKY} ; ga:declaredHostUnitsPerGuestUnit 70 .",
                    f"b:u a ga:Bridge ; {SKY} .")
    assert {x["predicate"] for x in r["input"]["refusals"]} >= {"host", "guest",
                                                                 "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"}


def test_the_shipped_facts_pass_the_facts_guard():
    """Every real run passes ontology/ga-space.ttl through rules/facts-input.rq;
    this pins that it states no derived or bridge predicate."""
    r = run("um-skycraft")
    assert r["input"]["facts_files"] == ["ontology/ga-space.ttl"] and r["input"]["verdict"] == H


def test_unit_nodes_are_read_only_at_the_iri_the_rule_mints(monkeypatch, tmp_path):
    """Defence in depth: with the bridge guard switched off, a hand-made unit
    node at another IRI still decides nothing."""
    import passport.bridge as pb
    off = tmp_path / "off.rq"
    off.write_text("SELECT ?s ?p ?o ?why WHERE { FILTER(false) }")
    monkeypatch.setattr(pb, "BRIDGE_GUARD", off)
    r = run_snippet(tmp_path, "b:t a ga:Bridge ; ga:host game:ultrakill ; ga:guest game:minecraft ; "
                              "ga:declaredHostUnitsPerGuestUnit 2 . <urn:x> ga:unitCheckOf b:t ; "
                              "ga:declarationForm ga:declaredHostUnitsPerGuestUnit ; "
                              "ga:bestRelativeError 0 ; ga:worstRelativeError 0 .")
    (d,) = r["bridges"][0]["checks"]["units"]["declarations"]
    assert d["verdict"] == U and d["missing"] == ["ULTRAKILL has no sourced unit length"]


def test_every_contract_message_is_refused_somewhere():
    """Every sh:message in the contract is produced by at least one example or
    snippet above, so no shape is one that cannot fail."""
    import re
    contract = (ROOT / "contracts" / "bridge.shacl.ttl").read_text()
    messages = set(re.findall(r'sh:message "([^"]+)"', contract))
    seen = {m for *_, m in SNIPPETS.values()}
    for name in EXPECTED:
        for b in run(name)["bridges"]:
            for c in b["checks"].values():
                seen.update(c.get("refusals") or [])
                for d in c.get("declarations", []):
                    seen.update(d.get("refusals") or [])
                    seen.update(d.get("unsettled") or [])
    assert messages - seen == set()


# ------------------------------------------------------------------ the guards


def test_disagreeing_evaluators_claim_nothing():
    default = {"conforms": False, "focus_nodes": 3,
               "violations": [{"focus_node": "urn:b", "path": "urn:p", "message": "m"}]}
    verified = {"conforms": False, "report": {"results": []}}
    _, ev = _refusals(verified, default)
    assert not ev["agree"] and "different refusals" in ev["problems"][0]


def test_a_contract_that_saw_nothing_claims_nothing():
    _, ev = _refusals({"conforms": True, "report": {"results": []}},
                      {"conforms": True, "focus_nodes": 0, "violations": []})
    assert not ev["agree"] and "no focus node" in ev["problems"][0]


def test_a_declining_evaluator_claims_nothing():
    _, ev = _refusals({"conforms": None, "undetermined": "shapes graph not compiled"},
                      {"conforms": True, "focus_nodes": 4, "violations": []})
    assert not ev["agree"]


@pytest.mark.parametrize("name,code", [("um-skycraft", 0), ("wrong-unit-ratio", 1), ("um-killcraft", 2),
                                       ("wrong-forged-derived", 1)])
def test_cli_exit_codes(name, code):
    p = subprocess.run([sys.executable, "-m", "passport.bridge", "check", str(EX / f"{name}.ttl")],
                       cwd=ROOT, capture_output=True, text=True, env=os.environ.copy(), timeout=120)
    assert p.returncode == code, p.stderr
    assert json.loads(p.stdout)["exit"] == code


def test_cli_facts_flag_marks_the_run_synthetic():
    """Without --facts the made-up game does not exist, and the declaration is
    refused because its host is not a game; with it, the facts check refuses
    the broken basis and the run says it read synthetic facts."""
    base = [sys.executable, "-m", "passport.bridge", "check", str(EX / "wrong-broken-basis.ttl")]
    plain = subprocess.run(base, cwd=ROOT, capture_output=True, text=True, env=os.environ.copy(), timeout=120)
    synth = subprocess.run(base + ["--facts", str(EX / "facts" / "wrong-broken-basis.ttl")], cwd=ROOT,
                           capture_output=True, text=True, env=os.environ.copy(), timeout=120)
    a, b = json.loads(plain.stdout), json.loads(synth.stdout)
    assert (plain.returncode, synth.returncode) == (1, 1)
    assert a["input"]["synthetic_facts"] is False and b["input"]["synthetic_facts"] is True
    assert a["bridges"][0]["checks"]["declaration"]["refusals"] == [
        "A bridge's host must be a game that a facts file declares."]
    assert b["bridges"][0]["checks"]["declaration"]["verdict"] == H
    assert b["bridges"][0]["checks"]["facts"]["verdict"] == R


# ------------------------------------------------------------------ the engine's decimal fault


def _engine_values(exprs: list[str]) -> list:
    with Engine(scratch("dec")) as e:
        e.call("onto_clear")
        e.call("onto_load", turtle="<urn:a> <urn:b> <urn:c> .")
        out = []
        for x in exprs:
            (row,) = e.call("onto_query", query=f"SELECT ?x WHERE {{ BIND ({x} AS ?x) }}")["results"]
            out.append(row.get("x"))
        return out


def test_the_engines_decimal_fault_is_as_documented():
    """docs/BRIDGES.md and rules/bridge.rq describe this fault; if a release
    fixes it, this test fails and the description must change."""
    v = _engine_values(["(170 / 69.991251093613298337)", "(171 / 69.991251093613298337)",
                        "(1000 / 69.991251093613298337)", "(1000 / 69.99125109361329833)", "(1000 / 70)",
                        "(0.0 / 0.5)", "(0.0 / 2.0)", "(0 / 0.01905)", "(0.0 * 0.5)",
                        "((1 / 3) * 0.5)", "((1 / 3) * 2)"])
    bound = [x is not None for x in v]
    assert bound == [True, False, False, True, True, False, True, False, False, False, True]


def _with_rule(monkeypatch, tmp_path, old: str, new: str):
    import passport.bridge as pb
    text = pb.RULE.read_text()
    assert old in text
    patched = tmp_path / "bridge.rq"
    patched.write_text(text.replace(old, new))
    monkeypatch.setattr(pb, "RULE", patched)


DOUBLE_ERROR = "BIND (xsd:decimal(?errD) AS ?err)"


def test_a_decimal_error_term_drops_a_large_ratio_and_the_checker_fails_closed(monkeypatch, tmp_path):
    """Computed in decimals, as the first version of the rule did, the error
    for 1000 per block has no value. The checker must refuse that declaration,
    not call it undetermined as if a fact were missing."""
    _with_rule(monkeypatch, tmp_path, DOUBLE_ERROR, "BIND (ABS(((?d / xsd:decimal(?lo1)) - 1)) AS ?err)")
    r = check(EX / "wrong-unit-ratio-large.ttl")
    (d,) = r["bridges"][0]["checks"]["units"]["declarations"]
    assert (d["verdict"], d["refusals"]) == (R, [ENGINE_DROPPED])
    assert (d["scale_combinations"], d["scale_combinations_evaluated"]) == (1, 0)
    assert r["exit"] == 1
    # and the same patched rule still evaluates a small ratio normally
    (d,) = check(EX / "um-skycraft.ttl")["bridges"][0]["checks"]["units"]["declarations"]
    assert d["verdict"] == H


def test_one_dropped_scale_out_of_three_is_not_hidden_by_the_minimum(monkeypatch, tmp_path):
    """Half-Life has three scales. Drop the error for the range alone and the
    minimum over the other two would quietly say 1.6 percent; the count of
    evaluated combinations catches it."""
    _with_rule(monkeypatch, tmp_path, DOUBLE_ERROR,
               "BIND (IF((?lo1 = ?hi1), xsd:decimal(?errD), ?nothing) AS ?err)")
    u = {x["form"]: x for x in check(EX / "um-minecraft-x-half-life.ttl")["bridges"][0]
         ["checks"]["units"]["declarations"]}
    d = u["declaredHostUnitsPerGuestUnit"]
    assert (d["verdict"], d["scale_combinations"], d["scale_combinations_evaluated"]) == (R, 3, 2)


def test_health_fails_closed_when_the_engine_drops_the_policy(monkeypatch, tmp_path):
    _with_rule(monkeypatch, tmp_path, "BIND ((?hMax / ?gMax) AS ?policy)", "BIND (?nothing AS ?policy)")
    h = check(EX / "um-minecraft-x-half-life.ttl")["bridges"][0]["checks"]["health"]
    assert (h["verdict"], h["refusals"]) == (R, [ENGINE_DROPPED])


def test_docs_bridges_page_is_current():
    """docs/BRIDGES.md's tables are written from the engine's output; this
    fails if a verdict or a number moved and the page was not regenerated."""
    p = subprocess.run([sys.executable, "scripts/bridges_report.py", "--check"], cwd=ROOT,
                       capture_output=True, text=True, env=os.environ.copy(), timeout=600)
    assert p.returncode == 0, p.stderr
