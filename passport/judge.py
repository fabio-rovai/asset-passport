"""Export an item with a passport; admit it, or not, at another game's border.

Two lanes, one border:

  passport  sender: lift the item into hub terms, reason, write a certificate,
            onto_pack it, and sign the pack with the game's export key.
            receiver: check the signature against the issuing game's PUBLISHED
            key, onto_unpack (which re-runs THIS machine's Lean checker over
            the certificate), pin the rules, re-derive, then the border.  Needs
            an engine whose onto_pack takes certificate_dir (open-ontologies #266).
  direct    one store, one trust domain, nothing to sign; this module runs
            oo-cert over the certificate itself, then the same border.  For a
            released engine without #266.

Games are discovered on disk (passport/games.py); every function that takes a
game key also takes `root`, the games root, which defaults to <repo>/games.

The border is the same function in both lanes, so the two lanes can be compared.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

from . import games as _games
from . import sign as _sign
from .engine import GA, ROOT, Engine, EngineError, scratch
from .games import GAMES, Game, discover  # noqa: F401  (GAMES: the default root, discovered)

NS = "https://tesseractsemantics.com/ns/asset-passport/"
HUB = ROOT / "ontology" / "ga-core.ttl"
RULE = ROOT / "rules" / "convert.rq"
PROFILE = "owl-rl-ext"  # cls-hv1 derives ga:fromGame; oo-cert checks that rule too

GATES = ("signature", "unpack", "rules", "closure", "border")
ADMITTED = ("accepted", "converted", "converted_with_loss")

ACCEPTED_PROOF = ("certificate_accepted", "certificate_accepted_under_supplied_rules")


def game_dir(game: str, root=None) -> Path:
    return _games.get(game, root).dir


def catalogue(game: str, root=None) -> list[dict]:
    return json.loads((game_dir(game, root) / "items.json").read_text())


def item_record(game: str, item_id: str, root=None) -> dict:
    for rec in catalogue(game, root):
        if rec["id"] == item_id:
            return rec
    raise KeyError(f"{game} has no item {item_id!r}")


def mapping(game: str, root=None) -> dict:
    return json.loads((game_dir(game, root) / "mapping.json").read_text())


# ------------------------------------------------------------------ the lanes


def _lift(e: Engine, game: str, rec: dict, run: Path, profile: Path | None = None, root=None) -> str:
    """Load the hub and the source profile, ingest the one item. Returns its IRI."""
    e.call("onto_clear")
    e.load(HUB)
    e.load(profile or game_dir(game, root) / "profile.ttl")
    item_json = run / "item.json"
    item_json.write_text(json.dumps(rec))
    ing = e.call("onto_ingest", path=str(item_json), format="json",
                 mapping=str(game_dir(game, root) / "mapping.json"))
    if "error" in ing or not ing.get("ok", True):
        raise EngineError(f"ingest refused the item: {ing}")
    return mapping(game, root)["base_iri"] + rec["id"]


def export(game: str, rec: dict, run: Path, binary: str | None = None,
           profile: Path | None = None, root=None, key=None, sign_as: str | None = None) -> dict:
    """Sender side. Writes run/passport.pack and returns what the engine said.

    With `key` (an Ed25519 private key) the pack is signed as `sign_as`, which
    defaults to the source game's IRI. Without one it leaves unsigned, and a
    receiver refuses it at the first gate."""
    out = run / "export"
    out.mkdir(parents=True, exist_ok=True)
    cert = out / "cert"
    pack = run / "passport.pack"
    with Engine(out, binary) as e:
        if not e.accepts("onto_pack", "certificate_dir"):
            raise EngineError("this engine build cannot carry a certificate in a pack "
                              "(open-ontologies #266); use the direct lane")
        iri = _lift(e, game, rec, out, profile, root)
        reason = e.call("onto_reason", profile=PROFILE, certificate_dir=str(cert))
        packed = e.call("onto_pack", path=str(pack), name=f"{game}-{rec['id']}",
                        version="0.1.0", certificate_dir=str(cert), profile=PROFILE)
        if "error" in packed:
            raise EngineError(f"onto_pack refused: {packed}")
        signature = None
        if key is not None:
            signature = _sign.sign_pack(pack, sign_as or _games.get(game, root, binary).iri, key)
            e.transcript.append({"tool": "ed25519-sign", "args": {"pack": "<run>/passport.pack",
                                 "game": signature["game"]}, "result": {
                                 "public_key_sha256": signature["public_key_sha256"]}})
        return {"item_iri": iri, "pack": pack, "reason": reason, "packed": packed,
                "signature": signature, "transcript": e.transcript}


def sign_existing(pack: Path, game_iri: str, key) -> dict:
    """Sign a pack file that already exists (the forger's and the dishonest
    issuer's route: change a pack, then sign what they changed)."""
    return _sign.sign_pack(pack, game_iri, key)


def admit(pack: Path, target: str, run: Path, binary: str | None = None, root=None) -> dict:
    """Receiver side. Five gates, in order; the first that fails decides.

      signature  the passport is signed; the game it names is a game this
                 receiver knows; the signature verifies against the export key
                 in THIS receiver's copy of that game's published profile
      unpack     the digests match the content (which is what binds the
                 signature to the graph and the certificate) and THIS
                 machine's Lean checker accepts the proof
      rules      the passport's rules are the source game's PUBLISHED rules,
                 not a doctored copy (a proof over doctored premises still
                 checks), and the game that signed is the game the item is
                 derived to come from (one game cannot sign another's goods)
      closure    this machine derives the item's classification itself and
                 refuses a passport that left a conclusion out
      border     the target game's contract, on both SHACL evaluators
    """
    out = run / "import"
    out.mkdir(parents=True, exist_ok=True)
    cert = out / "cert"
    known = discover(root, binary)
    if target not in known:
        raise ValueError(f"unknown game {target!r}; the games root has {sorted(known)}")
    with Engine(out, binary) as e:
        published = {g.iri: (g.label, g.export_key) for g in known.values()}
        sig = _sign.verify(pack, published)
        e.transcript.append({"tool": "ed25519-verify", "args": {"pack": "<passport>"},
                             "result": {k: v for k, v in sig.items() if k != "content_sha256"}})
        signature = {k: sig.get(k) for k in ("game", "label", "public_key_sha256", "claimed_key_sha256")}
        signature["verified"] = sig["ok"]
        if not sig["ok"]:
            return _stopped(e, "signature", target, {}, sig["why"], signature=signature)

        e.call("onto_clear")
        unpacked = e.call("onto_unpack", path=str(pack), certificate_out_dir=str(cert))
        proof = _proof_from_unpack(unpacked)
        if not unpacked.get("loaded"):
            why = unpacked.get("error") or unpacked.get("why_not_loaded") or "the pack did not load"
            return _stopped(e, "unpack", target, proof, why, signature=signature)

        try:
            item, src = _the_item(e)
        except EngineError as err:
            return _stopped(e, "rules", target, proof, f"The passport must describe one item from one game: {err}.",
                            signature=signature)
        claimed = _hub_types(e, item)
        source = next((g for g in known.values() if g.iri == src), None)
        if source is None:
            return _stopped(e, "rules", target, proof, f"No published profile for the source game {src}.",
                            item=item, src=src, hub_types=claimed, signature=signature)
        drift = profile_drift(cert / "asserted.tsv", source.key, item, binary, root)
        if drift["added"] or drift["removed"]:
            return _stopped(e, "rules", target, proof,
                            f"This passport's rules are not {_games.possessive(source.label)} published rules.",
                            item=item, src=src, hub_types=claimed, drift=drift, signature=signature)
        derived_src = _derived_objects(cert / "derivations.tsv", item, GA + "fromGame")
        if derived_src != [src]:
            return _stopped(e, "rules", target, proof,
                            "The passport states which game the item comes from instead of deriving it "
                            f"from the published rules (derived: {derived_src or 'nothing'}).",
                            item=item, src=src, hub_types=claimed, signature=signature)
        if sig["game"] != src:
            return _stopped(e, "rules", target, proof,
                            f"Signed by {sig.get('label')}, but the item is derived to come from {source.label}. "
                            "One game cannot vouch for another game's items.",
                            item=item, src=src, hub_types=claimed, signature=signature)

        claimed_facts = _hub_facts(e, item)
        e.call("onto_reason", profile=PROFILE)
        derived = _hub_types(e, item)
        omitted = sorted(_hub_facts(e, item) - claimed_facts)
        if omitted:
            return _stopped(e, "closure", target, proof,
                            "This passport leaves out what follows from its own facts: "
                            + "; ".join(omitted) + ".",
                            item=item, src=src, hub_types=derived, omitted=omitted, signature=signature)

        verdict = _border(e, target, proof, cert, item, src, derived, root)
        verdict["signature"] = signature
        verdict["transcript"] = e.transcript
        return verdict


def _derived_objects(derivations: Path, subject: str, predicate: str) -> list[str]:
    """The objects of (subject, predicate, ?) that the certificate DERIVES, as
    opposed to ones the sender asserted. Lean has checked every one of these
    steps against the asserted facts and the rules the rules gate pinned."""
    if not Path(derivations).exists():
        return []
    found = set()
    for line in Path(derivations).read_text().splitlines():
        cols = line.split("\t")
        if len(cols) >= 4 and cols[1].strip("<>") == subject and cols[2].strip("<>") == predicate:
            found.add(cols[3].strip("<>"))
    return sorted(found)


def _stopped(e: Engine, stage: str, target: str, proof: dict, why: str, *, item=None, src=None,
             hub_types=None, **extra) -> dict:
    return {"verdict": "refused", "stage": stage, "headline": "Refused before the border.",
            "refusals": [{"message": why}], "losses": [], "notes": [], "evaluators": {},
            "item_iri": item, "source": src, "target": target, "hub_types": hub_types or [],
            "why": [], "conversion": {}, "proof": {k: v for k, v in proof.items() if k != "unpack"},
            "engine": e.server_info, "transcript": e.transcript, **extra}


_PUBLISHED: dict[tuple, Counter] = {}


def published_tbox(game: str, binary: str | None = None, root=None) -> Counter:
    """The asserted lines a certificate holds for the hub plus the PUBLISHED
    profile of this game, computed here by the engine, not copied from a pack.
    Cached by the bytes of the hub and the profile, so a rewritten profile
    (a new export key, say) is pinned again."""
    profile = game_dir(game, root) / "profile.ttl"
    key = (hashlib.sha256(HUB.read_bytes() + b"\0" + profile.read_bytes()).hexdigest(), binary)
    if key not in _PUBLISHED:
        with Engine(scratch(f"pin-{game}"), binary) as e:
            e.call("onto_clear")
            e.load(HUB)
            e.load(profile)
            d = e.workdir / "cert"
            e.call("onto_reason", profile=PROFILE, certificate_dir=str(d))
            _PUBLISHED[key] = _tsv_lines(d / "asserted.tsv")
    return _PUBLISHED[key]


def profile_drift(asserted: Path, game: str, item: str, binary: str | None = None, root=None) -> dict:
    packed = _tsv_lines(asserted, skip_subject=item)
    published = published_tbox(game, binary, root)
    show = lambda c: sorted(" ".join(_short(t) or t for t in l.split("\t")) for l in c.elements())
    return {"added": show(packed - published), "removed": show(published - packed)}


_BNODE = re.compile(r"_:[A-Za-z0-9]+")


def _tsv_lines(path: Path, skip_subject: str | None = None) -> Counter:
    """Asserted triples as a multiset, blank-node labels erased (they are
    minted fresh on every load, so two loads of one file never share them)."""
    c: Counter = Counter()
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        if skip_subject and line.split("\t", 1)[0].strip("<>") == skip_subject:
            continue
        c[_BNODE.sub("_:b", line)] += 1
    return c


def judge_direct(game: str, rec: dict, target: str, run: Path,
                 binary: str | None = None, checker: str | None = None, root=None) -> dict:
    """Both sides in one store; oo-cert is run here, by this module. One store
    is one trust domain, so there is no pack and no signature to check."""
    out = run / "direct"
    out.mkdir(parents=True, exist_ok=True)
    cert = out / "cert"
    _games.get(target, root, binary)  # an unknown target is an error before any engine work
    with Engine(out, binary) as e:
        _lift(e, game, rec, out, root=root)
        e.call("onto_reason", profile=PROFILE, certificate_dir=str(cert))
        proof = run_oo_cert(cert, checker)
        e.transcript.append({"tool": "oo-cert", "args": {"certificate": "<run>/direct/cert"},
                             "result": proof})
        item, src = _the_item(e)
        verdict = _border(e, target, proof, cert, item, src, _hub_types(e, item), root)
        verdict["signature"] = None
        verdict["transcript"] = e.transcript
        return verdict


# ------------------------------------------------------------------ the proof


def find_oo_cert(explicit: str | None = None) -> str | None:
    for c in (explicit, os.environ.get("OO_CERT"),
              str(ROOT.parent / "open-ontologies" / "lean" / ".lake" / "build" / "bin" / "oo-cert")):
        if c and Path(c).exists():
            return c
    return shutil.which("oo-cert")


def run_oo_cert(cert: Path, checker: str | None = None) -> dict:
    """Run the Lean checker over a certificate. The exit code is the verdict."""
    bin_ = find_oo_cert(checker)
    if not bin_:
        return {"status": "checker_absent_nothing_was_checked"}
    p = subprocess.run([bin_, str(cert / "asserted.tsv"), str(cert / "derivations.tsv")],
                       capture_output=True, text=True, timeout=120)
    report = {}
    for line in reversed(p.stdout.strip().splitlines()):
        try:
            report = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    status = "certificate_accepted" if p.returncode == 0 else "certificate_refused"
    return {"status": status, "exit": p.returncode, "theorem": report.get("theorem"),
            "derivations": report.get("derivations"), "asserted": report.get("asserted"),
            "checker_sha256": (report.get("checker") or {}).get("self_sha256"),
            "detail": None if p.returncode == 0 else (p.stdout + p.stderr)[-600:]}


def _proof_from_unpack(u: dict) -> dict:
    """The receiver's verdict, as onto_unpack wrote it. A pack refused before the
    checker ran (a digest mismatch) has no certificate block at all."""
    c = u.get("certificate") or {}
    checker = c.get("checker_says_it_is") or {}
    status = c.get("verdict") or ("pack_refused_before_the_checker" if not u.get("loaded") else None)
    return {"status": status, "theorem": c.get("theorem"), "derivations": c.get("derivations"),
            "asserted": c.get("asserted"), "checked_here": c.get("checked_here"),
            "checker_sha256": checker.get("self_sha256") if isinstance(checker, dict) else None,
            "unpack": u}


# ------------------------------------------------------------------ the border


def _the_item(e: Engine) -> tuple[str, str]:
    found = e.call("onto_query", query=(
        f"SELECT ?item ?src WHERE {{ ?item a <{GA}Item> ; <{GA}fromGame> ?src }}"))
    rows = found.get("results", [])
    if len(rows) != 1:
        raise EngineError(f"expected exactly one item with a source game, found {rows}")
    return rows[0]["item"].strip("<>"), rows[0]["src"].strip("<>")


def _hub_types(e: Engine, item: str) -> list[str]:
    types = e.call("onto_query", query=(
        f"SELECT ?t WHERE {{ <{item}> a ?t FILTER(STRSTARTS(STR(?t), \"{GA}\")) }}"))
    return sorted(r["t"].strip("<>").split("#")[-1] for r in types.get("results", []))


def _hub_facts(e: Engine, item: str) -> set[str]:
    """Every hub-vocabulary fact about the item, as short text: its ga: classes
    and its ga: property values. The closure gate compares two of these."""
    res = e.call("onto_query", query=(
        f"SELECT ?p ?o WHERE {{ <{item}> ?p ?o FILTER(STRSTARTS(STR(?p), \"{GA}\") || "
        f"(?p = <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> && isIRI(?o) && STRSTARTS(STR(?o), \"{GA}\"))) }}"))
    return {f"{_short(r['p'])} {_short(r['o'])}" for r in res.get("results", [])}


def _border(e: Engine, target: str, proof: dict, cert: Path, item: str, src: str,
            hub_types: list[str], root=None) -> dict:
    tgt = _games.get(target, root)
    e.load(tgt.profile)
    e.call("onto_load", turtle=f"<{item}> <{GA}importTarget> <{tgt.iri}> .")
    conv = e.call("onto_query", query=RULE.read_text())
    triples = conv.get("triples", [])
    if triples:
        e.call("onto_load", turtle="\n".join(
            f"{t['subject']} {t['predicate']} {t['object']} ." for t in triples))
    conversion = {t["predicate"].strip("<>").split("#")[-1]:
                  (_short(t["object"]) if t["object"].startswith("<") else _literal(t["object"])) for t in triples}

    border, loss_file = tgt.border, tgt.loss
    if not border.exists():
        raise EngineError(f"{tgt.label} has no border contract at {border}")
    verified = e.call("onto_shacl", shapes=str(border), verified=True)
    default = e.call("onto_shacl", shapes=str(border))
    loss = e.call("onto_shacl", shapes=str(loss_file)) if loss_file.exists() else None

    if not default.get("focus_nodes"):
        # The verified evaluator conforms vacuously over a store with no item
        # in it (measured: it said True when a file load had wiped the store).
        default = {**default, "conforms": None, "error": "the border saw no focus node"}
    verdict = decide(proof, conversion, verified, default, loss)
    verdict.update({
        "stage": "border",
        "item_iri": item,
        "source": src,
        "target": target,
        "hub_types": hub_types,
        "why": derivation_steps(cert, item),
        "conversion": conversion,
        "proof": {k: v for k, v in proof.items() if k != "unpack"},
        "engine": e.server_info,
    })
    return verdict


def decide(proof: dict, conversion: dict, verified: dict, default: dict, loss: dict | None) -> dict:
    """The verdict is a function of what the checkers returned, and nothing else."""
    refusals = [{"message": v.get("message"), "path": _short(v.get("path")),
                 "constraint": v.get("constraint")}
                for v in default.get("violations", []) if v.get("severity", "Violation") == "Violation"]
    losses = [{"message": v.get("message"), "path": _short(v.get("path"))}
              for v in (loss or {}).get("violations", []) if v.get("severity") == "Warning"]
    notes = []

    evaluators = {"verified": verified.get("conforms"), "default": default.get("conforms")}
    base = {"refusals": refusals, "losses": losses, "notes": notes, "evaluators": evaluators}

    if proof.get("status") not in ACCEPTED_PROOF:
        return {**base, "verdict": "refused", "headline": "The passport's proof did not check.",
                "refusals": [{"message": f"Lean checker: {proof.get('status')}"}] + refusals}
    if None in evaluators.values() or "error" in verified or "error" in default:
        return {**base, "verdict": "undetermined",
                "headline": "A border check could not run, so nothing is claimed."}
    if evaluators["verified"] != evaluators["default"]:
        return {**base, "verdict": "undetermined",
                "headline": "The two SHACL evaluators disagree, so nothing is claimed."}
    if evaluators["verified"] is False:
        return {**base, "verdict": "refused", "headline": "Refused at the border."}
    if loss is not None and loss.get("conforms") is None:
        return {**base, "verdict": "undetermined", "headline": "The loss check could not run."}
    if losses:
        return {**base, "verdict": "converted_with_loss", "headline": "Admitted, with losses named."}
    if any(k.endswith("InTarget") for k in conversion):
        return {**base, "verdict": "converted", "headline": "Admitted, converted."}
    return {**base, "verdict": "accepted", "headline": "Admitted as is."}


def derivation_steps(cert: Path, item: str) -> list[dict]:
    """The certificate's own steps whose conclusion is about this item."""
    f = cert / "derivations.tsv"
    if not f.exists():
        return []
    steps = []
    for line in f.read_text().splitlines():
        cols = line.split("\t")
        if len(cols) < 4 or cols[1].strip("<>") != item:
            continue
        concl = cols[1:4]
        if concl[2].startswith("_:"):
            continue  # a step to an anonymous restriction, plumbing for cls-hv1
        prem = [cols[i:i + 3] for i in range(4, len(cols), 3)]
        steps.append({"rule": cols[0],
                      "conclusion": " ".join(_short(x) for x in concl),
                      "premises": [" ".join(_short(x) for x in p) for p in prem]})
    return steps


PREFIXES = {GA: "ga:", NS + "craft#": "craft:", NS + "battle#": "battle:",
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type": "a",
            "http://www.w3.org/2000/01/rdf-schema#": "rdfs:",
            "http://www.w3.org/2002/07/owl#": "owl:"}


def _short(term) -> str | None:
    if term is None:
        return None
    t = term.strip("<>")
    for long, short in (*PREFIXES.items(), *_games.PREFIXES.items()):
        if t == long:
            return short
        if t.startswith(long):
            return short + t[len(long):]
    if t.startswith('"'):
        return _literal(t)
    return t


def _literal(term: str):
    """'"350"^^<...#decimal>' -> 350 (an int when it is whole), 'true' -> True."""
    if not term.startswith('"'):
        return term
    lex = term[1:term.rindex('"')]
    dt = term[term.rindex('"') + 1:]
    if dt.endswith("boolean>"):
        return lex == "true"
    if any(dt.endswith(x) for x in ("integer>", "decimal>", "double>", "float>")):
        n = float(lex)
        return int(n) if n == int(n) else n
    return lex
