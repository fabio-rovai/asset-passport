"""Games found on disk, and the command line."""

import json
import os
import subprocess
import sys

import pytest
from _support import games_copy, needs_packs

from passport import games
from passport.engine import EngineError, ROOT, scratch
from passport.judge import catalogue, judge_direct

NS = "https://tesseractsemantics.com/ns/asset-passport/"
PUZZLE = """@prefix ga: <https://tesseractsemantics.com/ns/asset-passport/ga#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/puzzle#game> a ga:Game ; rdfs:label "Tile Puzzle" ; ga:maxPlayerHealth 3 .
"""


def test_the_two_games_are_discovered_with_their_published_names():
    found = games.discover()
    assert {k: (g.iri, g.label) for k, g in found.items()} == {
        "battle": (NS + "battle#game", "Pocket Battlers"),
        "craft": (NS + "craft#game", "Blockcraft"),
    }
    assert all(g.border.exists() for g in found.values())


def test_a_new_directory_with_a_profile_is_a_new_game():
    root = games_copy()
    (root / "puzzle").mkdir()
    (root / "puzzle" / "profile.ttl").write_text(PUZZLE)
    (root / "notes").mkdir()  # no profile.ttl: not a game
    found = games.discover(root)
    assert sorted(found) == ["battle", "craft", "puzzle"]
    assert (found["puzzle"].iri, found["puzzle"].label) == ("https://example.org/puzzle#game", "Tile Puzzle")


def test_the_label_is_read_by_the_engine_not_by_a_pattern():
    """A comment that looks like a declaration is not one. A pattern over the
    Turtle text would find both lines; the engine finds the real one."""
    root = games_copy()
    (root / "puzzle").mkdir()
    (root / "puzzle" / "profile.ttl").write_text(
        '# <https://example.org/decoy#game> a ga:Game ; rdfs:label "Decoy" .\n' + PUZZLE)
    assert games.discover(root)["puzzle"].label == "Tile Puzzle"


def test_a_profile_with_two_games_is_refused():
    root = games_copy()
    (root / "puzzle").mkdir()
    (root / "puzzle" / "profile.ttl").write_text(
        PUZZLE + '<https://example.org/puzzle#other> a ga:Game ; rdfs:label "Other" .\n')
    with pytest.raises(EngineError, match="exactly one ga:Game"):
        games.discover(root)


def test_the_games_root_comes_from_the_environment(monkeypatch):
    root = games_copy()
    (root / "puzzle").mkdir()
    (root / "puzzle" / "profile.ttl").write_text(PUZZLE)
    monkeypatch.setenv("ASSET_PASSPORT_GAMES", str(root))
    assert "puzzle" in games.discover()
    monkeypatch.delenv("ASSET_PASSPORT_GAMES")
    assert "puzzle" not in games.discover()


def test_an_unknown_game_is_an_error_not_a_verdict():
    with pytest.raises(ValueError, match="unknown game 'souls'"):
        judge_direct("craft", catalogue("craft")[0], "souls", scratch("t"))


# ------------------------------------------------------------------ the CLI


def cli(*args, env=None):
    p = subprocess.run([sys.executable, "-m", "passport", *args], cwd=ROOT, capture_output=True,
                       text=True, timeout=300, env={**os.environ, **(env or {})})
    lines = p.stdout.strip().splitlines()
    return p.returncode, json.loads(lines[-1]) if lines else None, p.stderr


@pytest.mark.parametrize("src,into,item,code,verdict", [
    ("battle", "craft", "super_potion", 0, "converted"),
    ("battle", "craft", "capture_orb", 1, "refused"),
    ("craft", "battle", "golden_apple", 0, "converted_with_loss"),
])
def test_cli_judge_exit_codes(src, into, item, code, verdict):
    rc, out, err = cli("judge", "--from", src, "--into", into, "--item", item)
    assert (rc, out["verdict"]) == (code, verdict), err


def test_cli_judge_reads_an_item_file():
    d = scratch("cli")
    f = d / "blade.json"
    f.write_text(json.dumps({"id": "big", "kind": "DiamondSword", "name": "x", "attack": 20, "material": "Diamond"}))
    rc, out, _ = cli("judge", "--from", "craft", "--into", "battle", "--item", str(f))
    assert rc == 1 and out["stage"] == "border"
    assert any("one turn" in m for m in out["refusals"])


def test_cli_errors_exit_2():
    rc, out, _ = cli("judge", "--from", "craft", "--into", "souls", "--item", "tnt")
    assert rc == 2 and "unknown game" in out["error"]
    rc, out, _ = cli("judge", "--from", "craft", "--into", "battle", "--item", "no_such_item")
    assert rc == 2 and "no item" in out["error"]


def test_cli_keys_writes_outside_the_repo_and_publishes():
    root = games_copy()
    keys = scratch("keys") / "k"
    rc, out, err = cli("keys", "--game", "craft", "--write", "--games", str(root),
                       env={"ASSET_PASSPORT_KEYS": str(keys)})
    assert rc == 0, err
    assert out["generated"] is True and out["published_in_profile"] is True
    assert out["private_key"].startswith(str(keys)) and os.path.exists(out["private_key"])
    assert games.discover(root)["craft"].export_key == out["public_key"]
    rc, again, _ = cli("keys", "--game", "craft", "--games", str(root), env={"ASSET_PASSPORT_KEYS": str(keys)})
    assert rc == 0 and again["generated"] is False and again["public_key"] == out["public_key"]


@needs_packs
def test_cli_export_then_admit():
    root = games_copy()
    keys = scratch("keys") / "k"
    env = {"ASSET_PASSPORT_KEYS": str(keys)}
    for g in ("craft", "battle"):
        rc, _, err = cli("keys", "--game", g, "--write", "--games", str(root), env=env)
        assert rc == 0, err
    d = scratch("cli")
    rc, ex, err = cli("export", "--from", "battle", "--item", "super_potion", "--out", str(d / "p.pack"),
                      "--games", str(root), env=env)
    assert rc == 0, err
    assert ex["signature"]["game"] == NS + "battle#game"
    rc, v, err = cli("admit", str(d / "p.pack"), "--into", "craft", "--games", str(root), env=env)
    assert (rc, v["verdict"], v["signature"]["verified"]) == (0, "converted", True), err
    rc, v, _ = cli("admit", str(d / "p.pack"), "--into", "craft", "--games", str(root))  # no keys needed to admit
    assert rc == 0
    rc, ex, _ = cli("export", "--from", "battle", "--item", "capture_orb", "--out", str(d / "o.pack"),
                    "--games", str(root), env=env)
    rc, v, _ = cli("admit", str(d / "o.pack"), "--into", "craft", "--games", str(root))
    assert (rc, v["verdict"], v["stage"]) == (1, "refused", "border")
    rc, ex, _ = cli("export", "--from", "battle", "--item", "super_potion", "--out", str(d / "u.pack"),
                    "--unsigned", "--games", str(root), env={"ASSET_PASSPORT_KEYS": str(scratch("nokeys"))})
    rc, v, _ = cli("admit", str(d / "u.pack"), "--into", "craft", "--games", str(root))
    assert (rc, v["verdict"], v["stage"]) == (1, "refused", "signature")


def test_cli_exit_codes_follow_the_verdict():
    """Admitted is 0, refused is 1, and a verdict that claims nothing is 2,
    the same as a failed run: a script must not read 'held' as 'refused'."""
    from passport.__main__ import exit_code
    assert [exit_code({"verdict": v}) for v in
            ("accepted", "converted", "converted_with_loss", "refused", "undetermined")] == [0, 0, 0, 1, 2]
