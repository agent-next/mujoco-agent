#!/usr/bin/env python3
"""Run a test suite as many small processes at once.

    run_parallel.py [--runner unittest|pytest] [--jobs N] [ALL | test files...]

unittest: one process per TestCase class of each test module (the given files,
or `test*.py` under --start-dir for ALL); a module that defines load_tests runs
whole, so the suite it builds is kept; a package __init__.py under --start-dir
that names load_tests makes --start-dir one standard `unittest discover` (given
files outside it still run). pytest:
one process per test file of the repo's own collection (its options and
ignores); given files outside that collection are dropped. A collection error,
or a full run that collects nothing, fails. A class with `run_alone = True`
(wall-clock bounds) runs after the pool, by itself (its whole module, if the
module defines load_tests).
Prints each failing unit's output, then one summary line; exit 1 on failure.
"""

import argparse
import fnmatch
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Records collected test files from pytest's own collection (any -q/-qq/addopts), each with
# its effective run_alone flag (inherited, imported or annotated classes included).
COLLECT_PLUGIN = '''
import os
def pytest_collection_finish(session):
    alone = {}
    for item in session.items:
        f = item.nodeid.split("::")[0]
        alone[f] = alone.get(f, False) or bool(getattr(getattr(item, "cls", None), "run_alone", False))
    with open(os.environ["CI_COLLECT_OUT"], "w") as fh:
        fh.write("\\n".join(f"{f}\\t{int(a)}" for f, a in sorted(alone.items())))
'''


def tests_of(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from tests_of(item)
        else:
            yield item


def module_name(path, roots):
    """Dotted name of a test file, relative to the first import root holding it."""
    path = os.path.abspath(path)
    for root in roots:
        if path.startswith(root + os.sep):
            return str(Path(os.path.relpath(path, root)).with_suffix("")).replace(os.sep, ".")
    raise ValueError(f"{path} is outside every import root")


def unittest_units(paths, start_dir):
    """(unit id, run_alone) pairs, import errors, import roots, modules skipped at import. Without a <start_dir>/__init__.py, start_dir is
    an import root too (as `discover` does), ahead of the repo root."""
    roots = [os.getcwd()]
    if not (Path(start_dir) / "__init__.py").exists():
        roots.insert(0, os.path.abspath(start_dir))
    for root in reversed(roots):
        sys.path.insert(0, root)
    if not paths:
        paths = discover_paths(start_dir)
    loader = unittest.defaultTestLoader
    units, broken, skipped = set(), [], []
    for path in paths:
        name = module_name(path, roots)
        try:
            suite = loader.loadTestsFromName(name)
        except unittest.SkipTest as e:  # skipped at import; `unittest <module>` would crash on it
            skipped.append(f"{name}: {e}")
            continue
        tests = list(tests_of(suite))
        failed = [t for t in tests if type(t).__name__ == "_FailedTest"]
        if failed:
            broken += [f"{t.id()}: {t._exception}" for t in failed]
            continue
        alone = any(getattr(type(t), "run_alone", False) for t in tests)
        # load_tests builds its own suite; a factory-made class has no importable name: run the module once
        if hasattr(sys.modules.get(name), "load_tests") or any("<" in type(t).__qualname__ for t in tests):
            units.add((name, alone))
            continue
        for t in tests:
            cls = type(t)  # by its defining module: an imported alias has no name of its own
            units.add((f"{cls.__module__}.{cls.__qualname__}", bool(getattr(cls, "run_alone", False))))
    return sorted(units), broken, roots, skipped


def package_hook(start_dir):
    """A package __init__.py naming load_tests (defined or imported); it shapes the discovered suite."""
    return next((str(p) for p in sorted(Path(start_dir).rglob("__init__.py"))
                 if re.search(r"\bload_tests\b", p.read_text(errors="replace"))), None)


def pytest_files(paths):
    with tempfile.TemporaryDirectory() as td:
        Path(td, "ci_collect_plugin.py").write_text(COLLECT_PLUGIN)
        out_file = Path(td, "collected.txt")
        env = {**os.environ, "CI_COLLECT_OUT": str(out_file),
               "PYTHONPATH": os.pathsep.join(p for p in (td, os.environ.get("PYTHONPATH")) if p)}
        out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-p",
                              "ci_collect_plugin", "-p", "no:cacheprovider"],
                             capture_output=True, text=True, env=env)
        rows = [line.split("\t") for line in out_file.read_text().splitlines()] if out_file.exists() else []
    files, alone = [f for f, _ in rows], {f for f, a in rows if a == "1"}
    if out.returncode != 0 or not files:
        return None, None, f"pytest collection failed (exit {out.returncode}, {len(files)} files)\n{out.stdout}{out.stderr}"
    if not paths:
        return files, alone, None
    collected = {os.path.normpath(f) for f in files}
    outside = sorted(p for p in paths if os.path.normpath(p) not in collected)
    if outside:  # an ignored file was selected: its user may be any test, so run them all
        print("not in the repo's pytest collection: " + " ".join(outside) + "; running the full collection")
        return files, alone, None
    return paths, {p for p in paths if os.path.normpath(p) in {os.path.normpath(a) for a in alone}}, None


def discover_paths(start_dir):
    """test*.py files unittest discovery imports: below start_dir it enters packages only."""
    found = []
    for dirpath, dirs, names in os.walk(start_dir):
        if os.path.normpath(dirpath) != os.path.normpath(start_dir) and \
                not os.path.exists(os.path.join(dirpath, "__init__.py")):
            dirs[:] = []
            continue
        dirs.sort()
        found += [os.path.join(dirpath, n) for n in sorted(names) if fnmatch.fnmatch(n, "test*.py")]
    return found


def run(unit, argv, env=None):
    start = time.monotonic()
    if "pytest" in argv:  # counts from a junit report: quiet options (-qq) hide the summary line
        with tempfile.TemporaryDirectory() as td:
            report = Path(td, "report.xml")
            out = subprocess.run([*argv, f"--junitxml={report}"], capture_output=True, text=True, env=env)
            suites = ET.parse(report).getroot().iter("testsuite") if report.exists() else []
            totals = [(int(x.get("tests", 0)), int(x.get("skipped", 0))) for x in suites]
        ran, skipped = sum(t for t, _ in totals) - sum(k for _, k in totals), sum(k for _, k in totals)
    else:
        out = subprocess.run(argv, capture_output=True, text=True, env=env)
        found = re.search(r"^Ran (\d+) test", out.stdout + out.stderr, re.M)
        ran = int(found.group(1)) if found else 0
        found = re.search(r"skipped=(\d+)", out.stdout + out.stderr)
        skipped = int(found.group(1)) if found else 0
    return unit, out.returncode, out.stdout + out.stderr, time.monotonic() - start, ran, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runner", choices=("unittest", "pytest"), default="unittest")
    ap.add_argument("--jobs", type=int, default=int(os.environ.get("TEST_JOBS", 0)))
    ap.add_argument("--start-dir", default="tests", help="unittest discovery root for ALL")
    ap.add_argument("tests", nargs="*")
    args = ap.parse_args(argv)
    paths = [] if args.tests in ([], ["ALL"]) else args.tests
    env, skipped = None, []
    if args.runner == "pytest":
        files, alone, error = pytest_files(paths)
        if error:
            print(error)
            return 1
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        units = [(p, [*cmd, p], p in alone) for p in files]
    else:
        hook = package_hook(args.start_dir)
        if hook:  # the discover unit covers --start-dir; given files outside it run as usual
            hooked = os.path.abspath(args.start_dir) + os.sep
            outside = [p for p in paths if not os.path.abspath(p).startswith(hooked)]
            names, broken, roots, skipped = unittest_units(outside, args.start_dir) if outside else ([], [], [], [])
        else:
            names, broken, roots, skipped = unittest_units(paths, args.start_dir)
        if broken:
            print("import error:\n" + "\n".join(broken))
            return 1
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(
            [*roots, *([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])])}
        # -P: no implicit cwd ahead of PYTHONPATH, so children import from the roots in collection order
        cmd = [sys.executable, *(["-P"] if sys.version_info >= (3, 11) else []), "-m", "unittest", "-q"]
        units = [(u, [*cmd, u], alone) for u, alone in names]
        if hook:
            print(f"{hook} names load_tests: {args.start_dir} runs as one `unittest discover`")
            top = ["-t", os.getcwd()] if (Path(args.start_dir) / "__init__.py").exists() else []
            units.append((f"discover {args.start_dir}",
                          [sys.executable, "-m", "unittest", "discover", "-q", *top, "-s", args.start_dir],
                          True))  # a hook-built suite's flags are unknown: keep it out of the pool
    workers = args.jobs or 2 * (os.cpu_count() or 1)
    start = time.monotonic()
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda u: run(u[0], u[1], env), [u for u in units if not u[2]]))
    results += [run(u[0], u[1], env) for u in units if u[2]]
    failed = [r for r in results if r[1] != 0]
    for line in skipped:
        print(f"skipped at import: {line}")
    for unit, _, output, *_ in failed:
        print(f"FAIL {unit}\n{output}")
    slowest = max(results, key=lambda r: r[3]) if results else ("-", 0, "", 0.0)
    print(f"{len(results)} units, {len(failed)} failed, {sum(r[4] for r in results)} tests ran, "
          f"{sum(r[5] for r in results) + len(skipped)} skipped, {time.monotonic() - start:.0f}s wall, "
          f"{workers} workers on {os.cpu_count()} cpus, slowest {slowest[0]} {slowest[3]:.0f}s")
    # pytest's own collection already proved a full run non-empty; -qq hides its counts
    if args.runner == "unittest" and not paths and not sum(r[4] + r[5] for r in results) and not skipped:
        print("no tests ran")
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
