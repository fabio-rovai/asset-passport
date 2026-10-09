"""Cross-origin access for the live forge.

The static page on GitHub Pages calls the engine API on Vercel, which is a
different origin, so the API must say which origins may read its answers.
Only the published page and the local server are named; any other origin gets
no allow-origin header and the browser keeps the answer from it.
"""

from __future__ import annotations

ALLOWED_ORIGINS = frozenset({
    "https://fabio-rovai.github.io",
    "http://localhost:8765",
    "http://127.0.0.1:8765",
})


def cors_headers(origin: str | None) -> list[tuple[str, str]]:
    """Headers to add to a response for a request sent from `origin`."""
    headers = [("vary", "Origin")]
    if origin in ALLOWED_ORIGINS:
        headers += [
            ("access-control-allow-origin", origin),
            ("access-control-allow-methods", "GET, POST, OPTIONS"),
            ("access-control-allow-headers", "content-type"),
            ("access-control-max-age", "600"),
        ]
    return headers
