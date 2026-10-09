"""The bridge checker, pinned against the real engine.

Every row of Universal Modder's "Unit mappings" table that we model has its
verdicts pinned here, and every check in contracts/bridge.shacl.ttl is shown
refusing something: a check that has never refused anything proves nothing.
"""

import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

from passport.bridge import ROOT, _refusals, check

EX = ROOT / "examples" / "bridges"
H, R, U, N = "holds", "refused", "undetermined", "not_declared"


@lru_cache(maxsize=None)
def run(name: str) -> dict:
    return check(EX / f"{name}.ttl")


def checks(name: str) -> dict:
    (b,) = run(name)["bridges"]
    return b["checks"]


def verdicts(name: str) -> dict:
    return {k: c["verdict"] for k, c in checks(name).items()}


# file -> (overall, axes, handedness, units, health); declaration and facts hold
# unless a row says otherwise below.
EXPECTED = {
    # the table's rows, as the table states them
    "um-gta-v-example":            (U, U, U, H, N),
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
    # wrong on purpose
    "wrong-naive-xyz":             (R, R, H, H, N),
    "wrong-mirrored":              (R, R, R, H, N),
    "wrong-mirror-declared":       (R, R, H, H, N),
    "wrong-false-mirror-claim":    (R, H, R, H, N),
    "wrong-degenerate-map":        (R, R, R, H, N),
    "wrong-unit-ratio":            (R, N, N, R, N),
    "wrong-health-multiplier":     (R, N, N, N, R),
    "wrong-health-native-and-multiplier": (R, N, N, N, R),
    "wrong-unsourced-fact":        (R, N, N, U, N),
    "wrong-malformed-axis":        (R, R, R, N, N),
    "wrong-broken-basis":          (R, R, R, N, N),
}
DECLARATION_REFUSED = {"wrong-malformed-axis"}
FACTS_REFUSED = {"wrong-unsourced-fact", "wrong-broken-basis"}


def test_every_example_is_pinned():
    assert {p.stem for p in EX.glob("*.ttl")} == set(EXPECTED)


@pytest.mark.parametrize("name", list(EXPECTED))
def test_verdicts(name):
    overall, axes, hand, units, health = EXPECTED[name]
    r = run(name)
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
    assert d["implied_low"] == d["implied_high"] == pytest.approx(69.99125109361329, abs=1e-12)
    assert d["best_relative_error"] == d["worst_relative_error"] == 0.000125


def test_faith_runner_seventy_per_metre_is_skyrims_unit():
    d = _units("um-faith-runner-skyrim")["declaredHostUnitsPerMetre"]
    assert d["best_relative_error"] == 0.000125


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


def test_half_life_forty_per_block_fits_one_valve_scale_of_two():
    """Valve gives a unit as roughly 1 inch or 0.75 inches. 40 per block is
    1.6 percent from the first and 23.8 percent from the second."""
    u = _units("um-minecraft-x-half-life")
    for form in ("declaredHostUnitsPerGuestUnit", "declaredSpanHostUnits"):
        d = u[form]
        assert d["best_relative_error"] == 0.016 and d["worst_relative_error"] == 0.238
        assert d["implied_low"] == pytest.approx(39.37007874015748)
        assert d["implied_high"] == pytest.approx(52.493438320209975)
        assert d["verdict"] == U and d["unsettled"]
    # 72 units ~ 1.8 m is the same ratio, computed by the engine from the pair
    assert u["declaredSpanHostUnits"]["ratio_as_declared"] == 40


def test_half_life_health_times_five_is_the_proportional_policy():
    h = checks("um-minecraft-x-half-life")["health"]
    assert (h["declared_multiplier"], h["policy_multiplier"], h["error"]) == (5, 5, 0)


def test_garrys_redemption_matches_valves_prop_scale_exactly():
    """0.01905 m is 0.75 inch: Valve's props scale (16 units to the foot), and
    25 percent from its "1 HU ~ 1 inch" character scale. The best error is an
    exact 0: written as (d - imp) / imp the engine would drop it (0.0 / 0.01905
    is unbound), so this also pins the workaround in rules/bridge.rq."""
    d = _units("um-garrys-redemption")["declaredMetresPerGuestUnit"]
    assert (d["best_relative_error"], d["worst_relative_error"]) == (0, 0.25)
    assert (d["implied_low"], d["implied_high"]) == (0.01905, 0.0254)


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


def test_a_declared_mirror_passes_handedness_but_not_the_axis_map():
    c = checks("wrong-mirror-declared")
    assert c["handedness"]["verdict"] == H and c["handedness"]["handedness"] == -1
    assert [m for m in c["axes"]["refusals"] if "guest's z" in m]


def test_handedness_refuses_a_mirror_claimed_but_not_done():
    h = checks("wrong-false-mirror-claim")["handedness"]
    assert (h["handedness"], h["declared_handedness"]) == (1, -1) and h["refusals"]


def test_handedness_refuses_two_axes_onto_one():
    assert checks("wrong-degenerate-map")["handedness"]["handedness"] == 0


def test_unit_check_refuses_a_wrong_ratio():
    d = _units("wrong-unit-ratio")["declaredHostUnitsPerGuestUnit"]
    assert d["best_relative_error"] == 0.0856 and d["refusals"]


def test_health_check_refuses_a_wrong_multiplier():
    h = checks("wrong-health-multiplier")["health"]
    assert (h["policy_multiplier"], h["error"]) == (5, 1) and h["refusals"]


def test_health_check_refuses_native_and_multiplied():
    assert any("natively" in m for m in _refusal("wrong-health-native-and-multiplier", "health"))


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
"""
SKY = "ga:host game:skyrim ; ga:guest game:minecraft"
NEW_GAME = "game:t a ga:Game ; rdfs:label \"T\" . "

# One small file per remaining shape: each must be refused with that shape's message.
SNIPPETS = {
    "two hosts": ("b:t a ga:Bridge ; ga:host game:skyrim , game:fallout-new-vegas ; ga:guest game:minecraft .",
                  "A bridge names exactly one host game."),
    "no guest": ("b:t a ga:Bridge ; ga:host game:skyrim .", "A bridge names exactly one guest game."),
    "mirrored yes": (f'b:t a ga:Bridge ; {SKY} ; ga:mirrored "yes" .',
                     "A bridge says once, true or false, whether it mirrors the world."),
    "negative ratio": (f"b:t a ga:Bridge ; {SKY} ; ga:declaredHostUnitsPerGuestUnit -70 .",
                       "A unit ratio is one positive number."),
    "two ratios": (f"b:t a ga:Bridge ; {SKY} ; ga:declaredHostUnitsPerGuestUnit 70 , 64 .",
                   "A unit ratio is one positive number."),
    "zero span": (f"b:t a ga:Bridge ; ga:host game:half-life ; ga:guest game:minecraft ; "
                  "ga:declaredSpanHostUnits 72 ; ga:declaredSpanMetres 0 .",
                  "A span is one positive number of host units and one positive length in metres."),
    "zero length": (f"b:t a ga:Bridge ; {SKY} ; ga:declaredMetresPerGuestUnit 0 .",
                    "A unit length is one positive number."),
    "two multipliers": ("b:t a ga:Bridge ; ga:host game:half-life ; ga:guest game:minecraft ; "
                        "ga:declaredHealthMultiplier 5 , 6 .", "A health multiplier is one positive number."),
    "native false": ("b:t a ga:Bridge ; ga:host game:half-life ; ga:guest game:minecraft ; ga:healthNative false .",
                     "ga:healthNative is only ever stated as true; a bridge that converts health declares a multiplier instead."),
    "guest y and z": (f'b:t a ga:Bridge ; {SKY} ; ga:guestXFrom "+x" ; ga:guestYFrom "+w" ; ga:guestZFrom "up" .',
                      "The guest's y must be read off one signed host axis: +x, -x, +y, -y, +z or -z."),
    "guest z": (f'b:t a ga:Bridge ; {SKY} ; ga:guestXFrom "+x" ; ga:guestYFrom "+z" ; ga:guestZFrom "down" .',
                "The guest's z must be read off one signed host axis: +x, -x, +y, -y, +z or -z."),
    "zero units": ("game:t a ga:Game ; ga:lengthEvidence fact:t . fact:t ga:units 0 ; ga:metres 1 ; "
                   "ga:source <https://example.org/s> ; ga:quote \"q\" . "
                   "b:t a ga:Bridge ; ga:host game:t ; ga:guest game:minecraft ; ga:declaredHostUnitsPerGuestUnit 1 .",
                   "A length statement is about a positive number of units."),
    "bad direction": ("game:t a ga:Game ; ga:axisEvidence fact:t . fact:t ga:direction ga:East ; ga:axis \"+q\" ; "
                      "ga:source <https://example.org/s> ; ga:quote \"q\" . "
                      "b:t a ga:Bridge ; ga:host game:t ; ga:guest game:minecraft ; ga:guestXFrom \"+x\" .",
                      "A direction is one signed axis: +x, -x, +y, -y, +z or -z."),
    "unsourced axis": ("game:t a ga:Game ; ga:axisEvidence fact:t . fact:t ga:direction ga:East ; ga:axis \"+x\" . "
                       "b:t a ga:Bridge ; ga:host game:t ; ga:guest game:minecraft ; ga:guestXFrom \"+x\" .",
                       "An axis direction is admitted only with the page it was read from."),
    "unquoted axis": ("game:t a ga:Game ; ga:axisEvidence fact:t . fact:t ga:direction ga:East ; ga:axis \"+x\" ; "
                      "ga:source <https://example.org/s> . "
                      "b:t a ga:Bridge ; ga:host game:t ; ga:guest game:minecraft ; ga:guestXFrom \"+x\" .",
                      "An axis direction is admitted only with the source's own words."),
    "blank-node fact": ("game:t a ga:Game ; ga:lengthEvidence [ ga:units 1 ; ga:metres 1 ; "
                        "ga:source <https://example.org/s> ; ga:quote \"q\" ] . "
                        "b:t a ga:Bridge ; ga:host game:t ; ga:guest game:minecraft ; ga:declaredHostUnitsPerGuestUnit 1 .",
                        "A unit length must be an IRI, not a blank node: the rule writes its metres per unit onto it."),
    "unsourced health": ("game:t a ga:Game ; ga:healthEvidence fact:t . fact:t ga:maxHealth 50 ; ga:quote \"q\" . "
                         "b:t a ga:Bridge ; ga:host game:t ; ga:guest game:minecraft ; ga:declaredHealthMultiplier 2.5 .",
                         "A health maximum is admitted only with the page it was read from."),
    "unquoted health": ("game:t a ga:Game ; ga:healthEvidence fact:t . fact:t ga:maxHealth 50 ; "
                        "ga:source <https://example.org/s> . "
                        "b:t a ga:Bridge ; ga:host game:t ; ga:guest game:minecraft ; ga:declaredHealthMultiplier 2.5 .",
                        "A health maximum is admitted only with the source's own words."),
}


@pytest.mark.parametrize("case", list(SNIPPETS))
def test_each_remaining_shape_refuses(case, tmp_path):
    body, message = SNIPPETS[case]
    f = tmp_path / "t.ttl"
    f.write_text(PREFIXES + "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n" + body + "\n")
    r = check(f)
    assert r["evaluators"]["agree"], r["evaluators"]["problems"]
    (b,) = r["bridges"]
    msgs = [m for c in b["checks"].values() for m in (c.get("refusals") or [])]
    assert message in msgs, msgs
    assert r["verdict"] == R and r["exit"] == 1


def test_every_contract_message_is_refused_somewhere():
    """Every sh:message in the contract is produced by at least one example or
    snippet above, so no shape is one that cannot fail."""
    import re
    contract = (ROOT / "contracts" / "bridge.shacl.ttl").read_text()
    messages = set(re.findall(r'sh:message "([^"]+)"', contract))
    seen = {m for _, m in SNIPPETS.values()}
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


@pytest.mark.parametrize("name,code", [("um-skycraft", 0), ("wrong-unit-ratio", 1), ("um-killcraft", 2)])
def test_cli_exit_codes(name, code):
    p = subprocess.run([sys.executable, "-m", "passport.bridge", "check", str(EX / f"{name}.ttl")],
                       cwd=ROOT, capture_output=True, text=True, env=os.environ.copy(), timeout=120)
    assert p.returncode == code, p.stderr
    assert json.loads(p.stdout)["exit"] == code


# ------------------------------------------------------------------ the rule's workaround


def _with_rule(monkeypatch, tmp_path, old: str, new: str):
    import passport.bridge as pb
    text = pb.RULE.read_text()
    assert old in text
    patched = tmp_path / "bridge.rq"
    patched.write_text(text.replace(old, new))
    monkeypatch.setattr(pb, "RULE", patched)


def test_the_naive_error_term_loses_an_exact_match(monkeypatch, tmp_path):
    """Written as (d - imp) / imp, an exact match divides a decimal zero by
    0.01905, the engine returns no value, and Garry's Redemption's exact match
    with Valve's props scale disappears from the minimum."""
    _with_rule(monkeypatch, tmp_path, "ABS(((?d / ?imp) - 1))", "ABS(((?d - ?imp) / ?imp))")
    (d,) = check(EX / "um-garrys-redemption.ttl")["bridges"][0]["checks"]["units"]["declarations"]
    assert d["best_relative_error"] != 0


def test_docs_bridges_page_is_current():
    """docs/BRIDGES.md's tables are written from the engine's output; this
    fails if a verdict or a number moved and the page was not regenerated."""
    p = subprocess.run([sys.executable, "scripts/bridges_report.py", "--check"], cwd=ROOT,
                       capture_output=True, text=True, env=os.environ.copy(), timeout=600)
    assert p.returncode == 0, p.stderr
