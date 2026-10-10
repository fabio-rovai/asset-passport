"""The HTTP side of the live forge, shared by local.py and the Vercel function.

Both servers used to carry their own copy of this code, and only the local copy
had tests. Each server now keeps only its routing (local.py serves /api/engine
and /api/judge; Vercel rewrites /api/x to /api/index?p=x) and inherits the rest
from ApiHandlerMixin, so the code the tests drive is the code Vercel runs.
"""

from __future__ import annotations

import json
import re
import traceback

from .api import BadRequest, engine_info, judge
from .engine import EngineError, EngineTimeout
from .cors import cors_headers
from .present import scrub

MAX_BODY = 20_000          # the largest request body the forge reads
DRAIN_LIMIT = 1_000_000    # an oversized body up to this size is read and dropped
_LENGTH = re.compile(r"[0-9]{1,12}")
ALLOW = "GET, HEAD, POST, OPTIONS"


class LengthRequired(BadRequest):
    pass


class ApiHandlerMixin:
    """Mix into a BaseHTTPRequestHandler subclass, before it in the bases."""

    timeout = 30  # seconds a socket may sit idle, so a client that stalls frees the worker
    _head_only = False  # set while answering HEAD: the headers of GET, no body

    def _cors(self):
        for k, v in cors_headers(self.headers.get("origin")):
            self.send_header(k, v)

    def do_OPTIONS(self):
        """Answer the browser's preflight for a cross-origin POST."""
        self.send_response(204)
        self._cors()
        self.send_header("content-length", "0")
        self.end_headers()

    def _json(self, code, obj, extra=()):
        body = json.dumps(obj).encode()
        self.send_response(code)
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("content-type", "application/json")
        self._cors()
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(body)))
        if self.close_connection:
            self.send_header("connection", "close")
        self.end_headers()
        if not self._head_only:
            self.wfile.write(body)

    def _head(self, serve):
        """Answer HEAD with what GET would send, minus the body. Without this
        the stdlib answered 501 with an HTML page and no CORS headers."""
        self._head_only = True
        try:
            return serve()
        finally:
            self._head_only = False

    def _not_allowed(self):
        """PUT, DELETE and PATCH: a JSON 405 that names the methods there are.
        Any body is left unread, so the connection is not reused."""
        self.close_connection = True
        return self._json(405, {"error": f"method not allowed; this API answers {ALLOW}"},
                          [("allow", ALLOW)])

    do_PUT = do_DELETE = do_PATCH = _not_allowed

    def _body_length(self) -> int:
        """The declared body size. Anything but a plain count of bytes is refused,
        so a length such as 'abc' or -1 is a bad request, not an engine failure
        and not a read that waits for the client to hang up.

        A body with no content-length (Transfer-Encoding: chunked, say) used
        to be read as zero bytes, so a valid request came back as 'game and
        target must be two different games'. It is now refused as such."""
        raw = self.headers.get("content-length")
        if self.headers.get("transfer-encoding") is not None or raw is None:
            raise LengthRequired("send the body with a content-length header; chunked bodies are not read")
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

    def _is_json(self) -> bool:
        ctype = (self.headers.get("content-type") or "").split(";")[0].strip().lower()
        return ctype == "application/json"

    def _serve_judge(self):
        try:
            n = self._body_length()
        except BadRequest as e:
            self.close_connection = True  # the body's end is unknown, so this connection cannot be reused
            return self._json(411 if isinstance(e, LengthRequired) else 400, {"error": str(e)})
        if n > MAX_BODY:
            self._drop_body(n)
            return self._json(400, {"error": "request too large"})
        if not self._is_json():
            # A text/plain or form POST is a 'simple' request: a browser sends
            # it cross-origin with no preflight, so any page could make its
            # visitors run the engine and CORS would only hide the answer.
            # Requiring application/json forces the preflight, which the
            # allow-list refuses for every origin it does not name.
            self._drop_body(n)
            return self._json(415, {"error": "send the request as content-type application/json"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:  # not JSON, or not UTF-8
            return self._json(400, {"error": "the request body is not JSON"})
        try:
            return self._json(200, judge(body))
        except BadRequest as e:
            return self._json(400, {"error": str(e)})
        except EngineTimeout as e:
            # The engine hung and was stopped. Nothing was judged, so the
            # verdict is undetermined; the message names the limit, never a path.
            self.log_error("%s", scrub({"m": str(e)})["m"])
            return self._json(504, {"verdict": "undetermined",
                                    "error": f"The engine did not answer within {e.timeout:g} s, so it was "
                                             "stopped and nothing is claimed."})
        except EngineError:
            self.log_error("%s", scrub({"trace": traceback.format_exc()})["trace"])
            return self._json(502, {"verdict": "undetermined",
                                    "error": "The engine run failed, so nothing is claimed. The server log has "
                                             "the details."})
        except Exception:  # the engine failed; say so, do not invent a verdict
            # The details (scratch paths, the engine's own message) go to the
            # server log, scrubbed of machine paths; the client is told only
            # that the run failed, since its input already passed every check.
            self.log_error("%s", scrub({"trace": traceback.format_exc()})["trace"])
            return self._json(502, {"error": "the engine run failed; the server log has the details"})
