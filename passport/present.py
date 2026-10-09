"""How engine output is shown: long strings clipped, machine paths removed.
Shared by the build and the live API, so both pages present the same way."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from .engine import ROOT


def compact(obj, limit: int = 400, items: int = 24):
    """A transcript the page can carry: long strings clipped, long lists cut,
    each cut saying so. The passport file holds everything."""
    if isinstance(obj, str) and len(obj) > limit:
        return obj[:limit] + f" … [{len(obj) - limit} more characters]"
    if isinstance(obj, list):
        out = [compact(x, limit, items) for x in obj[:items]]
        if len(obj) > items:
            out.append(f"… [{len(obj) - items} more entries]")
        return out
    if isinstance(obj, dict):
        return {k: compact(v, limit, items) for k, v in obj.items()}
    return obj


def scrub(obj):
    """Machine paths out of everything a page will show."""
    text = json.dumps(obj)
    tmp = tempfile.gettempdir()
    for prefix, name in ((str(ROOT), "<repo>"), (str(ROOT.parent / "open-ontologies"), "<open-ontologies>"),
                         ("/private" + tmp, "<tmp>"), (tmp, "<tmp>"), ("/tmp", "<tmp>"),
                         (str(Path.home()), "~")):
        text = text.replace(prefix, name)
    text = re.sub(r"<tmp>/asset-passport-[A-Za-z0-9_-]+", "<run>", text)
    return json.loads(text)
