"""The live forge: one request, one engine run, the engine's own answer back.

Shared by local.py and the Vercel function in api/index.py. Input is checked
against the game's own mapping and profile before the engine sees it: a field
the game does not define is refused, not passed through, and so is a type that
a game with elemental types does not place, or an id that would make the item
one of the game's own terms.
"""

from __future__ import annotations

import functools
import hashlib
import os
import re
import shutil
import unicodedata
from pathlib import Path

from .engine import GA, Engine, engine_binary, scratch
from .judge import GAMES, catalogue, find_oo_cert, game_dir, judge_direct, mapping
from .present import compact, scrub

XSD = "http://www.w3.org/2001/XMLSchema#"
MAX = 100_000


class BadRequest(ValueError):
    pass


def _sha256(path: str | None) -> str | None:
    """The file's sha256. GET /api/engine is anonymous, so the three engine
    binaries are hashed once per process and file version, not on every call."""
    if not path or not Path(path).exists():
        return None
    st = Path(path).stat()
    return _sha256_of(str(Path(path).resolve()), st.st_size, st.st_mtime_ns)


@functools.lru_cache(maxsize=16)
def _sha256_of(path: str, size: int, mtime_ns: int) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def engine_info() -> dict:
    binary = shutil.which(engine_binary()) or engine_binary()
    return {
        "tag": os.environ.get("OO_ENGINE_TAG", "local build"),
        "binary_sha256": _sha256(binary),
        "oo_cert_sha256": _sha256(find_oo_cert()),
        "oo_shacl_sha256": _sha256(os.environ.get("OO_SHACL")),
    }


RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
_VOCAB: dict[str, dict] = {}


def vocabulary(game: str) -> dict:
    """What the game's published profile says, read by the engine: every term
    in the game's own namespace, whether the game declares elemental types,
    and, for each lookup field, the values the profile places on the hub's
    type scale. Cached per process by the bytes of the profile."""
    profile = game_dir(game) / "profile.ttl"
    key = hashlib.sha256(profile.read_bytes()).hexdigest()
    if _VOCAB.get(game, {}).get("key") == key:
        return _VOCAB[game]
    m = mapping(game)
    base = m["base_iri"]
    run = scratch("vocab")
    try:
        with Engine(run) as e:
            e.call("onto_clear")
            loaded = e.load(profile)
            if "error" in loaded:
                raise RuntimeError(f"{game} profile did not load: {loaded['error']}")

            def rows(q: str) -> list[dict]:
                out = e.call("onto_query", query=q)
                if "error" in out:
                    raise RuntimeError(f"vocabulary query failed: {out['error']}")
                return out.get("results", [])

            terms = {r["t"].strip("<>") for r in rows(
                f"SELECT DISTINCT ?t WHERE {{ {{ ?t ?p ?o }} UNION {{ ?s ?t ?o }} UNION {{ ?s ?p ?t }} "
                f'FILTER(isIRI(?t) && STRSTARTS(STR(?t), "{base}")) }}')}
            typed = any(r["t"].startswith('"true"') for r in rows(
                f"SELECT ?t WHERE {{ ?g a <{GA}Game> ; <{GA}hasElementalTypes> ?t }}"))
            placed = {}
            for f in m["mappings"]:
                if not f.get("lookup") or f["field"] == "kind":
                    continue
                placed[f["field"]] = sorted(
                    r["v"].strip("<>")[len(base):] for r in rows(
                        f"SELECT DISTINCT ?v WHERE {{ <{f['predicate']}> <{RDFS}subPropertyOf>* ?p . "
                        f"?r <{OWL}onProperty> ?p ; <{OWL}hasValue> ?v ; <{RDFS}subClassOf> ?c . "
                        f"?c <{OWL}onProperty> <{GA}elementalType> . "
                        f'FILTER(STRSTARTS(STR(?v), "{base}")) }}'))
    finally:
        shutil.rmtree(run, ignore_errors=True)
    _VOCAB[game] = {"key": key, "base": base, "terms": terms, "typed": typed, "placed": placed}
    return _VOCAB[game]


def _text(label: str, v) -> str:
    """A free-text value a person typed: a string of printable characters.
    A lone surrogate cannot be written as UTF-8, so the engine's JSON reader
    refused it and the client saw an engine failure; control and format
    characters (bidirectional overrides among them) have no place in a name."""
    if not isinstance(v, str):
        raise BadRequest(f"{label} must be a string")
    if any(unicodedata.category(c).startswith("C") for c in v):
        raise BadRequest(f"{label} must hold only printable characters")
    return v


def clean_item(game: str, item: dict) -> dict:
    if not isinstance(item, dict):
        raise BadRequest("item must be an object")
    label = GAMES[game]["label"]
    kinds = {r["kind"] for r in catalogue(game)}
    kind = item.get("kind")
    if not isinstance(kind, str) or kind not in kinds:
        raise BadRequest(f"{label} has no kind {kind!r}; it has {sorted(kinds)}")
    fields = {m["field"]: ("lookup" if m.get("lookup") else m.get("datatype", "string"))
              for m in mapping(game)["mappings"]}
    vocab = vocabulary(game)
    rec = {"kind": kind}
    raw_id = _text("id", item.get("id") or "forged_item")
    rec["id"] = re.sub(r"[^a-z0-9_]", "_", raw_id.lower())[:48] or "forged_item"
    if vocab["base"] + rec["id"] in vocab["terms"]:
        # The item's IRI is the base IRI plus its id, so id 'game' made the
        # item the source game itself, typed as a weapon.
        raise BadRequest(f"id {rec['id']!r} is a term of {label}'s own rules; choose another id")
    name = _text("name", item.get("name") or "Forged item").strip()[:40]
    rec["name"] = name
    for k, v in item.items():
        if k in ("id", "kind", "name"):
            continue
        if k not in fields:
            raise BadRequest(f"{label} items have no field {k!r}")
        dt = fields[k]
        if dt in ("lookup", "string"):
            if not isinstance(v, str) or not re.fullmatch(r"[A-Za-z][A-Za-z ]{0,23}", v):
                raise BadRequest(f"{k} must be a word of up to 24 letters")
            if dt == "lookup":
                v = v.replace(" ", "")
                placed = vocab["placed"].get(k) or []
                if vocab["typed"] and placed and v not in placed:
                    # The game says every thing it has carries an elemental
                    # type, so a value it does not place is not one of its
                    # types. Passed through, it vanished at the border with no
                    # loss named. A game without types (Blockcraft) keeps an
                    # unplaced value, and the border names what that costs.
                    raise BadRequest(f"{label} has no {k} {v!r}; it has {placed}")
            rec[k] = v
            continue
        if dt == XSD + "boolean":
            if not isinstance(v, bool):
                raise BadRequest(f"{k} must be true or false")
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 <= v <= MAX):
                raise BadRequest(f"{k} must be a number from 0 to {MAX:,}")
            if dt == XSD + "integer" and v != int(v):
                raise BadRequest(f"{k} must be a whole number in {label}")
            v = int(v) if dt == XSD + "integer" else v
        rec[k] = v
    return rec


def judge(body: dict) -> dict:
    if not isinstance(body, dict):
        raise BadRequest("send a JSON object")
    game, target = body.get("game"), body.get("target")
    if not (isinstance(game, str) and isinstance(target, str)) or game not in GAMES or target not in GAMES or game == target:
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
