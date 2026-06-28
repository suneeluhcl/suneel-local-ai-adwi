"""
test_runner.py
Master test runner for SuneelWorkSpace.
Run: python3 tests/test_runner.py  OR  run-tests
"""

import json
import os
import subprocess
import sys
import time
try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # noqa: S405 — trusted internal JUnit XML only
from datetime import datetime, timezone

WORKSPACE = os.path.expanduser("~/SuneelWorkSpace")
RESULTS_DIR = os.path.join(WORKSPACE, "tests/reports")


def run_all_tests(verbose: bool = True, fix_on_fail: bool = True) -> dict:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(RESULTS_DIR, f"test_report_{timestamp}.json")
    junit_path = os.path.join(RESULTS_DIR, f"junit_{timestamp}.xml")

    print(f"\n{'='*60}")
    print(f"SuneelWorkSpace Test Suite")
    print(f"   Started: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")

    cmd = [
        sys.executable, "-m", "pytest",
        "tests/",
        "--tb=short",
        f"--junit-xml={junit_path}",
        "-v" if verbose else "-q",
        "--no-header",
        "--color=yes",
        f"--rootdir={WORKSPACE}",
        "-p", "no:cacheprovider",
    ]

    start = time.time()
    result = subprocess.run(cmd, cwd=WORKSPACE)
    duration = time.time() - start

    results = _parse_junit(junit_path)
    results["duration_seconds"] = round(duration, 1)
    results["timestamp"] = datetime.now(timezone.utc).isoformat()
    results["exit_code"] = result.returncode

    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)

    passed = results.get("passed", 0)
    failed = results.get("failed", 0)
    errors = results.get("errors", 0)
    skipped = results.get("skipped", 0)
    total = passed + failed + errors

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed | {failed} failed | {errors} errors | {skipped} skipped")
    print(f"   Duration: {duration:.1f}s | Report: {report_path}")
    print(f"{'='*60}\n")

    return results


def _parse_junit(junit_path: str) -> dict:
    if not os.path.exists(junit_path):
        return {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "failures": []}
    try:
        tree = ET.parse(junit_path)
        root = tree.getroot()
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        if suite is None:
            return {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "failures": []}

        total = int(suite.get("tests", 0))
        failures = int(suite.get("failures", 0))
        errors = int(suite.get("errors", 0))
        skipped = int(suite.get("skipped", 0))
        passed = total - failures - errors - skipped

        failure_details = []
        for testcase in suite.findall(".//testcase"):
            for tag in ("failure", "error"):
                elem = testcase.find(tag)
                if elem is not None:
                    failure_details.append({
                        "test": f"{testcase.get('classname', '')}.{testcase.get('name', '')}",
                        "message": elem.get("message", "")[:200],
                        "type": elem.get("type", ""),
                    })

        return {"passed": passed, "failed": failures, "errors": errors,
                "skipped": skipped, "total": total, "failures": failure_details}
    except Exception as e:
        return {"passed": 0, "failed": 0, "errors": 0, "skipped": 0,
                "failures": [], "parse_error": str(e)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SuneelWorkSpace Test Runner")
    parser.add_argument("--no-fix", action="store_true")
    parser.add_argument("--quiet", "-q", action="store_true")
    parser.add_argument("--loop", type=int, default=1)
    args = parser.parse_args()

    for i in range(args.loop):
        if args.loop > 1:
            print(f"\nTest Loop {i+1}/{args.loop}")
        run_all_tests(verbose=not args.quiet, fix_on_fail=not args.no_fix)
        if args.loop > 1 and i < args.loop - 1:
            time.sleep(3)
