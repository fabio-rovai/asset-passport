"""Judge every catalogue item and every forgery with the real engine, and write
what it said to site/data/. Nothing on the page is typed by hand: each verdict,
number, message and proof status is copied from an engine or checker response.

    python3 scripts/build_site.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from passport import forge, games, sign  # noqa: E402
from passport.engine import engine_binary, scratch  # noqa: E402
from passport.present import compact, scrub  # noqa: E402
from passport.judge import (GATES, admit, catalogue, export, find_oo_cert,  # noqa: E402
                            judge_direct)

SITE = ROOT / "site"
DATA = SITE / "data"
PASSPORTS = SITE / "passports"
OO = ROOT.parent / "open-ontologies"


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def other(game: str, known: dict) -> str:
    return next(g for g in known if g != game)


def ensure_keys(binary: str) -> dict:
    """Each game's private export key, from outside the repository. A missing
    key is generated, and the game's profile is rewritten to publish its public
    half; a profile that publishes a different key from the one on this machine
    is rewritten too. Both are said out loud, because both change a committed file."""
    keys = {}
    for key, g in games.discover(binary=binary).items():
        priv = sign.load_private(key)
        if priv is None:
            priv = sign.generate()
            path = sign.write_private(key, priv)
            print(f"no export key for {g.label}: generated one at {path}")
        pub = sign.public_b64(priv)
        if g.export_key != pub:
            games.publish_key(key, pub, binary=binary)
            print(f"rewrote {g.profile.relative_to(ROOT)}: ga:exportKey is now the public half of "
                  f"{sign.key_path(key)} (sha256 {sign.key_sha256(pub)[:16]}...)")
        keys[key] = priv
    return keys


def main() -> None:
    binary = engine_binary()
    DATA.mkdir(parents=True, exist_ok=True)
    keys = ensure_keys(binary)
    known = games.discover(binary=binary)
    if len(known) != 2:
        raise SystemExit(f"the page shows two games side by side; the games root has {sorted(known)}")
    if PASSPORTS.exists():
        shutil.rmtree(PASSPORTS)
    PASSPORTS.mkdir(parents=True)

    transfers = {}
    for game in known:
        for rec in catalogue(game):
            key = f"{game}:{rec['id']}"
            run = scratch("build")
            ex = export(game, rec, run, binary, key=keys[game])
            v = admit(ex["pack"], other(game, known), run, binary)
            d = judge_direct(game, rec, other(game, known), run, binary)
            agree = (v["verdict"] == d["verdict"] and v["conversion"] == d["conversion"])
            if not agree:
                raise SystemExit(f"{key}: passport lane {v['verdict']} {v['conversion']} "
                                 f"!= direct lane {d['verdict']} {d['conversion']}")
            if not (v["signature"] or {}).get("verified"):
                raise SystemExit(f"{key}: an honest, signed passport did not pass the signature gate: {v}")
            shutil.copy(ex["pack"], PASSPORTS / f"{game}-{rec['id']}.pack")
            v["passport"] = f"passports/{game}-{rec['id']}.pack"
            v["export_transcript"] = compact(ex["transcript"])
            v["transcript"] = compact(v["transcript"])
            v["lanes_agree"] = agree
            transfers[key] = v
            print(f"{key:24s} -> {other(game, known):6s} {v['verdict']:20s} {v['conversion']}")

    # The forgers' attempts on the Capture Orb. The page prints whatever admit() said.
    run = scratch("forge")
    packs = forge.forge_all(run, keys[forge.SOURCE], binary)
    forgeries = []
    for name, title, did, why in forge.ATTEMPTS:
        r = run / f"admit-{name}"
        r.mkdir()
        v = admit(packs[name], forge.TARGET, r, binary)
        v["transcript"] = compact(v["transcript"])
        through = v["verdict"] != "refused"
        forgeries.append({"name": name, "title": title, "did": did, "why": why,
                          "verdict": v, "gets_through": through})
        print(f"forgery {name:13s} -> {v['verdict']} at {v['stage']}"
              + ("  (gets through)" if through else ""))

    oo_rev = subprocess.run(["git", "-C", str(OO), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip() if OO.exists() else None
    cert_bin = find_oo_cert()
    out = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": {
            "binary_sha256": sha256(binary),
            "open_ontologies_rev": oo_rev,
            "tool_version": forge.read(PASSPORTS / "craft-diamond_sword.pack")["manifest"].get("tool_version"),
            "oo_cert_sha256": sha256(cert_bin) if cert_bin else None,
        },
        "gates": list(GATES),
        "games": {k: {"label": g.label, "iri": g.iri, "items": catalogue(k),
                      "export_key_sha256": sign.key_sha256(g.export_key) if g.export_key else None,
                      "profile": g.profile.read_text()} for k, g in known.items()},
        "transfers": transfers,
        "forgeries": forgeries,
        "files": {
            "hub": (ROOT / "ontology" / "ga-core.ttl").read_text(),
            "rule": (ROOT / "rules" / "convert.rq").read_text(),
            "craft_border": (ROOT / "contracts" / "craft-border.shacl.ttl").read_text(),
            "battle_border": (ROOT / "contracts" / "battle-border.shacl.ttl").read_text(),
            "craft_loss": (ROOT / "contracts" / "craft-loss.shacl.ttl").read_text(),
            "battle_loss": (ROOT / "contracts" / "battle-loss.shacl.ttl").read_text(),
        },
    }
    (DATA / "verdicts.json").write_text(json.dumps(scrub(out), indent=1))
    write_readme_table(transfers, forgeries, known)
    print(f"wrote {DATA / 'verdicts.json'} ({(DATA / 'verdicts.json').stat().st_size // 1024} KB)")


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
    readme = ROOT / "README.md"
    text = readme.read_text()
    a, b = "<!-- verdicts:start -->", "<!-- verdicts:end -->"
    head, rest = text.split(a, 1)
    _, tail = rest.split(b, 1)
    readme.write_text(head + a + "\n" + "\n".join(rows) + "\n" + b + tail)


if __name__ == "__main__":
    main()
