"""Serve the page and the live forge on http://localhost:8765.

    python3 local.py            # engine: $OO_BIN, else ../open-ontologies/target/release
"""

import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from passport.api import BadRequest, engine_info, judge  # noqa: E402

PORT = 8765


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT / "site"), **k)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/engine":
            return self._json(200, engine_info())
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/judge":
            return self._json(404, {"error": "no such route"})
        try:
            n = int(self.headers.get("content-length") or 0)
            if n > 20_000:
                raise BadRequest("request too large")
            return self._json(200, judge(json.loads(self.rfile.read(n) or b"{}")))
        except (BadRequest, json.JSONDecodeError) as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:  # the engine failed; say so, do not invent a verdict
            return self._json(502, {"error": f"the engine run failed: {e}"})


if __name__ == "__main__":
    print(f"http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
