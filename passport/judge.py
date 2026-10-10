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

The signing module (and with it the cryptography package) is imported only by
export() and admit(): the direct lane signs nothing and runs without it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import unicodedata
from collections import Counter
from pathlib import Path

from . import games as _games
from .engine import GA, ROOT, Engine, EngineError, scratch
from .games import GAMES, Game, discover  # noqa: F401  (GAMES: the default root, discovered)

NS = "https://tesseractsemantics.com/ns/asset-passport/"
HUB = ROOT / "ontology" / "ga-core.ttl"
RULE = ROOT / "rules" / "convert.rq"
PROFILE = "owl-rl-ext"  # cls-hv1 derives ga:fromGame; oo-cert checks that rule too

GATES = ("signature", "unpack", "rules", "closure", "border")
ADMITTED = ("accepted", "converted", "converted_with_loss")

ACCEPTED_PROOF = ("certificate_accepted", "certificate_accepted_under_supplied_rules")
# A proof that was never checked is not a proof that failed: no checker on this
# machine, or a checker that crashed or could not read its input. Nothing is
# claimed either way, so these are undetermined, never refused.
UNCHECKED_PROOF = ("checker_absent_nothing_was_checked", "checker_failed", "checker_runs_disagree")
# What onto_unpack says when the checker it ran did not accept: a refusal, or a
# certificate it could not read. A crash is reported as the second, and an exit
# 1 with no verdict as the first, so both are checked again here (_recheck).
RECHECKED = ("certificate_refused", "certificate_unreadable")
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


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


class NotOneItem(EngineError):
    """The store does not hold exactly one item with a source game."""


class BadItem(ValueError):
    """An item record a game does not define: a failed run, never a verdict."""


MAX_NUMBER = 100_000
XSD = "http://www.w3.org/2001/XMLSchema#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
_VOCAB: dict[tuple, dict] = {}


def vocabulary(game: str, root=None, binary: str | None = None) -> dict:
    """What the game's published profile says, read by the engine: every term
    in the game's own namespace, whether the game declares elemental types,
    and, for each lookup field, the values the profile places on the hub's
    type scale. Cached per process by the profile's path and bytes."""
    profile = game_dir(game, root) / "profile.ttl"
    key = (str(profile.resolve()), hashlib.sha256(profile.read_bytes()).hexdigest(), binary)
    if key in _VOCAB:
        return _VOCAB[key]
    m = mapping(game, root)
    base = m["base_iri"]
    run = scratch("vocab")
    try:
        with Engine(run, binary) as e:
            e.call("onto_clear")
            loaded = e.load(profile)
            if "error" in loaded:
                raise EngineError(f"{game} profile did not load: {loaded['error']}")

            def rows(q: str) -> list[dict]:
                out = e.call("onto_query", query=q)
                if "error" in out:
                    raise EngineError(f"vocabulary query failed: {out['error']}")
                return out.get("results", [])

            terms = {r["t"].strip("<>") for r in rows(
                f"SELECT DISTINCT ?t WHERE {{ {{ ?t ?p ?o }} UNION {{ ?s ?t ?o }} UNION {{ ?s ?p ?t }} "
                f'FILTER(isIRI(?t) && STRSTARTS(STR(?t), "{base}")) }}')}
            typed = any(r["t"].startswith('"true"') for r in rows(
                f"SELECT ?t WHERE {{ ?g a <{GA}Game> ; <{GA}hasElementalTypes> ?t }}"))
            placed = {}
            for f in m["mappings"]:
                if not f.get("lookup") or f["field"] == "kind":
                    continue
                placed[f["field"]] = sorted(
                    r["v"].strip("<>")[len(base):] for r in rows(
                        f"SELECT DISTINCT ?v WHERE {{ <{f['predicate']}> <{RDFS}subPropertyOf>* ?p . "
                        f"?r <{OWL}onProperty> ?p ; <{OWL}hasValue> ?v ; <{RDFS}subClassOf> ?c . "
                        f"?c <{OWL}onProperty> <{GA}elementalType> . "
                        f'FILTER(STRSTARTS(STR(?v), "{base}")) }}'))
    finally:
        shutil.rmtree(run, ignore_errors=True)
    _VOCAB[key] = {"base": base, "terms": terms, "typed": typed, "placed": placed}
    return _VOCAB[key]


# A zero-width joiner and the variation selectors build one emoji out of
# several code points (a family, a coloured heart), so a name may hold them.
# Every other control or format character, the bidirectional overrides among
# them, is refused. The variation selectors are combining marks (category Mn),
# so only the joiner needs naming here.
_JOINERS = {"\u200d"}


def _text(label: str, v) -> str:
    """A free-text value a person typed: a string of printable characters.
    A lone surrogate cannot be written as UTF-8, so the engine's JSON reader
    refused it and the client saw an engine failure."""
    if not isinstance(v, str):
        raise BadItem(f"{label} must be a string")
    if any(unicodedata.category(c).startswith("C") and c not in _JOINERS for c in v):
        raise BadItem(f"{label} must hold only printable characters")
    return v


def clean_item(game: str, item, root=None, binary: str | None = None) -> dict:
    """The one check every front door (the command line and the live API)
    applies to an item record that did not come from the game's own catalogue.
    The kind is one the game defines; every field is one its mapping defines,
    and every field the game's own record of that kind has is present; every
    number is from 0 to 100,000; a lookup value of a game with elemental types
    is one its profile places on a type; the id is not a term of the game's own
    rules; and the free text is printable. Returns the record as the engine
    will see it."""
    if not isinstance(item, dict):
        raise BadItem("item must be an object")
    g = _games.get(game, root, binary)
    label = g.label
    records = catalogue(game, root)
    kinds = {r["kind"] for r in records}
    kind = item.get("kind")
    if not isinstance(kind, str) or kind not in kinds:
        raise BadItem(f"{label} has no kind {kind!r}; it has {sorted(kinds)}")
    fields = {m["field"]: ("lookup" if m.get("lookup") else m.get("datatype", "string"))
              for m in mapping(game, root)["mappings"]}
    vocab = vocabulary(game, root, binary)
    rec = {"kind": kind}
    raw_id = _text("id", item.get("id") or "forged_item")
    rec["id"] = re.sub(r"[^a-z0-9_]", "_", raw_id.lower())[:48] or "forged_item"
    if vocab["base"] + rec["id"] in vocab["terms"]:
        # The item's IRI is the base IRI plus its id, so id 'game' made the
        # item the source game itself, typed as a weapon.
        raise BadItem(f"id {rec['id']!r} is a term of {_games.possessive(label)} own rules; choose another id")
    rec["name"] = _text("name", item.get("name") or "Forged item").strip()[:40]
    for k, v in item.items():
        if k in ("id", "kind", "name"):
            continue
        if k not in fields:
            raise BadItem(f"{label} items have no field {k!r}")
        dt = fields[k]
        if dt in ("lookup", "string"):
            if not isinstance(v, str) or not re.fullmatch(r"[A-Za-z][A-Za-z ]{0,23}", v):
                raise BadItem(f"{k} must be a word of up to 24 letters")
            if dt == "lookup":
                v = v.replace(" ", "")
                placed = vocab["placed"].get(k) or []
                if vocab["typed"] and placed and v not in placed:
                    # The game says every thing it has carries an elemental
                    # type, so a value it does not place is not one of its
                    # types. Passed through, it vanished at the border with no
                    # loss named. A game without types (Blockcraft) keeps an
                    # unplaced value, and the border names what that costs.
                    raise BadItem(f"{label} has no {k} {v!r}; it has {placed}")
            rec[k] = v
            continue
        if dt == XSD + "boolean":
            if not isinstance(v, bool):
                raise BadItem(f"{k} must be true or false")
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 <= v <= MAX_NUMBER):
                raise BadItem(f"{k} must be a number from 0 to {MAX_NUMBER:,}")
            if dt == XSD + "integer" and v != int(v):
                raise BadItem(f"{k} must be a whole number in {label}")
            v = int(v) if dt == XSD + "integer" else v
        rec[k] = v
    # The fields the game's own record of this kind has are the fields the
    # kind needs: a creature without a type passed every check above and came
    # back from Pocket Battlers' border admitted with no type at all.
    own = [set(r) - {"id", "kind", "name"} for r in records if r["kind"] == kind]
    missing = sorted(set.intersection(*own) - set(rec))
    if missing:
        raise BadItem(f"{kind} in {label} must have {', '.join(missing)}: {_games.possessive(label)} own "
                      f"{kind} has {'it' if len(missing) == 1 else 'them'}")
    return rec


def item_namespace(g: Game) -> str:
    """The namespace a game's items live in, from the receiver's own copy of
    the game: its mapping's base IRI, else its game IRI up to the last # or /."""
    m = g.dir / "mapping.json"
    if m.exists():
        base = json.loads(m.read_text()).get("base_iri")
        if base:
            return base
    cut = max(g.iri.rfind("#"), g.iri.rfind("/"))
    return g.iri[:cut + 1]


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
    if key is not None:
        from . import sign as _sign
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
    from . import sign as _sign
    return _sign.sign_pack(pack, game_iri, key)


def admit(pack: Path, target: str, run: Path, binary: str | None = None, root=None) -> dict:
    """Receiver side. Five gates, in order; the first that fails decides.

      signature  the passport is signed; the game it names is a game this
                 receiver knows; the signature verifies against the export key
                 in THIS receiver's copy of that game's published profile
      unpack     the digests match the content (which is what binds the
                 signature to the graph and the certificate), the content the
                 engine unpacked is the content the signature covers, and THIS
                 machine's Lean checker accepts the proof
      rules      the passport's rules are the source game's PUBLISHED rules,
                 not a doctored copy (a proof over doctored premises still
                 checks); the item lives in the source game's namespace and
                 states only that game's own fields, so every hub fact about it
                 must be derived; and the game that signed is the game the item
                 is derived to come from (one game cannot sign another's goods)
      closure    this machine derives the item's classification itself, from
                 its own copy of the hub and the published profile plus the
                 item's own fields and nothing else the passport carries, and
                 refuses a passport that left a conclusion out or claimed one
                 that does not follow
      border     the target game's contract, on both SHACL evaluators

    The passport file is read once. Its bytes are copied into the run
    directory, and the signature gate and the engine both read that copy, so a
    file that changes while it is being admitted cannot be verified as one
    passport and unpacked as another.
    """
    from . import sign as _sign

    out = run / "import"
    out.mkdir(parents=True, exist_ok=True)
    cert = out / "cert"
    known = discover(root, binary)
    if target not in known:
        raise ValueError(f"unknown game {target!r}; the games root has {sorted(known)}")
    private = out / "passport.pack"
    private.write_bytes(Path(pack).read_bytes())  # a file that cannot be read is a failed run
    with Engine(out, binary) as e:
        if not e.accepts("onto_unpack", "certificate_out_dir"):
            raise EngineError("this engine build cannot carry a certificate in a pack "
                              "(open-ontologies #266), so it cannot admit a passport; use the direct lane")
        published = {g.iri: (g.label, g.export_key) for g in known.values()}
        sig = _sign.verify(private, published)
        e.transcript.append({"tool": "ed25519-verify", "args": {"pack": "<passport>"},
                             "result": {k: v for k, v in sig.items() if k != "content_sha256"}})
        signature = {k: sig.get(k) for k in ("game", "label", "public_key_sha256", "claimed_key_sha256")}
        signature["verified"] = sig["ok"]
        if not sig["ok"]:
            return _stopped(e, "signature", target, {}, sig["why"], signature=signature)

        e.call("onto_clear")
        unpacked = e.call("onto_unpack", path=str(private), certificate_out_dir=str(cert))
        proof = _proof_from_unpack(unpacked)
        if proof.get("status") in RECHECKED:
            # The engine reports a checker that crashed as a certificate it
            # could not read, and one that exited 1 without a verdict as a
            # refusal, so its word alone does not separate a forged proof from
            # a broken checker. This machine's checker is run again over the
            # certificate the engine kept; only a refusal it reports in its own
            # JSON verdict stays a refusal.
            proof = _recheck(e, cert, proof)
            if proof["status"] != "certificate_refused":
                return _stopped(e, "unpack", target, proof, _unchecked_why(proof),
                                signature=signature, verdict="undetermined")
        if not unpacked.get("loaded"):
            why = unpacked.get("error") or unpacked.get("why_not_loaded") or "the pack did not load"
            return _stopped(e, "unpack", target, proof, why, signature=signature)
        unpacked_digest = (unpacked.get("manifest") or {}).get("content_sha256")
        if unpacked_digest is None:
            return _stopped(e, "unpack", target, proof,
                            "The engine did not report the digest of what it unpacked, so nothing ties "
                            "the signature to the content and nothing is claimed.",
                            signature=signature, verdict="undetermined")
        if unpacked_digest != sig["content_sha256"]:
            return _stopped(e, "unpack", target, proof,
                            f"The content the engine unpacked (digest {unpacked_digest[:16]}...) is not the "
                            f"content the signature covers ({sig['content_sha256'][:16]}...).",
                            signature=signature)
        if proof.get("status") == "no_certificate_in_pack" or not (cert / "asserted.tsv").exists():
            return _stopped(e, "unpack", target, proof,
                            "This passport carries no certificate, so there is no proof for this machine "
                            "to check and no rules to compare with the published ones.",
                            signature=signature)
        if proof.get("status") not in ACCEPTED_PROOF:
            if proof.get("status") in UNCHECKED_PROOF or proof.get("status") is None:
                return _stopped(e, "unpack", target, proof, _unchecked_why(proof),
                                signature=signature, verdict="undetermined")
            return _stopped(e, "unpack", target, proof, f"Lean checker: {proof.get('status')}",
                            signature=signature)

        try:
            item, src = _the_item(e)
        except NotOneItem as err:  # an engine that failed or hung is not a refusal
            return _stopped(e, "rules", target, proof, f"The passport must describe one item from one game: {err}.",
                            signature=signature)
        claimed = _hub_types(e, item)
        source = next((g for g in known.values() if g.iri == src), None)
        if source is None:
            return _stopped(e, "rules", target, proof, f"No published profile for the source game {src}.",
                            item=item, src=src, hub_types=claimed, signature=signature)
        ns = item_namespace(source)
        if not item.startswith(ns) or len(item) == len(ns):
            return _stopped(e, "rules", target, proof,
                            f"The item {item} is not named in {_games.possessive(source.label)} namespace ({ns}), "
                            "so it is not that game's item to vouch for.",
                            item=item, src=src, hub_types=claimed, signature=signature)
        try:
            drift = profile_drift(cert / "asserted.tsv", source.key, item, binary, root)
        except ValueError as err:
            return _stopped(e, "rules", target, proof,
                            f"This passport's rules cannot be compared with {_games.possessive(source.label)} "
                            f"published rules: {err}.",
                            item=item, src=src, hub_types=claimed, signature=signature)
        if drift["added"] or drift["removed"]:
            return _stopped(e, "rules", target, proof,
                            f"This passport's rules are not {_games.possessive(source.label)} published rules.",
                            item=item, src=src, hub_types=claimed, drift=drift, signature=signature)
        native, foreign = item_assertions(cert / "asserted.tsv", item, ns)
        if foreign:
            return _stopped(e, "rules", target, proof,
                            "The passport states facts about the item instead of deriving it from "
                            f"{_games.possessive(source.label)} published rules; an item may state only "
                            f"{_games.possessive(source.label)} own fields: " + "; ".join(foreign[:5]) + ".",
                            item=item, src=src, hub_types=claimed, signature=signature)
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

        # The closure gate, and the border after it, judge only what the rules
        # gate compared: this machine's own hub and its own copy of the source
        # game's published profile, plus the item's own fields as the
        # certificate asserts them. Anything else in the passport's graph (a
        # rule or a game parameter the certificate does not carry) is not
        # loaded, and a hub fact the passport claims about the item that does
        # not follow from those is refused here.
        claimed_facts = _hub_facts(e, item)
        e.call("onto_clear")
        e.load(HUB)
        e.load(source.profile)
        e.call("onto_load", turtle="\n".join(native))
        e.call("onto_reason", profile=PROFILE)
        derived = _hub_types(e, item)
        derived_facts = _hub_facts(e, item)
        omitted = sorted(derived_facts - claimed_facts)
        if omitted:
            return _stopped(e, "closure", target, proof,
                            "This passport leaves out what follows from its own facts: "
                            + "; ".join(omitted) + ".",
                            item=item, src=src, hub_types=derived, omitted=omitted, signature=signature)
        unfounded = sorted(claimed_facts - derived_facts)
        if unfounded:
            return _stopped(e, "closure", target, proof,
                            "This passport claims what does not follow from the item's fields and "
                            f"{_games.possessive(source.label)} published rules: " + "; ".join(unfounded) + ".",
                            item=item, src=src, hub_types=derived, unfounded=unfounded, signature=signature)

        verdict = _border(e, target, proof, cert, item, src, derived, root)
        verdict["signature"] = signature
        verdict["transcript"] = e.transcript
        return verdict


def _recheck(e: Engine, cert: Path, engine_proof: dict) -> dict:
    """Run this machine's oo-cert over the certificate directory onto_unpack
    kept, and return the proof as that run reports it. The engine's own word is
    kept beside it, under engine_status."""
    again = run_oo_cert(cert)
    e.transcript.append({"tool": "oo-cert", "args": {"certificate": "<run>/import/cert", "why": (
        f"onto_unpack reported {engine_proof.get('status')}; the checker is run again here")},
        "result": again})
    proof = {**engine_proof, **{k: v for k, v in again.items() if k != "exit"},
             "engine_status": engine_proof.get("status")}
    if again["status"] in ACCEPTED_PROOF:
        # One run of the checker refused or could not read the certificate and
        # the next accepted it: the two runs disagree, so nothing is claimed.
        proof["status"] = "checker_runs_disagree"
    return proof


def _unchecked_why(proof: dict) -> str:
    if proof.get("status") == "checker_absent_nothing_was_checked":
        return ("This machine has no Lean checker (oo-cert), so the proof was not checked "
                "and nothing is claimed.")
    if proof.get("status") == "checker_runs_disagree":
        return (f"The engine's run of the Lean checker reported {proof.get('engine_status')}, and a second run "
                "on this machine accepted the same certificate, so nothing is claimed.")
    return (f"The Lean checker did not run to a verdict ({proof.get('status') or 'no status'}), "
            "so the proof was not checked and nothing is claimed.")


def item_assertions(asserted: Path, item: str, ns: str) -> tuple[list[str], list[str]]:
    """The certificate's asserted statements about the item, split into the
    ones a source game may state (its own fields: rdf:type or a predicate in
    its namespace, with any IRI value in its namespace, never a hub term) and
    the rest. Returns (native statements as N-Triples lines, the rest as short
    text)."""
    native, foreign = [], []
    for line in Path(asserted).read_text().splitlines():
        cols = line.split("\t")
        if len(cols) != 3 or cols[0].strip("<>") != item:
            continue
        p, o = cols[1].strip("<>"), cols[2]
        p_ok = (p == RDF_TYPE or p.startswith(ns)) and not p.startswith(GA)
        if o.startswith("_:"):
            o_ok = False
        elif o.startswith("<"):
            o_ok = o.strip("<>").startswith(ns) and not o.strip("<>").startswith(GA)
        else:
            o_ok = p != RDF_TYPE
        if p_ok and o_ok:
            native.append(f"{cols[0]} {cols[1]} {cols[2]} .")
        else:
            foreign.append(f"{_short(cols[1])} {_short(cols[2])}")
    return native, foreign


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
             hub_types=None, verdict: str = "refused", **extra) -> dict:
    refused = verdict == "refused"
    return {"verdict": verdict, "stage": stage,
            "headline": "Refused before the border." if refused else why,
            "refusals": [{"message": why}] if refused else [], "losses": [],
            "notes": [] if refused else [{"message": why}], "evaluators": {},
            "item_iri": item, "source": src, "target": target, "hub_types": hub_types or [],
            "why": [], "conversion": {}, "proof": {k: v for k, v in proof.items() if k != "unpack"},
            "engine": engine_identity(e), "transcript": e.transcript, **extra}


_PUBLISHED: dict[tuple, "TBox"] = {}


class TBox:
    """Asserted triples compared up to blank-node isomorphism.

    Blank-node labels are minted fresh on every load, so two loads of one file
    never share them, and erasing the labels is not enough: it would let a
    sender swap the hasValue of one restriction with another's and keep the
    same multiset of lines (measured: Diamond made Steel-typed and Iron
    Rock-typed passed this gate when labels were erased).

    So every blank node is replaced by its full outgoing structure, nested:
    a restriction becomes [a owl:Restriction ; owl:onProperty X ; owl:hasValue Y].
    A triple whose subject is an IRI is one statement, with any blank-node
    object written out in full; a blank node that is the object of nothing
    (a general class axiom's subject, say) is one statement on its own, written
    out in full. Two multisets of statements are equal exactly when the graphs
    are isomorphic, PROVIDED every blank node is the object of at most one
    triple and none is part of a cycle, which is what Turtle's [ ] and ( )
    syntax produce. A graph that breaks that proviso is refused with a
    ValueError rather than compared unsoundly."""

    def __init__(self, statements: Counter, render: dict):
        self.statements = statements  # canonical JSON text -> count
        self.render = render          # canonical JSON text -> short readable text

    @classmethod
    def read(cls, path: Path, skip_subject: str | None = None) -> "TBox":
        triples = []
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            cols = line.split("\t")
            if len(cols) != 3:
                raise ValueError(f"an asserted line that is not one triple: {line[:120]!r}")
            if skip_subject and cols[0].strip("<>") == skip_subject:
                continue
            triples.append(tuple(cols))
        return cls.of(triples)

    @classmethod
    def of(cls, triples: list[tuple[str, str, str]]) -> "TBox":
        bnode = lambda t: t.startswith("_:")
        out: dict[str, list] = {}
        indeg: Counter = Counter()
        for s, p, o in triples:
            if bnode(s):
                out.setdefault(s, []).append((p, o))
            if bnode(o):
                indeg[o] += 1
        nodes = set(out) | set(indeg)
        shared = sorted(b for b in nodes if indeg[b] > 1)
        if shared:
            raise ValueError(f"blank node {shared[0]} is the object of {indeg[shared[0]]} statements, "
                             "and this gate compares only blank nodes that hang from one statement each")
        memo: dict[str, list] = {}
        visiting: set[str] = set()

        def canon(b: str) -> list:
            if b in memo:
                return memo[b]
            if b in visiting:
                raise ValueError(f"blank node {b} is part of a cycle, which this gate cannot compare")
            visiting.add(b)
            props = sorted(([p, canon(o) if bnode(o) else o] for p, o in out.get(b, [])),
                           key=lambda x: json.dumps(x))
            visiting.discard(b)
            memo[b] = ["[]", props]
            return memo[b]

        stmts: Counter = Counter()
        render: dict = {}
        for s, p, o in triples:
            if bnode(s):
                continue
            c = [s, p, canon(o) if bnode(o) else o]
            k = json.dumps(c)
            stmts[k] += 1
            render[k] = " ".join(_show(x) for x in c)
        for b in sorted(out):
            if indeg[b] == 0:
                c = canon(b)
                k = json.dumps(c)
                stmts[k] += 1
                render[k] = _show(c)
        unreached = sorted(nodes - set(memo))
        if unreached:
            raise ValueError(f"blank node {unreached[0]} is part of a cycle, which this gate cannot compare")
        return cls(stmts, render)


def _show(c) -> str:
    if isinstance(c, list):
        return "[" + " ; ".join(f"{_short(p)} {_show(o)}" for p, o in c[1]) + "]"
    return _short(c) or c


def published_tbox(game: str, binary: str | None = None, root=None) -> TBox:
    """The asserted statements a certificate holds for the hub plus the
    PUBLISHED profile of this game, computed here by the engine, not copied
    from a pack. Cached by the bytes of the hub and the profile, so a rewritten
    profile (a new export key, say) is pinned again."""
    profile = game_dir(game, root) / "profile.ttl"
    key = (hashlib.sha256(HUB.read_bytes() + b"\0" + profile.read_bytes()).hexdigest(), binary)
    if key not in _PUBLISHED:
        work = scratch(f"pin-{game}")
        try:
            with Engine(work, binary) as e:
                e.call("onto_clear")
                e.load(HUB)
                e.load(profile)
                d = e.workdir / "cert"
                e.call("onto_reason", profile=PROFILE, certificate_dir=str(d))
                try:
                    _PUBLISHED[key] = TBox.read(d / "asserted.tsv")
                except ValueError as err:
                    raise EngineError(f"{profile}: the published rules cannot be pinned: {err}") from err
        finally:
            shutil.rmtree(work, ignore_errors=True)  # the pinned statements are kept in memory
    return _PUBLISHED[key]


def profile_drift(asserted: Path, game: str, item: str, binary: str | None = None, root=None) -> dict:
    """What the packed rules add to, and remove from, the published ones.
    Raises ValueError when the packed rules cannot be compared soundly."""
    published = published_tbox(game, binary, root)
    packed = TBox.read(asserted, skip_subject=item)
    added = packed.statements - published.statements
    removed = published.statements - packed.statements
    return {"added": sorted(packed.render[k] for k in added.elements()),
            "removed": sorted(published.render[k] for k in removed.elements())}


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
        if proof.get("status") in UNCHECKED_PROOF:
            # Nothing was checked, so nothing is claimed: undetermined at the
            # gate where the proof is checked, never a refusal at the border.
            held = _stopped(e, "unpack", target, proof, _unchecked_why(proof), item=item, src=src,
                            hub_types=_hub_types(e, item), verdict="undetermined")
            held["signature"] = None
            return held
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
    try:
        p = subprocess.run([bin_, str(cert / "asserted.tsv"), str(cert / "derivations.tsv")],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as err:
        return {"status": "checker_failed", "exit": None, "detail": f"{type(err).__name__}: {err}"[-600:]}
    report = {}
    for line in reversed(p.stdout.strip().splitlines()):
        try:
            report = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if not isinstance(report, dict):
        report = {}
    # oo-cert exits 0 when every step checks and 1 when the checker rejects a
    # step, and either way prints its verdict as one JSON object with "ok".
    # Any other code (2 is its code for a file it could not read or a wrong
    # command line; a negative code is a signal, a crash), or an exit with no
    # such verdict on stdout, means the checker never reached a verdict, which
    # is not a refusal.
    said = report.get("ok")
    if p.returncode == 0 and said is True:
        status = "certificate_accepted"
    elif p.returncode == 1 and said is False:
        status = "certificate_refused"
    else:
        status = "checker_failed"
    return {"status": status, "exit": p.returncode, "theorem": report.get("theorem"),
            "derivations": report.get("derivations"), "asserted": report.get("asserted"),
            "checker_sha256": (report.get("checker") or {}).get("self_sha256"),
            "detail": None if status == "certificate_accepted" else (p.stdout + p.stderr)[-600:]}


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
    if "error" in found:
        raise EngineError(f"the item query failed: {found['error']}")
    rows = found.get("results", [])
    if len(rows) != 1:
        raise NotOneItem(f"expected exactly one item with a source game, found {rows}")
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
    # Every value the rule constructs is kept: a field with two values is
    # shown with both, and decide() claims nothing for it, rather than one
    # value silently replacing the other.
    values: dict[str, list] = {}
    for t in triples:
        v = _short(t["object"]) if t["object"].startswith("<") else _literal(t["object"])
        bucket = values.setdefault(t["predicate"].strip("<>").split("#")[-1], [])
        if v not in bucket:
            bucket.append(v)
    conversion = {k: (v[0] if len(v) == 1 else sorted(v, key=lambda x: (str(type(x)), x)))
                  for k, v in values.items()}

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
        "engine": engine_identity(e),
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
        if proof.get("status") in UNCHECKED_PROOF or proof.get("status") is None:
            return {**base, "verdict": "undetermined",
                    "headline": "The proof could not be checked on this machine, so nothing is claimed.",
                    "notes": [{"message": f"Lean checker: {proof.get('status')}"}]}
        return {**base, "verdict": "refused", "headline": "The proof did not check.",
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
    several = {k: v for k, v in conversion.items() if isinstance(v, list)}
    if several:
        k, v = next(iter(sorted(several.items())))
        return {**base, "verdict": "undetermined",
                "headline": f"The conversion gives {k} {len(v)} values ({', '.join(map(str, v))}), "
                            "so nothing is claimed.",
                "notes": [{"message": f"{k}: {v}"} for k, v in sorted(several.items())]}
    if losses:
        return {**base, "verdict": "converted_with_loss", "headline": "Admitted, with losses named."}
    if any(k.endswith("InTarget") for k in conversion):
        return {**base, "verdict": "converted", "headline": "Admitted, converted."}
    return {**base, "verdict": "accepted", "headline": "Admitted as is."}


def derivation_steps(cert: Path, item: str) -> list[dict]:
    """The certificate's own steps whose conclusion is about this item, in a
    fixed order and with blank-node labels that do not change between runs
    (canonical_steps)."""
    f = cert / "derivations.tsv"
    if not f.exists():
        return []
    raw = []
    for line in f.read_text().splitlines():
        cols = line.split("\t")
        if len(cols) < 4 or cols[1].strip("<>") != item:
            continue
        if cols[3].startswith("_:"):
            continue  # a step to an anonymous restriction, plumbing for cls-hv1
        raw.append((cols[0], cols[1:4], [cols[i:i + 3] for i in range(4, len(cols), 3)]))
    return [{"rule": rule, "conclusion": " ".join(_short(x) for x in concl),
             "premises": [" ".join(_short(x) for x in prem) for prem in prems]}
            for rule, concl, prems in canonical_steps(raw)]


def canonical_steps(raw: list[tuple]) -> list[tuple]:
    """Steps as (rule, conclusion terms, list of premise terms), in a fixed
    order, with every blank-node term renamed _:b0, _:b1, ... by first
    appearance in that order.

    The engine writes its steps in an order that varies from run to run and
    mints a fresh label for each blank node on every load, so two builds of the
    same item listed the same steps in another order and under other labels.
    The order is decided with every blank-node term erased, so it does not
    depend on the labels, and the labels are then renamed in that order. Only
    a whole term that starts with _: is a blank node; a literal that contains
    those characters is left as it is."""
    erase = lambda terms: ["_:" if t.startswith("_:") else t for t in terms]
    ordered = sorted(raw, key=lambda st: (st[0], erase(st[1]), [erase(p) for p in st[2]],
                                          st[1], st[2]))
    names: dict[str, str] = {}
    rename = lambda terms: [names.setdefault(t, f"_:b{len(names)}") if t.startswith("_:") else t
                            for t in terms]
    out = []
    for rule, concl, prems in ordered:
        concl = rename(concl)
        out.append((rule, concl, [rename(p) for p in prems]))
    return out


_BINARY_SHA: dict[tuple, str | None] = {}


def engine_identity(e: Engine) -> dict:
    """Which engine judged: the binary that ran and its sha256, and, as a
    separate field, what its MCP layer calls itself (the transport library's
    name and version, not the engine's)."""
    path = shutil.which(e.binary) or e.binary
    sha = None
    try:
        st = os.stat(path)
        key = (path, st.st_size, st.st_mtime_ns)
        if key not in _BINARY_SHA:
            _BINARY_SHA[key] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        sha = _BINARY_SHA[key]
    except OSError:
        pass
    return {"binary": Path(path).name, "binary_sha256": sha, "mcp_server_info": e.server_info}


# Each discovered game adds its own prefix (passport/games.py, from its mapping's base IRI).
PREFIXES = {GA: "ga:",
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
