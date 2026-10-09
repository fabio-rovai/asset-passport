"""Vercel function for the live forge. Runs the PINNED engine release fetched
and checksummed by build.sh; nothing here reimplements a verdict."""

import json
import os
import shutil
import stat
import sys
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BUNDLED = Path(__file__).resolve().parent / "_bin"
RUN_BIN = Path("/tmp/asset-passport-bin")


def _install(name: str) -> str | None:
    """Copy a bundled binary to /tmp and make it executable. Concurrent cold
    starts used to race on one path ('Text file busy'); each copy now lands
    under a unique name and is renamed into place, which is atomic, and a
    process that already runs the old file keeps running it."""
    src, dst = BUNDLED / name, RUN_BIN / name
    if not src.exists():
        return None
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return str(dst)
    RUN_BIN.mkdir(parents=True, exist_ok=True)
    tmp = RUN_BIN / f".{name}.{uuid.uuid4().hex}"
    shutil.copyfile(src, tmp)
    tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(tmp, dst)
    return str(dst)


for var, name in (("OO_BIN", "open-ontologies"), ("OO_CERT", "oo-cert"), ("OO_SHACL", "oo-shacl")):
    path = _install(name)
    if path:
        os.environ[var] = path
tag_file = BUNDLED / "TAG"
if tag_file.exists():
    os.environ.setdefault("OO_ENGINE_TAG", tag_file.read_text().strip())

from passport.api import BadRequest, engine_info, judge  # noqa: E402
from passport.cors import cors_headers  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _cors(self):
        for k, v in cors_headers(self.headers.get("origin")):
            self.send_header(k, v)

    def do_OPTIONS(self):
        """Answer the browser's preflight for a cross-origin POST."""
        self.send_response(204)
        self._cors()
        self.send_header("content-length", "0")
        self.end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self._cors()
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        q = parse_qs(urlparse(self.path).query)
        return (q.get("p") or [""])[0]

    def do_GET(self):
        if self._route() == "engine":
            return self._json(200, engine_info())
        return self._json(404, {"error": "no such route"})

    def do_POST(self):
        if self._route() != "judge":
            return self._json(404, {"error": "no such route"})
        try:
            n = int(self.headers.get("content-length") or 0)
            if n > 20_000:
                raise BadRequest("request too large")
            return self._json(200, judge(json.loads(self.rfile.read(n) or b"{}")))
        except (BadRequest, json.JSONDecodeError) as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:
            return self._json(502, {"error": f"the engine run failed: {e}"})
