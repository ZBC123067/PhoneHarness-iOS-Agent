"""Run the complete offline PhoneHarness unit-regression suite.

This runner intentionally discovers only ``test-agent-*-unit.py`` files.
Interactive legacy scripts may launch apps, send input, or depend on a live
USB-forwarded device; they are not regression evidence and must be run only
through their separately approved device gates.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time


TEST_PATTERN = "test-agent-*-unit.py"
DEFAULT_TIMEOUT_SECONDS = 180
FAILURE_OUTPUT_LIMIT = 4000


def discover_tests(root: Path) -> list[Path]:
    """Return the stable, offline-only unit-test manifest."""

    return sorted(path for path in root.glob(TEST_PATTERN) if path.is_file())


def run_test(script: Path, *, environment: dict[str, str]) -> tuple[bool, float, str]:
    """Run one isolated test script without a shell interpreter."""

    started = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=script.parent,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return False, time.monotonic() - started, "timeout\n%s" % output[-FAILURE_OUTPUT_LIMIT:]

    return result.returncode == 0, time.monotonic() - started, result.stdout


def main() -> int:
    root = Path(__file__).resolve().parent
    tests = discover_tests(root)
    if not tests:
        print("REGRESSION_RESULT FAIL total=0 reason=no_offline_unit_tests_found")
        return 2

    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    failures: list[tuple[Path, str]] = []
    started = time.monotonic()

    print("PhoneHarness Offline Unit Regression")
    print("Scope: test-agent-*-unit.py only; no device or interactive legacy scripts.")
    for index, script in enumerate(tests, start=1):
        passed, elapsed, output = run_test(script, environment=environment)
        status = "PASS" if passed else "FAIL"
        print("%s %d/%d %s %.2fs" % (status, index, len(tests), script.name, elapsed))
        if not passed:
            failures.append((script, output[-FAILURE_OUTPUT_LIMIT:]))

    elapsed = time.monotonic() - started
    print(
        "REGRESSION_RESULT %s total=%d passed=%d failed=%d elapsed_seconds=%.2f"
        % (
            "PASS" if not failures else "FAIL",
            len(tests),
            len(tests) - len(failures),
            len(failures),
            elapsed,
        )
    )
    for script, output in failures:
        print("FAILED_TEST %s" % script.name)
        print(output)

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
