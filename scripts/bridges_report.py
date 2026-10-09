"""Write the generated sections of docs/BRIDGES.md from the engine's verdicts.

    python3 scripts/bridges_report.py          # rewrite the sections
    python3 scripts/bridges_report.py --check  # exit 1 if they are stale

Every number in those sections is read off passport.bridge.check(), which reads
it off the engine. Nothing in them is typed by hand.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from passport.bridge import SPACE, check  # noqa: E402
from passport.engine import Engine, scratch  # noqa: E402

DOC = ROOT / "docs" / "BRIDGES.md"
EX = ROOT / "examples" / "bridges"
GROUPS = [("um-", "Universal Modder's table, as written"),
          ("src-", "The same projects, read from their own source"),
          ("syn-", "This repository's own games"),
          ("wrong-", "Wrong on purpose")]
FORM = {"declaredHostUnitsPerGuestUnit": "host units per guest unit",
        "declaredHostUnitsPerMetre": "host units per metre",
        "declaredMetresPerGuestUnit": "m per guest unit",
        "declaredMetresPerHostUnit": "m per host unit",
        "declaredSpanHostUnits": "host units per metre, from a stated span"}


def n(x) -> str:
    if x is None:
        return "none"
    if isinstance(x, bool):
        return str(x).lower()
    if isinstance(x, int):
        return str(x)
    return f"{x:.6g}"


def pct(x) -> str:
    return "none" if x is None else f"{x * 100:.4g}%"


def cell(c: dict, key: str) -> str:
    v = c[key]["verdict"]
    return "" if v == "not_declared" else f"**{v}**" if v == "refused" else v


def units_text(c: dict) -> list[str]:
    out = []
    for d in c.get("declarations", []):
        declared = d["declared"]
        if isinstance(declared, dict):
            declared = f"{n(declared['host_units'])} host units in {n(declared['metres'])} m"
            said = f"{declared} ({n(d.get('ratio_as_declared'))} {FORM[d['form']]})"
        else:
            said = f"{n(declared)} {FORM[d['form']]}"
        if d.get("best_relative_error") is None:
            out.append(f"Units: {said}; {d['verdict']}: " + "; ".join(d.get("missing") or []) + ".")
            continue
        lo, hi = d["implied_low"], d["implied_high"]
        implied = n(lo) if lo == hi else f"{n(lo)} to {n(hi)}"
        err = pct(d["best_relative_error"]) if d["best_relative_error"] == d["worst_relative_error"] \
            else f"{pct(d['best_relative_error'])} to {pct(d['worst_relative_error'])}"
        out.append(f"Units: {said}; the sourced unit lengths imply {implied}, off by {err}; {d['verdict']}.")
    return out


def row_text(b: dict) -> str:
    c = b["checks"]
    parts = []
    a = c["axes"]
    if a["verdict"] != "not_declared":
        decl = ", ".join(f"{k} = host {v}" for k, v in sorted(a["declared"].items()))
        der = ", ".join(f"{k} = host {v}" for k, v in sorted(a.get("derived", {}).items())) or "nothing"
        parts.append(f"Axes: declares guest {decl}; the sourced directions give {der}; {a['verdict']}"
                     + (": " + "; ".join(a["missing"]) if a.get("missing") else "") + ".")
    h = c["handedness"]
    if h["verdict"] != "not_declared":
        if h.get("handedness") is None:
            parts.append(f"Handedness: {h['verdict']}: " + "; ".join(h.get("missing") or []) + ".")
        else:
            parts.append(f"Handedness: the map's determinant through both bases is {n(h['handedness'])}, "
                         f"and the bridge declares {n(h['declared_handedness'])}; {h['verdict']}.")
    parts += units_text(c["units"])
    he = c["health"]
    if he["verdict"] != "not_declared":
        if he.get("declared_multiplier") is None:
            parts.append(f"Health: declared native; {he['verdict']}.")
        else:
            native = "native and " if he.get("declared_native") else ""
            parts.append(f"Health: declares {native}times {n(he['declared_multiplier'])}; the proportional policy "
                         f"(host maximum over guest maximum) is {n(he.get('policy_multiplier'))}; {he['verdict']}"
                         + (": " + "; ".join(he["missing"]) if he.get("missing") else "") + ".")
    for k in ("declaration", "facts"):
        if c[k]["verdict"] == "refused":
            parts.append(f"{k.capitalize()}: refused: " + " ".join(c[k]["refusals"]))
    return " ".join(parts)


def results_section(runs: dict[str, dict]) -> str:
    lines = []
    for prefix, title in GROUPS:
        names = [k for k in runs if k.startswith(prefix)]
        if not names:
            continue
        lines += [f"#### {title}", "",
                  "| File | Row | Evidence | Axes | Handedness | Units | Health | Verdict | Exit |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for name in names:
            r = runs[name]
            (b,) = r["bridges"]
            c = b["checks"]
            v = f"**{b['verdict']}**" if b["verdict"] == "refused" else b["verdict"]
            lines.append(f"| `{name}.ttl` | {b['label']} | {b['evidence']} | {cell(c, 'axes')} | "
                         f"{cell(c, 'handedness')} | {cell(c, 'units')} | {cell(c, 'health')} | {v} | {r['exit']} |")
        lines.append("")
        for name in names:
            (b,) = runs[name]["bridges"]
            lines.append(f"- **{b['label']}** ({b['host']} hosting {b['guest']}). {row_text(b)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def facts_section() -> str:
    """Every sourced game fact in ontology/ga-space.ttl, with what the engine
    derives from it (metres per unit, basis determinant)."""
    import passport.bridge as pb
    with Engine(scratch("facts")) as e:
        e.call("onto_clear")
        e.load(SPACE)
        pb._apply_rule(e)
        rows = pb._rows(e, """
            SELECT ?label ?kind ?ev ?units ?metres ?feet ?inches ?dir ?axis ?health ?mpu ?det ?src ?arch ?quote ?level ?note
            WHERE {
              ?g a ga:Game ; <http://www.w3.org/2000/01/rdf-schema#label> ?label ; ?kind ?ev .
              FILTER (?kind IN (ga:lengthEvidence, ga:axisEvidence, ga:healthEvidence))
              ?ev ga:source ?src ; ga:quote ?quote ; ga:evidenceLevel ?level .
              OPTIONAL { ?ev ga:units ?units } OPTIONAL { ?ev ga:metres ?metres }
              OPTIONAL { ?ev ga:feet ?feet } OPTIONAL { ?ev ga:inches ?inches }
              OPTIONAL { ?ev ga:direction ?dir } OPTIONAL { ?ev ga:axis ?axis }
              OPTIONAL { ?ev ga:maxHealth ?health } OPTIONAL { ?ev ga:metresPerUnit ?mpu }
              OPTIONAL { ?g ga:basisDeterminant ?det } OPTIONAL { ?ev ga:archivedCopy ?arch }
              OPTIONAL { ?ev ga:note ?note }
            } ORDER BY ?label ?kind ?dir ?ev""")
    v = lambda r, k: pb._value(r[k]) if k in r else None
    lines = ["| Game | Fact | Engine derives | Evidence | Source | Quote |", "|---|---|---|---|---|---|"]
    for r in rows:
        kind = pb._local(r["kind"])
        if kind == "lengthEvidence":
            length = (f"{n(v(r, 'metres'))} m" if "metres" in r else f"{n(v(r, 'feet'))} ft" if "feet" in r
                      else f"{n(v(r, 'inches'))} in")
            units = v(r, "units")
            fact = f"{n(units)} unit{'' if units == 1 else 's'} = {length}"
            derived = f"{n(v(r, 'mpu'))} m per unit"
        elif kind == "axisEvidence":
            fact = f"{pb._local(r['dir'])} is {v(r, 'axis')}"
            derived = f"basis determinant {n(v(r, 'det'))}" if "det" in r else "basis incomplete"
        else:
            fact, derived = f"maximum health {n(v(r, 'health'))}", ""
        src = v(r, "src")
        link = f"[page]({src})" + (f", [copy opened]({v(r, 'arch')})" if "arch" in r else "")
        quote = str(v(r, "quote")).replace("|", "\\|")
        if "note" in r:
            quote += " *(Our reading: " + str(v(r, "note")).replace("|", "\\|") + ")*"
        lines.append(f"| {v(r, 'label')} | {fact} | {derived} | {v(r, 'level')} | {link} | {quote} |")
    return "\n".join(lines) + "\n"


def render(doc: str) -> str:
    runs = {p.stem: check(p) for p in sorted(EX.glob("*.ttl"),
                                             key=lambda p: ([g for g, _ in GROUPS].index(p.stem.split("-")[0] + "-"), p.stem))}
    for name, body in (("results", results_section(runs)), ("facts", facts_section())):
        start, end = f"<!-- bridges:{name}:start -->", f"<!-- bridges:{name}:end -->"
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
        if not pattern.search(doc):
            raise SystemExit(f"docs/BRIDGES.md has no {start} marker")
        doc = pattern.sub(lambda _: f"{start}\n{body}{end}", doc)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if docs/BRIDGES.md is stale")
    args = ap.parse_args()
    old = DOC.read_text()
    new = render(old)
    if args.check:
        if new != old:
            print("docs/BRIDGES.md is stale: run python3 scripts/bridges_report.py", file=sys.stderr)
            return 1
        print("docs/BRIDGES.md is current")
        return 0
    DOC.write_text(new)
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
