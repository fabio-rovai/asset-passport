"""Shared by the tests: which engine this is, and a games root with test keys.

No test needs the real private keys in ~/.asset-passport/keys. Each test that
signs copies games/ to a temporary root and publishes keys it made a moment ago.
"""

import shutil
from pathlib import Path

import pytest

from passport import games, sign
from passport.engine import GA, ROOT, Engine, scratch


def packs_carry_certificates() -> bool:
    with Engine(scratch("caps")) as e:
        return e.accepts("onto_pack", "certificate_dir")


needs_packs = pytest.mark.skipif(
    not packs_carry_certificates(),
    reason="this engine cannot carry a certificate in a pack (open-ontologies #266, after v2.0.1)")


def games_copy(strip_keys: tuple[str, ...] = ()) -> Path:
    """games/ copied to a temporary directory. For each game in strip_keys, any
    export key line is removed, so that game publishes no key."""
    root = scratch("games") / "games"
    shutil.copytree(ROOT / "games", root, ignore=shutil.ignore_patterns("__pycache__"))
    for key in strip_keys:
        p = root / key / "profile.ttl"
        p.write_text("\n".join(l for l in p.read_text().split("\n") if f"<{GA}exportKey>" not in l))
    return root


def signed_root() -> tuple[Path, dict]:
    """A games root in which every game publishes a fresh test key."""
    root = games_copy()
    keys = {}
    for key in games.discover(root):
        keys[key] = sign.generate()
        games.publish_key(key, sign.public_b64(keys[key]), root)
    return root, keys
