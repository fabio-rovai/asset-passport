"""The live forge: one request, one engine run, the engine's own answer back.

Shared by local.py and the Vercel function in api/index.py. Input goes through
the same check the command line uses (judge.clean_item) before the engine sees
it: a field the game does not define is refused, not passed through, and so is a
missing field the game's own record of that kind has, a type that a game with
elemental types does not place, or an id that would make the item one of the
game's own terms.
"""

from __future__ import annotations

import functools
import hashlib
import os
import shutil
from pathlib import Path

from . import judge as _judge
from .engine import engine_binary, scratch
from .judge import GAMES, find_oo_cert, judge_direct
from .present import scrub, shown_transcript

MAX = _judge.MAX_NUMBER


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


def vocabulary(game: str) -> dict:
    """The game's vocabulary as the engine reads it (judge.vocabulary)."""
    return _judge.vocabulary(game)


def clean_item(game: str, item) -> dict:
    """The command line's item check (judge.clean_item), with its refusal as a 400."""
    try:
        return _judge.clean_item(game, item)
    except _judge.BadItem as err:
        raise BadRequest(str(err)) from err


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
    v["transcript"] = shown_transcript(v["transcript"])
    v["lane"] = "live"
    return scrub(v)
