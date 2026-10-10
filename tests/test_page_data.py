"""The page's data is the engine's output, the same from one build to the next,
and checked field by field against the engine.

  - The "why" steps came out in another order, with other blank-node labels,
    on every build, and so did the transcripts' blank nodes and the engine's
    sampled inferences. Two builds now differ only in digests, pack sizes and
    timestamps.
  - scripts/build_site.py --check compared only each transfer's verdict and
    converted values, and each forgery's verdict and gate. It now compares
    every field the page renders and fails with a diff.
"""

import copy
import importlib.util
import json
import shutil

import pytest
from _support import needs_packs

from passport.engine import ROOT, scratch
from passport.judge import canonical_steps, derivation_steps
from passport.present import shown_transcript

ITEM = "https://tesseractsemantics.com/ns/asset-passport/craft#s"
T = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
ON, HAS = "<http://www.w3.org/2002/07/owl#onProperty>", "<http://www.w3.org/2002/07/owl#hasValue>"
GA = "https://tesseractsemantics.com/ns/asset-passport/ga#"
VERDICTS = ROOT / "site" / "data" / "verdicts.json"


def _derivations(a: str, b: str, reverse: bool) -> list[str]:
    """Two cls-hv1 steps through two restrictions labelled a and b, and one rdfs9 step."""
    lines = [
        f"cls-hv1\t<{ITEM}>\t<{GA}fromGame>\t<urn:game>\t_:{a}\t{ON}\t<{GA}fromGame>\t_:{a}\t{HAS}\t<urn:game>\t<{ITEM}>\t{T}\t_:{a}",
        f"cls-hv1\t<{ITEM}>\t<{GA}elementalType>\t<{GA}Rock>\t_:{b}\t{ON}\t<{GA}elementalType>\t_:{b}\t{HAS}\t<{GA}Rock>\t<{ITEM}>\t{T}\t_:{b}",
        f"rdfs9\t<{ITEM}>\t{T}\t<{GA}Item>\t<{ITEM}>\t{T}\t<urn:Thing>\t<urn:Thing>\t<http://www.w3.org/2000/01/rdf-schema#subClassOf>\t<{GA}Item>",
    ]
    return list(reversed(lines)) if reverse else lines


def test_two_certificates_of_one_item_give_the_same_why_list(tmp_path):
    """The labels are random on every load and the order is the engine's; the
    old list was sorted by text that included the labels, so it changed."""
    (tmp_path / "derivations.tsv").write_text("\n".join(_derivations("d019206c19e860fb7c98ef3f70e60ba8",
                                                                     "bcf239d06468fa1b512be81ba04fc04e", False)))
    first = derivation_steps(tmp_path, ITEM)
    (tmp_path / "derivations.tsv").write_text("\n".join(_derivations("0aa3c6f1d2e4b5a6978877665544332",
                                                                     "ff00ee11dd22cc33bb44aa5599668877", True)))
    assert derivation_steps(tmp_path, ITEM) == first
    assert [s["rule"] for s in first] == ["cls-hv1", "cls-hv1", "rdfs9"]
    labels = [p.split()[0] for s in first if s["rule"] == "cls-hv1" for p in s["premises"][:1]]
    assert labels == ["_:b0", "_:b1"]


def test_canonical_steps_renames_by_first_appearance_and_leaves_literals():
    raw = [("r", ["<x>", "<p>", '"_:not a node"'], [["_:zz", "<q>", "_:yy"]]),
           ("r", ["<x>", "<p>", "<a>"], [["_:yy", "<q>", "<b>"]])]
    out = canonical_steps(raw)
    assert out[0] == ("r", ["<x>", "<p>", '"_:not a node"'], [["_:b0", "<q>", "_:b1"]])
    assert out[1] == ("r", ["<x>", "<p>", "<a>"], [["_:b1", "<q>", "<b>"]])


def test_two_runs_give_the_same_transcript():
    def run(a, b, order):
        return [{"tool": "onto_reason", "args": {}, "result": {
            "sample_inferences": [f"<x> a _:{a}", f"<y> a _:{b}"][::order],
            "report": {"ignored": [{"subject": f"_:{b}"}]}}}]
    one = shown_transcript(run("c4787bdd46277da0c4787bdd46277da0", "e8e99421033d1990e8e99421033d1990", 1))
    two = shown_transcript(run("be5cad0908e0c96be5cad0908e0c96aa", "d55a86fae7d3075d55a86fae7d30751", -1))
    assert one == two
    assert one[0]["result"]["sample_inferences"] == ["<x> a _:b0", "<y> a _:b1"]


# ------------------------------------------------------------------ build_site.py --check


def _build():
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _plants():
    """Hand edits, one per kind of field the page renders, each of which --check must catch."""
    def why(d):
        d["transfers"]["craft:diamond_sword"]["why"][0]["premises"][0] = "craft:diamond_sword a craft:Feather"

    def refusal(d):
        d["transfers"]["craft:tnt"]["refusals"][0]["message"] = "TNT is fine."

    def derivations(d):
        d["transfers"]["battle:emberfox"]["proof"]["derivations"] = 99

    def card(d):
        d["forgeries"][0]["did"] = "Nothing at all."

    def profile(d):
        d["games"]["battle"]["profile"] = d["games"]["battle"]["profile"].replace("100", "999", 1)

    def call_args(d):
        d["transfers"]["craft:golden_apple"]["transcript"][1]["args"] = {"turtle": "<contents of something else>"}

    def reply(d):
        d["transfers"]["craft:golden_apple"]["transcript"][1]["result"]["triples_loaded"] = 1

    def rule(d):
        d["files"]["rule"] += "\n# planted\n"

    return {f.__name__: f for f in (why, refusal, derivations, card, profile, call_args, reply, rule)}


def _volatile(d):
    """What changes from one honest build to the next."""
    d["built_at"] = "2099-01-01T00:00:00+00:00"
    sig = d["transfers"]["craft:tnt"]["signature"]
    sig["public_key_sha256"] = sig["claimed_key_sha256"] = "0" * 64
    for c in d["transfers"]["craft:tnt"]["transcript"]:
        if isinstance(c.get("result"), dict) and "manifest" in c["result"]:
            c["result"]["manifest"]["content_sha256"] = "f" * 64
            c["result"]["manifest"]["created_at"] = "2099-01-01T00:00:00.000000+00:00"
        if isinstance(c.get("result"), dict) and "certificate" in c["result"]:
            c["result"]["certificate"]["certificate_bytes"] = 1


def test_page_differences_ignore_what_changes_between_honest_builds():
    b = _build()
    committed = json.loads(VERDICTS.read_text())
    again = copy.deepcopy(committed)
    _volatile(again)
    assert b.page_differences(again, committed) == []


@pytest.mark.parametrize("plant", sorted(_plants()))
def test_page_differences_name_every_rendered_field_that_differs(plant):
    b = _build()
    committed = json.loads(VERDICTS.read_text())
    planted = copy.deepcopy(committed)
    _plants()[plant](planted)
    diff = b.page_differences(committed, planted)
    assert diff and diff[0] == "--- site/data/verdicts.json", plant


def test_the_engines_replies_are_compared_only_on_the_binary_that_built_the_file():
    b = _build()
    committed = json.loads(VERDICTS.read_text())
    other = copy.deepcopy(committed)
    _plants()["reply"](other)
    other["engine"]["binary_sha256"] = "1" * 64
    assert b.page_differences(other, committed) == []
    assert any("replies in the transcripts were not compared" in n for n in b.engine_differences(other, committed))
    _plants()["call_args"](other)  # the arguments are this repository's, and are compared on any engine
    assert b.page_differences(other, committed)


@needs_packs
def test_check_runs_the_engine_and_fails_with_a_diff_on_a_hand_edit(monkeypatch, capsys):
    b = _build()
    data = scratch("data")
    shutil.copy(VERDICTS, data / "verdicts.json")
    monkeypatch.setattr(b, "DATA", data)
    b.main(["--check"])
    out = capsys.readouterr().out
    assert "--check: site/data/verdicts.json gives what the engine says now, in every field the page renders" in out
    planted = json.loads(VERDICTS.read_text())
    _plants()["why"](planted)
    (data / "verdicts.json").write_text(json.dumps(planted))
    with pytest.raises(SystemExit, match="is not what the engine says now"):
        b.main(["--check"])
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert any(l.startswith("-") and '"craft:diamond_sword a craft:Feather"' in l for l in lines), out[-2000:]
    assert any(l.startswith("+") and '"_:b0 owl:onProperty ga:elementalType"' in l for l in lines), out[-2000:]
