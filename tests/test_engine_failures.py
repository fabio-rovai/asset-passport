"""An engine that hangs, a Lean checker that crashes, and the directories a run
leaves behind. Each check here refuses something, and each was added after a
review found the failure it pins.

  - An engine that stops answering used to block the command line, the build
    and a serverless worker for ever (readline with no deadline). It is now
    stopped after $ASSET_PASSPORT_ENGINE_TIMEOUT seconds and the verdict is
    undetermined, never a refusal and never a hang.
  - A checker that crashed while onto_unpack ran it was reported as a refused
    (or unreadable) certificate, and the passport was refused. The checker is
    now run again here, and only a refusal it states in its own JSON verdict
    stays a refusal.
  - The bridge checker left a scratch directory behind on every run.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

import pytest
from _support import needs_packs, signed_root

from passport import api, judge
from passport.bridge import check as bridge_check
from passport.engine import ROOT, Engine, EngineError, EngineTimeout, reply_timeout, scratch

# An MCP server that answers the handshake and then never answers again. With
# HANG_AT_START set it never answers the handshake either. It writes its pid
# first, so a test can see that the process was stopped.
FAKE_ENGINE = r'''#!/usr/bin/env python3
import json, os, sys, time
pidfile = os.environ.get("FAKE_ENGINE_PIDFILE")
if pidfile:
    with open(pidfile, "a") as f:
        f.write(f"{os.getpid()}\n")
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    if m["method"] == "initialize" and not os.environ.get("HANG_AT_START"):
        r = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "fake", "version": "0"}}
    elif m["method"] == "tools/list" and not os.environ.get("HANG_AT_START"):
        r = {"tools": []}
    else:
        time.sleep(100000)
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}) + "\n")
    sys.stdout.flush()
'''


@pytest.fixture
def fake_engine(tmp_path, monkeypatch):
    p = tmp_path / "fake-engine"
    p.write_text(FAKE_ENGINE.replace("/usr/bin/env python3", sys.executable, 1))
    p.chmod(0o755)
    pids = tmp_path / "pids"
    monkeypatch.setenv("FAKE_ENGINE_PIDFILE", str(pids))
    monkeypatch.setenv("ASSET_PASSPORT_ENGINE_TIMEOUT", "1")
    return str(p), pids


def _all_stopped(pids) -> bool:
    for pid in (int(x) for x in pids.read_text().split()):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        return False
    return True


# ------------------------------------------------------------------ an engine that hangs


def test_an_engine_that_stops_answering_is_stopped_at_the_deadline(fake_engine):
    binary, pids = fake_engine
    t0 = time.monotonic()
    with Engine(scratch("hang"), binary) as e:
        with pytest.raises(EngineTimeout) as err:
            e.call("onto_clear")
    assert time.monotonic() - t0 < 15
    assert "did not answer tools/call within 1 s" in str(err.value)
    assert "ASSET_PASSPORT_ENGINE_TIMEOUT" in str(err.value)
    assert e.proc.poll() is not None and _all_stopped(pids)


def test_an_engine_that_never_finishes_starting_is_stopped(fake_engine, monkeypatch):
    binary, pids = fake_engine
    monkeypatch.setenv("HANG_AT_START", "1")
    with pytest.raises(EngineTimeout, match="did not answer initialize within 1 s"):
        Engine(scratch("hang"), binary)
    assert _all_stopped(pids)


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "inf", "nan"])
def test_a_timeout_that_is_not_a_positive_number_is_refused(raw, monkeypatch):
    monkeypatch.setenv("ASSET_PASSPORT_ENGINE_TIMEOUT", raw)
    with pytest.raises(EngineError, match="must be a positive number of seconds"):
        reply_timeout()


def test_the_default_deadline_is_sixty_seconds(monkeypatch):
    monkeypatch.delenv("ASSET_PASSPORT_ENGINE_TIMEOUT", raising=False)
    assert reply_timeout() == 60


def _cli(*args, env):
    code = "import sys; from passport.__main__ import main; sys.exit(main(sys.argv[1:]))"
    p = subprocess.run([sys.executable, "-c", code, *args], cwd=ROOT, capture_output=True, text=True,
                       timeout=120, env={**os.environ, **env})
    return p.returncode, json.loads(p.stdout.strip().splitlines()[-1]), p.stderr


def test_cli_an_engine_that_stops_answering_is_undetermined_with_exit_2(fake_engine):
    binary, pids = fake_engine
    rc, out, err = _cli("judge", "--from", "craft", "--into", "battle", "--item", "tnt",
                        env={"OO_BIN": binary})
    assert rc == 2, err
    assert out["verdict"] == "undetermined" and out["type"] == "EngineTimeout", out
    assert "did not answer" in out["error"] and "within 1 s" in out["error"]
    assert _all_stopped(pids)


def test_the_live_api_turns_a_hung_engine_into_an_undetermined_error(fake_engine, monkeypatch):
    """api.judge raises EngineTimeout; the HTTP layer (tests/test_cors.py)
    answers 504 with the verdict undetermined. Nothing is left in the
    temporary directory either way."""
    binary, pids = fake_engine
    monkeypatch.setenv("OO_BIN", binary)
    fresh = scratch("empty")
    monkeypatch.setattr(tempfile, "tempdir", str(fresh))
    item = {"kind": "DiamondSword", "attack": 7, "material": "Diamond"}
    monkeypatch.setattr(api, "clean_item", lambda game, it: {"id": "x", "name": "x", **it})
    with pytest.raises(EngineTimeout):
        api.judge({"game": "craft", "target": "battle", "item": item})
    assert os.listdir(fresh) == [] and _all_stopped(pids)


# ------------------------------------------------------------------ a checker that crashes


def _checker(body: str) -> str:
    d = scratch("chk")
    p = d / "oo-cert"
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(0o755)
    return str(p)


@pytest.fixture(scope="module")
def honest_sword():
    """A passport for Blockcraft's Diamond Sword, signed with a test key."""
    root, keys = signed_root()
    rec = judge.item_record("craft", "diamond_sword", root)
    return root, judge.export("craft", rec, scratch("t"), root=root, key=keys["craft"])["pack"]


@needs_packs
@pytest.mark.parametrize("body,engine_says", [
    ("kill -SEGV $$", "certificate_unreadable"),  # a crash
    ("exit 1", "certificate_refused"),            # exit 1 with no verdict on stdout
])
def test_a_checker_that_crashes_while_admitting_is_undetermined_not_refused(honest_sword, monkeypatch,
                                                                             body, engine_says):
    """onto_unpack ran $OO_CERT, which crashed, and reported the certificate
    unreadable or refused; the passport was refused at unpack. Nothing was
    checked, so nothing may be claimed: the checker is run again over the
    certificate the engine kept, and its run has no verdict either."""
    root, pack = honest_sword
    monkeypatch.setenv("OO_CERT", _checker(body))
    v = judge.admit(pack, "battle", scratch("t"), root=root)
    assert (v["verdict"], v["stage"]) == ("undetermined", "unpack"), v
    assert v["proof"]["status"] == "checker_failed" and v["proof"]["engine_status"] == engine_says
    assert v["refusals"] == [] and "did not run to a verdict" in v["headline"]
    assert any(c["tool"] == "oo-cert" and "run again here" in c["args"]["why"] for c in v["transcript"])


@needs_packs
def test_with_the_real_checker_the_same_passport_is_admitted(honest_sword):
    """The control for the test above: the same passport, this machine's real oo-cert."""
    root, pack = honest_sword
    v = judge.admit(pack, "battle", scratch("t"), root=root)
    assert (v["verdict"], v["proof"]["status"]) == ("converted", "certificate_accepted")


@pytest.mark.parametrize("body,status", [
    ("kill -SEGV $$", "checker_failed"),
    ("exit 2", "checker_failed"),
    ("exit 1", "checker_failed"),                       # no verdict on stdout
    ("exit 0", "checker_failed"),                       # no verdict on stdout
    ("echo '{\"ok\":true}'; exit 1", "checker_failed"),  # a verdict and an exit code that disagree
    ("echo '{\"ok\":false,\"rule\":\"rdfs9\"}'; exit 1", "certificate_refused"),
    ("echo '{\"ok\":true,\"theorem\":\"OOCert.certificate_sound\"}'; exit 0", "certificate_accepted"),
])
def test_only_the_checkers_own_verdict_decides(body, status):
    assert judge.run_oo_cert(scratch("chk"), _checker(body))["status"] == status


# ------------------------------------------------------------------ directories left behind


def test_the_bridge_checker_leaves_no_directory(monkeypatch):
    fresh = scratch("empty")
    monkeypatch.setattr(tempfile, "tempdir", str(fresh))
    assert bridge_check(ROOT / "examples" / "bridges" / "um-skycraft.ttl")["verdict"]
    assert os.listdir(fresh) == []


def test_the_bridge_checker_leaves_no_directory_when_the_engine_fails(fake_engine, monkeypatch):
    binary, _ = fake_engine
    fresh = scratch("empty")
    monkeypatch.setattr(tempfile, "tempdir", str(fresh))
    with pytest.raises(EngineError):
        bridge_check(ROOT / "examples" / "bridges" / "um-skycraft.ttl", binary)
    assert os.listdir(fresh) == []
