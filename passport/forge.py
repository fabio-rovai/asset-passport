"""Ways to smuggle Pocket Battlers' Capture Orb into Blockcraft, each played by a competent forger.

A forgery that fails tells you a check works. A forgery that SUCCEEDS tells you
where the guarantee ends, and that is printed on the page too.

  tamper     edit the graph, leave the digests alone
  unhook     delete the inferred `orb a ga:CaptureDevice`, recompute every digest
  false_step rewrite the certificate's step to conclude ga:HealingConsumable, recompute
  own_rules  re-export honestly under a doctored profile (the orb is a potion)
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

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
