"""Signed exports: a game vouches for the passports it issues.

What is signed is one line of bytes:

    b"asset-passport-signature/1\\n" + game IRI + b"\\n" + manifest.content_sha256

content_sha256 is the engine's digest over the graph AND the certificate, and
onto_unpack refuses a pack whose content does not match it. So the signature
gate checks who vouched for that digest, and the unpack gate checks that the
content is the content the digest names. Neither is enough alone.

The receiver verifies against the public key in ITS OWN copy of the issuing
game's published profile (ga:exportKey), never against a key the pack carries.
Private keys live outside the repository, in ~/.asset-passport/keys
(ASSET_PASSPORT_KEYS overrides), one file per game IRI, as unencrypted PKCS#8
PEM, readable by the owner only.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .engine import GA, ROOT
from .games import possessive

TAG = b"asset-passport-signature/1\n"
ALG = "Ed25519"


# ------------------------------------------------------------------ keys
#
# A private key belongs to a game IDENTITY, the game's IRI, not to a directory
# name: two games roots can both have a directory called "craft" that declare
# different games, and they must never share a key. So the file name carries a
# digest of the IRI:
#
#     <keys dir>/<directory key>.<first 16 hex of sha256(game IRI)>.ed25519
#
# The directory key is only there to make the file recognisable to a person.


def keys_dir() -> Path:
    return Path(os.environ.get("ASSET_PASSPORT_KEYS") or Path.home() / ".asset-passport" / "keys").expanduser()


def _ident(game) -> tuple[str, str]:
    """(directory key, IRI) of a discovered game, or of a (key, iri) pair."""
    if isinstance(game, tuple):
        return game
    return game.key, game.iri


def iri_tag(game_iri: str) -> str:
    return hashlib.sha256(game_iri.encode()).hexdigest()[:16]


def key_path(game) -> Path:
    key, iri = _ident(game)
    return keys_dir() / f"{key}.{iri_tag(iri)}.ed25519"


def legacy_key_path(game) -> Path:
    """Where keys were kept before they were bound to a game's IRI."""
    return keys_dir() / f"{_ident(game)[0]}.ed25519"


def public_b64(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    pub = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def key_sha256(pub_b64: str) -> str:
    return hashlib.sha256(base64.b64decode(pub_b64)).hexdigest()


def _read_private(p: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(p.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{p} is not an Ed25519 private key")
    return key


def load_private(game) -> Ed25519PrivateKey | None:
    """The private key bound to this game's IRI, or None.

    A key in the older, directory-named file (<key>.ed25519) is adopted only
    when its public half is the export key this game's profile already
    publishes, which shows it is this game's key; adopting renames it to the
    IRI-bound name, so it cannot later be adopted by another game. A
    directory-named key that does not match is left alone and not used."""
    p = key_path(game)
    if p.exists():
        return _read_private(p)
    old = legacy_key_path(game)
    published = getattr(game, "export_key", None)
    if old.exists() and published:
        key = _read_private(old)
        if public_b64(key) == published:
            os.replace(old, p)
            return key
    return None


def write_private(game, key: Ed25519PrivateKey, force: bool = False) -> Path:
    """Write a private key to the keys directory, never inside the repository."""
    p = key_path(game)
    if ROOT.resolve() in p.resolve().parents:
        raise ValueError(f"refusing to write a private key inside the repository ({p}); "
                         "set ASSET_PASSPORT_KEYS to a directory outside it")
    if p.exists() and not force:
        raise FileExistsError(f"{p} already exists")
    p.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    return p


def generate() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def set_export_key(profile: Path, game_iri: str, pub_b64: str) -> None:
    """Publish a key in a profile: drop any line that states this game's
    ga:exportKey in the full-IRI form this function writes, and append one.
    The caller re-reads the profile through the engine to confirm it."""
    lead = f"<{game_iri}> <{GA}exportKey> "
    lines = [l for l in Path(profile).read_text().split("\n") if not l.startswith(lead)]
    while lines and lines[-1] == "":
        lines.pop()
    if not any("export key" in l.lower() for l in lines if l.startswith("#")):
        lines += ["", "# The export key this game signs its passports with (Ed25519, base64 of the raw 32 bytes).",
                  "# A receiver verifies a passport against this line in its own copy of this file."]
    lines.append(f'{lead}"{pub_b64}" .')
    Path(profile).write_text("\n".join(lines) + "\n")


# ------------------------------------------------------------------ signing


def message(game_iri: str, content_sha256: str) -> bytes:
    return TAG + game_iri.encode() + b"\n" + content_sha256.encode()


def _strict_pairs(pairs):
    keys = [k for k, _ in pairs]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise ValueError(f"duplicate JSON key {dup[0]!r}")
    return dict(pairs)


def read_pack(path: Path) -> dict:
    """Parse a pack, refusing duplicate keys: two readers that resolve a
    duplicate differently would be checking two different passports."""
    return json.loads(Path(path).read_text(), object_pairs_hook=_strict_pairs)


def sign_pack(path: Path, game_iri: str, key: Ed25519PrivateKey) -> dict:
    """Add a signature to a pack file in place. Returns the signature block."""
    pack = read_pack(path)
    manifest = pack.get("manifest") if isinstance(pack, dict) else None
    digest = manifest.get("content_sha256") if isinstance(manifest, dict) else None
    if not isinstance(digest, str) or not digest:
        raise ValueError("this pack has no content_sha256, so there is nothing to sign")
    pub = public_b64(key)
    pack["signature"] = {"alg": ALG, "game": game_iri, "public_key_sha256": key_sha256(pub),
                         "value": base64.b64encode(key.sign(message(game_iri, digest))).decode()}
    Path(path).write_text(json.dumps(pack, indent=2))
    return pack["signature"]


def verify(path: Path, published: dict[str, tuple[str, str | None]]) -> dict:
    """The signature gate. `published` maps a game IRI to (label, export key)
    as THIS receiver's copies of the published profiles state them.

    Returns {"ok": bool, "why": str | None, ...facts}. Nothing in the pack
    chooses the key: the pack names a game, and the receiver looks it up.

    A file that cannot be opened raises OSError: that is a failed run, not a
    verdict on a passport. A file that opens but is not a well-formed passport
    (not JSON, a duplicated key, not an object) is refused."""
    try:
        pack = read_pack(path)
    except ValueError as err:  # includes JSONDecodeError and UnicodeDecodeError
        return {"ok": False, "why": f"The passport is not well-formed JSON: {err}."}
    if not isinstance(pack, dict):
        return {"ok": False, "why": f"The passport is a JSON {type(pack).__name__}, not an object."}
    if "manifest" in pack and not isinstance(pack["manifest"], dict):
        return {"ok": False, "why": "The passport's manifest is not an object."}
    sig = pack.get("signature")
    if not isinstance(sig, dict) or not all(isinstance(sig.get(k), str) for k in ("alg", "game", "value")):
        return {"ok": False, "why": "This passport is not signed. No game vouches for it."}
    out = {"game": sig["game"], "claimed_key_sha256": sig.get("public_key_sha256")}
    if sig["alg"] != ALG:
        return {**out, "ok": False, "why": f"The signature uses {sig['alg']!r}; only {ALG} is accepted."}
    if sig["game"] not in published:
        return {**out, "ok": False,
                "why": f"The passport says it was signed by {sig['game']}, which is not a game this receiver knows."}
    label, pub = published[sig["game"]]
    out["label"] = label
    if not pub:
        return {**out, "ok": False, "why": f"{label} publishes no export key, so nothing it signs can be checked."}
    try:
        out["public_key_sha256"] = key_sha256(pub)
        if len(base64.b64decode(pub, validate=True)) != 32:
            raise ValueError("not 32 bytes")
    except (binascii.Error, ValueError):
        return {**out, "ok": False,
                "why": f"{possessive(label)} published export key is not base64 of a 32-byte Ed25519 key."}
    digest = (pack.get("manifest") or {}).get("content_sha256")
    if not isinstance(digest, str) or not digest:
        return {**out, "ok": False,
                "why": "The passport has no content digest, so the signature is bound to nothing."}
    try:
        raw = base64.b64decode(sig["value"], validate=True)
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(raw, message(sig["game"], digest))
    except (InvalidSignature, binascii.Error, ValueError):
        return {**out, "ok": False,
                "why": f"The signature does not verify against {possessive(label)} published export key. "
                       "Either the passport changed after it was signed, or someone else signed it."}
    return {**out, "ok": True, "why": None, "content_sha256": digest}
