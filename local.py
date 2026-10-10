"""Serve the page and the live forge on http://localhost:8765.

    python3 local.py            # engine: $OO_BIN, else ../open-ontologies/target/release
"""

import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from passport.server import ApiHandlerMixin  # noqa: E402

PORT = 8765


class Handler(ApiHandlerMixin, SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT / "site"), **k)

    def _api(self) -> bool:
        return self.path.split("?")[0].startswith("/api/")

    def _api_get(self):
        """GET under /api/, as the Vercel function answers it: the engine
        route, else a JSON 404 with the CORS headers, never the static
        server's HTML page."""
        if self.path.split("?")[0] == "/api/engine":
            return self._serve_engine()
        return self._json(404, {"error": "no such route"})

    def do_GET(self):
        if self._api():
            return self._api_get()
        return super().do_GET()

    def do_HEAD(self):
        if self._api():
            return self._head(self._api_get)
        return super().do_HEAD()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/judge":
            return self._json(404, {"error": "no such route"})
        return self._serve_judge()


if __name__ == "__main__":
    print(f"http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
