"""The CI checks in this folder refuse what they exist to refuse.

These run in the ordinary pytest suite and need no engine: each feeds a check a
small hand-made input, first one it must accept and then one it must refuse.
"""

import copy
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(f"ci_{name}", HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


emp = _load("engine_matches_page")
sk = _load("skips")

# What build_site.py --check prints, in its own format, for two transfers and three forgeries.
OUTPUT = """--check: throwaway keys in /tmp/x; nothing in the repository will be written
craft:diamond_sword      -> battle converted             {'typeInTarget': 'ga:Rock', 'damageInTarget': 35}
battle:emberfox          -> craft  converted_with_loss   {'hitPointsInTarget': 20, 'damageInTarget': 8}
forgery tamper        -> refused at unpack
forgery source_omits  -> refused at closure
forgery source_lies   -> converted at border  (gets through)
--check: done; nothing was written
"""

DATA = {
    "transfers": {
        "craft:diamond_sword": {"target": "battle", "verdict": "converted",
                                "conversion": {"typeInTarget": "ga:Rock", "damageInTarget": 35}},
        "battle:emberfox": {"target": "craft", "verdict": "converted_with_loss",
                            "conversion": {"hitPointsInTarget": 20, "damageInTarget": 8}},
    },
    "forgeries": [
        {"name": "tamper", "verdict": {"verdict": "refused", "stage": "unpack"}, "gets_through": False},
        {"name": "source_omits", "verdict": {"verdict": "refused", "stage": "closure"}, "gets_through": False},
        {"name": "source_lies", "verdict": {"verdict": "converted", "stage": "border"}, "gets_through": True},
    ],
}


def test_matching_data_is_accepted():
    assert emp.differences(OUTPUT, DATA) == []


def _edit(fn):
    d = copy.deepcopy(DATA)
    fn(d)
    return d


@pytest.mark.parametrize("plant, says", [
    (lambda d: d["transfers"]["battle:emberfox"]["conversion"].update(damageInTarget=9), "conversion"),
    (lambda d: d["transfers"]["craft:diamond_sword"].update(verdict="refused"), "verdict"),
    (lambda d: d["transfers"]["craft:diamond_sword"].update(target="craft"), "target"),
    (lambda d: d["transfers"].pop("battle:emberfox"), "has no such transfer"),
    (lambda d: d["transfers"].update({"craft:tnt": {"target": "battle", "verdict": "refused", "conversion": {}}}),
     "the engine did not judge it"),
    (lambda d: d["forgeries"][2].update(gets_through=False), "gets_through"),
    (lambda d: d["forgeries"][2]["verdict"].update(verdict="refused"), "verdict"),
    (lambda d: d["forgeries"][1]["verdict"].update(stage="rules"), "stage"),
    (lambda d: d["forgeries"].reverse(), "forgeries: verdicts.json lists"),
    (lambda d: d["forgeries"].pop(), "forgeries: verdicts.json lists"),
], ids=["number", "transfer-verdict", "target", "missing-transfer", "extra-transfer",
        "gets-through", "forgery-verdict", "stage", "order", "missing-forgery"])
def test_a_hand_edit_is_refused(plant, says):
    bad = emp.differences(OUTPUT, _edit(plant))
    assert bad and any(says in line for line in bad), bad


def test_an_unfinished_or_unreadable_check_is_refused():
    assert "did not finish" in emp.differences(OUTPUT.replace("--check: done; nothing was written\n", ""), DATA)[0]
    garbled = "\n".join(l.replace("->", "=>") for l in OUTPUT.splitlines())
    assert "nothing was compared" in emp.differences(garbled, DATA)[0]


def test_the_cli_exits_non_zero_on_a_difference(tmp_path, capsys):
    import json
    out = tmp_path / "check.txt"
    out.write_text(OUTPUT)
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(DATA))
    bad.write_text(json.dumps(_edit(lambda d: d["transfers"]["battle:emberfox"]["conversion"].update(damageInTarget=9))))
    assert emp.main(["--output", str(out), "--verdicts", str(good)]) == 0
    assert emp.main(["--output", str(out), "--verdicts", str(bad)]) == 1
    assert "REFUSED: battle:emberfox: conversion" in capsys.readouterr().out


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3" skipped="{n}">
<testcase classname="tests.test_a" name="test_runs" time="0.1"/>
{cases}
</testsuite></testsuites>
"""
SKIP_266 = ('<testcase classname="tests.test_verdicts" name="test_lie" time="0">'
            '<skipped type="pytest.skip" message="this engine cannot carry a certificate in a pack (open-ontologies #266, after v2.0.1)"/></testcase>')
SKIP_NODE = ('<testcase classname="tests.test_cors" name="test_config_as_committed" time="0">'
             '<skipped type="pytest.skip" message="node is not installed"/></testcase>')


def _junit(tmp_path, *cases):
    p = tmp_path / "report.xml"
    p.write_text(JUNIT.format(n=len(cases), cases="\n".join(cases)))
    return p


def test_no_skip_is_accepted(tmp_path):
    assert sk.verdict(_junit(tmp_path), []) == []


def test_any_skip_is_refused_when_none_is_allowed(tmp_path):
    bad = sk.verdict(_junit(tmp_path, SKIP_266), [])
    assert len(bad) == 1 and "test_lie skipped" in bad[0]


def test_only_the_allowed_reason_may_skip(tmp_path):
    assert sk.verdict(_junit(tmp_path, SKIP_266), ["#266"]) == []
    bad = sk.verdict(_junit(tmp_path, SKIP_266, SKIP_NODE), ["#266"])
    assert len(bad) == 1 and "node is not installed" in bad[0]
    assert sk.main([str(_junit(tmp_path, SKIP_NODE)), "--allow", "#266"]) == 1


def test_a_report_with_no_tests_is_refused(tmp_path):
    p = tmp_path / "empty.xml"
    p.write_text('<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="0"/></testsuites>')
    assert "no tests" in sk.verdict(p, [])[0]
