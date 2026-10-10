"""One check for an item that did not come from a game's own catalogue, used
by the command line and by the live API alike (judge.clean_item).

Before, each front door had its own copy, and they had drifted: the API
refused an id that is one of the game's own terms and a type the game does not
place, and the command line passed both to the engine; neither refused a
Pocket Battlers creature with no type at all, which the border then admitted.
"""

import json
import os
import subprocess
import sys

import pytest

from passport import api, judge
from passport.engine import ROOT, scratch

EMBERFOX = {"id": "fox", "kind": "Emberfox", "name": "Fox", "hp": 50, "movePower": 40,
            "moveName": "Ember", "type": "Fire"}


def cli(*args):
    code = "import sys; from passport.__main__ import main; sys.exit(main(sys.argv[1:]))"
    p = subprocess.run([sys.executable, "-c", code, *args], cwd=ROOT, capture_output=True, text=True, timeout=300)
    return p.returncode, json.loads(p.stdout.strip().splitlines()[-1]), p.stderr


def item_file(rec) -> str:
    f = scratch("item") / "item.json"
    f.write_text(json.dumps(rec))
    return str(f)


def test_the_api_delegates_to_the_command_lines_check(monkeypatch):
    seen = []
    monkeypatch.setattr(judge, "clean_item", lambda game, item, *a, **k: seen.append((game, item)) or {"ok": 1})
    assert api.clean_item("battle", EMBERFOX) == {"ok": 1} and seen == [("battle", EMBERFOX)]


@pytest.mark.parametrize("missing", ["type", "moveName", "hp"])
def test_a_field_the_games_own_record_of_that_kind_has_is_required(missing):
    rec = {k: v for k, v in EMBERFOX.items() if k != missing}
    with pytest.raises(api.BadRequest, match=f"Emberfox in Pocket Battlers must have {missing}: "
                                             "Pocket Battlers' own Emberfox has it"):
        api.clean_item("battle", rec)
    with pytest.raises(judge.BadItem, match=f"must have {missing}"):
        judge.clean_item("battle", rec)
    assert api.clean_item("battle", EMBERFOX)["type"] == "Fire"  # the control


def test_cli_a_creature_without_a_type_exits_2_with_the_reason():
    rec = {k: v for k, v in EMBERFOX.items() if k != "type"}
    rc, out, err = cli("judge", "--from", "battle", "--into", "craft", "--item", item_file(rec))
    assert rc == 2 and "Emberfox in Pocket Battlers must have type" in out["error"], (out, err)


@pytest.mark.parametrize("change,why", [
    ({"id": "game"}, "is a term of Pocket Battlers' own rules"),
    ({"type": "Plasma"}, "Pocket Battlers has no type 'Plasma'"),
    ({"name": "Fox‮"}, "name must hold only printable characters"),
])
def test_cli_refuses_what_the_api_refuses(change, why):
    rc, out, err = cli("judge", "--from", "battle", "--into", "craft", "--item", item_file({**EMBERFOX, **change}))
    assert rc == 2 and why in out["error"], (out, err)


FAMILY = "Fam \U0001F468‍\U0001F469‍\U0001F467"   # three people joined by ZWJ
HEART = "Heart ❤️"                                  # a heart with variation selector 16


@pytest.mark.parametrize("name", [FAMILY, HEART, "Shield ⚔︎"])
def test_a_name_may_hold_joiners_and_variation_selectors(name):
    assert api.clean_item("battle", {**EMBERFOX, "name": name})["name"] == name


@pytest.mark.parametrize("bad", ["‎", "‮", "⁦", "﻿", "\u0000", "­", "​", "\ud800"])
def test_other_control_and_format_characters_are_still_refused(bad):
    with pytest.raises(api.BadRequest, match="name must hold only printable characters"):
        api.clean_item("battle", {**EMBERFOX, "name": f"Fox{bad}"})


def test_a_name_with_a_joiner_reaches_a_verdict():
    v = api.judge({"game": "battle", "target": "craft", "item": {**EMBERFOX, "name": FAMILY}})
    assert v["verdict"] == "converted_with_loss", v["headline"]
