"""Vercel function for the live forge. Runs the PINNED engine release fetched
and checksummed by build.sh; nothing here reimplements a verdict."""

import os
import shutil
import stat
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BUNDLED = Path(__file__).resolve().parent / "_bin"
# Not under a name that starts 'asset-passport-': present.scrub rewrites any
# such /tmp directory to '<run>', the per-run scratch, and the transcript then
# said the bundled SHACL checker was a per-run file ('<run>/oo-shacl').
RUN_BIN = Path("/tmp/ap-engine-bin")


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
    # A variable that is already set wins, so importing this module on a
    # machine that holds a local build (the tests do) never swaps in the
    # Linux binaries a dry run of build.sh left in api/_bin.
    if os.environ.get(var):
        continue
    path = _install(name)
    if path:
        os.environ[var] = path
# vercel.json gives this function 30 s. With the engine's default 60 s
# deadline, a hung engine was cut off by the platform first, and the client got
# Vercel's own error instead of the 504 JSON that says nothing is claimed.
os.environ.setdefault("ASSET_PASSPORT_ENGINE_TIMEOUT", "20")
tag_file = BUNDLED / "TAG"
if tag_file.exists() and os.environ.get("OO_BIN") == str(RUN_BIN / "open-ontologies"):
    os.environ.setdefault("OO_ENGINE_TAG", tag_file.read_text().strip())

from http.server import BaseHTTPRequestHandler  # noqa: E402

from passport.server import ApiHandlerMixin  # noqa: E402


class handler(ApiHandlerMixin, BaseHTTPRequestHandler):
    """Vercel rewrites /api/x to /api/index?p=x (vercel.json), so the route is p."""

    def _route(self):
        q = parse_qs(urlparse(self.path).query)
        return (q.get("p") or [""])[0]

    def do_GET(self):
        if self._route() == "engine":
            return self._serve_engine()
        return self._json(404, {"error": "no such route"})

    def do_HEAD(self):
        return self._head(self.do_GET)

    def do_POST(self):
        if self._route() != "judge":
            return self._json(404, {"error": "no such route"})
        return self._serve_judge()
