"""Checks that the verdicts the page ships are the verdicts the engine gives now.

    python3 tests/e2e/ci/engine_matches_page.py                    # runs scripts/build_site.py --check
    python3 tests/e2e/ci/engine_matches_page.py --output check.txt  # compares a saved --check output

The browser tests trust site/data/verdicts.json: the page draws every stamp and
number from it. `build_site.py --check` judges every catalogue item and every
forgery with the engine on throwaway keys, writes nothing, and itself fails
with a diff unless the committed file gives what the engine says in every field
the page renders: verdicts, stages, headlines, refusals, losses, converted
values, the "why" steps, proof status and step count, evaluators, the forgery
cards, the games' items and profiles, the source files, and each transcript
entry as the page prints it (the engine's replies only when the check ran the
binary that built the file). Digests, keys, signatures, pack sizes, blank-node
labels and timestamps change from one honest build to the next and are masked.

This script runs --check, so it fails on any of those differences, and then
reads the lines --check printed and refuses unless the committed file says the
same for every transfer (target, verdict and every converted value) and for
every forgery (verdict, the gate that decided, whether it gets through, and the
order the page shows them in). With --output it compares a saved --check output
by those lines alone.

It needs an engine that can carry a certificate in a pack (open-ontologies
#266), so CI runs it in the job that builds the engine from main.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VERDICTS = ROOT / "site" / "data" / "verdicts.json"

# The two line shapes build_site.py prints, one per transfer and one per forgery:
#   craft:crystal_sword      -> battle converted             {'typeInTarget': 'ga:Rock', 'damageInTarget': 30}
#   forgery source_lies   -> converted at border  (gets through)
TRANSFER = re.compile(r"^(?P<key>[A-Za-z0-9_-]+:[A-Za-z0-9_-]+)\s+-> (?P<target>\S+)\s+(?P<verdict>\S+)\s+(?P<conversion>\{.*\})$")
FORGERY = re.compile(r"^forgery (?P<name>\S+)\s+-> (?P<verdict>\S+) at (?P<stage>\S+)(?P<through>  \(gets through\))?$")


def parse(output: str) -> tuple[dict, list]:
    transfers, forgeries = {}, []
    for line in output.splitlines():
        m = TRANSFER.match(line)
        if m:
            if m["key"] in transfers:
                raise ValueError(f"--check printed {m['key']} twice")
            transfers[m["key"]] = {"target": m["target"], "verdict": m["verdict"],
                                   "conversion": ast.literal_eval(m["conversion"])}
            continue
        m = FORGERY.match(line)
        if m:
            forgeries.append({"name": m["name"], "verdict": m["verdict"], "stage": m["stage"],
                              "gets_through": bool(m["through"])})
    return transfers, forgeries


def differences(output: str, data: dict) -> list[str]:
    """Every way the committed data disagrees with the engine's output. Empty means they agree."""
    if "--check: done; nothing was written" not in output:
        return ["build_site.py --check did not finish; its output does not end with its done line"]
    engine_t, engine_f = parse(output)
    if not engine_t or not engine_f:
        return [f"--check printed {len(engine_t)} transfers and {len(engine_f)} forgeries; "
                "its output format may have changed, so nothing was compared"]
    bad = []
    page_t = data.get("transfers", {})
    for key in sorted(set(engine_t) | set(page_t)):
        if key not in page_t:
            bad.append(f"{key}: the engine judged it, but verdicts.json has no such transfer")
            continue
        if key not in engine_t:
            bad.append(f"{key}: verdicts.json has it, but the engine did not judge it")
            continue
        e, p = engine_t[key], page_t[key]
        for field in ("target", "verdict", "conversion"):
            if e[field] != p.get(field):
                bad.append(f"{key}: {field} is {p.get(field)!r} in verdicts.json and {e[field]!r} from the engine")
    page_f = [{"name": f.get("name"), "verdict": (f.get("verdict") or {}).get("verdict"),
               "stage": (f.get("verdict") or {}).get("stage"), "gets_through": f.get("gets_through")}
              for f in data.get("forgeries", [])]
    if [f["name"] for f in page_f] != [f["name"] for f in engine_f]:
        bad.append(f"forgeries: verdicts.json lists {[f['name'] for f in page_f]}, "
                   f"the engine judged {[f['name'] for f in engine_f]}")
    by_name = {f["name"]: f for f in page_f}
    for e in engine_f:
        p = by_name.get(e["name"])
        if p is None:
            continue
        for field in ("verdict", "stage", "gets_through"):
            if e[field] != p[field]:
                bad.append(f"forgery {e['name']}: {field} is {p[field]!r} in verdicts.json and {e[field]!r} from the engine")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--output", type=Path, help="a saved build_site.py --check output to compare instead of running it")
    ap.add_argument("--verdicts", type=Path, default=VERDICTS, help="the verdicts file to check (default: site/data/verdicts.json)")
    a = ap.parse_args(argv)
    if a.output:
        output = a.output.read_text()
    else:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py"), "--check"],
                           cwd=ROOT, capture_output=True, text=True)
        output = r.stdout
        sys.stdout.write(r.stdout)
        if r.returncode != 0:
            sys.stdout.write(r.stderr)
            print(f"REFUSED: build_site.py --check exited with {r.returncode}")
            return 1
    bad = differences(output, json.loads(a.verdicts.read_text()))
    for line in bad:
        print(f"REFUSED: {line}")
    if bad:
        print(f"{a.verdicts} does not match the engine. Rebuild it with python3 scripts/build_site.py.")
        return 1
    t, f = parse(output)
    print(f"verdicts.json matches the engine: {len(t)} transfers and {len(f)} forgeries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
