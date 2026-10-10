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
from passport.engine import (ROOT, ConfigError, Engine, EngineError, EngineTimeout, reply_timeout, run_deadline,
                             scratch)

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


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "inf", "nan", "1e10", "86401"])
def test_a_timeout_that_is_not_a_positive_number_is_refused(raw, monkeypatch):
    """1e10 passed this check once and then broke every engine start with a
    TypeError from selectors that did not name the variable."""
    monkeypatch.setenv("ASSET_PASSPORT_ENGINE_TIMEOUT", raw)
    with pytest.raises(ConfigError, match="ASSET_PASSPORT_ENGINE_TIMEOUT must be a positive number of seconds"):
        reply_timeout()


def test_a_timeout_of_a_day_is_accepted(monkeypatch):
    monkeypatch.setenv("ASSET_PASSPORT_ENGINE_TIMEOUT", "86400")
    assert reply_timeout() == 86400


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
    rc, out, err = _cli("judge", "--from", "craft", "--into", "battle", "--item", "blast_block",
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
    item = {"kind": "CrystalSword", "attack": 7, "material": "Crystal"}
    monkeypatch.setattr(api, "clean_item", lambda game, it: {"id": "x", "name": "x", **it})
    with pytest.raises(EngineTimeout):
        api.judge({"game": "craft", "target": "battle", "item": item})
    assert os.listdir(fresh) == [] and _all_stopped(pids)


# An MCP server that answers every request, slowly. A real engine behind a slow
# disk, or one that hangs only after the first ten seconds, looks like this.
SLOW_ENGINE = r'''#!/usr/bin/env python3
import json, sys, time
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    time.sleep(0.3)
    if m["method"] == "initialize":
        r = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "slow", "version": "0"}}
    elif m["method"] == "tools/list":
        r = {"tools": []}
    else:
        r = {"content": [{"type": "text", "text": "{}"}]}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}) + "\n")
    sys.stdout.flush()
'''

# The real engine behind a proxy that holds each reply for 0.3 s.
SLOW_PROXY = r'''#!/usr/bin/env python3
import os, subprocess, sys, threading, time
p = subprocess.Popen([os.environ["REAL_OO_BIN"], *sys.argv[1:]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     bufsize=0)
def up():
    for line in sys.stdin.buffer:
        p.stdin.write(line)
    p.stdin.close()
threading.Thread(target=up, daemon=True).start()
for line in p.stdout:
    if b'"id"' in line:
        time.sleep(0.3)
    sys.stdout.buffer.write(line)
    sys.stdout.buffer.flush()
'''


# An MCP server that answers the handshake, starts a checker of its own that
# hangs, and never answers again: what the real engine does when the oo-cert
# or oo-shacl it runs hangs.
PARENT_ENGINE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, time
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    if m["method"] == "initialize":
        r = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "parent", "version": "0"}}
    elif m["method"] == "tools/list":
        r = {"tools": []}
    else:
        child = subprocess.Popen(["sleep", "100000"])
        with open(os.environ["CHILD_PIDFILE"], "w") as f:
            f.write(str(child.pid))
        time.sleep(100000)
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}) + "\n")
    sys.stdout.flush()
'''

# An MCP server that answers the handshake and then never reads its input
# again, so a large enough message fills the pipe.
DEAF_ENGINE = r'''#!/usr/bin/env python3
import json, sys, time
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    if m["method"] == "initialize":
        r = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "deaf", "version": "0"}}
    else:
        r = {"tools": []}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}) + "\n")
    sys.stdout.flush()
    if m["method"] == "tools/list":
        time.sleep(100000)
'''


def _script(tmp_path, name, body) -> str:
    p = tmp_path / name
    p.write_text(body.replace("/usr/bin/env python3", sys.executable, 1))
    p.chmod(0o755)
    return str(p)


def _gone(pid: int, within: float = 3.0) -> bool:
    """The process is gone (killed and reaped by whoever adopted it)."""
    end = time.monotonic() + within
    while time.monotonic() < end:
        st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        if not st or st.startswith("Z"):
            return True
        time.sleep(0.05)
    return False


def test_a_slow_engine_is_stopped_at_the_runs_deadline_not_only_at_each_reply(tmp_path, monkeypatch):
    """Every reply takes 0.3 s, well under the 1 s limit on one reply, so a
    limit on each reply never fires and a run of many calls went on as long
    as it had calls (62.8 s for one live request behind a 2 s delay)."""
    binary = _script(tmp_path, "slow-engine", SLOW_ENGINE)
    monkeypatch.setenv("ASSET_PASSPORT_ENGINE_TIMEOUT", "1")
    t0 = time.monotonic()
    with run_deadline(2):
        with Engine(scratch("slow"), binary) as e:
            with pytest.raises(EngineTimeout) as err:
                for _ in range(100):
                    e.call("onto_clear")
    assert time.monotonic() - t0 < 4
    assert "the 2 s the whole run may take" in str(err.value) and "ASSET_PASSPORT_RUN_TIMEOUT" in str(err.value)
    assert err.value.timeout == 2


def test_without_a_run_deadline_the_same_slow_engine_finishes(tmp_path, monkeypatch):
    """The control: with no run deadline, the slow engine answers every call."""
    binary = _script(tmp_path, "slow-engine", SLOW_ENGINE)
    monkeypatch.setenv("ASSET_PASSPORT_ENGINE_TIMEOUT", "1")
    monkeypatch.delenv("ASSET_PASSPORT_RUN_TIMEOUT", raising=False)
    with run_deadline():
        with Engine(scratch("slow"), binary) as e:
            for _ in range(8):
                assert e.call("onto_clear") == {}


def test_the_live_api_holds_one_deadline_for_the_whole_request(tmp_path, monkeypatch):
    """api.judge starts several engines; ASSET_PASSPORT_RUN_TIMEOUT bounds them all."""
    from passport.engine import engine_binary
    monkeypatch.setenv("REAL_OO_BIN", engine_binary())
    binary = _script(tmp_path, "slow-proxy", SLOW_PROXY)
    monkeypatch.setenv("OO_BIN", binary)
    monkeypatch.setenv("ASSET_PASSPORT_ENGINE_TIMEOUT", "1")
    monkeypatch.setenv("ASSET_PASSPORT_RUN_TIMEOUT", "2")
    t0 = time.monotonic()
    with pytest.raises(EngineTimeout, match="ASSET_PASSPORT_RUN_TIMEOUT"):
        api.judge({"game": "craft", "target": "battle",
                   "item": {"id": "x", "name": "X", "kind": "CrystalSword", "attack": 7, "material": "Crystal"}})
    assert time.monotonic() - t0 < 4


def test_the_vercel_function_sets_a_run_deadline_under_its_own_limit():
    """vercel.json gives the function 30 s; the run must be stopped before that."""
    vercel = json.loads((ROOT / "vercel.json").read_text())
    limit = vercel["functions"]["api/index.py"]["maxDuration"]
    src = (ROOT / "api" / "index.py").read_text()
    import re
    run = float(re.search(r'"ASSET_PASSPORT_RUN_TIMEOUT", "([0-9.]+)"', src).group(1))
    reply = float(re.search(r'"ASSET_PASSPORT_ENGINE_TIMEOUT", "([0-9.]+)"', src).group(1))
    assert reply <= run < limit


def test_stopping_a_hung_engine_stops_the_checker_it_started(tmp_path, monkeypatch):
    """The engine was killed and the oo-cert it had started went on running,
    adopted by PID 1, one process leaked per hung request."""
    binary = _script(tmp_path, "parent-engine", PARENT_ENGINE)
    pidfile = tmp_path / "child"
    monkeypatch.setenv("CHILD_PIDFILE", str(pidfile))
    monkeypatch.setenv("ASSET_PASSPORT_ENGINE_TIMEOUT", "1")
    with Engine(scratch("parent"), binary) as e:
        with pytest.raises(EngineTimeout):
            e.call("onto_unpack")
    child = int(pidfile.read_text())
    assert _gone(child), f"the engine's child {child} is still running"


def test_a_write_to_an_engine_that_stopped_reading_has_a_deadline(tmp_path, monkeypatch):
    """A message larger than the pipe's buffer, to an engine that no longer
    reads: the write blocked for ever and the deadline never applied, because
    only reads were timed."""
    binary = _script(tmp_path, "deaf-engine", DEAF_ENGINE)
    monkeypatch.setenv("ASSET_PASSPORT_ENGINE_TIMEOUT", "1")
    big = tmp_path / "big.ttl"
    big.write_text("<urn:a> <urn:b> \"" + "x" * 400_000 + "\" .\n")
    t0 = time.monotonic()
    with Engine(scratch("deaf"), binary) as e:
        with pytest.raises(EngineTimeout, match="did not answer tools/call within 1 s"):
            e.load(big)
    assert time.monotonic() - t0 < 4


def test_a_checker_that_hangs_is_stopped_at_the_engine_deadline(monkeypatch):
    """run_oo_cert used a fixed 120 s whatever ASSET_PASSPORT_ENGINE_TIMEOUT said,
    so a hung checker held a live request past Vercel's 30 s."""
    monkeypatch.setenv("ASSET_PASSPORT_ENGINE_TIMEOUT", "1")
    t0 = time.monotonic()
    proof = judge.run_oo_cert(scratch("chk"), _checker("exec sleep 100000"))
    assert time.monotonic() - t0 < 4
    assert proof["status"] == "checker_failed"
    assert "did not finish within 1 s" in proof["detail"] and "ASSET_PASSPORT_ENGINE_TIMEOUT" in proof["detail"]


def test_a_checker_that_hangs_in_the_live_lane_gives_undetermined_quickly(monkeypatch):
    monkeypatch.setenv("ASSET_PASSPORT_ENGINE_TIMEOUT", "1")
    monkeypatch.setenv("OO_CERT", _checker("exec sleep 100000"))
    t0 = time.monotonic()
    v = api.judge({"game": "craft", "target": "battle",
                   "item": {"id": "x", "name": "X", "kind": "CrystalSword", "attack": 7, "material": "Crystal"}})
    assert time.monotonic() - t0 < 10
    assert (v["verdict"], v["stage"], v["proof"]["status"]) == ("undetermined", "unpack", "checker_failed")


# ------------------------------------------------------------------ a closure query that fails


@needs_packs
@pytest.mark.parametrize("fail", ["claimed", "derived", "both"])
def test_a_failed_closure_query_is_a_failed_run_not_a_refusal_or_a_pass(honest_sword, monkeypatch, fail):
    """The closure gate read a failed query as an empty answer: one failure
    refused an honest passport for claiming what 'does not follow', and two
    compared two empty sets and let the gate pass unchecked."""
    root, pack = honest_sword
    real = Engine.call
    seen = []

    def call(self, tool, **args):
        if tool == "onto_query" and "?p ?o WHERE" in args.get("query", ""):
            seen.append(1)
            n = len(seen)
            if fail == "both" or (fail == "claimed" and n == 1) or (fail == "derived" and n == 2):
                return {"error": "the store is busy"}
        return real(self, tool, **args)

    monkeypatch.setattr(Engine, "call", call)
    with pytest.raises(EngineError, match="the hub fact query failed"):
        judge.admit(pack, "battle", scratch("t"), root=root)


# ------------------------------------------------------------------ a checker that crashes


def _checker(body: str) -> str:
    d = scratch("chk")
    p = d / "oo-cert"
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(0o755)
    return str(p)


@pytest.fixture(scope="module")
def honest_sword():
    """A passport for Blockcraft's Crystal Sword, signed with a test key."""
    root, keys = signed_root()
    rec = judge.item_record("craft", "crystal_sword", root)
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
    ("exit 2", "checker_failed"),                       # nothing said about the certificate's files
    ("echo 'usage: oo-cert ASSERTED DERIVATIONS' >&2; exit 2", "checker_failed"),
    ("echo 'asserted.tsv line 1: expected three tab-separated terms' >&2; exit 2", "certificate_unreadable"),
    ("echo 'derivations.tsv line 10: expected rule, conclusion, premises' >&2; exit 2",
     "certificate_unreadable"),
    ("exit 1", "checker_failed"),                       # no verdict on stdout
    ("exit 0", "checker_failed"),                       # no verdict on stdout
    ("echo '{\"ok\":true}'; exit 1", "checker_failed"),  # a verdict and an exit code that disagree
    ("echo '{\"ok\":false,\"rule\":\"rdfs9\"}'; exit 1", "certificate_refused"),
    ("echo '{\"ok\":true,\"theorem\":\"OOCert.certificate_sound\"}'; exit 0", "certificate_accepted"),
])
def test_only_the_checkers_own_verdict_decides(body, status):
    assert judge.run_oo_cert(scratch("chk"), _checker(body))["status"] == status


# ------------------------------------------------------------------ a malformed certificate, signed


@pytest.fixture(scope="module")
def honest_orb():
    """A passport for Pocket Battlers' Capture Orb, signed with a test key,
    with the key, so a test can play the dishonest issuer."""
    root, keys = signed_root()
    rec = judge.item_record("battle", "capture_orb", root)
    pack = judge.export("battle", rec, scratch("t"), root=root, key=keys["battle"])["pack"]
    return root, keys["battle"], pack


def _files(p):
    return p["manifest"]["certificate"]["files"]


def _horn(p):
    f = _files(p)
    f["horn.tsv"] = f.pop("derivations.tsv")
    f["rules.tsv"] = "x\n"


MALFORMED = {
    "an extra certificate file": lambda p: _files(p).__setitem__("evil.tsv", "x"),
    "a derivation line that is not a step": lambda p: _files(p).__setitem__(
        "derivations.tsv", _files(p)["derivations.tsv"] + "\nnot\ta\tstep"),
    "no derivations.tsv": lambda p: _files(p).pop("derivations.tsv"),
    "an asserted.tsv that is not triples": lambda p: _files(p).__setitem__("asserted.tsv", "\x00garbage"),
    "a rule-table certificate in place of oo-cert's": _horn,
}


@needs_packs
@pytest.mark.parametrize("name", sorted(MALFORMED))
def test_a_signed_passport_with_a_malformed_certificate_is_refused_at_unpack(honest_orb, name):
    """The issuer, with its own key, adds a junk certificate file (or breaks
    one), re-digests and signs. Its Capture Orb would be refused at
    Blockcraft's border, and with the certificate broken it was reported
    undetermined (exit 2, 'this machine failed') instead. A malformed
    certificate is the sender's defect: refused at unpack, before the border."""
    from passport import forge, sign
    root, key, honest = honest_orb
    p = forge.read(honest)
    MALFORMED[name](p)
    forge.redigest(p)
    out = forge.write(p, scratch("mal") / "passport.pack")
    sign.sign_pack(out, judge._games.get("battle", root).iri, key)
    v = judge.admit(out, "craft", scratch("t"), root=root)
    assert (v["verdict"], v["stage"]) == ("refused", "unpack"), (v["headline"], v["refusals"], v["proof"])
    assert v["signature"]["verified"] is True
    assert v["proof"]["status"] == "certificate_unreadable"
    assert v["refusals"] and "certificate" in v["refusals"][0]["message"]


@needs_packs
def test_the_honest_orb_reaches_the_border_and_is_refused_there(honest_orb):
    """The control for the test above: unchanged, the same signed passport
    passes unpack and is refused by Blockcraft's border, not before it."""
    root, _, honest = honest_orb
    v = judge.admit(honest, "craft", scratch("t"), root=root)
    assert (v["verdict"], v["stage"]) == ("refused", "border")


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
