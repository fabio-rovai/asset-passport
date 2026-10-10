"""Check the "Units and axes" and health rows of a two-game bridge contract.

    python3 -m passport.bridge check examples/bridges/um-skycraft.ttl

The engine decides. First it runs two input guards, each on its input alone:
rules/bridge-input.rq on the bridge file (a bridge file may describe only its
bridges, never a game fact or anything the rule derives) and
rules/facts-input.rq on ontology/ga-space.ttl and any --facts file (a facts
file may state only sourced game facts). A row from either refuses the run.
Then it loads the facts and the bridge file into one store, applies
rules/bridge.rq until it adds nothing new, and runs contracts/bridge.shacl.ttl
on both of the engine's SHACL evaluators. A check is refused when the contract
refuses it, and both evaluators must return the same refusals or nothing is
claimed. A check is undetermined when a fact it needs has no source, so the
rule derived nothing to compare. When every fact a check needs is sourced and
the engine still returned no value, the check is refused: a declaration the
engine cannot evaluate is not admitted. A health policy declared native is
reported as not checked, because there is nothing to compare it with.

Game facts come from ontology/ga-space.ttl. A run given --facts also reads the
named file, is marked synthetic in its output, and exists so that tests can
build a game with a broken fact.

Exit status: 0 when every declared check holds, 1 when any check is refused,
2 when nothing is refused but something is undetermined, or the run failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import GA, ROOT, Engine, EngineError, scratch

SPACE = ROOT / "ontology" / "ga-space.ttl"
RULE = ROOT / "rules" / "bridge.rq"
BRIDGE_GUARD = ROOT / "rules" / "bridge-input.rq"
FACTS_GUARD = ROOT / "rules" / "facts-input.rq"
CONTRACT = ROOT / "contracts" / "bridge.shacl.ttl"
MAX_PASSES = 6

HOLDS, REFUSED, UNDETERMINED = "holds", "refused", "undetermined"
NOT_DECLARED, NOT_CHECKED = "not_declared", "not_checked"
CHECKS = ("declaration", "facts", "axes", "handedness", "units", "health")

ENGINE_DROPPED = ("The engine returned no value for this check although every fact it needs is sourced; "
                  "a declaration the engine cannot evaluate is not admitted.")
SCOPE = {
    "declaredHostUnitsPerGuestUnit": "both games' unit lengths",
    "declaredHostUnitsPerMetre": "the host's own unit length only; the guest's unit is not involved",
    "declaredMetresPerHostUnit": "the host's own unit length only; the guest's unit is not involved",
    "declaredSpanHostUnits": "the host's own unit length only; the guest's unit is not involved",
    "declaredMetresPerGuestUnit": "the guest's own unit length only; the host's unit is not involved",
}

LETTERS = {"x": "guestXFrom", "y": "guestYFrom", "z": "guestZFrom"}
UNIT_FORMS = ("declaredHostUnitsPerGuestUnit", "declaredHostUnitsPerMetre",
              "declaredMetresPerGuestUnit", "declaredMetresPerHostUnit", "declaredSpanHostUnits")
DECLARATION_PATHS = {"host", "guest", "guestXFrom", "guestYFrom", "guestZFrom", "mirrored", "mirrorDirection",
                     "declaredHostUnitsPerGuestUnit", "declaredHostUnitsPerMetre",
                     "declaredMetresPerGuestUnit", "declaredMetresPerHostUnit",
                     "declaredSpanHostUnits", "declaredSpanMetres"}
DIRECTIONS = ("East", "North", "Up")


# ------------------------------------------------------------------ terms


def _local(term: str | None) -> str | None:
    if term is None:
        return None
    t = term.strip("<>")
    return t[len(GA):] if t.startswith(GA) else t


def _value(term: str):
    """'"70"^^<...#integer>' -> 70, '"true"^^<...#boolean>' -> True, '<iri>' -> 'iri'."""
    if not term.startswith('"'):
        return term.strip("<>")
    lex = term[1:term.rindex('"')]
    dt = term[term.rindex('"') + 1:]
    if not dt.startswith("^^") or dt.endswith("string>"):
        return lex.replace('\\"', '"').replace("\\\\", "\\")
    if dt.endswith("boolean>"):
        return lex == "true"
    if dt.endswith("integer>"):
        return int(lex)
    if any(dt.endswith(x) for x in ("decimal>", "double>", "float>")):
        n = float(lex)
        return int(n) if n == int(n) and "." not in lex and "e" not in lex.lower() else n
    return lex


def _rows(e: Engine, query: str) -> list[dict]:
    res = e.call("onto_query", query=f"PREFIX ga: <{GA}>\n" + query)
    if "error" in res:
        raise EngineError(f"query refused: {res}")
    return res.get("results", [])


def _props(e: Engine, node: str) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in _rows(e, f"SELECT ?p ?o WHERE {{ <{node}> ?p ?o }}"):
        out.setdefault(_local(r["p"]), []).append(_value(r["o"]))
    return out


# ------------------------------------------------------------------ the engine run


def _apply_rule(e: Engine) -> int:
    """Apply rules/bridge.rq until it returns nothing new. Returns the passes run."""
    seen: set[tuple] = set()
    rule = RULE.read_text()
    for n in range(1, MAX_PASSES + 1):
        res = e.call("onto_query", query=rule)
        if "error" in res:
            raise EngineError(f"the rule did not run: {res}")
        new = [t for t in res.get("triples", [])
               if (t["subject"], t["predicate"], t["object"]) not in seen]
        if not new:
            return n
        seen.update((t["subject"], t["predicate"], t["object"]) for t in new)
        loaded = e.call("onto_load", turtle="\n".join(
            f"{t['subject']} {t['predicate']} {t['object']} ." for t in new))
        if "error" in loaded:
            raise EngineError(f"the rule's conclusions did not load: {loaded}")
    raise EngineError(f"the rule was still adding triples after {MAX_PASSES} passes")


def _refusals(verified: dict, default: dict) -> tuple[dict, dict]:
    """Both evaluators' refusals as {(focus, path)}; the evaluators' summary."""
    d = {(v.get("focus_node"), _local(v.get("path"))): v.get("message")
         for v in default.get("violations", []) if v.get("severity", "Violation") == "Violation"}
    vr = {(r.get("focus", "").strip("<>"), _local(r.get("path")))
          for r in (verified.get("report") or {}).get("results", [])}
    summary = {"verified": verified.get("conforms"), "default": default.get("conforms"),
               "default_focus_nodes": default.get("focus_nodes", 0)}
    problems = []
    if verified.get("conforms") is None:
        problems.append("the verified evaluator declined: " + str(verified.get("undetermined")
                                                                  or verified.get("error")))
    if default.get("conforms") is None:
        problems.append("the default evaluator withheld its verdict: "
                        + str(default.get("warning") or default.get("error")))
    if not default.get("focus_nodes"):
        # The verified evaluator conforms vacuously over a store with nothing
        # in it; a contract that saw no focus node has checked nothing.
        problems.append("the contract saw no focus node")
    if not problems and set(d) != vr:
        problems.append("the two SHACL evaluators returned different refusals: "
                        f"default only {sorted(map(str, set(d) - vr))}, "
                        f"verified only {sorted(map(str, vr - set(d)))}")
    summary["agree"] = not problems
    summary["problems"] = problems
    return d, summary


def _guard(e: Engine, query: Path, f: Path) -> list[dict]:
    """Run an input guard on a store that holds only file f."""
    e.call("onto_clear")
    loaded = e.load(f)
    if "error" in loaded or not loaded.get("ok", True):
        raise EngineError(f"{f.name} did not load: {loaded}")
    res = e.call("onto_query", query=query.read_text())
    if "error" in res:
        raise EngineError(f"the input guard {query.name} did not run: {res}")
    return [{"file": _shown(f), "subject": _value(r["s"]), "predicate": _local(r["p"]),
             "object": _value(r["o"]), "reason": _value(r["why"])} for r in res.get("results", [])]


def _shown(f: Path) -> str:
    try:
        return str(Path(f).resolve().relative_to(ROOT))
    except ValueError:
        return str(f)


def check(path: Path | str, binary: str | None = None, facts=()) -> dict:
    path = Path(path)
    facts = [Path(f) for f in facts]
    with Engine(scratch("bridge"), binary) as e:
        refusals = _guard(e, BRIDGE_GUARD, path)
        for f in (SPACE, *facts):
            refusals += _guard(e, FACTS_GUARD, f)
        inputs = {"verdict": REFUSED if refusals else HOLDS, "refusals": refusals,
                  "facts_files": [_shown(f) for f in (SPACE, *facts)], "synthetic_facts": bool(facts)}
        if refusals:
            return {"file": str(path), "verdict": REFUSED, "exit": 1, "input": inputs, "bridges": [],
                    "unattributed_refusals": [], "engine": e.server_info}

        e.call("onto_clear")
        for f in (SPACE, *facts, path):
            loaded = e.load(f)
            if "error" in loaded or not loaded.get("ok", True):
                raise EngineError(f"{f.name} did not load: {loaded}")
        passes = _apply_rule(e)
        verified = e.call("onto_shacl", shapes=str(CONTRACT), verified=True)
        default = e.call("onto_shacl", shapes=str(CONTRACT))
        refusals, evaluators = _refusals(verified, default)

        bridges = [r["b"].strip("<>") for r in _rows(e, "SELECT ?b WHERE { ?b a ga:Bridge } ORDER BY ?b")]
        attributed: set = set()
        results = []
        for b in bridges:
            res, used = _judge_bridge(e, b, refusals, evaluators)
            attributed |= used
            results.append(res)
        stray = [{"focus": f, "path": p, "message": m}
                 for (f, p), m in sorted(refusals.items(), key=str) if (f, p) not in attributed]

        verdicts = [r["verdict"] for r in results]
        if not evaluators["agree"]:
            overall = UNDETERMINED
        elif stray or REFUSED in verdicts:
            overall = REFUSED
        elif not results or any(v != HOLDS for v in verdicts):
            overall = UNDETERMINED
        else:
            overall = HOLDS
        return {
            "file": str(path),
            "verdict": overall,
            "exit": {HOLDS: 0, REFUSED: 1}.get(overall, 2),
            "input": inputs,
            "bridges": results,
            "unattributed_refusals": stray,
            "evaluators": evaluators,
            "rule_passes": passes,
            "engine": e.server_info,
        }


# ------------------------------------------------------------------ one bridge


def _game(e: Engine, g: str | None) -> dict:
    if not g:
        return {"iri": None, "label": None, "facts": [], "axes": {}, "lengths": [], "health": []}
    props = _props(e, g)
    facts = []
    for kind in ("lengthEvidence", "axisEvidence", "healthEvidence"):
        for ev in props.get(kind, []):
            if ev.startswith("_:"):
                # A blank node cannot be named in a query, and the rule cannot
                # write onto one; the contract refuses it (sh:nodeKind sh:IRI).
                facts.append({"node": ev, "kind": kind, "blank_node": True})
                continue
            ep = _props(e, ev)
            facts.append({"node": ev, "kind": kind, **{k: (v[0] if len(v) == 1 else v)
                                                        for k, v in ep.items()}})
    sourced = [f for f in facts if f.get("source")]
    axes = {}
    for f in sourced:
        if f["kind"] == "axisEvidence":
            axes[_local(f.get("direction"))] = f.get("axis")
    return {"iri": g, "label": (props.get("http://www.w3.org/2000/01/rdf-schema#label") or [g])[0],
            "basis_determinant": (props.get("basisDeterminant") or [None])[0],
            "facts": facts, "axes": axes,
            "lengths": [f for f in sourced if f["kind"] == "lengthEvidence"],
            "health": [f for f in sourced if f["kind"] == "healthEvidence"]}


def _judge_bridge(e: Engine, b: str, refusals: dict, evaluators: dict) -> tuple[dict, set]:
    p = _props(e, b)
    one = lambda k: (p.get(k) or [None])[0]
    host, guest = _game(e, one("host")), _game(e, one("guest"))
    used: set = set()

    def refused_at(focus: str, paths) -> list[str]:
        hits = [(f, q) for (f, q) in refusals if f == focus and q in paths]
        used.update(hits)
        return [refusals[h] for h in hits]

    checks: dict[str, dict] = {}

    # declaration
    msgs = refused_at(b, DECLARATION_PATHS)
    checks["declaration"] = {"verdict": REFUSED if msgs else HOLDS, "refusals": msgs}

    # facts
    msgs = []
    for game in (host, guest):
        for f in game["facts"]:
            msgs += refused_at(f["node"], {None, "source", "quote", "units", "axis",
                                           "centimetresFrom", "centimetresTo"})
        if game["iri"]:
            msgs += refused_at(game["iri"], {"basisDeterminant"})
    checks["facts"] = {"verdict": REFUSED if msgs else HOLDS, "refusals": msgs,
                       "host": _fact_summary(host), "guest": _fact_summary(guest)}

    # (a) the axis map
    declared = {L: one(prop) for L, prop in LETTERS.items() if one(prop) is not None}
    derived = {L: one("derivedGuest" + L.upper() + "From") for L in declared}
    if not declared:
        checks["axes"] = {"verdict": NOT_DECLARED}
    else:
        msgs = refused_at(b, {f"axis{L.upper()}Agrees" for L in declared})
        if one("mirrored") is True and one("mirrorDirection") is None:
            missing = ["the bridge declares a mirror without naming the world direction it flips "
                       "(ga:mirrorDirection), so no single map can be derived"]
        else:
            missing = [_axis_gap(L, host, guest) for L in declared if derived[L] is None]
        verdict = REFUSED if msgs else (UNDETERMINED if missing else HOLDS)
        checks["axes"] = {"verdict": verdict, "declared": declared,
                          "mirror_direction": _local(one("mirrorDirection")),
                          "derived": {L: v for L, v in derived.items() if v is not None},
                          "refusals": msgs, "missing": missing}

    # (b) handedness
    if not declared:
        checks["handedness"] = {"verdict": NOT_DECLARED}
    else:
        msgs = refused_at(b, {"handednessAgreement"})
        hand = one("handedness")
        missing = []
        if len(declared) < 3:
            missing.append("the bridge declares only part of the axis map")
        for game in (host, guest):
            gaps = [d for d in DIRECTIONS if d not in game["axes"]]
            if gaps:
                missing.append(f"{game['label']} has no sourced {', '.join(gaps)} axis")
        verdict = REFUSED if msgs else (HOLDS if hand is not None else UNDETERMINED)
        checks["handedness"] = {"verdict": verdict, "handedness": hand,
                                "declared_handedness": one("declaredHandedness"),
                                "mirrored_declared": bool(one("mirrored")),
                                "host_basis_determinant": host["basis_determinant"],
                                "guest_basis_determinant": guest["basis_determinant"],
                                "refusals": msgs, "missing": [] if hand is not None else missing}

    # (c) the unit ratio
    forms = [f for f in UNIT_FORMS if one(f) is not None]
    if not forms:
        checks["units"] = {"verdict": NOT_DECLARED}
    else:
        decls = []
        for f in forms:
            entry = {"form": f, "declared": one(f), "checks": SCOPE[f]}
            if f == "declaredSpanHostUnits":
                entry["declared"] = {"host_units": one(f), "metres": one("declaredSpanMetres")}
            need = ((guest,) if f == "declaredMetresPerGuestUnit" else
                    (host, guest) if f == "declaredHostUnitsPerGuestUnit" else (host,))
            missing = [f"{g['label']} has no sourced unit length" for g in need if not g["lengths"]]
            # The rule mints the unit node's IRI; nothing else is read as one.
            up = _props(e, f"{b}-units-{f}")
            g1 = lambda k: (up.get(k) or [None])[0]
            if missing:
                entry.update(verdict=UNDETERMINED, missing=missing)
            elif (g1("unitCheckOf") != b or g1("bestRelativeError") is None
                  or g1("worstRelativeError") is None
                  or g1("scaleCombinationsEvaluated") != g1("scaleCombinations")):
                entry.update(verdict=REFUSED, refusals=[ENGINE_DROPPED],
                             scale_combinations=g1("scaleCombinations"),
                             scale_combinations_evaluated=g1("scaleCombinationsEvaluated"))
            else:
                u = f"{b}-units-{f}"
                hard = refused_at(u, {"bestRelativeError"})
                soft = refused_at(u, {"worstRelativeError"})
                entry.update(
                    implied_low=g1("impliedLow"), implied_high=g1("impliedHigh"),
                    best_relative_error=g1("bestRelativeError"),
                    worst_relative_error=g1("worstRelativeError"),
                    ratio_as_declared=g1("declaredValue"),
                    scale_combinations=g1("scaleCombinations"),
                    refusals=hard,
                    unsettled=soft if not hard else [],
                    verdict=REFUSED if hard else (UNDETERMINED if soft else HOLDS))
            decls.append(entry)
        vs = [d["verdict"] for d in decls]
        checks["units"] = {"verdict": REFUSED if REFUSED in vs else UNDETERMINED if UNDETERMINED in vs else HOLDS,
                           "declarations": decls}

    # (d) health
    mult, native = one("declaredHealthMultiplier"), one("healthNative")
    if mult is None and native is None:
        checks["health"] = {"verdict": NOT_DECLARED}
    else:
        msgs = refused_at(b, {"healthMultiplierError", "healthNative", "declaredHealthMultiplier"})
        entry = {"declared_multiplier": mult, "declared_native": native,
                 "policy_multiplier": one("healthPolicyMultiplier"),
                 "error": one("healthMultiplierError"), "refusals": msgs}
        if msgs:
            entry["verdict"] = REFUSED
        elif mult is None:
            # Native by policy: health crosses unconverted, so there is no
            # number to compare and nothing for the engine to decide.
            entry["verdict"] = NOT_CHECKED
            entry["note"] = "declared native: health crosses unconverted by policy, so nothing is compared"
        elif entry["policy_multiplier"] is not None and entry["error"] is not None:
            entry["verdict"] = HOLDS
        else:
            missing = [f"{g['label']} has no sourced maximum health" for g in (host, guest) if not g["health"]]
            if missing:
                entry.update(verdict=UNDETERMINED, missing=missing)
            else:
                entry.update(verdict=REFUSED, refusals=[ENGINE_DROPPED])
        checks["health"] = entry

    if not evaluators["agree"]:
        for c in checks.values():
            if c["verdict"] in (HOLDS, REFUSED):
                c["verdict"] = UNDETERMINED
                c.setdefault("missing", []).extend(evaluators["problems"])

    vs = [c["verdict"] for c in checks.values()]
    substantive = [checks[k]["verdict"] for k in ("axes", "handedness", "units", "health")]
    if REFUSED in vs:
        verdict = REFUSED
    elif UNDETERMINED in vs or all(v in (NOT_DECLARED, NOT_CHECKED) for v in substantive):
        verdict = UNDETERMINED
    else:
        verdict = HOLDS
    return ({"bridge": b, "label": one("http://www.w3.org/2000/01/rdf-schema#label"),
             "host": host["label"], "guest": guest["label"],
             "evidence": one("evidenceLevel"), "project": one("project"),
             "table_row": one("tableRow"), "verdict": verdict, "checks": checks}, used)


def _fact_summary(game: dict) -> dict:
    return {"game": game["label"],
            "metres_per_unit": [f["metresPerUnit"] if f.get("metresPerUnit") is not None
                                else [f.get("metresPerUnitLow"), f.get("metresPerUnitHigh")]
                                for f in game["lengths"]],
            "axes": game["axes"],
            "max_health": [f.get("maxHealth") for f in game["health"]]}


def _axis_gap(letter: str, host: dict, guest: dict) -> str:
    on_letter = [d for d, a in guest["axes"].items() if isinstance(a, str) and a[1:] == letter]
    if not on_letter:
        return f"{guest['label']} has no sourced direction along its {letter} axis"
    return f"{host['label']} has no sourced {on_letter[0]} axis"


# ------------------------------------------------------------------ CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m passport.bridge",
                                 description="Check a two-game bridge's units, axes and health against sourced game facts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="judge one or more bridge files; prints JSON")
    c.add_argument("files", nargs="+", type=Path)
    c.add_argument("--binary", help="the open-ontologies engine (default: $OO_BIN)")
    c.add_argument("--facts", action="append", default=[], type=Path, metavar="FILE",
                   help="also read game facts from FILE; the run is marked synthetic")
    args = ap.parse_args(argv)
    worst = 0
    out = []
    for f in args.files:
        if not f.exists():
            out.append({"file": str(f), "verdict": UNDETERMINED, "exit": 2, "error": "no such file"})
            worst = max(worst, 2) if worst != 1 else 1
            continue
        try:
            r = check(f, args.binary, args.facts)
        except EngineError as err:
            r = {"file": str(f), "verdict": UNDETERMINED, "exit": 2, "error": str(err)}
        out.append(r)
        worst = 1 if 1 in (worst, r["exit"]) else max(worst, r["exit"])
    json.dump(out[0] if len(out) == 1 else out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return worst


if __name__ == "__main__":
    sys.exit(main())
