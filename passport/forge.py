"""Ways to smuggle Pocket Battlers' Capture Orb into Blockcraft, each played by a competent forger.

A forgery that fails tells you a check works. A forgery that SUCCEEDS tells you
where the guarantee ends, and that is printed on the page too.

Without Pocket Battlers' private key:
  tamper        edit the graph of a signed passport, leave the digests alone
  unhook        delete the inferred `orb a ga:CaptureDevice`, recompute every digest
  false_step    rewrite the certificate's step to conclude ga:HealingConsumable, recompute
  forger_lie    export the orb as a SuperPotion and sign it with the forger's own key
With it (Pocket Battlers itself is the dishonest one):
  source_omits  sign a passport that leaves the capture-device conclusion out
  source_rules  sign a passport packed under a doctored copy of its own profile
  source_lies   sign the orb exported as a SuperPotion: this one gets through
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from . import sign

GA = "https://tesseractsemantics.com/ns/asset-passport/ga#"
RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
REFUSED = "CaptureDevice"     # the class the border refuses
DISGUISE = "HealingConsumable"  # what the forger claims instead


def _u64(n: int) -> bytes:
    return struct.pack("<Q", n)


def content_digest(graph: str, cert: dict | None) -> str:
    """open-ontologies src/pack.rs::content_digest, byte for byte."""
    h = hashlib.sha256()
    h.update(b"oo-pack-content/1\n")
    g = graph.encode()
    h.update(_u64(len(g)))
    h.update(g)
    if cert is None:
        h.update(_u64(0))
    else:
        h.update(_u64(1))
        for s in (cert["format"], cert.get("profile_claimed_by_sender") or ""):
            b = s.encode()
            h.update(_u64(len(b)))
            h.update(b)
        h.update(_u64(cert["asserted"]))
        h.update(_u64(cert["derivations"]))
        files = cert["files"]
        h.update(_u64(len(files)))
        for name in sorted(files):  # BTreeMap order
            nb, bb = name.encode(), files[name].encode()
            h.update(_u64(len(nb)))
            h.update(nb)
            h.update(_u64(len(bb)))
            h.update(bb)
    return h.hexdigest()


def redigest(pack: dict) -> dict:
    """What any forger can do: make both digests agree with the forged content."""
    m = pack["manifest"]
    m["sha256"] = hashlib.sha256(pack["graph"].encode()).hexdigest()
    m["content_sha256"] = content_digest(pack["graph"], m.get("certificate"))
    return pack


def _drop_lines(text: str, needle: str) -> str:
    return "\n".join(l for l in text.split("\n") if needle not in l)


def tamper(pack: dict, item: str) -> dict:
    pack["graph"] = _drop_lines(pack["graph"], f"<{item}> {RDF_TYPE} <{GA}{REFUSED}>")
    return pack


def unhook(pack: dict, item: str) -> dict:
    return redigest(tamper(pack, item))


def false_step(pack: dict, item: str) -> dict:
    old = f"<{GA}{REFUSED}>"
    new = f"<{GA}{DISGUISE}>"
    pack["graph"] = pack["graph"].replace(f"<{item}> {RDF_TYPE} {old}", f"<{item}> {RDF_TYPE} {new}")
    files = pack["manifest"]["certificate"]["files"]
    files["derivations.tsv"] = "\n".join(
        l.replace(f"<{item}>\t{RDF_TYPE}\t{old}", f"<{item}>\t{RDF_TYPE}\t{new}", 1)
        for l in files["derivations.tsv"].split("\n"))
    return redigest(pack)


def read(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def write(pack: dict, path: Path) -> Path:
    Path(path).write_text(json.dumps(pack, indent=2))
    return Path(path)


# ------------------------------------------------------------------ the attempts

ORB = "capture_orb"
SOURCE, TARGET = "battle", "craft"
LIE = {"id": "capture_orb", "kind": "SuperPotion", "name": "Capture Orb", "restoresHp": 10}
DOCTOR_FROM = "battle:CaptureOrb a owl:Class ; rdfs:subClassOf ga:CaptureDevice"
DOCTOR_TO = "battle:CaptureOrb a owl:Class ; rdfs:subClassOf ga:HealingConsumable"

# name, title, what the forger did, why it ends where it ends. The verdict
# itself is never written here: it is whatever admit() returns.
ATTEMPTS = [
    ("tamper", "Edit the passport",
     "Take a passport Pocket Battlers really signed, delete the line that says the orb is a capture "
     "device, and leave the digests alone.",
     "The signature still checks, because it covers the content digest and nobody touched the digest. "
     "The engine then finds that the graph no longer matches the pack's checksum of it, which the content "
     "digest is computed over too, so nothing is loaded."),
    ("unhook", "Edit it, then fix the digests",
     "Delete the same line, then recompute both SHA-256 digests the way the engine does. Anyone can "
     "recompute a digest. The forger has no Pocket Battlers key, so the old signature stays on.",
     "The signature covers the old digest. Against the new one, Pocket Battlers' published key does "
     "not verify it, so the passport is turned back before it is opened."),
    ("false_step", "Forge the proof",
     "Rewrite the certificate's step so it concludes the orb is a healing item, change the graph to "
     "match, and recompute the digests. No key.",
     "New content means a new digest, and the forger cannot sign it. Had Pocket Battlers signed this "
     "forged step itself, the Lean checker would refuse it at the next gate; the tests pin that too."),
    ("forger_lie", "Lie, and sign it yourself",
     "Export the orb with its kind set to SuperPotion and sign the passport in Pocket Battlers' name "
     "with a key the forger made. The signature is a real Ed25519 signature, by the wrong key.",
     "Blockcraft never uses a key that arrives in a passport. It looks up the export key in its own "
     "copy of Pocket Battlers' published profile, and the signature does not verify against that key."),
    ("source_omits", "The issuer leaves a line out",
     "Pocket Battlers itself deletes the line that says the orb is a capture device, recomputes the "
     "digests and signs the result with its real key.",
     "The signature is genuine and the proof checks, because every step left in it is still sound. A "
     "proof cannot show that nothing was left out, so Blockcraft works out what the thing is itself "
     "and finds the missing conclusion."),
    ("source_rules", "The issuer bends its own rules",
     "Pocket Battlers exports the orb under a doctored copy of its own profile, which says a capture "
     "orb is a healing item, and signs it with its real key. The proof is sound over the doctored "
     "premises, so Lean accepts it.",
     "A signature says who issued a passport, not that the rules inside it are the ones the issuer "
     "published. Blockcraft compares them, statement by statement, with its own copy of Pocket Battlers' "
     "published profile and finds the changed statement."),
    ("source_lies", "The issuer lies about the item",
     "Pocket Battlers exports the orb with its kind set to SuperPotion, under its real profile, and "
     "signs it with its real key. Every step from there is honest.",
     "This is where the guarantee ends. A passport proves who issued it and that the paperwork follows "
     "from the issuer's published rules. It cannot prove the issuer told the truth about what the thing "
     "is. Blockcraft knows whom to hold to account, and nothing more."),
]


def doctored_profile(published: Path, out: Path) -> Path:
    src = Path(published).read_text()
    assert DOCTOR_FROM in src, "the doctored profile no longer matches the published one"
    out.write_text(src.replace(DOCTOR_FROM, DOCTOR_TO))
    return out


def forge_all(run: Path, key, binary: str | None = None, root=None, forger_key=None) -> dict[str, Path]:
    """Write every attempt's passport under `run`. `key` is Pocket Battlers'
    real export key; `forger_key` is the forger's own (made fresh if absent)."""
    from .judge import catalogue, export, game_dir, sign_existing
    from . import games

    run.mkdir(parents=True, exist_ok=True)
    orb = next(r for r in catalogue(SOURCE, root) if r["id"] == ORB)
    iri = games.get(SOURCE, root, binary).iri
    honest = export(SOURCE, orb, run / "honest", binary, root=root, key=key)
    item = honest["item_iri"]
    packs = {
        "tamper": write(tamper(read(honest["pack"]), item), run / "tamper.pack"),
        "unhook": write(unhook(read(honest["pack"]), item), run / "unhook.pack"),
        "false_step": write(false_step(read(honest["pack"]), item), run / "false_step.pack"),
        "forger_lie": export(SOURCE, LIE, run / "forger_lie", binary, root=root,
                             key=forger_key or sign.generate(), sign_as=iri)["pack"],
    }
    omits = write(unhook(read(honest["pack"]), item), run / "source_omits.pack")
    sign_existing(omits, iri, key)
    packs["source_omits"] = omits
    (run / "source_rules").mkdir(exist_ok=True)
    doctored = doctored_profile(game_dir(SOURCE, root) / "profile.ttl", run / "source_rules" / "doctored.ttl")
    packs["source_rules"] = export(SOURCE, orb, run / "source_rules", binary, profile=doctored,
                                   root=root, key=key)["pack"]
    packs["source_lies"] = export(SOURCE, LIE, run / "source_lies", binary, root=root, key=key)["pack"]
    packs["honest"] = honest["pack"]
    return packs
