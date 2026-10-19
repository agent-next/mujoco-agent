#!/usr/bin/env bash
# Verify contract (pre-commit hook + CI). See SPEC.md "Legacy suite".
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-}"
[ -z "$PY" ] && [ -x .venv/bin/python ] && PY=.venv/bin/python
PY="${PY:-python3}"
# ALL (default), empty (no affected tests) or the affected test files, one
# quoted string from scripts/ci/affected.py; CI passes it as TESTS so a file
# name is never evaluated as shell code. An explicitly empty TESTS is a real
# selection (nothing affected) and must not fall back to ALL.
TESTS="${TESTS-ALL}"
"$PY" -m compileall -q src scripts
"$PY" scripts/legacy_ratchet.py "$TESTS"
