"""Hermetic tests for scripts/ci: each case builds a throwaway git repo."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CI = Path(__file__).resolve().parents[1] / "scripts" / "ci"
FILES = {
    "core.py": "VALUE = 1\n",
    "app.py": "import core\n",
    "lonely.py": "X = 2\n",
    "pkg/__init__.py": "",
    "pkg/util.py": "from . import helper\n",
    "pkg/helper.py": "H = 3\n",
    "mirror/core.py": "VALUE = 1\n",
    "mirror/tests/test_mirror.py": "import core\n",
    "data/table.tsv": "a\tb\n",
    "run.sh": "python3 lonely.py\n",
    "tests/test_app.py": '"""Mentions data/table.tsv in a docstring only."""\nimport app\n',
    "tests/test_pkg.py": "from pkg import util\n",
    "tests/test_dotted.py": "import pkg.helper\n",
    "deploy/tool.py": "T = 1\n",
    "deploy/main.py": "import tool\n",
    "docs/guide.md": "guide\n",
    "skills/admin/SKILL.md": "skill\n",
    "suite/__init__.py": "",
    "suite/test_s.py": "X = 1\n",
    "top/__init__.py": "",
    "top/mid/leaf.py": "L = 1\n",
    "tests/test_leaf.py": "import top.mid.leaf\n",
    ".allowlist": "x\n",
    "bin/probe": "#!/bin/sh\n",
    "tests/test_dotfile.py": 'ALLOW = ROOT / ".allowlist"\nTOOL = ROOT / "bin" / "probe"\n',
    "tests/test_skill.py": 'SKILL = ROOT / "skills" / "admin" / "SKILL.md"\n',
    "tests/test_doc.py": 'DOC = "docs/guide.md"\n',
    "tests/test_table.py": 'PATH = "data/table.tsv"\n',
    "tests/test_run.py": 'CMD = ["bash", "run.sh"]\n',
    "tests/fixtures/f.json": "{}\n",
    "tests/test_fixture.py": 'NAME = "f.json"\n',
    "tests/helpers.py": "H = 1\n",
    "tests/test_uses_helper.py": "import helpers\n",
    "tests/plugin_mod.py": "P = 1\n",
    "tests/plugged.py": "P = 2\n",
    "tests/test_plugins.py": 'pytest_plugins = ["tests.plugged"]\n',
    "reg.py": "R = 1\n",
    "tests/testreg.py": "import reg\n",
    "dyn.py": "D = 1\n",
    "tests/test_dyn.py": 'import importlib\nM = importlib.import_module("dyn")\n',
    "demo/Makefile": "check:\n\tsh check.sh\n",
    "demo/check.sh": "true\n",
    "demo/x.py": "X = 1\n",
    "tests/test_demo.py": 'CMD = ["make", "-C", "demo", "check"]\n',
    "ref/guide.txt": "g\n",
    "sub/test_up.py": 'DOC = Path(__file__).parent / "../ref/guide.txt"\n',
    "config.md": "c\n",
    "tests/config.md": "c\n",
    "tests/nested/test_cfg.py": 'CFG = Path(__file__).parent.parent / "../config.md"\n',
    "rel/__init__.py": "",
    "rel/core.py": "C = 1\n",
    "rel/service.py": 'import importlib\nCORE = importlib.import_module(".core", __package__)\n',
    "tests/test_rel_service.py": "import rel.service\n",
    ".rules.md": "r\n",
    "tests/nested/test_rules.py": 'RULES = Path(__file__).parent.parent / "../.rules.md"\n',
    "fx/__init__.py": "",
    "fx/core.py": "V = 1\n",
    "fx/conftest.py": "import fx.core\n",
    "fx/test_fx_direct.py": "import fx.core\n",
    "lib/__init__.py": "",
    "lib/core.py": "L = 1\n",
    "tests/test_lib_direct.py": "import lib.core\n",
    "tests/test_lib_dyn.py": 'import importlib\nM = importlib.import_module(".core", "lib")\n',
    "README.md": "docs\n",
    "Makefile": "check:\n\ttrue\n",
}


def git(root, *args):
    # host hooks (core.hooksPath) are not part of the system under test
    subprocess.run(["git", "-C", str(root), "-c", "core.hooksPath=/dev/null", *args],
                   check=True, capture_output=True)


def git_out(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True).stdout


class AffectedTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        for rel, text in FILES.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)
        git(self.root, "init", "-q", "-b", "work")
        git(self.root, "add", "-A")
        self.commit("base")

    def commit(self, msg):
        git(self.root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", msg)

    def change(self, *edits, delete=()):
        for rel in edits:
            with open(self.root / rel, "a") as fh:
                fh.write("# edit\n")
        for rel in delete:
            git(self.root, "rm", "-q", rel)
        git(self.root, "add", "-A")
        self.commit("change")
        out = subprocess.run([sys.executable, str(CI / "affected.py")], cwd=self.root,
                             capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def test_import_chain_selects_only_its_tests(self):
        r = self.change("core.py")  # the mirror test's `import core` may resolve here too
        self.assertEqual((r["mode"], r["tests"]),
                         ("subset", ["mirror/tests/test_mirror.py", "tests/test_app.py"]))

    def test_relative_import_resolves(self):
        r = self.change("pkg/helper.py")
        self.assertEqual(r["tests"], ["tests/test_dotted.py", "tests/test_pkg.py"])

    def test_package_init_is_a_dependency_of_dotted_imports(self):
        r = self.change("pkg/__init__.py")
        self.assertEqual(r["tests"], ["tests/test_dotted.py", "tests/test_pkg.py"])

    def test_path_string_and_subprocess_script_are_edges(self):
        self.assertEqual(self.change("data/table.tsv")["tests"], ["tests/test_table.py"])
        self.assertEqual(self.change("lonely.py")["tests"], ["tests/test_run.py"])

    def test_bare_name_in_own_subtree_is_an_edge(self):
        self.assertEqual(self.change("tests/fixtures/f.json")["tests"], ["tests/test_fixture.py"])

    def test_mirrored_tree_keeps_every_copy_python_might_import(self):
        self.assertEqual(self.change("mirror/core.py")["tests"],
                         ["mirror/tests/test_mirror.py", "tests/test_app.py"])

    def test_changed_test_runs_itself(self):
        self.assertEqual(self.change("tests/test_pkg.py")["tests"], ["tests/test_pkg.py"])

    def test_docs_only_runs_nothing(self):
        r = self.change("README.md")
        self.assertEqual((r["mode"], r["tests"]), ("none", []))

    def test_doc_read_by_a_test_selects_it(self):
        self.assertEqual(self.change("docs/guide.md")["tests"], ["tests/test_doc.py"])

    def test_package_init_reaches_every_test_in_its_package(self):
        self.assertEqual(self.change("suite/__init__.py")["tests"], ["suite/test_s.py"])

    def test_init_above_a_namespace_gap_is_a_dependency(self):
        self.assertEqual(self.change("top/__init__.py")["tests"], ["tests/test_leaf.py"])

    def test_dotfiles_and_extensionless_files_are_edges(self):
        self.assertEqual(self.change(".allowlist")["tests"], ["tests/test_dotfile.py"])
        self.assertEqual(self.change("bin/probe")["tests"], ["tests/test_dotfile.py"])

    def test_deleted_doc_runs_all(self):
        r = self.change(delete=["docs/guide.md"])
        self.assertEqual(r["mode"], "all")

    def test_path_built_from_literals_is_an_edge(self):
        self.assertEqual(self.change("skills/admin/SKILL.md")["tests"], ["tests/test_skill.py"])

    def test_code_no_test_reaches_runs_all(self):
        r = self.change("deploy/tool.py")
        self.assertEqual(r["mode"], "all")
        self.assertIn("no test reaches deploy/tool.py", r["reason"])

    def test_bad_config_runs_all(self):
        (self.root / ".ci").mkdir()
        (self.root / ".ci" / "affected.json").write_text("{not json")
        r = self.change("core.py")  # .ci/** is also a full glob; run on the next commit
        self.assertEqual(r["mode"], "all")
        r = self.change("core.py")
        self.assertEqual((r["mode"], r["reason"]), ("all", "diff or config unreadable"))

    def test_wrong_type_config_runs_all(self):
        (self.root / ".ci").mkdir()
        for text in ('{"tests": 5}', '{"tests": "test*.py"}', "null"):  # valid JSON, wrong shape
            (self.root / ".ci" / "affected.json").write_text(text)
            r = self.change("core.py")
            self.assertEqual(r["mode"], "all", text)
            self.assertIn("config unreadable", r["reason"])

    def test_selector_crash_runs_all(self):
        self.change("core.py")
        code = ("import importlib.util, json, sys\n"
                f"spec = importlib.util.spec_from_file_location('a', {str(CI / 'affected.py')!r})\n"
                "a = importlib.util.module_from_spec(spec); spec.loader.exec_module(a)\n"
                "def boom(*args): raise RuntimeError('bug')\n"
                "a.select = boom\nsys.exit(a.main([]))\n")
        out = subprocess.run([sys.executable, "-c", code], cwd=self.root, capture_output=True,
                             text=True, check=True)
        r = json.loads(out.stdout)
        self.assertEqual(r["mode"], "all")
        self.assertIn("selector error", r["reason"])

    def test_fail_safe_cases_run_all(self):
        self.assertEqual(self.change("Makefile")["mode"], "all")
        r = self.change(delete=["pkg/helper.py"])
        self.assertEqual(r["mode"], "all")
        self.assertIn("deleted", r["reason"])

    def test_helper_module_under_tests_is_not_a_test(self):
        self.assertEqual(self.change("tests/helpers.py")["tests"], ["tests/test_uses_helper.py"])
        # loaded by name (pytest_plugins), so no edge: it must not count as its own test
        self.assertEqual(self.change("tests/plugin_mod.py")["mode"], "all")

    def test_parent_relative_path_is_an_edge(self):
        self.assertEqual(self.change("ref/guide.txt")["tests"], ["sub/test_up.py"])
        # the base directory is unknown: the root file must stay a dependency too
        self.assertIn("tests/nested/test_cfg.py", self.change("config.md")["tests"])

    def test_change_reaching_conftest_runs_all(self):
        r = self.change("fx/core.py")
        self.assertEqual(r["mode"], "all")
        self.assertIn("conftest.py", r["reason"])

    def test_relative_dynamic_import_uses_its_package_argument(self):
        self.assertIn("tests/test_lib_dyn.py", self.change("lib/core.py")["tests"])

    def test_relative_dynamic_import_resolves(self):
        self.assertIn("tests/test_rel_service.py", self.change("rel/core.py")["tests"])

    def test_parent_relative_dotfile_keeps_its_dot(self):
        self.assertEqual(self.change(".rules.md")["tests"], ["tests/nested/test_rules.py"])

    def test_symlink_reads_as_its_target(self):
        (self.root / "data" / "link.tsv").symlink_to("table.tsv")
        (self.root / "tests" / "test_link.py").write_text('P = "data/link.tsv"\n')
        git(self.root, "add", "-A")
        self.commit("link")
        self.assertIn("tests/test_link.py", self.change("data/table.tsv")["tests"])

    def test_unittest_discovery_names_are_tests(self):
        self.assertEqual(self.change("reg.py")["tests"], ["tests/testreg.py"])

    def test_literal_dynamic_import_is_an_import(self):
        self.assertEqual(self.change("dyn.py")["tests"], ["tests/test_dyn.py"])
        self.assertEqual(self.change("tests/plugged.py")["tests"], ["tests/test_plugins.py"])

    def test_make_reaches_a_subproject_makefile(self):
        self.assertIn("tests/test_demo.py", self.change("demo/check.sh")["tests"])

    def test_rename_counts_as_deleting_the_old_path(self):
        git(self.root, "mv", "README.md", "OVERVIEW.md")
        self.commit("rename")
        out = subprocess.run([sys.executable, str(CI / "affected.py")], cwd=self.root,
                             capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(out.stdout)["mode"], "all")

    def test_file_nobody_uses_runs_all(self):
        (self.root / "orphan.cfg").write_text("x\n")
        git(self.root, "add", "-A")
        self.commit("orphan")
        r = self.change("orphan.cfg")
        self.assertEqual(r["mode"], "all")
        self.assertIn("no test reaches", r["reason"])


class RecallProbeTests(unittest.TestCase):
    def test_failed_mutation_commit_never_resets(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root, shim = Path(td.name) / "repo", Path(td.name) / "bin"
        root.mkdir()
        shim.mkdir()
        (root / "a.py").write_text("A = 1\n")
        git(root, "init", "-q", "-b", "work")
        for text in ("B = 1\n", "B = 2\n"):
            (root / "b.py").write_text(text)
            git(root, "add", "-A")
            git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", text)
        head = git_out(root, "rev-parse", "HEAD")
        real_git = subprocess.run(["sh", "-c", "command -v git"], capture_output=True,
                                  text=True).stdout.strip()
        (shim / "git").write_text(
            f'#!/bin/sh\nfor a in "$@"; do [ "$a" = commit ] && exit 1; done\nexec {real_git} "$@"\n')
        (shim / "git").chmod(0o755)
        env = {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}"}
        out = subprocess.run(["bash", str(CI / "recall.sh"), "a.py"], cwd=root, env=env,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("mutation commit failed", out.stderr)
        self.assertEqual(git_out(root, "rev-parse", "HEAD"), head)
        self.assertEqual((root / "a.py").read_text(), "A = 1\n")


class RecallDirtyTests(unittest.TestCase):
    def test_refuses_a_dirty_worktree(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        (root / "a.py").write_text("A = 1\n")
        git(root, "init", "-q", "-b", "work")
        git(root, "add", "-A")
        git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        (root / "a.py").write_text("A = 2\n")
        (root / "new.txt").write_text("keep\n")
        out = subprocess.run(["bash", str(CI / "recall.sh"), "a.py"], cwd=root,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertEqual((root / "a.py").read_text(), "A = 2\n")
        self.assertEqual((root / "new.txt").read_text(), "keep\n")


class RecallDefaultGlobTests(unittest.TestCase):
    def test_pytest_style_test_names_are_probed(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        (root / "tests").mkdir()
        (root / "tests" / "__init__.py").write_text("")
        (root / "a.py").write_text("A = 1\n")
        (root / "tests" / "a_test.py").write_text("import a\n")
        git(root, "init", "-q", "-b", "work")
        git(root, "add", "-A")
        git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        out = subprocess.run(["bash", str(CI / "recall.sh"), "a.py"], cwd=root, capture_output=True,
                             text=True, env={**os.environ, "AFFECTED": str(CI / "affected.py")})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("a.py: selected=1 failing=1 missed=[]", out.stdout)


class RecallCleanupTests(unittest.TestCase):
    def test_snapshot_dir_is_removed(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root, tmp = Path(td.name) / "repo", Path(td.name) / "tmp"
        (root / "tests").mkdir(parents=True)
        tmp.mkdir()
        (root / "a.py").write_text("A = 1\n")
        (root / "tests" / "test_a.py").write_text("import a\n")
        git(root, "init", "-q", "-b", "work")
        git(root, "add", "-A")
        git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        out = subprocess.run(["bash", str(CI / "recall.sh"), "a.py"], cwd=root, capture_output=True,
                             text=True, env={**os.environ, "TMPDIR": str(tmp),
                                             "AFFECTED": str(CI / "affected.py")})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(list(tmp.iterdir()), [])


class RecallUntrackedTests(unittest.TestCase):
    def test_refuses_untracked_target_even_when_status_hides_it(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        (root / "a.py").write_text("A = 1\n")
        git(root, "init", "-q", "-b", "work")
        git(root, "add", "-A")
        git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        git(root, "config", "status.showUntrackedFiles", "no")
        (root / "new.py").write_text("keep\n")
        out = subprocess.run(["bash", str(CI / "recall.sh"), "new.py"], cwd=root,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertEqual((root / "new.py").read_text(), "keep\n")


class RecallInjectionTests(unittest.TestCase):
    def test_file_names_are_not_shell_source(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        (root / "tests").mkdir()
        (root / "a.py").write_text("A = 1\n")
        (root / "tests" / "test_a;touch${IFS}SENTINEL;.py").write_text("import a\n")
        git(root, "init", "-q", "-b", "work")
        git(root, "add", "-A")
        git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        out = subprocess.run(["bash", str(CI / "recall.sh"), "a.py"], cwd=root,
                             capture_output=True, text=True,
                             env={**os.environ, "TEST_GLOB": "tests/*",
                                  "AFFECTED": str(CI / "affected.py")})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertFalse((root / "SENTINEL").exists())
        self.assertIn("a.py: selected=1 failing=1 missed=[]", out.stdout)


class RunParallelTests(unittest.TestCase):
    def suite(self, body, *args, package=True, files=None):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        (root / "tests").mkdir()
        if package:
            (root / "tests" / "__init__.py").write_text("")
        (root / "tests" / "test_x.py").write_text("import unittest\n" + body)
        for rel, text in (files or {}).items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        return subprocess.run([sys.executable, str(CI / "run_parallel.py"), *args], cwd=root,
                              capture_output=True, text=True)

    def test_counts_and_exit_zero(self):
        out = self.suite(
            "class A(unittest.TestCase):\n    def test_a(self): pass\n"
            "    @unittest.skip('x')\n    def test_s(self): pass\n"
            "class B(unittest.TestCase):\n    run_alone = True\n    def test_b(self): pass\n")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("2 units, 0 failed, 3 tests ran, 1 skipped", out.stdout)

    def test_explicit_paths_load_from_repo_root(self):
        out = self.suite("class A(unittest.TestCase):\n    def test_a(self): pass\n",
                         "tests/test_x.py")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("1 units, 0 failed, 1 tests ran", out.stdout)

    def test_tests_dir_without_init_is_its_own_import_root(self):
        out = self.suite("import helper\nclass A(unittest.TestCase):\n    def test_a(self): pass\n",
                         package=False, files={"tests/helper.py": "H = 1\n"})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("1 units, 0 failed, 1 tests ran", out.stdout)

    def test_load_tests_module_runs_whole(self):
        # load_tests builds a configured instance; rebuilding the class would pass
        out = self.suite(
            "class A(unittest.TestCase):\n"
            "    value = 0\n"
            "    def test_value(self): self.assertEqual(self.value, 0)\n"
            "def load_tests(loader, tests, pattern):\n"
            "    t = A('test_value'); t.value = 1\n"
            "    return unittest.TestSuite([t])\n")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("FAIL tests.test_x\n", out.stdout)

    def test_import_error_fails_with_its_message(self):
        out = self.suite("import no_such_module_xyz\n")
        self.assertEqual(out.returncode, 1)
        self.assertIn("no_such_module_xyz", out.stdout)

    @unittest.skipUnless(subprocess.run([sys.executable, "-m", "pytest", "--version"],
                                        capture_output=True).returncode == 0, "pytest absent")
    def test_pytest_collection_error_fails(self):
        for ini in ("", "[pytest]\naddopts = -qq\n"):
            out = self.suite("def test_ok(): pass\n", "--runner", "pytest",
                             files={"tests/test_bad.py": "import no_such_module_xyz\n",
                                    "pytest.ini": ini or "[pytest]\n"})
            self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
            self.assertIn("collection failed", out.stdout)

    @unittest.skipUnless(subprocess.run([sys.executable, "-m", "pytest", "--version"],
                                        capture_output=True).returncode == 0, "pytest absent")
    def test_pytest_quiet_addopts_still_runs_every_file(self):
        out = self.suite("def test_bad(): assert False\n", "--runner", "pytest",
                         files={"pytest.ini": "[pytest]\naddopts = -qq\n"})
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("FAIL tests/test_x.py", out.stdout)

    def test_non_package_tests_import_repo_root_modules(self):
        out = self.suite("import app\nclass A(unittest.TestCase):\n    def test_a(self): pass\n",
                         package=False, files={"app.py": "APP = 1\n"})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_explicit_path_outside_start_dir(self):
        out = self.suite("class A(unittest.TestCase):\n    def test_a(self): pass\n",
                         "mirror/test_m.py", package=False,
                         files={"mirror/test_m.py":
                                "import unittest\nclass M(unittest.TestCase):\n    def test_m(self): pass\n"})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("1 units, 0 failed, 1 tests ran", out.stdout)

    def test_cross_module_load_tests_keeps_configured_instances(self):
        out = self.suite(
            "from tests.cases import Case\n"
            "def load_tests(loader, tests, pattern):\n"
            "    t = Case('test_value'); t.value = 1\n"
            "    return unittest.TestSuite([t])\n",
            files={"tests/cases.py": "import unittest\nclass Case(unittest.TestCase):\n"
                                     "    value = 0\n"
                                     "    def test_value(self): self.assertEqual(self.value, 0)\n"})
        self.assertEqual(out.returncode, 1, out.stdout)

    def test_load_tests_module_keeps_run_alone(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        (root / "tests").mkdir()
        (root / "tests" / "__init__.py").write_text("")
        (root / "tests" / "test_y.py").write_text(
            "import unittest\nclass A(unittest.TestCase):\n    run_alone = True\n"
            "    def test_a(self): pass\n"
            "def load_tests(loader, tests, pattern):\n    return tests\n")
        probe = ("import sys; sys.path.insert(0, sys.argv[1]); import run_parallel as r; "
                 "print(r.unittest_units([], 'tests')[0])")
        out = subprocess.run([sys.executable, "-c", probe, str(CI)], cwd=root,
                             capture_output=True, text=True)
        self.assertIn("[('tests.test_y', True)]", out.stdout, out.stderr)

    @unittest.skipUnless(subprocess.run([sys.executable, "-m", "pytest", "--version"],
                                        capture_output=True).returncode == 0, "pytest absent")
    def test_pytest_env_addopts_cannot_hide_tests(self):
        td_env = {**os.environ, "PYTEST_ADDOPTS": "-qq"}
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        (root / "tests").mkdir()
        (root / "tests" / "test_x.py").write_text("def test_bad(): assert False\n")
        out = subprocess.run([sys.executable, str(CI / "run_parallel.py"), "--runner", "pytest"],
                             cwd=root, capture_output=True, text=True, env=td_env)
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("FAIL tests/test_x.py", out.stdout)

    @unittest.skipUnless(subprocess.run([sys.executable, "-m", "pytest", "--version"],
                                        capture_output=True).returncode == 0, "pytest absent")
    def test_pytest_collection_keeps_repo_ignore_options(self):
        out = self.suite("def test_ok(): pass\n", "--runner", "pytest",
                         files={"pytest.ini": "[pytest]\naddopts = --ignore=tests/fixtures\n",
                                "tests/fixtures/test_fx.py": "import no_such_module_xyz\n"})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("1 units, 0 failed", out.stdout)

    def test_package_load_tests_hook_shapes_the_run(self):
        hook = ("import unittest\nclass Extra(unittest.TestCase):\n    def test_e(self): self.fail('hook')\n"
                "def load_tests(loader, tests, pattern):\n"
                "    tests.addTests(loader.loadTestsFromTestCase(Extra))\n"
                "    tests.addTests(loader.discover('tests', pattern or 'test*.py', top_level_dir='.'))\n"
                "    return tests\n")
        out = self.suite("class A(unittest.TestCase):\n    def test_a(self): pass\n",
                         files={"tests/__init__.py": hook})
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("names load_tests", out.stdout)

    def test_imported_package_load_tests_hook_is_found(self):
        out = self.suite("class A(unittest.TestCase):\n    def test_a(self): pass\n",
                         files={"tests/__init__.py": "from .hook import load_tests\n",
                                "tests/hook.py": "import unittest\nclass Extra(unittest.TestCase):\n"
                                "    def test_e(self): self.fail('hook')\n"
                                "def load_tests(loader, tests, pattern):\n"
                                "    tests.addTests(loader.loadTestsFromTestCase(Extra))\n    return tests\n"})
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)

    def test_package_hook_still_runs_given_files_outside_it(self):
        out = self.suite("class A(unittest.TestCase):\n    def test_a(self): pass\n",
                         "tests/test_x.py", "mirror/test_other.py",
                         files={"tests/__init__.py": "def load_tests(loader, tests, pattern):\n"
                                "    return loader.discover('tests', pattern or 'test*.py', top_level_dir='.')\n",
                                "mirror/__init__.py": "",
                                "mirror/test_other.py": "import unittest\nclass M(unittest.TestCase):\n"
                                "    def test_m(self): self.fail('outside')\n"})
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("outside", out.stdout)

    def test_module_skipped_at_import_counts_as_a_skip(self):
        out = self.suite("raise unittest.SkipTest('absent')\n")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("1 skipped", out.stdout)

    def test_imported_alias_class_runs(self):
        out = self.suite("from tests.cases import Shared as Renamed\n",
                         files={"tests/cases.py": "import unittest\nclass Shared(unittest.TestCase):\n"
                                "    def test_s(self): pass\n"})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("1 tests ran", out.stdout)

    @unittest.skipUnless(subprocess.run([sys.executable, "-m", "pytest", "--version"],
                                        capture_output=True).returncode == 0, "pytest absent")
    def test_pytest_quiet_or_all_skipped_full_run_passes(self):
        for body in ("def test_ok(): pass\n", "import pytest\nskip = pytest.mark.skip\n@skip\ndef test_s(): pass\n"):
            out = self.suite(body, "--runner", "pytest", files={"pytest.ini": "[pytest]\naddopts = -qq\n"})
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    # Other holds its flag 3 s; Iso polls 2.5 s for it, so any overlap in the pool is seen
    ALONE = ("import os, time\nclass Iso(unittest.TestCase):\n    run_alone = True\n"
             "    def test_iso(self):\n        end = time.time() + 2.5\n"
             "        while time.time() < end:\n"
             "            self.assertFalse(os.path.exists('other.flag')); time.sleep(0.05)\n")
    OTHER = ("import os, time\nclass Other(unittest.TestCase):\n"
             "    def test_other(self):\n        open('other.flag', 'w').close(); time.sleep(3)\n"
             "        os.remove('other.flag')\n")

    @unittest.skipUnless(subprocess.run([sys.executable, "-m", "pytest", "--version"],
                                        capture_output=True).returncode == 0, "pytest absent")
    def test_pytest_keeps_run_alone_out_of_the_pool(self):
        out = self.suite(self.ALONE, "--runner", "pytest",
                         files={"tests/test_other.py": "import unittest\n" + self.OTHER})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_package_hook_discover_keeps_run_alone(self):
        out = self.suite(self.ALONE, "tests/test_x.py", "mirror/test_other.py",
                         files={"tests/__init__.py": "def load_tests(loader, tests, pattern):\n"
                                "    return loader.discover('tests', pattern or 'test*.py', top_level_dir='.')\n",
                                "mirror/__init__.py": "", "mirror/test_other.py": "import unittest\n" + self.OTHER})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    @unittest.skipUnless(subprocess.run([sys.executable, "-m", "pytest", "--version"],
                                        capture_output=True).returncode == 0, "pytest absent")
    def test_pytest_counts_survive_quiet_options(self):
        out = self.suite("import pytest\nskip = pytest.mark.skip\ndef test_ok(): pass\n@skip\ndef test_s(): pass\n",
                         "--runner", "pytest", files={"pytest.ini": "[pytest]\naddopts = -qq\n"})
        self.assertIn("1 tests ran, 1 skipped", out.stdout)

    @unittest.skipUnless(subprocess.run([sys.executable, "-m", "pytest", "--version"],
                                        capture_output=True).returncode == 0, "pytest absent")
    def test_pytest_inherited_run_alone_stays_out_of_the_pool(self):
        base = self.ALONE.replace("class Iso(unittest.TestCase):\n    run_alone = True\n",
                                  "class Base(unittest.TestCase):\n    run_alone: bool = True\n"
                                  "class Iso(Base):\n")
        out = self.suite(base, "--runner", "pytest",
                         files={"tests/test_other.py": "import unittest\n" + self.OTHER})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_full_run_respects_discovery_package_boundaries(self):
        out = self.suite("class A(unittest.TestCase):\n    def test_a(self): pass\n",
                         files={"tests/fixtures/test_invalid.py": "def broken(:\n"})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_factory_made_class_runs_by_module(self):
        out = self.suite("def make_case():\n    class Case(unittest.TestCase):\n"
                         "        def test_c(self): pass\n    return Case\nCase = make_case()\n")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("1 tests ran", out.stdout)

    def test_factory_module_runs_once_with_module_isolation(self):
        out = self.suite(self.ALONE + "def make_case():\n    class Case(unittest.TestCase):\n"
                         "        def test_c(self): pass\n    return Case\nCase = make_case()\n",
                         files={"tests/test_other.py": "import unittest\n" + self.OTHER})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("3 tests ran", out.stdout)  # test_iso + test_c once each, plus test_other

    def test_children_import_from_collection_roots_in_order(self):
        out = self.suite("import helper\nclass A(unittest.TestCase):\n"
                         "    def test_a(self): self.assertEqual(helper.WHERE, 'tests')\n",
                         package=False, files={"helper.py": "WHERE = 'root'\n",
                                               "tests/helper.py": "WHERE = 'tests'\n"})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_suite_skipped_in_setupclass_passes(self):
        out = self.suite("class A(unittest.TestCase):\n    @classmethod\n    def setUpClass(cls):\n"
                         "        raise unittest.SkipTest('absent')\n    def test_a(self): pass\n")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_full_run_that_runs_nothing_fails(self):
        out = self.suite("X = 1\n")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("no tests ran", out.stdout)

    @unittest.skipUnless(subprocess.run([sys.executable, "-m", "pytest", "--version"],
                                        capture_output=True).returncode == 0, "pytest absent")
    def test_pytest_full_run_collecting_nothing_fails(self):
        out = self.suite("def helper(): pass\n", "--runner", "pytest")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)

    @unittest.skipUnless(subprocess.run([sys.executable, "-m", "pytest", "--version"],
                                        capture_output=True).returncode == 0, "pytest absent")
    def test_pytest_given_files_keep_repo_ignores(self):
        out = self.suite("def test_ok(): pass\n", "--runner", "pytest", "tests/test_x.py",
                         "tests/fixtures/test_fx.py",
                         files={"pytest.ini": "[pytest]\naddopts = --ignore=tests/fixtures\n",
                                "tests/fixtures/test_fx.py": "import no_such_module_xyz\n"})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("1 units, 0 failed", out.stdout)
        self.assertIn("tests/fixtures/test_fx.py; running the full collection", out.stdout)

    def test_failure_exits_one_and_names_the_class(self):
        out = self.suite("class A(unittest.TestCase):\n    def test_a(self): self.fail('boom')\n")
        self.assertEqual(out.returncode, 1)
        self.assertIn("FAIL tests.test_x.A", out.stdout)
        self.assertIn("boom", out.stdout)


if __name__ == "__main__":
    unittest.main()
