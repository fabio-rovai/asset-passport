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

from passport import forge  # noqa: E402
from passport.engine import engine_binary, scratch  # noqa: E402
from passport.present import compact, scrub  # noqa: E402
from passport.judge import (GAMES, admit, catalogue, export, find_oo_cert,  # noqa: E402
                            game_dir, judge_direct)

SITE = ROOT / "site"
DATA = SITE / "data"
PASSPORTS = SITE / "passports"
OO = ROOT.parent / "open-ontologies"


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def other(game: str) -> str:
    return next(g for g in GAMES if g != game)


def doctored_battle(dir_: Path) -> Path:
    p = dir_ / "doctored-battle-profile.ttl"
    src = (game_dir("battle") / "profile.ttl").read_text()
    needle = "battle:CaptureOrb a owl:Class ; rdfs:subClassOf ga:CaptureDevice"
    assert needle in src, "the doctored profile no longer matches the published one"
    p.write_text(src.replace(needle, "battle:CaptureOrb a owl:Class ; rdfs:subClassOf ga:HealingConsumable"))
    return p


def main() -> None:
    binary = engine_binary()
    DATA.mkdir(parents=True, exist_ok=True)
    if PASSPORTS.exists():
        shutil.rmtree(PASSPORTS)
    PASSPORTS.mkdir(parents=True)

    transfers = {}
    for game in GAMES:
        for rec in catalogue(game):
            key = f"{game}:{rec['id']}"
            run = scratch("build")
            ex = export(game, rec, run, binary)
            v = admit(ex["pack"], other(game), run, binary)
            d = judge_direct(game, rec, other(game), run, binary)
            agree = (v["verdict"] == d["verdict"] and v["conversion"] == d["conversion"])
            if not agree:
                raise SystemExit(f"{key}: passport lane {v['verdict']} {v['conversion']} "
                                 f"!= direct lane {d['verdict']} {d['conversion']}")
            shutil.copy(ex["pack"], PASSPORTS / f"{game}-{rec['id']}.pack")
            v["passport"] = f"passports/{game}-{rec['id']}.pack"
            v["export_transcript"] = compact(ex["transcript"])
            v["transcript"] = compact(v["transcript"])
            v["lanes_agree"] = agree
            transfers[key] = v
            print(f"{key:24s} -> {other(game):6s} {v['verdict']:20s} {v['conversion']}")

    # The forger's attempts on the Capture Orb, each against the same honest passport.
    run = scratch("forge")
    orb = next(r for r in catalogue("battle") if r["id"] == "capture_orb")
    honest = export("battle", orb, run, binary)
    item = honest["item_iri"]
    attempts = [
        ("tamper", "Edit the passport",
         "Delete the line that says the orb is a capture device. Leave the digests alone.",
         forge.tamper(forge.read(honest["pack"]), item)),
        ("unhook", "Edit it, then fix the digests",
         "Delete the same line, then recompute both SHA-256 digests the way the engine does. "
         "A digest is not a signature: anyone can recompute it.",
         forge.unhook(forge.read(honest["pack"]), item)),
        ("false_step", "Forge the proof",
         "Rewrite the certificate's step so it concludes the orb is a healing item, "
         "change the graph to match, and recompute the digests.",
         forge.false_step(forge.read(honest["pack"]), item)),
    ]
    forgeries = []
    for name, title, did, pack in attempts:
        r = run / name
        r.mkdir()
        v = admit(forge.write(pack, run / f"{name}.pack"), "craft", r, binary)
        v["transcript"] = compact(v["transcript"])
        forgeries.append({"name": name, "title": title, "did": did, "verdict": v})
        print(f"forgery {name:11s} -> {v['verdict']} at {v['stage']}")

    r = run / "own_rules"
    r.mkdir()
    ex = export("battle", orb, r, binary, profile=doctored_battle(r))
    v = admit(ex["pack"], "craft", r, binary)
    v["transcript"] = compact(v["transcript"])
    forgeries.append({"name": "own_rules", "title": "Bring your own rules",
                      "did": "Export the orb honestly, but under a doctored copy of Pocket Battlers' "
                             "profile that says a capture orb is a healing item. The proof is real "
                             "and Lean accepts it: it is sound over the doctored premises.",
                      "verdict": v})
    print(f"forgery own_rules   -> {v['verdict']} at {v['stage']}")

    # Where the guarantee ends: a sender who lies about the item itself.
    r = run / "lie"
    r.mkdir()
    lie = {"id": "capture_orb", "kind": "SuperPotion", "name": "Capture Orb", "restoresHp": 10}
    ex = export("battle", lie, r, binary)
    v = admit(ex["pack"], "craft", r, binary)
    v["transcript"] = compact(v["transcript"])
    forgeries.append({"name": "lie", "title": "Lie about the item",
                      "did": "Export the orb with its kind field set to SuperPotion, under "
                             "Pocket Battlers' real profile. Every step from there is honest.",
                      "verdict": v, "gets_through": v["verdict"] != "refused"})
    print(f"forgery lie         -> {v['verdict']} at {v['stage']}  (expected to get through)")

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
        "games": {g: {"label": GAMES[g]["label"], "items": catalogue(g),
                      "profile": (game_dir(g) / "profile.ttl").read_text()} for g in GAMES},
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
    write_readme_table(transfers, forgeries)
    print(f"wrote {DATA / 'verdicts.json'} ({(DATA / 'verdicts.json').stat().st_size // 1024} KB)")


def write_readme_table(transfers: dict, forgeries: list) -> None:
    """The README's results table, written from the same output the page reads."""
    label = {g: GAMES[g]["label"] for g in GAMES}
    rows = ["| Item | Into | Verdict | Converted values | Proof steps (Lean) |", "|---|---|---|---|---|"]
    for key, v in transfers.items():
        game, item = key.split(":")
        conv = ", ".join(f"{k} {x}" for k, x in v["conversion"].items() if k.endswith("InTarget")) or "none"
        rows.append(f"| {label[game]} `{item}` | {label[v['target']]} | {v['verdict']} | {conv} | "
                    f"{v['proof'].get('derivations')} |")
    rows += ["", "| Forgery on the Capture Orb | Result | Stopped at |", "|---|---|---|"]
    for f in forgeries:
        v = f["verdict"]
        rows.append(f"| {f['title']} | {v['verdict']} | {v['stage'] if v['verdict'] == 'refused' else 'gets through'} |")
    readme = ROOT / "README.md"
    text = readme.read_text()
    a, b = "<!-- verdicts:start -->", "<!-- verdicts:end -->"
    head, rest = text.split(a, 1)
    _, tail = rest.split(b, 1)
    readme.write_text(head + a + "\n" + "\n".join(rows) + "\n" + b + tail)


if __name__ == "__main__":
    main()
