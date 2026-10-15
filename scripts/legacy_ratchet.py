"""Ratchet gate for the legacy test suite (see SPEC.md, "Legacy suite").

The pre-rewrite suite is known red. Each test file runs in its own pytest
process (the combined run segfaults), results are summed from JUnit XML, and
the gate fails if passes drop or failures/errors grow versus
tests/LEGACY_BASELINE.json. `--update` rewrites the baseline; only lower it
when tests are fixed or a legacy module is removed on purpose.
"""

import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "LEGACY_BASELINE.json"


def run_file(path: Path, xml_path: Path) -> dict:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    env.setdefault("MUJOCO_GL", "disabled")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-cov",
         f"--junitxml={xml_path}", str(path)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=600,
    )
    if not xml_path.exists():
        return {"passed": 0, "failed": 0, "errors": 1, "rc": proc.returncode}
    suite = ET.parse(xml_path).getroot()
    suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
    tests, fail, err, skip = (int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped"))
    return {"passed": tests - fail - err - skip, "failed": fail, "errors": err, "rc": proc.returncode}


def main() -> int:
    files = sorted((ROOT / "tests").rglob("test_*.py"))
    totals = {"passed": 0, "failed": 0, "errors": 0}
    with tempfile.TemporaryDirectory() as tmp:
        for i, path in enumerate(files):
            res = run_file(path, Path(tmp) / f"{i}.xml")
            for k in totals:
                totals[k] += res[k]
            print(f"{path.relative_to(ROOT)}: {res}")
    print(f"legacy totals: {totals}")
    if "--update" in sys.argv:
        BASELINE.write_text(json.dumps(totals, indent=2) + "\n")
        print(f"baseline written: {BASELINE.relative_to(ROOT)}")
        return 0
    base = json.loads(BASELINE.read_text())
    regressions = []
    if totals["passed"] < base["passed"]:
        regressions.append(f"passed {totals['passed']} < baseline {base['passed']}")
    for k in ("failed", "errors"):
        if totals[k] > base[k]:
            regressions.append(f"{k} {totals[k]} > baseline {base[k]}")
    if regressions:
        print("LEGACY RATCHET FAILED: " + "; ".join(regressions))
        return 1
    print(f"legacy ratchet ok (baseline {base})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
