"""Runs before any test module is imported.

No test may read or write the real export keys in ~/.asset-passport/keys. Every
test, and every command-line run a test starts (subprocesses inherit the
environment), gets a fresh, empty keys directory of its own instead. A test that
needs a key makes one.

Every temporary directory the tests make, in this process or in a command-line
run they start, lands in one directory for the session, which is removed when
the session ends. Without that, each run of the suite left hundreds of engine
stores in the system's temporary directory.
"""

import os
import shutil
import tempfile

SESSION_TMP = tempfile.mkdtemp(prefix="asset-passport-tests-")
tempfile.tempdir = SESSION_TMP
os.environ["TMPDIR"] = SESSION_TMP
os.environ["ASSET_PASSPORT_KEYS"] = tempfile.mkdtemp(prefix="asset-passport-test-keys-")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(SESSION_TMP, ignore_errors=True)
