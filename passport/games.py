"""Which games exist, found on disk and read by the engine.

A game is a directory under the games root that holds a profile.ttl. Its key
is the directory's name. Its IRI, its label and its published export key are
whatever the profile says, read by asking the engine a SPARQL query over the
loaded profile, not by pattern-matching Turtle text.

The games root is, in order of preference: the `root` argument, the
ASSET_PASSPORT_GAMES environment variable, and <repo>/games. Border and loss
contracts live in a `contracts` directory next to the games root when there is
one (ASSET_PASSPORT_CONTRACTS overrides), and in <repo>/contracts otherwise.
The lookup is per file: a contract missing from the first directory is looked
for in the next, so a sibling contracts/ directory adds to the repository's
contracts and does not hide them.

Two directories that declare the same game IRI are refused: the second would
otherwise replace the first game's published export key. Two games that publish
the same export key are refused too: a key vouches for one game. A game's
directory name is its key and part of its private key file's name, so it must
be lower-case letters, digits, "_" and "-" (a dot would let a directory take the
name of another game's key file).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .engine import GA, ROOT, ConfigError, Engine, EngineError, scratch

RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
GAME_KEY = re.compile(r"[a-z0-9_-]+")


@dataclass(frozen=True)
class Game:
    key: str
    iri: str
    label: str
    dir: Path
    contracts: tuple[Path, ...]  # where contracts are looked for, first match wins
    export_key: str | None  # base64 of the raw 32-byte Ed25519 public key
    max_player_health: float | None = None  # the profile's ga:maxPlayerHealth, as the engine read it

    @property
    def profile(self) -> Path:
        return self.dir / "profile.ttl"

    def _contract(self, name: str) -> Path:
        for d in self.contracts:
            if (d / name).exists():
                return d / name
        return self.contracts[0] / name  # absent everywhere: name where it was expected first

    @property
    def border(self) -> Path:
        return self._contract(f"{self.key}-border.shacl.ttl")

    @property
    def loss(self) -> Path:
        return self._contract(f"{self.key}-loss.shacl.ttl")

    def get(self, name: str, default=None):
        """Dict-style access, for code written against the old GAMES dict."""
        return getattr(self, name, default)

    def __getitem__(self, name: str):
        return getattr(self, name)


def possessive(label: str) -> str:
    """Blockcraft's, Pocket Battlers'."""
    return label + ("'" if label.endswith("s") else "'s")


def games_root(root: str | Path | None = None) -> Path:
    return Path(root or os.environ.get("ASSET_PASSPORT_GAMES") or ROOT / "games").resolve()


def contracts_dirs(root: str | Path | None = None) -> tuple[Path, ...]:
    """Where contracts are looked for, in order. Each contract file is looked
    up on its own, so a game whose contract is only in the repository still
    finds it when the games root has a contracts/ directory of its own."""
    explicit = os.environ.get("ASSET_PASSPORT_CONTRACTS")
    if explicit:
        return (Path(explicit).resolve(),)
    dirs = []
    sibling = games_root(root).parent / "contracts"
    if sibling.is_dir():
        dirs.append(sibling.resolve())
    if (ROOT / "contracts").resolve() not in dirs:
        dirs.append((ROOT / "contracts").resolve())
    return tuple(dirs)


def valid_export_key(b64: str) -> bool:
    """base64 that decodes to exactly 32 bytes, the size of an Ed25519 public key."""
    try:
        return len(base64.b64decode(b64, validate=True)) == 32
    except (binascii.Error, ValueError):
        return False


_CACHE: dict[tuple, dict[str, Game]] = {}
# Short names for each discovered game's own vocabulary, "craft:" for the
# mapping's base IRI, so the page can print battle:CaptureOrb, not a full IRI.
PREFIXES: dict[str, str] = {}


def _fingerprint(root: Path) -> tuple:
    """The cache key: every profile's path and the hash of its bytes, so a
    rewritten export key is a different set of games."""
    return tuple(sorted((p.parent.name, hashlib.sha256(p.read_bytes()).hexdigest())
                        for p in root.glob("*/profile.ttl")))


def discover(root: str | Path | None = None, binary: str | None = None) -> dict[str, Game]:
    """Every game under the root, keyed by directory name, in name order."""
    groot = games_root(root)
    if not groot.is_dir():
        raise ConfigError(f"no games root at {groot}")
    key = (str(groot), contracts_dirs(root), binary, _fingerprint(groot))
    if key in _CACHE:
        return _CACHE[key]
    found: dict[str, Game] = {}
    profiles = sorted(groot.glob("*/profile.ttl"))
    bad_names = [p.parent.name for p in profiles if not GAME_KEY.fullmatch(p.parent.name)]
    if bad_names:
        raise ConfigError(f"{groot / bad_names[0]}: a game's directory name must be lower-case letters, "
                          "digits, '_' and '-' only, because it names the game and its key file")
    if profiles:
        work = scratch("discover")
        try:
            with Engine(work, binary) as e:
                for profile in profiles:
                    e.call("onto_clear")
                    loaded = e.load(profile)
                    if "error" in loaded:
                        raise EngineError(f"{profile} did not load: {loaded['error']}")
                    rows = e.call("onto_query", query=(
                        f"SELECT ?g ?label ?key ?hp WHERE {{ ?g a <{GA}Game> ; <{RDFS_LABEL}> ?label . "
                        f"OPTIONAL {{ ?g <{GA}exportKey> ?key }} "
                        f"OPTIONAL {{ ?g <{GA}maxPlayerHealth> ?hp }} }}")).get("results", [])
                    games = {r["g"] for r in rows}
                    if len(games) != 1:
                        raise ConfigError(f"{profile} must declare exactly one ga:Game with an rdfs:label; "
                                          f"the engine found {len(games)}")
                    keys = {_lexical(r["key"]) for r in rows if r.get("key")}
                    if len(keys) > 1:
                        raise ConfigError(f"{profile} publishes {len(keys)} export keys; a game has one")
                    bad = sorted(k for k in keys if not valid_export_key(k))
                    if bad:
                        raise ConfigError(f"{profile} publishes an export key that is not base64 of a "
                                          f"32-byte Ed25519 public key: {bad[0]!r}")
                    labels = sorted({_lexical(r["label"]) for r in rows})
                    hps = {_lexical(r["hp"]) for r in rows if r.get("hp")}
                    iri = rows[0]["g"].strip("<>")
                    twin = next((g for g in found.values() if g.iri == iri), None)
                    if twin is not None:
                        raise ConfigError(f"{profile} and {twin.profile} both declare the game {iri}; "
                                          "one game has one profile, or either could replace the other's export key")
                    key_twin = next((g for g in found.values() if keys and g.export_key in keys), None)
                    if key_twin is not None:
                        raise ConfigError(f"{profile} and {key_twin.profile} publish the same export key; "
                                          "a key vouches for one game, or one game could sign as the other")
                    found[profile.parent.name] = Game(
                        key=profile.parent.name, iri=iri, label=labels[0],
                        dir=profile.parent, contracts=contracts_dirs(root),
                        export_key=next(iter(keys), None),
                        max_player_health=_number(next(iter(hps))) if len(hps) == 1 else None)
        finally:
            shutil.rmtree(work, ignore_errors=True)  # what discovery found is kept in memory
    for g in found.values():
        mapping = g.dir / "mapping.json"
        if mapping.exists():
            base = json.loads(mapping.read_text()).get("base_iri")
            if base:
                PREFIXES[base] = f"{g.key}:"
    _CACHE[key] = found
    return found


def get(game: str, root: str | Path | None = None, binary: str | None = None) -> Game:
    games = discover(root, binary)
    if game not in games:
        raise ValueError(f"unknown game {game!r}; the games root has {sorted(games)}")
    return games[game]


def by_iri(iri: str, root: str | Path | None = None, binary: str | None = None) -> Game | None:
    return next((g for g in discover(root, binary).values() if g.iri == iri), None)


def _number(lexical: str) -> int | float:
    n = float(lexical)
    return int(n) if n.is_integer() else n


def _lexical(term: str) -> str:
    """'"Blockcraft"' or '"x"^^<...>' or '"x"@en' -> x."""
    if not term.startswith('"'):
        return term
    return term[1:term.rindex('"')]


class _Default(Mapping):
    """The games under the default root, discovered on first use. Kept so code
    that reads GAMES[key]["label"] still works; new code calls discover()."""

    def _all(self) -> dict[str, Game]:
        return discover()

    def __getitem__(self, k):
        return self._all()[k]

    def __iter__(self):
        return iter(self._all())

    def __len__(self):
        return len(self._all())


GAMES = _Default()


def publish_key(game: str, pub_b64: str, root: str | Path | None = None, binary: str | None = None) -> Game:
    """Write a game's ga:exportKey into its profile, then read it back through
    the engine and refuse to return unless the profile now publishes exactly
    that key. A profile that states its key in a form the rewrite cannot
    replace is refused before anything is written, and a rewrite that does not
    read back as exactly the new key is undone, so a failed publish leaves the
    profile byte for byte as it was."""
    from .sign import set_export_key

    g = get(game, root, binary)
    before = g.profile.read_bytes()
    lead = f"<{g.iri}> <{GA}exportKey> "
    if g.export_key is not None and not any(l.startswith(lead) for l in before.decode().split("\n")):
        raise EngineError(f"{g.profile} states its export key in a form this command does not rewrite "
                          f"(not one line starting with {lead.strip()}). Replace that statement with "
                          f"{lead}\"<key>\" . or delete it, then run this again")
    set_export_key(g.profile, g.iri, pub_b64)
    try:
        after = get(game, root, binary)
        if after.export_key != pub_b64:
            raise EngineError(f"{g.profile} was rewritten, but the engine reads its export key as "
                              f"{after.export_key!r}, not the key just written")
    except Exception:
        g.profile.write_bytes(before)
        raise
    return after
