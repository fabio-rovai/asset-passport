"""Cross-origin access for the live forge, checked against the real local server.

The GitHub Pages copy of the page calls the API on another origin. These tests
show the allow-origin header is given to the named origins AND withheld from
any other, so the check is able to refuse.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import local
from passport.cors import ALLOWED_ORIGINS, cors_headers

PAGES = "https://fabio-rovai.github.io"


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), local.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


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


def test_named_origins_only():
    assert PAGES in ALLOWED_ORIGINS
    assert dict(cors_headers(PAGES))["access-control-allow-origin"] == PAGES
    for stranger in ("https://evil.example", "https://fabio-rovai.github.io.evil.example", None, ""):
        assert "access-control-allow-origin" not in dict(cors_headers(stranger))


def test_preflight_from_pages_is_allowed(server):
    code, headers, _ = _call(server + "/api/judge", "OPTIONS", PAGES,
                             headers={"Access-Control-Request-Method": "POST",
                                      "Access-Control-Request-Headers": "content-type"})
    assert code == 204
    assert headers["access-control-allow-origin"] == PAGES
    assert "POST" in headers["access-control-allow-methods"]
    assert "content-type" in headers["access-control-allow-headers"]


def test_preflight_from_stranger_is_refused(server):
    code, headers, _ = _call(server + "/api/judge", "OPTIONS", "https://evil.example",
                             headers={"Access-Control-Request-Method": "POST"})
    assert code == 204
    assert headers.get("access-control-allow-origin") is None


def test_bad_field_is_400_with_cors(server):
    body = json.dumps({"game": "craft", "target": "battle",
                       "item": {"kind": "DiamondSword", "name": "Sword", "colour": 3}}).encode()
    code, headers, raw = _call(server + "/api/judge", "POST", PAGES, body,
                               {"content-type": "application/json"})
    assert code == 400, raw
    assert headers["access-control-allow-origin"] == PAGES
    assert "no field" in json.loads(raw)["error"]


def test_oversized_request_is_400(server):
    body = b"{" + b" " * 20_001 + b"}"
    code, _, raw = _call(server + "/api/judge", "POST", PAGES, body,
                         {"content-type": "application/json"})
    assert code == 400
    assert json.loads(raw)["error"] == "request too large"


def test_engine_info_carries_cors(server):
    code, headers, raw = _call(server + "/api/engine", "GET", PAGES)
    assert code == 200
    assert headers["access-control-allow-origin"] == PAGES
    assert json.loads(raw)["binary_sha256"]


@pytest.mark.parametrize("attack,verdict,damage", [(12, "converted", 60), (20, "refused", 100)])
def test_cross_origin_judge(server, attack, verdict, damage):
    body = json.dumps({"game": "craft", "target": "battle",
                       "item": {"kind": "DiamondSword", "name": "Diamond Sword",
                                "attack": attack, "material": "Diamond"}}).encode()
    code, headers, raw = _call(server + "/api/judge", "POST", PAGES, body,
                               {"content-type": "application/json"})
    assert code == 200, raw
    assert headers["access-control-allow-origin"] == PAGES
    v = json.loads(raw)
    assert v["verdict"] == verdict, v["refusals"]
    assert v["conversion"]["damageInTarget"] == damage
