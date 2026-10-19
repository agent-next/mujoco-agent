#!/usr/bin/env python3
"""Pick the tests a change can affect, from the repo's own dependency graph.

    affected.py [--base REF] [--head REF] [--config FILE] [--format json|args]

Edges, file -> file it depends on:
  * Python imports (absolute, relative, `from x import y`), resolved by dotted
    suffix so flat `sys.path` layouts and `src/` packages both resolve;
  * a path or basename of a tracked file written in a code file's text
    (for Python: code string literals, not comments or docstrings)
    (fixtures, .tsv tables, scripts run by subprocess); a bare basename only
    counts toward an ancestor directory, the own subtree (below the root), or
    a path whose every directory is also a literal (ROOT / "a" / "b" / "c.md").
  * a data-only directory named in code (`ROOT / "fixtures" / "x"`) -> its files;
  * the word `make` in code -> the Makefile (and what the Makefile runs).
An import or file name with same-named candidates (mirrored trees) keeps every
candidate, plus every package __init__.py above it; an __init__.py is a
dependency of every file in its package (recall over precision).
Tests to run = test files in the reverse closure of the changed files.

Fail-safe: mode "all" when a changed file matches a `full` glob, no test
reaches a changed non-ignored file, a file was deleted, the diff or config
cannot be read, or the selector itself fails. Ignored files (docs, assets) go
through the graph too: a test that reads a doc still runs when it changes.
`--format args` prints `ALL`, nothing (no tests), or the test paths.
Config (optional, JSON, default `.ci/affected.json`): keys `tests`, `full`,
`ignore`, each a list of globs that replaces the default.
"""

import argparse
import ast
import fnmatch
import json
import os
import posixpath
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

DEFAULTS = {
    # test files only: a helper or fixture module under tests/ must be reached by a test like any file
    "tests": ["test*.py", "*_test.py"],  # unittest discovers test*.py, pytest also *_test.py
    "full": [
        ".github/**", "Makefile", "*.mk", "pyproject.toml", "setup.py", "setup.cfg",
        "requirements*.txt", "uv.lock", "poetry.lock", "Pipfile.lock", "tox.ini",
        "pytest.ini", "conftest.py", "package.json", "package-lock.json",
        "pnpm-lock.yaml", "yarn.lock", ".ci/**",
    ],
    "ignore": ["*.md", "docs/**", "LICENSE*", "NOTICE", ".gitignore", "*.png", "*.jpg",
               "*.gif", "*.svg", "*.mp4"],
}
CODE_SUFFIXES = {".py", ".sh", ".bash", ".mk", ""}  # "" = Makefile, extensionless scripts
WORD = re.compile(r"[\w.\-/]+")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def match(path, globs):
    """fnmatch where `**/` also matches zero directories and a bare name
    pattern matches the basename at any depth."""
    name = path.rsplit("/", 1)[-1]
    for g in globs:
        if "/" not in g:  # fnmatch's * crosses "/": test*.py would match tests/helpers.py
            if fnmatch.fnmatch(name, g):
                return True
        elif fnmatch.fnmatch(path, g) or fnmatch.fnmatch(path, g.replace("**/", "")):
            return True
    return False


def module_keys(path):
    """Every dotted suffix a file can be imported as: a/b/c.py -> a.b.c, b.c, c."""
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return {".".join(parts[i:]) for i in range(len(parts))} if parts else set()


def parse(path, text):
    try:
        return ast.parse(text, path)
    except (SyntaxError, ValueError):
        return None


def code_strings(tree):
    """String literals in code; docstrings and comments name files without using them."""
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
    return " ".join(n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and id(n) not in docs)


def imports(path, tree):
    pkg = path.rsplit("/", 1)[0].replace("/", ".") if "/" in path else ""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = pkg.split(".") if pkg else []
                up = up[: len(up) - (node.level - 1)] if node.level > 1 else up
                base = ".".join(p for p in (*up, base) if p)
            names.add(base)
            names.update(f"{base}.{a.name}" if base else a.name for a in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            # literal dynamic imports: importlib.import_module("x"), __import__("x")
            func = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if func in ("import_module", "__import__") and isinstance(node.args[0].value, str):
                target = node.args[0].value
                if target.startswith("."):  # import_module(".x", package): relative to that package
                    level = len(target) - len(target.lstrip("."))
                    given = node.args[1] if len(node.args) > 1 else next(
                        (k.value for k in node.keywords if k.arg == "package"), None)
                    base = given.value if isinstance(given, ast.Constant) and isinstance(given.value, str) else pkg
                    up = base.split(".") if base else []
                    up = up[: len(up) - (level - 1)] if level > 1 else up
                    target = ".".join(p for p in (*up, target.lstrip(".")) if p)
                names.add(target)
        elif isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "pytest_plugins" for t in node.targets):
            names.update(c.value for c in ast.walk(node.value)
                         if isinstance(c, ast.Constant) and isinstance(c.value, str))
    return names


def related(path, candidate):
    """A bare file name refers to a file in an ancestor directory of the
    referencing file or, below the repo root, in its own subtree."""
    here = path.rpartition("/")[0]
    there = candidate.rpartition("/")[0]
    if (here + "/").startswith(there + "/") or not there:
        return True
    return bool(here) and (there + "/").startswith(here + "/")


def spelled(parts, words):
    """Every directory of a path written as its own literal: ROOT / "a" / "b" / "c.md"."""
    return all(p in words for p in parts)


def build_graph(files, root):
    tracked = set(files)
    by_module = defaultdict(set)
    by_name = defaultdict(set)
    for f in files:
        if f.endswith(".py"):
            for key in module_keys(f):
                by_module[key].add(f)
        by_name[f.rsplit("/", 1)[-1]].add(f)
        by_name[f].add(f)
    dir_files = defaultdict(set)
    for f in files:
        parts = f.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dir_files["/".join(parts[:i])].add(f)
    # A directory named in code (ROOT / "fixtures" / "x") stands for its files, if
    # it holds data only: a code directory named that way is a path, not an input.
    data_dirs = defaultdict(set)
    for d, members in dir_files.items():
        if not any(m.endswith(".py") for m in members):
            data_dirs[d].add(d)
            data_dirs[d.rsplit("/", 1)[-1]].add(d)
    reverse = defaultdict(set)  # dependency -> dependents
    for f in files:  # a tracked symlink reads as its target
        if (root / f).is_symlink():
            target = posixpath.normpath(posixpath.join(posixpath.dirname(f), os.readlink(root / f)))
            if target in tracked:
                reverse[target].add(f)
    for f in files:
        if Path(f).suffix not in CODE_SUFFIXES:
            continue
        try:
            text = (root / f).read_text(errors="replace")
        except OSError:
            continue
        deps = set()
        if f.endswith(".py"):
            tree = parse(f, text)
            if tree is None:  # unparsable: fall back to every name in the text
                tree = ast.Module(body=[], type_ignores=[])
            else:
                text = code_strings(tree)
            for name in imports(f, tree):
                while name and name not in by_module:
                    name = name.rpartition(".")[0]
                for cand in by_module.get(name, ()):
                    # every copy Python might resolve, and the package
                    # __init__.py files importing it executes
                    deps.add(cand)
                    parts = cand.split("/")[:-1]
                    deps |= {"/".join(parts[:i]) + "/__init__.py" for i in range(1, len(parts) + 1)
                             } & tracked
        words = set(WORD.findall(text))
        for token in words:
            # only a leading "./" or "/" is noise: ".privacy-allowlist" keeps its dot
            token = token[2:] if token.startswith("./") else token.lstrip("/")
            if token.startswith("../"):  # Path(__file__).parent / "../x": the base is unknown, so take
                # the reading from the file's own directory in addition to the by-name edges below
                deps |= by_name.get(posixpath.normpath(posixpath.join(posixpath.dirname(f), token)), set())
                token = re.sub(r"^(\.\./)+", "", token)  # keep a dotfile's own dot
            if "/" in token and token in by_name:
                deps |= by_name[token]
            else:
                deps |= {c for c in by_name.get(token.rsplit("/", 1)[-1], ())
                         if related(f, c) or spelled(c.split("/")[:-1], words)}
        if "make" in words:  # `make -C sub` can reach any Makefile
            deps |= by_name.get("Makefile", set())
        for word in words:
            for d in data_dirs.get(word.strip("/"), ()):
                if related(f, d + "/x") or "/" in word or spelled(d.split("/"), words):
                    deps |= dir_files[d]
        if f.endswith("/__init__.py"):
            # importing anything in a package runs its __init__.py (tests/__init__.py too)
            deps.add(f)
            reverse[f] |= dir_files[f.rpartition("/")[0]] - {f}
        for d in deps - {f}:
            reverse[d].add(f)
    return reverse


def select(changed, files, root, config):
    if changed is None:
        return {"mode": "all", "reason": "diff or config unreadable"}
    full = [c for c in changed if match(c, config["full"])]
    if full:
        return {"mode": "all", "reason": f"global file changed: {full[0]}"}
    tracked = set(files)
    gone = [c for c in changed if c not in tracked]  # a test may read even a deleted doc
    if gone:
        return {"mode": "all", "reason": f"file deleted or renamed: {gone[0]}"}
    reverse = build_graph(files, root)
    is_test = {f for f in files if f.endswith(".py") and match(f, config["tests"])}
    why = {}
    for start in (c for c in changed if c in tracked):
        stack, seen, reached = [start], {start}, False
        while stack:
            cur = stack.pop()
            if cur != start and cur.rsplit("/", 1)[-1] == "conftest.py":
                # fixtures reach their consumers by name, not import: the graph cannot follow them
                return {"mode": "all", "reason": f"{start} reaches {cur}"}
            if cur in is_test:
                why.setdefault(cur, start)
                reached = True
            for dep in reverse.get(cur, ()):
                if dep not in seen:
                    seen.add(dep)
                    stack.append(dep)
        # A file no test reaches may still be covered in a way the graph cannot
        # see (a .js worker loaded by a test runner, a script run by name):
        # only ignorable files (docs, images) are allowed to select nothing.
        if not reached and not match(start, config["ignore"]):
            return {"mode": "all", "reason": f"no test reaches {start}"}
    if not why:
        return {"mode": "none", "reason": "no test reaches the changed docs/assets", "tests": []}
    return {"mode": "subset", "reason": f"{len(changed)} changed file(s)",
            "tests": sorted(why), "because": dict(sorted(why.items()))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="HEAD^1")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--config", default=".ci/affected.json")
    ap.add_argument("--format", choices=("json", "args"), default="json")
    args = ap.parse_args(argv)
    root = Path(git("rev-parse", "--show-toplevel").strip())
    config = dict(DEFAULTS)
    cfg = root / args.config
    try:
        if cfg.is_file():
            loaded = json.loads(cfg.read_text())
            if not isinstance(loaded, dict) or not all(
                    isinstance(v, list) and all(isinstance(g, str) for g in v) for v in loaded.values()):
                raise ValueError("config values must be lists of glob strings")
            config.update(loaded)
        changed = [p for p in git("diff", "--name-only", "--no-renames", args.base, args.head).splitlines() if p]
    except (subprocess.CalledProcessError, ValueError):  # unreadable diff or config
        changed = None
    files = [p for p in git("ls-files").splitlines() if (root / p).is_file()]
    try:
        result = {"changed": changed, **select(changed, files, root, config)}
    except Exception as exc:  # a selector bug must never skip tests
        result = {"changed": changed, "mode": "all", "reason": f"selector error: {exc!r}"}
    if args.format == "args":
        if result["mode"] == "all":
            print("ALL")
        elif result["tests"]:
            print(" ".join(result["tests"]))
        print(f"affected: {result['mode']} - {result['reason']}", file=sys.stderr)
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
