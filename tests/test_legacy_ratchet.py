"""Hermetic tests for the legacy ratchet gate (scripts/legacy_ratchet.py).

The ratchet anchors to the repository it lives in, so each case copies the
real script verbatim into a throwaway layout and runs it there. What runs is
the copy, but the copy is the current file, byte for byte. The pytest the
ratchet spawns is a fake (a `src/pytest.py` in the layout, reached through
the PYTHONPATH the ratchet itself sets) that reports JUnit XML from a marker
line in the target file: `# RESULTS <passed>,<failed>,<errors>`.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RATCHET = Path(__file__).resolve().parents[1] / "scripts" / "legacy_ratchet.py"
VERIFY = Path(__file__).resolve().parents[1] / ".claude" / "verify.sh"

FAKE_PYTEST = """\
import os, sys, xml.etree.ElementTree as ET
args = sys.argv[1:]
target = args[-1]
out = None
for a in args:
    if a.startswith("--junitxml="):
        out = a.split("=", 1)[1]
log = os.environ.get("FAKE_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(target + "\\n")
p, f, e = (int(x) for x in open(target).readline().split("RESULTS ", 1)[1].split(","))
suite = ET.Element("testsuite", {"tests": str(p + f + e), "failures": str(f),
                                 "errors": str(e), "skipped": "0"})
ET.ElementTree(suite).write(out)
sys.exit(1 if (f or e) else 0)
"""


class RatchetCase(unittest.TestCase):
    """A throwaway repo layout whose pytest and baselines are under test."""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.repo = self.tmp / "repo"
        for rel in ("scripts", "src", "tests"):
            (self.repo / rel).mkdir(parents=True)
        shutil.copy(RATCHET, self.repo / "scripts" / "legacy_ratchet.py")
        (self.repo / "src" / "pytest.py").write_text(FAKE_PYTEST)
        self.ran = self.tmp / "ran.log"  # the files the spawned pytest ran
        self.baselines({"passed": 0, "failed": 0, "errors": 0}, {})

    # -- helpers -----------------------------------------------------------
    def add(self, rel, results):
        """A test file whose fake pytest reports `results` = (p, f, e)."""
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# RESULTS %d,%d,%d\n" % results)
        return path

    def baselines(self, aggregate, files):
        (self.repo / "tests" / "LEGACY_BASELINE.json").write_text(
            json.dumps(aggregate) + "\n")
        (self.repo / "tests" / "LEGACY_BASELINE_FILES.json").write_text(
            json.dumps(files, indent=2, sort_keys=True) + "\n")

    def ratchet(self, *args):
        """Run the ratchet in the layout; return (rc, stdout)."""
        proc = subprocess.run([sys.executable, str(self.repo / "scripts" / "legacy_ratchet.py"),
                               *args], cwd=self.repo, capture_output=True, text=True,
                              env={**os.environ, "FAKE_LOG": str(self.ran)}, timeout=300)
        return proc.returncode, proc.stdout


class SubsetSelectionTests(RatchetCase):
    """The CI path: a selection runs only those files, one process each."""

    def test_selection_runs_only_the_selected_files(self):
        for name in ("test_a.py", "test_b.py", "test_c.py"):
            self.add("tests/" + name, (1, 0, 0))
        self.baselines({"passed": 3, "failed": 0, "errors": 0},
                       {f"tests/test_{c}.py": {"passed": 1, "failed": 0, "errors": 0}
                        for c in "abc"})
        rc, out = self.ratchet("tests/test_b.py tests/test_c.py")
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(Path(line).name for line in self.ran.read_text().split()),
                         ["test_b.py", "test_c.py"])

    def test_empty_selection_runs_nothing(self):
        self.add("tests/test_a.py", (1, 0, 0))
        self.baselines({"passed": 1, "failed": 0, "errors": 0},
                       {"tests/test_a.py": {"passed": 1, "failed": 0, "errors": 0}})
        rc, out = self.ratchet("")
        self.assertEqual(rc, 0, out)
        self.assertFalse(self.ran.exists(), out)
        self.assertIn("none affected", out)

    def test_selection_of_a_missing_file_fails(self):
        self.add("tests/test_a.py", (1, 0, 0))
        self.baselines({"passed": 1, "failed": 0, "errors": 0}, {})
        rc, out = self.ratchet("tests/test_gone.py")
        self.assertEqual(rc, 1, out)
        self.assertIn("no such test files: tests/test_gone.py", out)

    def test_no_selection_at_all_runs_everything(self):
        self.add("tests/test_a.py", (2, 0, 0))
        self.baselines({"passed": 2, "failed": 0, "errors": 0}, {})
        rc, out = self.ratchet()
        self.assertEqual(rc, 0, out)
        self.assertIn("legacy totals (all,", out)
        self.assertIn("test_a.py", self.ran.read_text())


class PerFileRegressionTests(RatchetCase):
    """In subset mode each file is gated against its own floor."""

    def floor(self, name, **kw):
        entry = {"passed": 0, "failed": 0, "errors": 0}
        entry.update(kw)
        return {name: entry}

    def test_passed_below_the_floor_fails(self):
        self.add("tests/test_a.py", (3, 0, 0))  # 3 passed, floor says 4
        self.add("tests/test_b.py", (2, 0, 0))
        self.baselines({"passed": 5, "failed": 0, "errors": 0},
                       self.floor("tests/test_a.py", passed=4))
        rc, out = self.ratchet("tests/test_a.py tests/test_b.py")
        self.assertEqual(rc, 1, out)
        self.assertIn("tests/test_a.py: passed 3 < baseline 4", out)

    def test_failures_over_the_floor_fails(self):
        self.add("tests/test_a.py", (1, 2, 0))  # 2 failures, floor allows 1
        self.baselines({"passed": 1, "failed": 0, "errors": 0},
                       self.floor("tests/test_a.py", passed=1, failed=1))
        rc, out = self.ratchet("tests/test_a.py")
        self.assertEqual(rc, 1, out)
        self.assertIn("tests/test_a.py: failed 2 > baseline 1", out)

    def test_errors_over_the_floor_fails(self):
        self.add("tests/test_a.py", (1, 0, 2))  # 2 errors, floor allows 1
        self.baselines({"passed": 1, "failed": 0, "errors": 0},
                       self.floor("tests/test_a.py", passed=1, errors=1))
        rc, out = self.ratchet("tests/test_a.py")
        self.assertEqual(rc, 1, out)
        self.assertIn("tests/test_a.py: errors 2 > baseline 1", out)

    def test_at_the_floor_passes(self):
        self.add("tests/test_a.py", (3, 1, 1))  # exactly the floor
        self.baselines({"passed": 3, "failed": 1, "errors": 1},
                       self.floor("tests/test_a.py", passed=3, failed=1, errors=1))
        rc, out = self.ratchet("tests/test_a.py")
        self.assertEqual(rc, 0, out)

    def test_new_file_must_be_green(self):
        # No floor entry: a new test file is not grandfathered red.
        self.add("tests/test_new.py", (1, 2, 0))
        self.baselines({"passed": 1, "failed": 2, "errors": 0}, {})
        rc, out = self.ratchet("tests/test_new.py")
        self.assertEqual(rc, 1, out)
        self.assertIn("new file not green", out)

    def test_new_green_file_passes(self):
        self.add("tests/test_new.py", (2, 0, 0))
        self.baselines({"passed": 2, "failed": 0, "errors": 0}, {})
        rc, out = self.ratchet("tests/test_new.py")
        self.assertEqual(rc, 0, out)

    def test_missing_floors_file_treats_every_selection_as_new(self):
        # LEGACY_BASELINE_FILES.json absent: no floor, so red files fail.
        self.add("tests/test_a.py", (1, 1, 0))
        (self.repo / "tests" / "LEGACY_BASELINE_FILES.json").unlink()
        self.baselines({"passed": 1, "failed": 1, "errors": 0}, {})
        rc, out = self.ratchet("tests/test_a.py")
        self.assertEqual(rc, 1, out)
        self.assertIn("new file not green", out)


class AggregateRegressionTests(RatchetCase):
    def test_all_mode_gates_on_the_aggregate(self):
        self.add("tests/test_a.py", (2, 1, 1))
        self.add("tests/test_b.py", (2, 1, 1))
        self.baselines({"passed": 5, "failed": 2, "errors": 2}, {})
        rc, out = self.ratchet("ALL")
        self.assertEqual(rc, 1, out)
        self.assertIn("passed 4 < baseline 5", out)

    def test_all_mode_ok_at_the_aggregate(self):
        self.add("tests/test_a.py", (2, 1, 1))
        self.baselines({"passed": 2, "failed": 1, "errors": 1}, {})
        rc, out = self.ratchet("ALL")
        self.assertEqual(rc, 0, out)


class UpdateTests(RatchetCase):
    def test_update_runs_everything_and_rewrites_both_baselines(self):
        self.add("tests/test_a.py", (2, 1, 1))
        self.add("tests/test_b.py", (1, 0, 0))
        self.baselines({"passed": 99, "failed": 0, "errors": 0},
                       {"tests/test_a.py": {"passed": 99, "failed": 0, "errors": 0}})
        rc, out = self.ratchet("--update")
        self.assertEqual(rc, 0, out)
        self.assertIn("baselines written", out)
        agg = json.loads((self.repo / "tests/LEGACY_BASELINE.json").read_text())
        self.assertEqual(agg, {"passed": 3, "failed": 1, "errors": 1})
        files = json.loads((self.repo / "tests/LEGACY_BASELINE_FILES.json").read_text())
        self.assertEqual(files["tests/test_a.py"],
                         {"passed": 2, "failed": 1, "errors": 1})
        self.assertEqual(files["tests/test_b.py"],
                         {"passed": 1, "failed": 0, "errors": 0})
        self.assertIn("test_b.py", self.ran.read_text())

    def test_update_ignores_a_selection(self):
        # A baseline rewrite must measure the whole suite, not a subset.
        self.add("tests/test_a.py", (1, 0, 0))
        self.add("tests/test_b.py", (1, 0, 0))
        self.baselines({"passed": 0, "failed": 0, "errors": 0}, {})
        rc, out = self.ratchet("tests/test_a.py", "--update")
        self.assertEqual(rc, 0, out)
        agg = json.loads((self.repo / "tests/LEGACY_BASELINE.json").read_text())
        self.assertEqual(agg, {"passed": 2, "failed": 0, "errors": 0})
        self.assertIn("test_b.py", self.ran.read_text())


class CrashedFileTests(RatchetCase):
    def test_file_that_never_reports_fails_the_gate(self):
        # A pytest that dies without JUnit XML must count as a crash, not as
        # zero tests passing.
        (self.repo / "src" / "pytest.py").write_text("import sys\nsys.exit(139)\n")
        self.add("tests/test_a.py", (1, 0, 0))
        self.baselines({"passed": 1, "failed": 0, "errors": 0},
                       {"tests/test_a.py": {"passed": 1, "failed": 0, "errors": 0}})
        rc, out = self.ratchet("tests/test_a.py")
        self.assertEqual(rc, 1, out)
        self.assertIn("crashed without reporting", out)
        self.assertIn("rc=139", out)


class VerifyHandoffTests(unittest.TestCase):
    """The CI handoff: verify.sh passes TESTS to the ratchet as one quoted
    argument. A stub interpreter records what each invocation received, so
    the contract script runs for real but nothing executes."""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.log = self.tmp / "calls.log"
        stub = self.tmp / "python-stub"
        stub.write_text("#!/usr/bin/env python3\n"
                        "import os, sys\n"
                        "with open(os.environ['STUB_LOG'], 'a') as fh:\n"
                        "    fh.write('\\0'.join(sys.argv[1:]) + '\\n')\n")
        stub.chmod(0o755)
        self.stub = str(stub)

    def run_verify(self, **env):
        proc = subprocess.run(["bash", str(VERIFY)], capture_output=True, text=True,
                              env={**os.environ, "PYTHON": self.stub,
                                   "STUB_LOG": str(self.log), **env}, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        calls = [line.split("\0") for line in self.log.read_text().splitlines()]
        ratchet_calls = [args for args in calls
                         if any("legacy_ratchet.py" in a for a in args)]
        self.assertEqual(len(ratchet_calls), 1, calls)
        return ratchet_calls[0]

    def test_empty_selection_stays_empty(self):
        # The selector prints nothing for a docs-only change; CI hands that
        # through as TESTS="" and it must reach the ratchet as empty, not ALL.
        args = self.run_verify(TESTS="")
        self.assertEqual(args[-1], "")

    def test_unset_selection_defaults_to_all(self):
        # A local pre-commit run gives no TESTS: keep the ALL default.
        args = self.run_verify()
        self.assertEqual(args[-1], "ALL")

    def test_selection_arrives_as_one_quoted_argument(self):
        # Many file names: one argument, never re-split or evaluated by a shell.
        args = self.run_verify(TESTS="tests/test_a.py tests/test_b.py")
        self.assertEqual(args[-1], "tests/test_a.py tests/test_b.py")
        self.assertEqual(len(args), 2)  # just the script path and the selection


if __name__ == "__main__":
    unittest.main()
