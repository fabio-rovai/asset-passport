"""Asset Passport on the command line.

    python3 -m passport judge  --from battle --into craft --item capture_orb
    python3 -m passport judge  --from craft --into battle --item my_sword.json
    python3 -m passport export --from battle --item capture_orb --out orb.pack
    python3 -m passport admit  orb.pack --into craft
    python3 -m passport keys   --game battle [--write] [--force]

Every subcommand takes --games DIR (default: $ASSET_PASSPORT_GAMES, else the
repository's games/). judge and admit print one line of JSON, the verdict, and
exit 0 when the item is admitted, 1 when it is refused, and 2 when nothing can
be claimed (undetermined) or the run failed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import games, sign
from .engine import EngineError, scratch
from .judge import ADMITTED, admit, export, item_record, judge_direct

ADMITTED_EXIT, REFUSED_EXIT, UNDETERMINED_EXIT = 0, 1, 2


def _print(obj: dict) -> None:
    print(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))


def summary(v: dict) -> dict:
    """The verdict without the transcript: what a script reading stdout needs."""
    return {
        "verdict": v["verdict"],
        "stage": v.get("stage"),
        "headline": v.get("headline"),
        "refusals": [r.get("message") for r in v.get("refusals", [])],
        "losses": [r.get("message") for r in v.get("losses", [])],
        "conversion": v.get("conversion", {}),
        "hub_types": v.get("hub_types", []),
        "item": v.get("item_iri"),
        "source": v.get("source"),
        "target": v.get("target"),
        "proof": (v.get("proof") or {}).get("status"),
        "signature": v.get("signature"),
        "evaluators": v.get("evaluators", {}),
    }


def exit_code(v: dict) -> int:
    if v["verdict"] in ADMITTED:
        return ADMITTED_EXIT
    return REFUSED_EXIT if v["verdict"] == "refused" else UNDETERMINED_EXIT


def _item(game: str, ref: str, root) -> dict:
    """An item id from the game's items.json, or a path to an item JSON file."""
    if os.path.exists(ref):
        rec = json.loads(Path(ref).read_text())
        if not isinstance(rec, dict) or "id" not in rec or "kind" not in rec:
            raise ValueError(f"{ref} must be one JSON object with at least an id and a kind")
        return rec
    return item_record(game, ref, root)


def _run(keep: bool):
    run = scratch("cli")
    return run, (lambda: None) if keep else (lambda: shutil.rmtree(run, ignore_errors=True))


def cmd_judge(a) -> int:
    run, done = _run(a.keep)
    try:
        v = judge_direct(a.source, _item(a.source, a.item, a.games), a.into, run, root=a.games)
    finally:
        done()
    _print(summary(v))
    return exit_code(v)


def cmd_export(a) -> int:
    key = sign.load_private(a.source) if not a.key else _load_key(a.key)
    if key is None and not a.unsigned:
        raise ValueError(f"no export key for {a.source} at {sign.key_path(a.source)}; run "
                         f"`python3 -m passport keys --game {a.source} --write`, pass --key, or pass --unsigned")
    run, done = _run(a.keep)
    try:
        ex = export(a.source, _item(a.source, a.item, a.games), run, root=a.games,
                    key=None if a.unsigned else key)
        out = Path(a.out or f"{a.source}-{Path(a.item).stem}.pack")
        shutil.copy(ex["pack"], out)
    finally:
        done()
    _print({"pack": str(out), "item": ex["item_iri"],
            "content_sha256": ex["packed"].get("content_sha256"), "signature": ex["signature"]})
    return 0


def _load_key(path: str):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(k, Ed25519PrivateKey):
        raise ValueError(f"{path} is not an Ed25519 private key")
    return k


def cmd_admit(a) -> int:
    run, done = _run(a.keep)
    try:
        v = admit(Path(a.pack).resolve(), a.into, run, root=a.games)
    finally:
        done()
    _print(summary(v))
    return exit_code(v)


def cmd_keys(a) -> int:
    g = games.get(a.game, a.games)
    key = sign.load_private(a.game)
    generated = False
    if key is None or a.force:
        key = sign.generate()
        sign.write_private(a.game, key, force=a.force)
        generated = True
    pub = sign.public_b64(key)
    if a.write and g.export_key != pub:
        g = games.publish_key(a.game, pub, a.games)
    _print({"game": g.iri, "label": g.label, "private_key": str(sign.key_path(a.game)),
            "generated": generated, "public_key": pub, "public_key_sha256": sign.key_sha256(pub),
            "published_in_profile": g.export_key == pub,
            "turtle": f'<{g.iri}> <{games.GA}exportKey> "{pub}" .'})
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m passport", description=__doc__.split("\n\n")[0])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--games", help="the games root (default: $ASSET_PASSPORT_GAMES, else <repo>/games)")
    common.add_argument("--keep", action="store_true", help="keep the run directory with the engine's files")
    sub = p.add_subparsers(dest="cmd", required=True)

    j = sub.add_parser("judge", parents=[common], help="judge an item in one store (no passport, no signature)")
    j.add_argument("--from", dest="source", required=True)
    j.add_argument("--into", required=True)
    j.add_argument("--item", required=True, help="an item id from the game's items.json, or a path to an item JSON")
    j.set_defaults(fn=cmd_judge)

    e = sub.add_parser("export", parents=[common], help="write a signed passport for an item")
    e.add_argument("--from", dest="source", required=True)
    e.add_argument("--item", required=True, help="an item id from the game's items.json, or a path to an item JSON")
    e.add_argument("--out", help="where to write the .pack (default: <game>-<item>.pack here)")
    e.add_argument("--key", help="a PEM Ed25519 private key (default: the game's key in the keys directory)")
    e.add_argument("--unsigned", action="store_true", help="write the passport without a signature")
    e.set_defaults(fn=cmd_export)

    m = sub.add_parser("admit", parents=[common], help="judge a passport file at a game's border")
    m.add_argument("pack")
    m.add_argument("--into", required=True)
    m.set_defaults(fn=cmd_admit)

    k = sub.add_parser("keys", parents=[common], help="make a game's export keypair and show its public key")
    k.add_argument("--game", required=True)
    k.add_argument("--write", action="store_true", help="publish the public key in the game's profile.ttl")
    k.add_argument("--force", action="store_true", help="replace an existing private key")
    k.set_defaults(fn=cmd_keys)
    return p


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    try:
        return a.fn(a)
    except (EngineError, ValueError, KeyError, OSError, FileExistsError) as err:
        _print({"error": str(err).strip("'\"")})
        return UNDETERMINED_EXIT


if __name__ == "__main__":
    sys.exit(main())
