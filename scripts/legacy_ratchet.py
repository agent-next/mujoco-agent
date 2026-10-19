"""Ratchet gate for the legacy test suite (see SPEC.md, "Legacy suite").

The pre-rewrite suite is known red. Each test file runs in its own pytest
process (the combined run segfaults), `--jobs N` of them at a time, results
are summed from JUnit XML, and the gate fails if passes drop or failures/
errors grow versus tests/LEGACY_BASELINE.json. With a file selection (the
space-separated `TESTS` from scripts/ci/affected.py, quoted as one argument)
only those files run, in parallel, and each is gated against its own floor in
tests/LEGACY_BASELINE_FILES.json; a file with no entry there is new and must
be green. An empty selection runs nothing. `--update` runs everything and
rewrites both baselines; only lower them when tests are fixed or a legacy
module is removed on purpose.
"""

import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "LEGACY_BASELINE.json"
BASELINE_FILES = ROOT / "tests" / "LEGACY_BASELINE_FILES.json"


def run_file(path: Path, xml_path: Path) -> dict:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    env.setdefault("MUJOCO_GL", "disabled")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-cov",
         f"--junitxml={xml_path}", str(path)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=600,
    )
    # 0-2 are test outcomes (2 = collection errors, still reported in XML) and
    # 5 = nothing collected; a signal, internal error or missing XML means the
    # file never reported.
    if proc.returncode not in (0, 1, 2, 5) or not xml_path.exists():
        return {"passed": 0, "failed": 0, "errors": 0, "rc": proc.returncode, "crashed": True}
    suite = ET.parse(xml_path).getroot()
    suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
    tests, fail, err, skip = (int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped"))
    return {"passed": tests - fail - err - skip, "failed": fail, "errors": err, "rc": proc.returncode}


def run_all(files, jobs):
    """Run each file in its own pytest process, `jobs` at a time."""
    results = {}
    with tempfile.TemporaryDirectory() as tmp, concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        futures = {pool.submit(run_file, path, Path(tmp) / f"{i}.xml"): path
                   for i, path in enumerate(files)}
        for fut in concurrent.futures.as_completed(futures):
            results[futures[fut]] = fut.result()
    return results


def check_aggregate(totals, base):
    regressions = []
    if totals["passed"] < base["passed"]:
        regressions.append(f"passed {totals['passed']} < baseline {base['passed']}")
    for k in ("failed", "errors"):
        if totals[k] > base[k]:
            regressions.append(f"{k} {totals[k]} > baseline {base[k]}")
    return regressions


def check_per_file(results, floors):
    regressions = []
    for path in sorted(results):
        rel = str(path.relative_to(ROOT))
        res = results[path]
        if rel not in floors:  # a new test file: green on arrival, not grandfathered
            if res["failed"] or res["errors"]:
                regressions.append(f"{rel}: new file not green: {res}")
            continue
        floor = floors[rel]
        if res["passed"] < floor["passed"]:
            regressions.append(f"{rel}: passed {res['passed']} < baseline {floor['passed']}")
        for k in ("failed", "errors"):
            if res[k] > floor[k]:
                regressions.append(f"{rel}: {k} {res[k]} > baseline {floor[k]}")
    return regressions


def parse_args(argv):
    """Return (update, jobs, tests); `--jobs` must carry its value. `tests` is
    the selection as one string (ALL, empty, or space-separated files), or
    None when no selection was given at all."""
    update = False
    jobs = int(os.environ.get("TEST_JOBS", "0")) or min(8, 2 * (os.cpu_count() or 1))
    rest = list(argv)
    files = []
    while rest:
        arg = rest.pop(0)
        if arg == "--update":
            update = True
        elif arg == "--jobs":
            jobs = int(rest.pop(0))  # raises cleanly if the value is missing
        else:
            files.append(arg)
    return update, jobs, (" ".join(files) if files else None)


def main() -> int:
    update, jobs, tests = parse_args(sys.argv[1:])
    if tests is None:  # no selection given: run everything, as before
        tests = "ALL"
    if update:
        tests = "ALL"  # a baseline rewrite must measure the whole suite
    if not tests:
        print("tests: none affected")
        return 0
    if tests == "ALL":
        files = sorted((ROOT / "tests").rglob("test_*.py"))
        mode = "all"
    else:
        files = [ROOT / name for name in tests.split()]
        missing = [name for name in tests.split() if not (ROOT / name).is_file()]
        if missing:
            print("LEGACY RATCHET FAILED: no such test files: " + " ".join(missing))
            return 1
        mode = "subset"
    results = run_all(files, jobs)
    totals = {"passed": 0, "failed": 0, "errors": 0}
    crashed = []
    for path in files:
        res = results[path]
        for k in totals:
            totals[k] += res[k]
        if res.get("crashed"):
            crashed.append(f"{path.relative_to(ROOT)} (rc={res['rc']})")
        print(f"{path.relative_to(ROOT)}: {res}")
    print(f"legacy totals ({mode}, {jobs} jobs): {totals}")
    if crashed:
        print("LEGACY RATCHET FAILED: test files crashed without reporting: " + ", ".join(crashed))
        return 1
    if update:
        BASELINE.write_text(json.dumps(totals, indent=2) + "\n")
        BASELINE_FILES.write_text(json.dumps(
            {str(p.relative_to(ROOT)): {k: r[k] for k in ("passed", "failed", "errors")}
             for p, r in sorted(results.items())}, indent=2, sort_keys=True) + "\n")
        print(f"baselines written: {BASELINE.relative_to(ROOT)}, {BASELINE_FILES.relative_to(ROOT)}")
        return 0
    if mode == "all":
        regressions = check_aggregate(totals, json.loads(BASELINE.read_text()))
    else:
        floors = json.loads(BASELINE_FILES.read_text()) if BASELINE_FILES.is_file() else {}
        regressions = check_per_file(results, floors)
    if regressions:
        print("LEGACY RATCHET FAILED: " + "; ".join(regressions))
        return 1
    print(f"legacy ratchet ok ({mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
