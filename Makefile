.PHONY: setup check

# ALL, nothing (no affected tests), or test files: CI passes the output of
# scripts/ci/affected.py here (see .github/workflows/ci.yml).
TESTS ?= ALL

setup:
	python3 --version
	python3 -c "import mujoco, pytest" || { echo "mujoco and pytest are required (requirements-ci.txt)"; exit 1; }

# The legacy suite is known red (see SPEC.md "Legacy suite"): scripts/legacy_ratchet.py
# runs each selected test file in its own pytest process, `TEST_JOBS` at a time, and
# gates against the ratchet baselines - ALL against the aggregate baseline, a
# subset against each file's own floor.
check:
	python3 -m compileall -q src scripts
	$(if $(strip $(TESTS)),python3 scripts/legacy_ratchet.py $(TESTS),@echo "tests: none affected")
