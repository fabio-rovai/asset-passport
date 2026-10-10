"""How engine output is shown: long strings clipped, machine paths removed.
Shared by the build and the live API, so both pages present the same way."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from .engine import ROOT


# Lists the engine prints in the order of a hash set, so the same run gives
# them in another order each time (onto_reason takes up to ten rdf:type
# inferences from a HashSet, src/reason.rs). They are sorted before they are
# shown.
UNORDERED = ("sample_inferences",)
# A blank-node label as the engine mints it: a random 128-bit number in hex,
# without leading zeros, new on every load.
_BNODE = re.compile(r"_:[0-9a-f]{20,32}\b")


def shown_transcript(calls: list) -> list:
    """A transcript as the page shows it: the engine's unordered lists sorted,
    blank-node labels renamed _:b0, _:b1, ... in order of first appearance,
    then compacted. Two builds of the same item then show the same transcript
    apart from digests, pack sizes and timestamps. The passport file keeps the
    engine's own labels."""
    return compact(relabel(_sorted_unordered(calls)))


def _sorted_unordered(obj):
    if isinstance(obj, dict):
        return {k: _sorted_unordered(sorted(v, key=str) if k in UNORDERED and isinstance(v, list) else v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sorted_unordered(x) for x in obj]
    return obj


def relabel(obj):
    """Every engine blank-node label in obj renamed by first appearance."""
    names: dict[str, str] = {}
    text = _BNODE.sub(lambda m: names.setdefault(m.group(0), f"_:b{len(names)}"),
                      json.dumps(obj, ensure_ascii=False))
    return json.loads(text)


def compact(obj, limit: int = 400, items: int = 24):
    """A transcript the page can carry: long strings clipped, long lists cut,
    each cut saying so. The passport file holds everything."""
    if isinstance(obj, dict):
        return {k: compact(v, limit, items) for k, v in obj.items()}
    if isinstance(obj, str) and len(obj) > limit:
        return obj[:limit] + f" … [{len(obj) - limit} more characters]"
    if isinstance(obj, list):
        out = [compact(x, limit, items) for x in obj[:items]]
        if len(obj) > items:
            out.append(f"… [{len(obj) - items} more entries]")
        return out
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
