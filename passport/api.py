"""The live forge: one request, one engine run, the engine's own answer back.

Shared by local.py and the Vercel function in api/index.py. Input is checked
against the game's own mapping before the engine sees it: a field the game does
not define is refused, not passed through.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

from .engine import engine_binary, scratch
from .judge import GAMES, catalogue, find_oo_cert, judge_direct, mapping
from .present import compact, scrub

XSD = "http://www.w3.org/2001/XMLSchema#"
MAX = 100_000


class BadRequest(ValueError):
    pass


def _sha256(path: str | None) -> str | None:
    if not path or not Path(path).exists():
        return None
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def engine_info() -> dict:
    binary = shutil.which(engine_binary()) or engine_binary()
    return {
        "tag": os.environ.get("OO_ENGINE_TAG", "local build"),
        "binary_sha256": _sha256(binary),
        "oo_cert_sha256": _sha256(find_oo_cert()),
        "oo_shacl_sha256": _sha256(os.environ.get("OO_SHACL")),
    }


def clean_item(game: str, item: dict) -> dict:
    if not isinstance(item, dict):
        raise BadRequest("item must be an object")
    kinds = {r["kind"] for r in catalogue(game)}
    kind = item.get("kind")
    if kind not in kinds:
        raise BadRequest(f"{GAMES[game]['label']} has no kind {kind!r}; it has {sorted(kinds)}")
    fields = {m["field"]: ("lookup" if m.get("lookup") else m.get("datatype", "string"))
              for m in mapping(game)["mappings"]}
    rec = {"kind": kind}
    raw_id = str(item.get("id") or "forged_item")
    rec["id"] = re.sub(r"[^a-z0-9_]", "_", raw_id.lower())[:48] or "forged_item"
    name = str(item.get("name") or "Forged item").strip()[:40]
    rec["name"] = name
    for k, v in item.items():
        if k in ("id", "kind", "name"):
            continue
        if k not in fields:
            raise BadRequest(f"{GAMES[game]['label']} items have no field {k!r}")
        dt = fields[k]
        if dt in ("lookup", "string"):
            if not isinstance(v, str) or not re.fullmatch(r"[A-Za-z][A-Za-z ]{0,23}", v):
                raise BadRequest(f"{k} must be a word of up to 24 letters")
            rec[k] = v.replace(" ", "") if dt == "lookup" else v
            continue
        if dt == XSD + "boolean":
            if not isinstance(v, bool):
                raise BadRequest(f"{k} must be true or false")
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 <= v <= MAX):
                raise BadRequest(f"{k} must be a number from 0 to {MAX:,}")
            if dt == XSD + "integer" and v != int(v):
                raise BadRequest(f"{k} must be a whole number in {GAMES[game]['label']}")
            v = int(v) if dt == XSD + "integer" else v
        rec[k] = v
    return rec


def judge(body: dict) -> dict:
    if not isinstance(body, dict):
        raise BadRequest("send a JSON object")
    game, target = body.get("game"), body.get("target")
    if game not in GAMES or target not in GAMES or game == target:
        raise BadRequest(f"game and target must be two different games of: {', '.join(sorted(GAMES))}")
    rec = clean_item(game, body.get("item"))
    run = scratch("live")
    try:
        v = judge_direct(game, rec, target, run)
    finally:
        shutil.rmtree(run, ignore_errors=True)
    v["transcript"] = compact(v["transcript"])
    v["lane"] = "live"
    return scrub(v)
