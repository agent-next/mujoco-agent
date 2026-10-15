#!/usr/bin/env bash
# Verify contract (pre-commit hook + CI). See SPEC.md "Legacy suite".
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-}"
[ -z "$PY" ] && [ -x .venv/bin/python ] && PY=.venv/bin/python
PY="${PY:-python3}"
"$PY" -m compileall -q src scripts
"$PY" scripts/legacy_ratchet.py
