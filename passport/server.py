"""The HTTP side of the live forge, shared by local.py and the Vercel function.

Both servers used to carry their own copy of this code, and only the local copy
had tests. Each server now keeps only its routing (local.py serves /api/engine
and /api/judge; Vercel rewrites /api/x to /api/index?p=x) and inherits the rest
from ApiHandlerMixin, so the code the tests drive is the code Vercel runs.
"""

from __future__ import annotations

import json
import re

from .api import BadRequest, engine_info, judge
from .cors import cors_headers

MAX_BODY = 20_000          # the largest request body the forge reads
DRAIN_LIMIT = 1_000_000    # an oversized body up to this size is read and dropped
_LENGTH = re.compile(r"[0-9]{1,12}")


class ApiHandlerMixin:
    """Mix into a BaseHTTPRequestHandler subclass, before it in the bases."""

    timeout = 30  # seconds a socket may sit idle, so a client that stalls frees the worker

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
        self.send_header("content-length", str(len(body)))
        if self.close_connection:
            self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _body_length(self) -> int:
        """The declared body size. Anything but a plain count of bytes is refused,
        so a length such as 'abc' or -1 is a bad request, not an engine failure
        and not a read that waits for the client to hang up."""
        raw = self.headers.get("content-length")
        if raw is None:
            return 0
        if not _LENGTH.fullmatch(raw.strip()):
            raise BadRequest("content-length must be a whole number of bytes")
        return int(raw.strip())

    def _drop_body(self, n: int):
        """Read and discard an oversized body so the client receives the 400
        instead of a connection reset; past DRAIN_LIMIT, close the connection."""
        if n > DRAIN_LIMIT:
            self.close_connection = True
            return
        while n > 0:
            chunk = self.rfile.read(min(n, 65_536))
            if not chunk:
                break
            n -= len(chunk)

    def _serve_engine(self):
        return self._json(200, engine_info())

    def _serve_judge(self):
        try:
            n = self._body_length()
        except BadRequest as e:
            self.close_connection = True  # the body's end is unknown, so this connection cannot be reused
            return self._json(400, {"error": str(e)})
        if n > MAX_BODY:
            self._drop_body(n)
            return self._json(400, {"error": "request too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:  # not JSON, or not UTF-8
            return self._json(400, {"error": "the request body is not JSON"})
        try:
            return self._json(200, judge(body))
        except BadRequest as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:  # the engine failed; say so, do not invent a verdict
            return self._json(502, {"error": f"the engine run failed: {e}"})
