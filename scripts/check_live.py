"""Check a deployed engine API the way the GitHub Pages copy will use it.

    python3 scripts/check_live.py https://<production alias>

Give the stable production alias (the 'Aliased:' line of `vercel deploy --prod`
or the domain in the project settings), not the per-deployment URL, which
changes on every deploy and may sit behind Vercel deployment protection.
Every request is sent anonymously with Origin https://fabio-rovai.github.io,
as a browser on the published page would send it. The script prints what the
server said and exits non-zero if any check fails.

It also checks that the deployment serves the page itself at /. The Vercel
project once ran under the Python framework preset, which built only the
function, so every path, / included, got the API's JSON 404 while every /api
check here still passed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PAGES = "https://fabio-rovai.github.io"
ROOT = Path(__file__).resolve().parent.parent


def pinned_engine_sha() -> str:
    """The open-ontologies Linux checksum build.sh pins for v2.0.1."""
    text = (ROOT / "build.sh").read_text()
    m = re.search(r'"v2\.0\.1 open-ontologies-x86_64-unknown-linux-gnu"\) echo ([0-9a-f]{64})', text)
    return m.group(1)


def call(url, method="GET", body=None, headers=None):
    h = {"Origin": PAGES, **(headers or {})}
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            code, hdrs, raw = r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        code, hdrs, raw = e.code, e.headers, e.read()
    return code, hdrs, raw, time.monotonic() - t0


def main(base: str) -> int:
    base = base.rstrip("/")
    failures = []

    def check(ok, label, detail):
        print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}")
        if not ok:
            failures.append(label)

    code, hdrs, raw, cold = call(base + "/api/engine")
    if code in (401, 403):
        check(False, "anonymous access", f"HTTP {code}; deployment protection is likely on for this URL")
        return 1
    info = json.loads(raw) if code == 200 else {}
    check(code == 200, "GET /api/engine", f"HTTP {code} in {cold:.2f}s (first request, may be cold)")
    check(info.get("tag") == "v2.0.1", "engine tag", repr(info.get("tag")))
    check(info.get("binary_sha256") == pinned_engine_sha(), "engine binary sha256",
          f"{info.get('binary_sha256')} (pinned {pinned_engine_sha()})")
    check(hdrs.get("access-control-allow-origin") == PAGES, "allow-origin on GET",
          repr(hdrs.get("access-control-allow-origin")))
    _, _, _, warm = call(base + "/api/engine")
    print(f"INFO  warm GET /api/engine: {warm:.2f}s")
    code, hdrs, _, _ = call(base + "/api/engine", "HEAD")
    check(code == 200 and (hdrs.get("content-type") or "").startswith("application/json"),
          "HEAD /api/engine", f"HTTP {code}, content-type {hdrs.get('content-type')!r}")

    for path in ("/", "/config.js"):
        code, hdrs, raw, _ = call(base + path)
        ctype = hdrs.get("content-type") or ""
        want = "text/html" if path == "/" else "javascript"
        check(code == 200 and want in ctype, f"GET {path} serves the page",
              f"HTTP {code}, content-type {ctype!r}, first bytes {raw[:40]!r}")

    for attack, want in ((12, "converted"), (20, "refused")):
        body = json.dumps({"game": "craft", "target": "battle",
                           "item": {"kind": "CrystalSword", "name": "Crystal Sword",
                                    "attack": attack, "material": "Crystal"}}).encode()
        code, hdrs, raw, t = call(base + "/api/judge", "POST", body, {"content-type": "application/json"})
        v = json.loads(raw) if code == 200 else {"error": raw[:200]}
        conv = v.get("conversion") or {}
        refusal = (v.get("refusals") or [{}])[0].get("message")
        check(code == 200 and v.get("verdict") == want, f"judge attack {attack}",
              f"HTTP {code} in {t:.2f}s, verdict {v.get('verdict')!r}, headline {v.get('headline')!r}, "
              f"damageInTarget {conv.get('damageInTarget')!r}, typeInTarget {conv.get('typeInTarget')!r}, "
              f"refusal {refusal!r}")

    # Client mistakes are 400s that name the mistake, never a 502 'engine run failed'.
    # Each body has every field its kind needs, so the one mistake planted is
    # the only thing wrong with it, and the check reads the error for that
    # mistake: a bare 400 passed against a deployment that refused the kind
    # itself, for a reason none of these checks names.
    sword = {"kind": "CrystalSword", "name": "Sword", "attack": 6, "material": "Crystal"}
    fox = {"kind": "Emberfox", "name": "Emberfox", "hp": 100, "movePower": 45, "moveName": "Cinder Puff",
           "type": "Fire"}
    mistakes = (
        ("invalid field", "craft", {**sword, "colour": 3}, "no field 'colour'"),
        ("kind that is a list", "craft", {**sword, "kind": ["CrystalSword"]}, "has no kind ['CrystalSword']"),
        ("name with a lone surrogate", "craft", {**sword, "name": "\ud800"}, "printable characters"),
        ("type the game does not place", "battle", {**fox, "type": "Plasma"}, "has no type 'Plasma'"),
    )
    for label, game, item, says in mistakes:
        body = json.dumps({"game": game, "target": "battle" if game == "craft" else "craft", "item": item}).encode()
        code, _, raw, _ = call(base + "/api/judge", "POST", body, {"content-type": "application/json"})
        try:
            error = json.loads(raw).get("error") or ""
        except ValueError:
            error = ""
        check(code == 400 and says in error, label, f"HTTP {code} {raw[:160]!r} (must name {says!r})")

    # A text/plain POST needs no preflight, so it must not run the engine.
    body = json.dumps({"game": "craft", "target": "battle",
                       "item": {"kind": "CrystalSword", "attack": 12, "material": "Crystal"}}).encode()
    code, _, raw, _ = call(base + "/api/judge", "POST", body,
                           {"Origin": "https://evil.example", "content-type": "text/plain;charset=UTF-8"})
    check(code == 415, "text/plain POST from a stranger", f"HTTP {code} {raw[:120]!r}")

    code, hdrs, _, _ = call(base + "/api/judge", "OPTIONS", None,
                            {"Access-Control-Request-Method": "POST",
                             "Access-Control-Request-Headers": "content-type"})
    check(code == 204 and hdrs.get("access-control-allow-origin") == PAGES, "preflight from Pages",
          f"HTTP {code}, allow-origin {hdrs.get('access-control-allow-origin')!r}")
    code, hdrs, _, _ = call(base + "/api/judge", "OPTIONS", None,
                            {"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    check(hdrs.get("access-control-allow-origin") is None, "preflight from a stranger",
          f"HTTP {code}, allow-origin {hdrs.get('access-control-allow-origin')!r}")

    print(f"{len(failures)} check(s) failed" if failures else "all checks passed")
    return 1 if failures else 0


def _url(text: str) -> str:
    if not re.match(r"https?://", text):
        raise argparse.ArgumentTypeError(f"{text!r} is not an http:// or https:// address")
    return text


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 epilog="It exits 0 when every check passes and 1 when any fails.")
    ap.add_argument("base", type=_url, help="the deployment's stable production address")
    sys.exit(main(ap.parse_args().base))
