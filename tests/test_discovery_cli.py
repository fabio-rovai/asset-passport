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


# ------------------------------------------------------------------ a second review: the CLI


def _item_file(rec):
    f = scratch("cli") / "item.json"
    f.write_text(json.dumps(rec))
    return str(f)


EMBERFOX = {"id": "fox", "kind": "Emberfox", "name": "Fox", "hp": 50, "movePower": 40,
            "moveName": "Ember", "type": "Fire"}


@pytest.mark.parametrize("change,why", [
    ({"kind": "NoSuchKind"}, "has no kind 'NoSuchKind'"),
    ({"hp": -5}, "hp must be a number from 0 to 100,000"),
    ({"hp": "abc"}, "hp must be a number from 0 to 100,000"),
    ({"extra": 1}, "items have no field 'extra'"),
])
def test_cli_an_item_file_gets_the_same_check_as_the_live_api(change, why):
    """judge used to admit an unknown kind 'as is', convert hp -5 to -1, pass
    an unknown field through, and refuse hp 'abc' for a false reason. The API
    returned 400 for each. Both front doors run one check now, and the CLI
    exits 2. The control: the same item unchanged is judged."""
    rc, out, err = cli("judge", "--from", "battle", "--into", "craft", "--item", _item_file(EMBERFOX))
    assert rc == 0, err
    rc, out, _ = cli("judge", "--from", "battle", "--into", "craft", "--item", _item_file({**EMBERFOX, **change}))
    assert rc == 2 and why in out["error"], out
    rc, out, _ = cli("export", "--from", "battle", "--item", _item_file({**EMBERFOX, **change}),
                     "--unsigned", "--out", str(scratch("cli") / "x.pack"))
    assert rc == 2 and why in out["error"], out
    from passport import api
    with pytest.raises(api.BadRequest, match=why.replace("(", r"\(")):
        api.clean_item("battle", {**EMBERFOX, **change})


def test_cli_an_error_message_keeps_its_closing_quote():
    rc, out, _ = cli("judge", "--from", "craft", "--into", "battle", "--item", "no_such_item")
    assert rc == 2 and out["error"] == "craft has no item 'no_such_item'"


def test_cli_no_lean_checker_exits_2_in_the_direct_lane():
    pre = "import passport.judge as j; j.find_oo_cert = lambda explicit=None: None; "
    p = subprocess.run([sys.executable, "-c", f"import sys; {pre}from passport.__main__ import main; "
                        "sys.exit(main(sys.argv[1:]))", "judge", "--from", "battle", "--into", "craft",
                        "--item", "super_potion"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    out = json.loads(p.stdout.strip().splitlines()[-1])
    assert (p.returncode, out["verdict"], out["stage"]) == (2, "undetermined", "unpack"), out
    assert out["proof"] == "checker_absent_nothing_was_checked" and out["refusals"] == []


@needs_packs
def test_cli_no_lean_checker_exits_2_in_the_passport_lane():
    pack = ROOT / "site" / "passports" / "battle-super_potion.pack"
    rc, out, _ = cli("admit", str(pack), "--into", "craft")
    assert rc == 0, out  # the control: with the checker, admitted
    rc, out, _ = cli("admit", str(pack), "--into", "craft", env={"OO_CERT": "/nonexistent/oo-cert"})
    assert (rc, out["verdict"], out["stage"], out["proof"]) == \
        (2, "undetermined", "unpack", "checker_absent_nothing_was_checked"), out


def _keys_env():
    return {"ASSET_PASSPORT_KEYS": str(scratch("keys") / "k")}


def test_cli_keys_force_without_write_is_refused_and_keeps_the_key():
    """--force alone used to overwrite the only key matching the published one."""
    root, env = games_copy(), _keys_env()
    rc, first, err = cli("keys", "--game", "battle", "--write", "--games", str(root), env=env)
    assert rc == 0, err
    before = open(first["private_key"], "rb").read()
    rc, out, _ = cli("keys", "--game", "battle", "--force", "--games", str(root), env=env)
    assert rc == 2 and "--force together with --write" in out["error"]
    assert open(first["private_key"], "rb").read() == before
    rc, second, err = cli("keys", "--game", "battle", "--force", "--write", "--games", str(root), env=env)
    assert rc == 0, err
    assert second["generated"] and second["published_in_profile"] and second["public_key"] != first["public_key"]
    assert open(second["replaced_key_moved_to"], "rb").read() == before
    assert games.discover(root)["battle"].export_key == second["public_key"]


@needs_packs
def test_cli_export_refuses_a_key_that_is_not_the_published_one():
    """export used to sign with any key and exit 0; every receiver refused the
    pack at the signature gate."""
    from passport import sign
    root, env = games_copy(), _keys_env()
    rc, _, err = cli("keys", "--game", "battle", "--write", "--games", str(root), env=env)
    assert rc == 0, err
    other = scratch("keys") / "other.pem"
    k = sign.generate()
    other.write_bytes(k.private_bytes(sign.serialization.Encoding.PEM, sign.serialization.PrivateFormat.PKCS8,
                                      sign.serialization.NoEncryption()))
    d = scratch("cli")
    rc, out, _ = cli("export", "--from", "battle", "--item", "super_potion", "--out", str(d / "a.pack"),
                     "--key", str(other), "--games", str(root), env=env)
    assert rc == 2 and "not the export key" in out["error"] and not (d / "a.pack").exists()
    rc, out, err = cli("export", "--from", "battle", "--item", "super_potion", "--out", str(d / "b.pack"),
                       "--key", str(other), "--sign-anyway", "--games", str(root), env=env)
    assert rc == 0, err
    rc, v, _ = cli("admit", str(d / "b.pack"), "--into", "craft", "--games", str(root))
    assert (rc, v["stage"]) == (1, "signature")


def test_cli_keys_on_a_profile_with_a_prefixed_key_line_changes_nothing():
    """A profile may state its key as battle:game ga:exportKey "..." . The
    rewrite only replaces the full-IRI line, so it used to append a second key,
    fail, and leave the whole games root unreadable, with a new private key
    written. Now it refuses before writing anything."""
    from passport import sign
    root, env = games_copy(), _keys_env()
    p = root / "battle" / "profile.ttl"
    iri = games.get("battle", root).iri
    lines = [l for l in p.read_text().split("\n") if not l.startswith(f"<{iri}> <")]
    p.write_text("\n".join(lines) + f'\nbattle:game ga:exportKey "{sign.public_b64(sign.generate())}" .\n')
    before = p.read_bytes()
    assert games.discover(root)["battle"].export_key  # the prefixed form is valid and read
    rc, out, _ = cli("keys", "--game", "battle", "--write", "--games", str(root), env=env)
    assert rc == 2 and "does not rewrite" in out["error"]
    assert p.read_bytes() == before
    assert not os.path.exists(env["ASSET_PASSPORT_KEYS"]) or not os.listdir(env["ASSET_PASSPORT_KEYS"])
    rc, out, _ = cli("judge", "--games", str(root), "--from", "battle", "--into", "craft", "--item", "super_potion")
    assert rc == 0, out


def test_cli_runs_leave_no_temporary_directories():
    """Every CLI process used to leave its discovery store behind, and admit a
    store per source game as well."""
    tmp = scratch("clitmp")
    pack = ROOT / "site" / "passports" / "battle-super_potion.pack"
    for args in (("judge", "--from", "battle", "--into", "craft", "--item", "capture_orb"),
                 ("admit", str(pack), "--into", "craft")):
        cli(*args, env={"TMPDIR": str(tmp)})
    assert sorted(os.listdir(tmp)) == []


# ------------------------------------------------------------------ one game into itself


@needs_packs
def test_cli_admit_refuses_a_passport_into_the_game_that_issued_it():
    """admit --into battle on a Pocket Battlers passport judged the item at
    Pocket Battlers' own border as if it were foreign, and gave a verdict."""
    pack = str(ROOT / "site" / "passports" / "battle-super_potion.pack")
    rc, out, _ = cli("admit", pack, "--into", "battle")
    assert rc == 2 and "issued by Pocket Battlers, so --into must name another game" in out["error"], out
    rc, out, _ = cli("admit", pack, "--into", "craft")  # the control
    assert rc == 0 and out["verdict"] == "converted", out


def test_cli_judge_refuses_one_game_twice():
    rc, out, _ = cli("judge", "--from", "craft", "--into", "craft", "--item", "tnt")
    assert rc == 2 and "two different games" in out["error"], out
