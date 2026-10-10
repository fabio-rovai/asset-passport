"""Judge every catalogue item and every forgery with the real engine, and write
what it said to site/data/. Nothing on the page is typed by hand: each verdict,
number, message and proof status is copied from an engine or checker response.

    python3 scripts/build_site.py              # the maintainer's build: signs with the games' real keys
    python3 scripts/build_site.py --check      # anyone: throwaway keys in a scratch copy, writes nothing,
                                               # and fails with a diff unless site/data/verdicts.json gives
                                               # what the engine says now in every field the page renders
    python3 scripts/build_site.py --new-keys   # make missing keys and REWRITE the games' published keys

The games' published export keys (ga:exportKey in games/*/profile.ttl) are the
trust anchors every receiver checks against, so a plain build never changes
them. Without the matching private key it stops and says what to do.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from passport import forge, games, sign  # noqa: E402
from passport.engine import engine_binary  # noqa: E402
from passport.engine import scratch as _scratch  # noqa: E402
from passport.present import scrub, shown_transcript  # noqa: E402
from passport.judge import (GATES, admit, catalogue, export, find_oo_cert,  # noqa: E402
                            judge_direct)

SITE = ROOT / "site"
DATA = SITE / "data"
PASSPORTS = SITE / "passports"
OO = ROOT.parent / "open-ontologies"


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# Every scratch directory this build makes, removed when the build ends,
# whether it succeeded or not.
_MADE: list[Path] = []


def scratch(prefix: str) -> Path:
    d = _scratch(prefix)
    _MADE.append(d)
    return d


def resolve_binary(binary: str) -> str:
    """The engine as a file: $OO_BIN may be a command name on PATH, and the
    build hashes the file, so a name is resolved before anything else runs."""
    found = shutil.which(binary) or binary
    if not Path(found).is_file():
        raise SystemExit(f"no engine binary at {binary!r}: set OO_BIN to the open-ontologies binary "
                         "or put it on PATH")
    return str(Path(found).resolve())


def shown(path: Path) -> str:
    """A path as a person reads it: relative to the repository when it is inside it."""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def other(game: str, known: dict) -> str:
    return next(g for g in known if g != game)


def real_keys(known: dict, binary: str, new_keys: bool) -> dict:
    """Each game's private export key, from outside the repository, bound to
    the game's IRI. A plain build refuses to go on when a key is missing or
    does not match the key the profile publishes. --new-keys makes a missing
    key, and rewrites a profile whose published key does not match, and says
    so, because a rewritten profile replaces a trust anchor."""
    keys, problems = {}, []
    for key, g in known.items():
        priv = sign.load_private(g)
        if priv is None and new_keys:
            priv = sign.generate()
            print(f"no export key for {g.label}: generated one at {sign.write_private(g, priv)}")
        if priv is None:
            problems.append(f"{g.label}: no private key at {sign.key_path(g)}")
            continue
        pub = sign.public_b64(priv)
        if g.export_key != pub:
            if not new_keys:
                problems.append(f"{g.label}: the key at {sign.key_path(g)} is not the export key "
                                f"{shown(g.profile)} publishes")
                continue
            games.publish_key(key, pub, binary=binary)
            print(f"rewrote {shown(g.profile)}: ga:exportKey is now the public half of "
                  f"{sign.key_path(g)} (sha256 {sign.key_sha256(pub)[:16]}...)")
        keys[key] = priv
    if problems:
        raise SystemExit(
            "The games' published export keys are the trust anchors every receiver checks, so this "
            "build does not replace them on its own.\n  " + "\n  ".join(problems) + "\n"
            "Run `python3 scripts/build_site.py --check` to judge everything with throwaway keys and write "
            "nothing, or, if you maintain these games, `--new-keys` to make keys and rewrite the profiles.")
    return keys


def throwaway_keys(binary: str) -> tuple[Path, dict]:
    """A scratch copy of the games root in which every game publishes a key made now."""
    root = scratch("check") / "games"
    shutil.copytree(games.games_root(), root, ignore=shutil.ignore_patterns("__pycache__"))
    keys = {}
    for key in games.discover(root, binary):
        keys[key] = sign.generate()
        games.publish_key(key, sign.public_b64(keys[key]), root, binary)
    return root, keys


def main(argv: list[str] | None = None) -> None:
    try:
        _main(argv)
    finally:
        while _MADE:
            shutil.rmtree(_MADE.pop(), ignore_errors=True)


def _main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="judge everything with throwaway keys in a scratch copy of the games; write nothing")
    mode.add_argument("--new-keys", action="store_true",
                      help="make missing private keys and rewrite the games' published export keys")
    a = ap.parse_args(argv)

    binary = resolve_binary(engine_binary())
    known = games.discover(binary=binary)
    if len(known) != 2:
        # Checked before anything is written: the page and this script show two games side by side.
        raise SystemExit(f"the page shows two games side by side; the games root has {sorted(known)}. "
                         "The judging code and the command line take any number of games; the page does not.")
    if a.check:
        root, keys = throwaway_keys(binary)
        print(f"--check: throwaway keys in {root}; nothing in the repository will be written")
    else:
        root, keys = None, real_keys(known, binary, a.new_keys)
    known = games.discover(root, binary)
    # Passports are written to scratch first and moved into site/ only when the
    # whole build has succeeded, so a build that fails halfway leaves site/ as it was.
    packs_dir = scratch("packs")

    transfers = {}
    for game in known:
        for rec in catalogue(game, root):
            key = f"{game}:{rec['id']}"
            run = scratch("build")
            ex = export(game, rec, run, binary, root=root, key=keys[game])
            v = admit(ex["pack"], other(game, known), run, binary, root=root)
            d = judge_direct(game, rec, other(game, known), run, binary, root=root)
            agree = (v["verdict"] == d["verdict"] and v["conversion"] == d["conversion"])
            if not agree:
                raise SystemExit(f"{key}: passport lane {v['verdict']} {v['conversion']} "
                                 f"!= direct lane {d['verdict']} {d['conversion']}")
            if not (v["signature"] or {}).get("verified"):
                raise SystemExit(f"{key}: an honest, signed passport did not pass the signature gate: {v}")
            shutil.copy(ex["pack"], packs_dir / f"{game}-{rec['id']}.pack")
            v["passport"] = f"passports/{game}-{rec['id']}.pack"
            v["export_transcript"] = shown_transcript(ex["transcript"])
            v["transcript"] = shown_transcript(v["transcript"])
            v["lanes_agree"] = agree
            transfers[key] = v
            print(f"{key:24s} -> {other(game, known):6s} {v['verdict']:20s} {v['conversion']}")

    # The forgers' attempts on the Capture Orb. The page prints whatever admit() said.
    run = scratch("forge")
    packs = forge.forge_all(run, keys[forge.SOURCE], binary, root=root)
    forgeries = []
    for name, title, did, why in forge.ATTEMPTS:
        r = run / f"admit-{name}"
        r.mkdir()
        v = admit(packs[name], forge.TARGET, r, binary, root=root)
        v["transcript"] = shown_transcript(v["transcript"])
        through = v["verdict"] != "refused"
        forgeries.append({"name": name, "title": title, "did": did, "why": why,
                          "verdict": v, "gets_through": through})
        print(f"forgery {name:13s} -> {v['verdict']} at {v['stage']}"
              + ("  (gets through)" if through else ""))

    # Everything the page will read is computed first, from the scratch copies.
    # site/ is touched only after that, and last of all.
    out = page_data(known, root, binary, packs_dir, transfers, forgeries)
    if a.check:
        committed = json.loads((DATA / "verdicts.json").read_text())
        bad = page_differences(out, committed, root)
        if bad:
            print("\n".join(bad))
            raise SystemExit("--check: site/data/verdicts.json is not what the engine says now, in the fields "
                             "the page renders (the diff above). Rebuild it with python3 scripts/build_site.py.")
        for note in engine_differences(out, committed):
            print(f"--check: note: {note}")
        compared = ("every field the page renders" if same_engine(out, committed) else
                    "every field the page renders except the engine's replies in the transcripts")
        print(f"--check: site/data/verdicts.json gives what the engine says now, in {compared}")
        print("--check: done; nothing was written")
        return
    publish(packs_dir, json.dumps(scrub(out), indent=1))
    write_readme_table(transfers, forgeries, known)
    write_readme_example(transfers, known, root)
    print(f"wrote {DATA / 'verdicts.json'} ({(DATA / 'verdicts.json').stat().st_size // 1024} KB)")


def page_data(known: dict, root, binary: str, packs_dir: Path, transfers: dict, forgeries: list) -> dict:
    """The whole of site/data/verdicts.json, as a dict, before machine paths
    are scrubbed out of it."""
    oo_rev = subprocess.run(["git", "-C", str(OO), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip() if OO.exists() else None
    cert_bin = find_oo_cert()
    files = {"hub": (ROOT / "ontology" / "ga-core.ttl").read_text(),
             "rule": (ROOT / "rules" / "convert.rq").read_text()}
    for k, g in known.items():  # each discovered game's contracts, wherever discovery found them
        if g.border.exists():
            files[f"{k}_border"] = g.border.read_text()
        if g.loss.exists():
            files[f"{k}_loss"] = g.loss.read_text()
    first_pack = next(iter(sorted(packs_dir.glob("*.pack"))))
    return {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": {
            "binary_sha256": sha256(binary),
            "open_ontologies_rev": oo_rev,
            "tool_version": forge.read(first_pack)["manifest"].get("tool_version"),
            "oo_cert_sha256": sha256(cert_bin) if cert_bin else None,
        },
        "gates": list(GATES),
        "games": {k: {"label": g.label, "iri": g.iri, "items": catalogue(k, root),
                      "max_player_health": g.max_player_health,
                      "export_key_sha256": sign.key_sha256(g.export_key) if g.export_key else None,
                      "profile": g.profile.read_text()} for k, g in known.items()},
        "transfers": transfers,
        "forgeries": forgeries,
        "files": files,
    }


# ------------------------------------------------------------------ --check: what the page renders

# What changes from one honest build to the next, and is masked before two
# builds are compared: digests (of a pack, a certificate, a key, a binary),
# Ed25519 public keys and signatures (base64), and blank-node labels, which the
# engine mints afresh on every load.
_VOLATILE = [
    (re.compile(r"\b[0-9a-f]{64}\b"), "<sha256>"),
    (re.compile(r"_:[A-Za-z0-9]{16,}"), "_:<bnode>"),
    (re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{86}=="), "<signature>"),
    (re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{43}="), "<public key>"),
    # A pack's size in bytes: the engine writes a blank-node label as a random
    # number in hex without leading zeros, so the size moves by a few bytes.
    (re.compile(r'("(?:certificate_)?bytes\\?":)[0-9]+'), r"\1<bytes>"),
    # The Lean checkers sit wherever this machine keeps them; the page shows
    # the path the build saw, and another machine's path is not a difference.
    (re.compile(r"[^\s\"']*/(oo-cert|oo-shacl)\b"), r"<\1>"),
]


def _mask(text: str) -> str:
    for pattern, sub in _VOLATILE:
        text = pattern.sub(sub, text)
    return text


def _clip(s: str, n: int) -> str:
    return s[:n] + "…" if len(s) > n else s


def _js(x) -> str:
    """JSON.stringify(x), which the page uses to print a transcript entry."""
    return json.dumps(x, separators=(",", ":"), ensure_ascii=False)


def _verdict_view(v: dict, results: bool = True) -> dict:
    """The fields of one verdict that the page renders (site/app.js: gatePlan,
    stampFor, whatItDoes, renderPassport and the forgery cards), each as the
    page prints it. Without `results`, each transcript entry keeps its tool and
    arguments (written by this repository) and drops the engine's reply."""
    sig = v.get("signature")
    calls = (v.get("export_transcript") or []) + (v.get("transcript") or [])
    return {
        "verdict": v.get("verdict"), "stage": v.get("stage"), "headline": v.get("headline"),
        "refusals": [r.get("message") for r in v.get("refusals") or []],
        "losses": [r.get("message") for r in v.get("losses") or []],
        "notes": [r.get("message") for r in v.get("notes") or []],
        "hub_types": v.get("hub_types"), "source": v.get("source"), "target": v.get("target"),
        "conversion": v.get("conversion"), "drift": v.get("drift"), "why": v.get("why"),
        "proof": {k: (v.get("proof") or {}).get(k) for k in ("status", "derivations", "theorem")},
        "evaluators": v.get("evaluators"),
        "signature": None if sig is None else {"label": sig.get("label"), "verified": sig.get("verified"),
                                               "public_key_sha256": sig.get("public_key_sha256")},
        "passport": v.get("passport"),
        # Masked before it is clipped, so a digest cut in half at the clip is
        # not read as a difference.
        "transcript": [[c.get("tool"), _clip(_mask(_js(c.get("args"))), 140)]
                       + ([_clip(_mask(_js(c.get("result"))), 260)] if results else [])
                       for c in calls],
    }


def page_view(data: dict, results: bool = True) -> dict:
    """Every field of verdicts.json the page renders, with what changes from
    one honest build to the next masked (_VOLATILE). Left out: built_at (a
    timestamp) and the engine block, which is compared on its own
    (engine_differences), and export_key_sha256, which the page does not show.
    `results` is passed on to _verdict_view."""
    view = {
        "gates": data.get("gates"),
        "games": {k: {"label": g.get("label"), "iri": g.get("iri"), "items": g.get("items"),
                      "max_player_health": g.get("max_player_health"), "profile": g.get("profile")}
                  for k, g in (data.get("games") or {}).items()},
        "transfers": {k: _verdict_view(v, results) for k, v in (data.get("transfers") or {}).items()},
        "forgeries": [{"name": f.get("name"), "title": f.get("title"), "did": f.get("did"), "why": f.get("why"),
                       "gets_through": f.get("gets_through"), "verdict": _verdict_view(f.get("verdict") or {}, results)}
                      for f in data.get("forgeries") or []],
        "files": data.get("files"),
    }
    return json.loads(_mask(json.dumps(view, ensure_ascii=False)))


def engine_differences(engine_out: dict, committed: dict) -> list[str]:
    """Where the engine this check ran differs from the one that built the
    committed file. The page's footer names the engine that built it, which
    stays true when another engine reproduces every verdict, so these are
    printed as notes, not refused."""
    mine, theirs = engine_out.get("engine") or {}, committed.get("engine") or {}
    notes = [f"the committed file was built by {k} {theirs.get(k)!r}; this check ran {mine.get(k)!r}"
             for k in sorted(set(mine) | set(theirs)) if mine.get(k) != theirs.get(k)]
    if not same_engine(engine_out, committed):
        notes.append("this check ran another engine binary than the one that built the file, so the engine's "
                     "replies in the transcripts were not compared; every other rendered field was")
    return notes


def same_engine(engine_out: dict, committed: dict) -> bool:
    """Did this check run the very engine binary that built the committed file?"""
    sha = (engine_out.get("engine") or {}).get("binary_sha256")
    return sha is not None and sha == (committed.get("engine") or {}).get("binary_sha256")


def page_differences(engine_out: dict, committed: dict, root=None) -> list[str]:
    """A unified diff of what the page would render from the engine's output
    now and from the committed verdicts.json; empty when they agree. `root`
    is the scratch games root a --check run judged in: its path stands where
    the committed file has the repository's games/.

    The engine's replies in the transcript are compared only when this check
    ran the binary that built the file. Another build words its replies its
    own way (measured: the engine at the commit CI pins leaves
    focus_nodes_by_target out of every onto_shacl reply), and the page's
    transcript is a record of the engine its footer names. Every verdict,
    message, number, step and argument is compared either way."""
    results = same_engine(engine_out, committed)
    text = json.dumps(scrub(engine_out), ensure_ascii=False)
    if root is not None:
        for form in {str(root), str(Path(root).resolve())}:
            text = text.replace(scrub({"p": form})["p"], "games")
    mine = json.dumps(page_view(json.loads(text), results), indent=1, sort_keys=True, ensure_ascii=False).splitlines()
    theirs = json.dumps(page_view(committed, results), indent=1, sort_keys=True, ensure_ascii=False).splitlines()
    return list(difflib.unified_diff(theirs, mine, "site/data/verdicts.json", "the engine now", lineterm="", n=2))


def publish(packs_dir: Path, verdicts: str) -> None:
    """Put the new passports and verdicts.json in place together. Both are
    written beside their final places first, then each is renamed into place,
    so the passports on disk and the verdicts that cite them are swapped one
    straight after the other, with nothing left to compute in between."""
    DATA.mkdir(parents=True, exist_ok=True)
    new_packs = PASSPORTS.with_name(PASSPORTS.name + ".new")
    old_packs = PASSPORTS.with_name(PASSPORTS.name + ".old")
    new_verdicts = DATA / "verdicts.json.new"
    for leftover in (new_packs, old_packs):
        if leftover.exists():
            shutil.rmtree(leftover)
    shutil.copytree(packs_dir, new_packs)
    new_verdicts.write_text(verdicts)
    if PASSPORTS.exists():
        os.replace(PASSPORTS, old_packs)
    os.replace(new_packs, PASSPORTS)
    os.replace(new_verdicts, DATA / "verdicts.json")
    if old_packs.exists():
        shutil.rmtree(old_packs)


def _num(x) -> str:
    return str(int(x)) if isinstance(x, (int, float)) and x == int(x) else str(x)


def write_readme_example(transfers: dict, known: dict, root) -> None:
    """The README's worked example, with every number taken from the data and
    the engine: the item's own stats, each game's ga:maxPlayerHealth as the
    engine read it, and the converted values the engine computed."""
    craft, battle = known["craft"], known["battle"]
    sword = next(r for r in catalogue("craft", root) if r["id"] == "crystal_sword")
    blast = next(r for r in catalogue("craft", root) if r["id"] == "blast_block")
    sv, bv = transfers["craft:crystal_sword"], transfers["craft:blast_block"]
    rock = str(sv["conversion"].get("typeInTarget", "")).split(":")[-1]
    text = (f"A {sword['name']} deals {_num(sword['attack'])} of a player's {_num(craft.max_player_health)} HP in "
            f"{craft.label}. In {battle.label} it becomes a move with power "
            f"{_num(sv['conversion']['damageInTarget'])} of {_num(battle.max_player_health)}, and its type is {rock}. "
            "Nobody typed that type. Blockcraft's profile says \"anything made of crystal is Rock-typed\", and the "
            f"engine derives the rest, so the sword is strong against a Fire creature. A {blast['name']} is "
            f"{bv['verdict']}, because {_num(blast['blastDamage'])} of {_num(craft.max_player_health)} HP becomes "
            f"{_num(bv['conversion']['damageInTarget'])} of {_num(battle.max_player_health)}, which would knock out "
            "a full-health creature in one turn. A Capture Orb is "
            f"{transfers['battle:capture_orb']['verdict']} by {craft.label}, where nothing can own a mob.")
    _replace_block("example", text)


def _replace_block(name: str, body: str) -> None:
    readme = ROOT / "README.md"
    text = readme.read_text()
    a, b = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    head, rest = text.split(a, 1)
    _, tail = rest.split(b, 1)
    readme.write_text(head + a + "\n" + body + "\n" + b + tail)


def write_readme_table(transfers: dict, forgeries: list, known: dict) -> None:
    """The README's results table, written from the same output the page reads."""
    label = {k: g.label for k, g in known.items()}
    rows = ["| Item | Into | Verdict | Converted values | Proof steps (Lean) |", "|---|---|---|---|---|"]
    for key, v in transfers.items():
        game, item = key.split(":")
        conv = ", ".join(f"{k} {x}" for k, x in v["conversion"].items() if k.endswith("InTarget")) or "none"
        rows.append(f"| {label[game]} `{item}` | {label[v['target']]} | {v['verdict']} | {conv} | "
                    f"{v['proof'].get('derivations')} |")
    rows += ["", "| Forgery on the Capture Orb | Result | Stopped at |", "|---|---|---|"]
    for f in forgeries:
        v = f["verdict"]
        at = f"gate {GATES.index(v['stage']) + 1}, {v['stage']}" if v["verdict"] == "refused" else "gets through"
        rows.append(f"| {f['title']} | {v['verdict']} | {at} |")
    _replace_block("verdicts", "\n".join(rows))


if __name__ == "__main__":
    main()
