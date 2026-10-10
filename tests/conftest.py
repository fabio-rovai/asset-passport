"""Runs before any test module is imported.

No test may read or write the real export keys in ~/.asset-passport/keys. Every
test, and every command-line run a test starts (subprocesses inherit the
environment), gets a fresh, empty keys directory of its own instead. A test that
needs a key makes one.
"""

import os
import tempfile

os.environ["ASSET_PASSPORT_KEYS"] = tempfile.mkdtemp(prefix="asset-passport-test-keys-")
