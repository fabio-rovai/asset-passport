"""The live forge's HTTP layer, checked over real HTTP against BOTH servers.

The GitHub Pages copy of the page calls the API on another origin, and the API
that answers it in production is api/index.py on Vercel, not local.py. Every
test here therefore runs twice: once against local.Handler and once against the
Vercel handler, addressed the way vercel.json rewrites it (/api/index?p=judge).
The tests show the allow-origin header is given to the named origin AND
withheld from any other, and that malformed requests are refused as 400s.
"""

import importlib.util
import json
import shutil
import socket
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import local
import passport.server
from passport import api
from passport.cors import ALLOWED_ORIGINS, cors_headers
from passport.present import scrub

ROOT = Path(__file__).resolve().parent.parent
PAGES = "https://fabio-rovai.github.io"


def _vercel_module():
    spec = importlib.util.spec_from_file_location("vercel_index", ROOT / "api" / "index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _vercel_handler():
    return _vercel_module().handler


SERVERS = {
    "local": (lambda: local.Handler, "/api/{}"),
    "vercel": (_vercel_handler, "/api/index?p={}"),
}


@pytest.fixture(scope="module", params=sorted(SERVERS))
def server(request):
    make, route = SERVERS[request.param]
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield lambda name: base + route.format(name)
    srv.shutdown()
    srv.server_close()


def _call(url, method="GET", origin=None, body=None, headers=None):
    h = dict(headers or {})
    if origin:
        h["Origin"] = origin
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _raw(url, head: bytes, body: bytes = b"", timeout=10) -> bytes:
    """Send a hand-written request, so the headers can be ones urllib refuses to send."""
    host, port = url.split("//")[1].split("/")[0].split(":")
    path = "/" + url.split("//")[1].split("/", 1)[1]
    with socket.create_connection((host, int(port)), timeout=timeout) as s:
        s.sendall(b"POST " + path.encode() + b" HTTP/1.1\r\nHost: x\r\n" + head + b"\r\n" + body)
        out = b""
        while True:
            try:
                chunk = s.recv(65_536)
            except socket.timeout:
                return out + b"<<TIMEOUT>>"
            if not chunk:
                return out
            out += chunk
            if b"\r\n\r\n" in out:
                hdr, _, rest = out.partition(b"\r\n\r\n")
                for line in hdr.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        if len(rest) >= int(line.split(b":")[1]):
                            return out


def _judge_body(**item):
    return json.dumps({"game": "craft", "target": "battle", "item": item}).encode()


JSON = {"content-type": "application/json"}


def test_named_origins_only():
    assert PAGES in ALLOWED_ORIGINS
    assert dict(cors_headers(PAGES))["access-control-allow-origin"] == PAGES
    for stranger in ("https://evil.example", "https://fabio-rovai.github.io.evil.example",
                     "https://fabio-rovai.github.io/", "http://fabio-rovai.github.io", "null", None, ""):
        assert "access-control-allow-origin" not in dict(cors_headers(stranger))


def test_preflight_from_pages_is_allowed(server):
    code, headers, _ = _call(server("judge"), "OPTIONS", PAGES,
                             headers={"Access-Control-Request-Method": "POST",
                                      "Access-Control-Request-Headers": "content-type"})
    assert code == 204
    assert headers["access-control-allow-origin"] == PAGES
    assert "POST" in headers["access-control-allow-methods"]
    assert "content-type" in headers["access-control-allow-headers"]


def test_preflight_from_stranger_is_refused(server):
    code, headers, _ = _call(server("judge"), "OPTIONS", "https://evil.example",
                             headers={"Access-Control-Request-Method": "POST"})
    assert code == 204
    assert headers.get("access-control-allow-origin") is None


def test_bad_field_is_400_with_cors(server):
    body = _judge_body(kind="CrystalSword", name="Sword", colour=3)
    code, headers, raw = _call(server("judge"), "POST", PAGES, body, JSON)
    assert code == 400, raw
    assert headers["access-control-allow-origin"] == PAGES
    assert "no field" in json.loads(raw)["error"]


def test_bad_game_names_the_real_keys(server):
    body = json.dumps({"game": "x", "target": "battle", "item": {"kind": "CrystalSword"}}).encode()
    code, _, raw = _call(server("judge"), "POST", PAGES, body, JSON)
    assert code == 400
    msg = json.loads(raw)["error"]
    assert "battle" in msg and "craft" in msg, msg
    assert "blocky" not in msg and "souls" not in msg, msg


def test_oversized_request_is_400(server):
    """The client must READ the 400, not get a connection reset."""
    body = b"{" + b" " * 20_001 + b"}"
    code, _, raw = _call(server("judge"), "POST", PAGES, body, JSON)
    assert code == 400
    assert json.loads(raw)["error"] == "request too large"


@pytest.mark.parametrize("length", [b"abc", b"-1", b"+5", b"1e3"])
def test_malformed_content_length_is_400(server, length):
    """A length that is not a plain count of bytes was a 502 ('abc') or a read
    that hung until the client hung up (-1)."""
    out = _raw(server("judge"), b"Content-Length: " + length + b"\r\n", b"{}")
    assert b"<<TIMEOUT>>" not in out, out
    assert out.startswith(b"HTTP/1.0 400") or out.startswith(b"HTTP/1.1 400"), out
    assert b"content-length must be a whole number of bytes" in out


def test_body_that_is_not_json_is_400(server):
    for body in (b"{not json", b"\xff\xfe"):
        code, _, raw = _call(server("judge"), "POST", PAGES, body, JSON)
        assert code == 400, raw
        assert json.loads(raw)["error"] == "the request body is not JSON"


def test_unknown_route_is_404(server):
    code, _, _ = _call(server("nothing"), "POST", PAGES, b"{}", JSON)
    assert code == 404


def test_engine_info_carries_cors(server):
    code, headers, raw = _call(server("engine"), "GET", PAGES)
    assert code == 200
    assert headers["access-control-allow-origin"] == PAGES
    assert json.loads(raw)["binary_sha256"]


@pytest.mark.parametrize("attack,verdict,damage", [(12, "converted", 60), (20, "refused", 100)])
def test_cross_origin_judge(server, attack, verdict, damage):
    body = _judge_body(kind="CrystalSword", name="Crystal Sword", attack=attack, material="Crystal")
    code, headers, raw = _call(server("judge"), "POST", PAGES, body, JSON)
    assert code == 200, raw
    assert headers["access-control-allow-origin"] == PAGES
    v = json.loads(raw)
    assert v["verdict"] == verdict, v["refusals"]
    assert v["conversion"]["damageInTarget"] == damage


# ------------------------------------------------------------------ site/config.js

NODE = shutil.which("node")
HARNESS = """
const src = require("fs").readFileSync(process.argv[1], "utf8");
for (const host of process.argv.slice(2)) {
  const window = {}, location = { hostname: host };
  new Function("window", "location", src)(window, location);
  console.log(host + " " + JSON.stringify(window.ASSET_PASSPORT_API_BASE));
}
"""


def _config_bases(tmp_path, api):
    src = (ROOT / "site" / "config.js").read_text()
    if api is not None:
        assert src.count('const VERCEL_API = "') == 1
        start = src.index('const VERCEL_API = "') + len('const VERCEL_API = "')
        src = src[:start] + api + src[src.index('"', start):]
    path = tmp_path / "config.js"
    path.write_text(src)
    hosts = ["fabio-rovai.github.io", "evilgithub.io", "someone-else.github.io",
             "fabio-rovai.github.io.evil.example", "localhost", "127.0.0.1"]
    out = subprocess.run([NODE, "-e", HARNESS, str(path), *hosts],
                         capture_output=True, text=True, check=True).stdout
    return dict(line.split(" ", 1) for line in out.strip().splitlines())


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_config_points_only_the_published_page_at_the_api(tmp_path):
    bases = _config_bases(tmp_path, "https://api.example")
    assert bases["fabio-rovai.github.io"] == '"https://api.example/"'
    for other in ("evilgithub.io", "someone-else.github.io", "fabio-rovai.github.io.evil.example",
                  "localhost", "127.0.0.1"):
        assert bases[other] == '""', (other, bases[other])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_config_as_committed(tmp_path):
    """The committed VERCEL_API is either empty (forge off on Pages) or an
    https URL with no trailing slash, and only the published page uses it."""
    src = (ROOT / "site" / "config.js").read_text()
    start = src.index('const VERCEL_API = "') + len('const VERCEL_API = "')
    api = src[start:src.index('"', start)]
    assert api == "" or (api.startswith("https://") and not api.endswith("/")), api
    bases = _config_bases(tmp_path, None)
    assert bases["fabio-rovai.github.io"] == json.dumps(api + "/" if api else "")
    assert bases["localhost"] == '""'


# ------------------------------------------------------------------ client mistakes are 400s


def _post(server, item, game="craft", target="battle", headers=JSON):
    body = json.dumps({"game": game, "target": target, "item": item}).encode()
    code, hdrs, raw = _call(server("judge"), "POST", PAGES, body, headers)
    return code, hdrs, json.loads(raw) if raw else None


@pytest.mark.parametrize("kind", [["CrystalSword"], {"a": 1}, 7, None])
def test_kind_that_is_not_a_string_is_400(server, kind):
    """A list or dict kind raised TypeError ('unhashable type') inside the
    set lookup, and the client got 502 'the engine run failed'."""
    code, _, v = _post(server, {"kind": kind})
    assert code == 400, v
    assert "has no kind" in v["error"]


@pytest.mark.parametrize("name", ["\ud800", "Sword\u0000", "\u202eevil", ["Sword"]])
def test_name_that_is_not_printable_text_is_400(server, name):
    """A lone surrogate passed the 40-character cut, the engine's JSON reader
    refused item.json, and the 502 carried the scratch path."""
    code, _, v = _post(server, {"kind": "CrystalSword", "name": name, "attack": 4, "material": "Crystal"})
    assert code == 400, v
    assert v["error"].startswith("name must"), v
    assert "/" not in v["error"]


@pytest.mark.parametrize("item_id", ["game", "attack", "material", "name"])
def test_id_that_names_a_profile_term_is_400(server, item_id):
    """The item IRI is the base IRI plus the id, so id 'game' made the item the
    game node itself, typed as a weapon, and the verdict was 'converted'."""
    code, _, v = _post(server, {"id": item_id, "kind": "CrystalSword", "attack": 12, "material": "Crystal"})
    assert code == 400, v
    assert "own rules" in v["error"]


def test_type_the_typed_game_does_not_place_is_400(server):
    """Pocket Battlers says every creature has an elemental type, and places
    four. An unplaced type was dropped at the border with no loss named, so
    'Plasma' got a cleaner verdict ('converted') than 'Fire' did."""
    item = {"id": "emberfox", "kind": "Emberfox", "hp": 100, "movePower": 45, "moveName": "Cinder Puff"}
    code, _, v = _post(server, {**item, "type": "Plasma"}, "battle", "craft")
    assert code == 400, v
    assert "'Plasma'" in v["error"] and "Fire" in v["error"]
    code, _, v = _post(server, {**item, "type": "Fire"}, "battle", "craft")
    assert code == 200, v
    assert v["verdict"] == "converted_with_loss" and v["losses"], v


def test_unplaced_material_of_an_untyped_game_still_reaches_the_border(server):
    """Blockcraft has no elemental types and leaves gold unplaced on purpose;
    the API passes it on and the engine refuses it at the border, by name."""
    code, _, v = _post(server, {"kind": "CrystalSword", "name": "Gold Sword", "attack": 4, "material": "Gold"})
    assert code == 200, v
    assert v["verdict"] == "refused" and v["stage"] == "border", v


def test_vocabulary_comes_from_the_profile():
    craft, battle = api.vocabulary("craft"), api.vocabulary("battle")
    assert battle["typed"] and battle["placed"]["type"] == ["Fire", "Grass", "Rock", "Water"]
    assert not craft["typed"] and craft["placed"]["material"] == ["Crystal", "Iron", "Stone", "Wood"]
    assert craft["base"] + "game" in craft["terms"]


# ------------------------------------------------------------------ engine failures


def test_engine_failure_is_a_generic_502(server, monkeypatch):
    """The 502 used to repeat the exception, scratch path and all."""
    import tempfile
    leak = f"{tempfile.gettempdir()}/asset-passport-live-abc/direct/item.json"

    def boom(body):
        raise RuntimeError(f"ingest refused the item: Failed to parse {leak}")

    monkeypatch.setattr(passport.server, "judge", boom)
    code, hdrs, raw = _call(server("judge"), "POST", PAGES, _judge_body(kind="CrystalSword"), JSON)
    assert code == 502, raw
    assert hdrs["access-control-allow-origin"] == PAGES
    err = json.loads(raw)["error"]
    assert err.startswith("the engine run failed")
    assert "asset-passport-live" not in err and tempfile.gettempdir() not in err and "/" not in err


def test_an_engine_that_stops_answering_is_a_504_that_claims_nothing(server, monkeypatch, tmp_path):
    """The forge used to wait for ever on a hung engine (and Vercel cut it off
    with no JSON at all). The engine is now stopped at the deadline and the
    client is told so, with no machine path in the message."""
    import sys
    from test_engine_failures import FAKE_ENGINE
    fake = tmp_path / "fake-engine"
    fake.write_text(FAKE_ENGINE.replace("/usr/bin/env python3", sys.executable, 1))
    fake.chmod(0o755)
    monkeypatch.setenv("OO_BIN", str(fake))
    monkeypatch.setenv("ASSET_PASSPORT_ENGINE_TIMEOUT", "1")
    body = _judge_body(kind="CrystalSword", attack=7, material="Crystal")
    code, hdrs, raw = _call(server("judge"), "POST", PAGES, body, JSON)
    assert code == 504, raw
    assert hdrs["access-control-allow-origin"] == PAGES
    out = json.loads(raw)
    assert out == {"verdict": "undetermined",
                   "error": "The engine did not answer within 1 s, so it was stopped and nothing is claimed."}


def test_the_vercel_function_stops_a_hung_engine_before_its_own_time_limit(monkeypatch):
    """The function may run for maxDuration seconds (vercel.json); the engine's
    deadline must fire first, or the 504 JSON never reaches the client."""
    from passport.engine import reply_timeout
    monkeypatch.delenv("ASSET_PASSPORT_ENGINE_TIMEOUT", raising=False)
    _vercel_module()
    limit = json.loads((ROOT / "vercel.json").read_text())["functions"]["api/index.py"]["maxDuration"]
    assert reply_timeout() < limit


def test_an_engine_error_is_a_502_that_claims_nothing(server, monkeypatch):
    from passport.engine import EngineError

    def boom(body):
        raise EngineError("ingest refused the item: /private/var/folders/x/asset-passport-live-1/item.json")

    monkeypatch.setattr(passport.server, "judge", boom)
    code, _, raw = _call(server("judge"), "POST", PAGES, _judge_body(kind="CrystalSword"), JSON)
    out = json.loads(raw)
    assert code == 502 and out["verdict"] == "undetermined", raw
    assert out["error"].startswith("The engine run failed, so nothing is claimed") and "/" not in out["error"]


# ------------------------------------------------------------------ content type and length


@pytest.mark.parametrize("ctype", ["text/plain;charset=UTF-8", "application/x-www-form-urlencoded",
                                   "multipart/form-data; boundary=x", None])
def test_judge_needs_application_json(server, monkeypatch, ctype):
    """A text/plain POST is a simple request: a stranger's page could make its
    visitors' browsers run the engine with no preflight. It must not reach judge."""
    calls = []
    monkeypatch.setattr(passport.server, "judge", lambda body: calls.append(body) or {})
    headers = {"content-type": ctype} if ctype else {}
    code, _, raw = _call(server("judge"), "POST", "https://evil.example",
                         _judge_body(kind="CrystalSword", attack=12, material="Crystal"), headers)
    assert code == 415, raw
    assert calls == []


def test_json_with_charset_is_accepted(server, monkeypatch):
    monkeypatch.setattr(passport.server, "judge", lambda body: {"seen": body["game"]})
    code, _, raw = _call(server("judge"), "POST", PAGES, _judge_body(kind="CrystalSword"),
                         {"content-type": "Application/JSON; charset=utf-8"})
    assert code == 200 and json.loads(raw) == {"seen": "craft"}, raw


def test_chunked_body_is_411_not_a_misleading_400(server):
    """A chunked body has no content-length; it was read as zero bytes and the
    client was told 'game and target must be two different games'."""
    body = _judge_body(kind="CrystalSword", attack=12, material="Crystal")
    chunked = hex(len(body))[2:].encode() + b"\r\n" + body + b"\r\n0\r\n\r\n"
    out = _raw(server("judge"), b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n", chunked)
    assert b"<<TIMEOUT>>" not in out, out
    assert out.split(b"\r\n")[0].split(b" ")[1] == b"411", out
    assert b"content-length" in out and b"two different games" not in out


def test_missing_content_length_is_411(server):
    out = _raw(server("judge"), b"Content-Type: application/json\r\n")
    assert out.split(b"\r\n")[0].split(b" ")[1] == b"411", out


# ------------------------------------------------------------------ other methods


def test_head_engine_is_200_json_without_body(server):
    code, hdrs, raw = _call(server("engine"), "HEAD", PAGES)
    assert code == 200
    assert hdrs["content-type"] == "application/json"
    assert hdrs["access-control-allow-origin"] == PAGES
    assert int(hdrs["content-length"]) > 0 and raw == b""


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("route", ["judge", "nothing"])
def test_get_and_head_on_another_api_route_are_a_json_404(server, method, route):
    """Vercel answered these with a JSON 404 carrying the CORS headers; local.py
    handed them to the static file server, which sent an HTML page without
    them, so the two servers disagreed on the same request."""
    code, hdrs, raw = _call(server(route), method, PAGES)
    assert code == 404, raw
    assert hdrs["content-type"] == "application/json"
    assert hdrs["access-control-allow-origin"] == PAGES
    assert int(hdrs["content-length"]) > 0
    if method == "HEAD":
        assert raw == b""
    else:
        assert json.loads(raw) == {"error": "no such route"}


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
def test_other_methods_are_json_405(server, method):
    code, hdrs, raw = _call(server("judge"), method, PAGES, b"{}", JSON)
    assert code == 405, raw
    assert "POST" in hdrs["allow"] and hdrs["content-type"] == "application/json"
    assert "not allowed" in json.loads(raw)["error"]


# ------------------------------------------------------------------ engine info and paths


def test_engine_info_hashes_each_binary_once(tmp_path, monkeypatch):
    """GET /api/engine is anonymous and used to hash three binaries per call."""
    import hashlib
    real, hashed = hashlib.sha256, []
    monkeypatch.setattr(hashlib, "sha256", lambda *a: hashed.append(1) or real(*a))
    api._sha256_of.cache_clear()
    first = api.engine_info()
    assert len(hashed) >= 2, first  # the engine and its checkers exist here, so they were hashed
    hashed.clear()
    assert api.engine_info() == first
    assert hashed == []  # the second call hashed nothing
    f = tmp_path / "bin"
    f.write_bytes(b"one")
    a = api._sha256(str(f))
    f.write_bytes(b"other")  # a new size, so a new cache key: a replaced binary is hashed again
    assert api._sha256(str(f)) == real(b"other").hexdigest() != a


def test_bundled_binaries_are_not_scrubbed_as_a_run():
    """The checker lived under /tmp/asset-passport-bin, which scrub() rewrites
    to '<run>', so the transcript said the checker was a per-run file."""
    run_bin = _vercel_module().RUN_BIN
    shown = scrub({"checker": str(run_bin / "oo-shacl")})["checker"]
    assert "<run>" not in shown and shown.endswith("/oo-shacl"), shown
