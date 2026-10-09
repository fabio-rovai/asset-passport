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
from passport.cors import ALLOWED_ORIGINS, cors_headers

ROOT = Path(__file__).resolve().parent.parent
PAGES = "https://fabio-rovai.github.io"


def _vercel_handler():
    spec = importlib.util.spec_from_file_location("vercel_index", ROOT / "api" / "index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.handler


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
    body = _judge_body(kind="DiamondSword", name="Sword", colour=3)
    code, headers, raw = _call(server("judge"), "POST", PAGES, body, JSON)
    assert code == 400, raw
    assert headers["access-control-allow-origin"] == PAGES
    assert "no field" in json.loads(raw)["error"]


def test_bad_game_names_the_real_keys(server):
    body = json.dumps({"game": "x", "target": "battle", "item": {"kind": "DiamondSword"}}).encode()
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
    body = _judge_body(kind="DiamondSword", name="Diamond Sword", attack=attack, material="Diamond")
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
