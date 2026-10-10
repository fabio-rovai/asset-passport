"""Asset Passport on the command line.

    python3 -m passport judge  --from battle --into craft --item capture_orb
    python3 -m passport judge  --from craft --into battle --item my_sword.json
    python3 -m passport export --from battle --item capture_orb --out orb.pack
    python3 -m passport admit  orb.pack --into craft
    python3 -m passport keys   --game battle [--write [--force]]

Every subcommand takes --games DIR (default: $ASSET_PASSPORT_GAMES, else the
repository's games/). judge and admit print one line of JSON, the verdict, and
exit 0 when the item is admitted, 1 when it is refused, and 2 when nothing can
be claimed (undetermined) or the run failed. An engine that fails, or does not
answer within $ASSET_PASSPORT_ENGINE_TIMEOUT seconds (default 60), gives the
verdict undetermined with the reason under "error", and exit 2. A passport file that cannot be
opened is a failed run (2); one that opens but is not a well-formed, signed
passport is refused at the signature gate (1).

An item file given to judge or export goes through the same check as the live
API (judge.clean_item): a kind or a field the game does not define, or a number
outside 0 to 100,000, is a failed run (2), not a verdict.

export refuses (2) to sign with a key whose public half is not the export key
the game's profile publishes, because every receiver would refuse that
passport; --sign-anyway overrides. keys --force replaces a game's key only
together with --write, so the profile never keeps publishing a key whose
private half is gone, and the old key is moved aside, never deleted.

The judge subcommand signs nothing and runs without the cryptography package.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import games
from .engine import EngineError, scratch
from .judge import ADMITTED, admit, clean_item, export, item_record, judge_direct

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
        return clean_item(game, rec, root)
    return item_record(game, ref, root)


def _run(keep: bool):
    run = scratch("cli")
    return run, (lambda: None) if keep else (lambda: shutil.rmtree(run, ignore_errors=True))


def cmd_judge(a) -> int:
    if a.source == a.into:
        raise ValueError("--from and --into must name two different games, as in the live API")
    run, done = _run(a.keep)
    try:
        v = judge_direct(a.source, _item(a.source, a.item, a.games), a.into, run, root=a.games)
    finally:
        done()
    _print(summary(v))
    return exit_code(v)


def cmd_export(a) -> int:
    key = None
    if not a.unsigned:  # an unsigned export never opens a key file
        from . import sign
        g = games.get(a.source, a.games)
        key = _load_key(a.key) if a.key else sign.load_private(g)
        if key is None:
            raise ValueError(f"no export key for {g.iri} at {sign.key_path(g)}; run "
                             f"`python3 -m passport keys --game {a.source} --write`, pass --key, or pass --unsigned")
        if sign.public_b64(key) != g.export_key and not a.sign_anyway:
            raise ValueError(
                f"the key this export would sign with (sha256 {sign.key_sha256(sign.public_b64(key))[:16]}...) is "
                f"not the export key {g.profile} publishes"
                + (f" (sha256 {sign.key_sha256(g.export_key)[:16]}...)" if g.export_key else " (it publishes none)")
                + ", so every receiver would refuse the passport at the signature gate. Publish this key with "
                f"`python3 -m passport keys --game {a.source} --write`, or pass --sign-anyway")
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


def _issuer(pack: Path) -> str | None:
    """The game a passport's signature block names, read without trusting it.
    A pack that is not a JSON object with a signature names nobody; the
    signature gate refuses it, so it is not refused here."""
    try:
        sig = json.loads(pack.read_text()).get("signature")
    except (ValueError, OSError, AttributeError, UnicodeDecodeError):
        return None
    return sig.get("game") if isinstance(sig, dict) else None


def cmd_admit(a) -> int:
    pack = Path(a.pack)
    if not pack.is_file():
        raise FileNotFoundError(f"no passport file at {pack}")
    target = games.get(a.into, a.games)
    if _issuer(pack) == target.iri:
        # A passport carries an item out of the game that issued it. Admitted
        # back into that game, it was judged against the game's own border as
        # if it were foreign, which judge and the live API refuse to do.
        raise ValueError(f"this passport was issued by {target.label}, so --into must name another game: "
                         "a game does not import its own items")
    run, done = _run(a.keep)
    try:
        v = admit(pack.resolve(), a.into, run, root=a.games)
    finally:
        done()
    _print(summary(v))
    return exit_code(v)


def cmd_keys(a) -> int:
    from . import sign
    if a.force and not a.write:
        raise ValueError("--force replaces the private key, and without --write the profile would go on "
                         "publishing the old key's public half, with nothing left that can sign for it; "
                         "pass --force together with --write")
    g = games.get(a.game, a.games)
    key = sign.load_private(g)  # bound to the game's IRI, not to its directory name
    generated, retired = False, None
    if key is None or a.force:
        retired = sign.retire_private(g) if a.force else None
        key = sign.generate()
        sign.write_private(g, key)
        generated = True
    pub = sign.public_b64(key)
    if a.write and g.export_key != pub:
        try:
            g = games.publish_key(a.game, pub, a.games)
        except Exception:
            if generated:  # the profile was left as it was, so the keys are too
                sign.key_path(g).unlink(missing_ok=True)
                if retired is not None:
                    os.replace(retired, sign.key_path(g))
            raise
    _print({"game": g.iri, "label": g.label, "private_key": str(sign.key_path(g)),
            "generated": generated, "replaced_key_moved_to": str(retired) if retired else None, "public_key": pub, "public_key_sha256": sign.key_sha256(pub),
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
    e.add_argument("--sign-anyway", action="store_true",
                   help="sign even when the key is not the export key the game's profile publishes")
    e.set_defaults(fn=cmd_export)

    m = sub.add_parser("admit", parents=[common], help="judge a passport file at a game's border")
    m.add_argument("pack")
    m.add_argument("--into", required=True)
    m.set_defaults(fn=cmd_admit)

    k = sub.add_parser("keys", parents=[common], help="make a game's export keypair and show its public key")
    k.add_argument("--game", required=True)
    k.add_argument("--write", action="store_true", help="publish the public key in the game's profile.ttl")
    k.add_argument("--force", action="store_true",
                   help="replace an existing private key (needs --write; the old key is moved aside)")
    k.set_defaults(fn=cmd_keys)
    return p


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    try:
        return a.fn(a)
    except EngineError as err:
        # The engine failed or stopped answering (EngineTimeout): nothing was
        # judged, so nothing is claimed either way.
        _print({"verdict": "undetermined", "error": _message(err), "type": type(err).__name__})
        return UNDETERMINED_EXIT
    except Exception as err:  # any other failure is a failed run (2), never a verdict
        _print({"error": _message(err), "type": type(err).__name__})
        return UNDETERMINED_EXIT


def _message(err: Exception) -> str:
    """str() of a KeyError is the repr of its argument, quoted; its argument
    is the message. Every other exception's str() is its message as written."""
    if isinstance(err, KeyError) and err.args:
        return str(err.args[0])
    return str(err) or type(err).__name__


if __name__ == "__main__":
    sys.exit(main())
