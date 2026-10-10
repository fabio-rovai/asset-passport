"""Fails a CI run whose pytest skips are not the ones that job expects.

    python3 tests/e2e/ci/skips.py report.xml                 # no test may skip
    python3 tests/e2e/ci/skips.py report.xml --allow "#266"  # a skip is allowed only when its reason says #266

pytest reports a skipped test as a pass for the run as a whole, so a job whose
engine quietly loses a capability stays green while the tests that need it stop
running. This reads the JUnit XML that `pytest --junitxml=report.xml` writes,
prints every skip with its reason, and exits non-zero when any skip is not
allowed, or when no test ran at all.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def skips(report: Path) -> tuple[int, list[tuple[str, str]]]:
    """How many tests ran, and (test id, reason) for each skipped one."""
    root = ET.parse(report).getroot()
    ran, skipped = 0, []
    for case in root.iter("testcase"):
        ran += 1
        for s in case.findall("skipped"):
            test = f"{case.get('classname', '')}::{case.get('name', '')}"
            skipped.append((test, s.get("message") or (s.text or "").strip()))
    return ran, skipped


def verdict(report: Path, allow: list[str]) -> list[str]:
    """Every reason to fail the run. Empty means the skips are the expected ones."""
    ran, skipped = skips(report)
    if ran == 0:
        return [f"{report} records no tests at all"]
    return [f"{test} skipped and is not allowed to: {reason}"
            for test, reason in skipped if not any(a in reason for a in allow)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("report", type=Path)
    ap.add_argument("--allow", action="append", default=[],
                    help="a skip whose reason contains this text is expected; may be given more than once")
    a = ap.parse_args(argv)
    ran, skipped = skips(a.report)
    print(f"{ran} tests recorded, {len(skipped)} skipped")
    for test, reason in skipped:
        print(f"  skipped {test}: {reason}")
    bad = verdict(a.report, a.allow)
    for line in bad:
        print(f"REFUSED: {line}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
