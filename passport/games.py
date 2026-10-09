"""Which games exist, found on disk and read by the engine.

A game is a directory under the games root that holds a profile.ttl. Its key
is the directory's name. Its IRI, its label and its published export key are
whatever the profile says, read by asking the engine a SPARQL query over the
loaded profile, not by pattern-matching Turtle text.

The games root is, in order of preference: the `root` argument, the
ASSET_PASSPORT_GAMES environment variable, and <repo>/games. Border and loss
contracts live in a `contracts` directory next to the games root when there is
one (ASSET_PASSPORT_CONTRACTS overrides), and in <repo>/contracts otherwise.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .engine import GA, ROOT, Engine, EngineError, scratch

RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"


@dataclass(frozen=True)
class Game:
    key: str
    iri: str
    label: str
    dir: Path
    contracts: Path
    export_key: str | None  # base64 of the raw 32-byte Ed25519 public key

    @property
    def profile(self) -> Path:
        return self.dir / "profile.ttl"

    @property
    def border(self) -> Path:
        return self.contracts / f"{self.key}-border.shacl.ttl"

    @property
    def loss(self) -> Path:
        return self.contracts / f"{self.key}-loss.shacl.ttl"

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


def contracts_root(root: str | Path | None = None) -> Path:
    explicit = os.environ.get("ASSET_PASSPORT_CONTRACTS")
    if explicit:
        return Path(explicit).resolve()
    sibling = games_root(root).parent / "contracts"
    return sibling if sibling.is_dir() else ROOT / "contracts"


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
        raise EngineError(f"no games root at {groot}")
    key = (str(groot), str(contracts_root(root)), binary, _fingerprint(groot))
    if key in _CACHE:
        return _CACHE[key]
    found: dict[str, Game] = {}
    profiles = sorted(groot.glob("*/profile.ttl"))
    if profiles:
        with Engine(scratch("discover"), binary) as e:
            for profile in profiles:
                e.call("onto_clear")
                loaded = e.load(profile)
                if "error" in loaded:
                    raise EngineError(f"{profile} did not load: {loaded['error']}")
                rows = e.call("onto_query", query=(
                    f"SELECT ?g ?label ?key WHERE {{ ?g a <{GA}Game> ; <{RDFS_LABEL}> ?label . "
                    f"OPTIONAL {{ ?g <{GA}exportKey> ?key }} }}")).get("results", [])
                games = {r["g"] for r in rows}
                if len(games) != 1:
                    raise EngineError(f"{profile} must declare exactly one ga:Game with an rdfs:label; "
                                      f"the engine found {len(games)}")
                keys = {_lexical(r["key"]) for r in rows if r.get("key")}
                if len(keys) > 1:
                    raise EngineError(f"{profile} publishes {len(keys)} export keys; a game has one")
                labels = sorted({_lexical(r["label"]) for r in rows})
                found[profile.parent.name] = Game(
                    key=profile.parent.name, iri=rows[0]["g"].strip("<>"), label=labels[0],
                    dir=profile.parent, contracts=contracts_root(root),
                    export_key=next(iter(keys), None))
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
    that key."""
    from .sign import set_export_key

    g = get(game, root, binary)
    set_export_key(g.profile, g.iri, pub_b64)
    after = get(game, root, binary)
    if after.export_key != pub_b64:
        raise EngineError(f"{g.profile} was rewritten, but the engine reads its export key as "
                          f"{after.export_key!r}, not the key just written")
    return after
