#!/bin/bash
# usage (inside a throwaway worktree): [RUNNER=pytest] [TEST_GLOB=':(glob)tests/**/test*.py'] recall.sh <file>...
# Breaks each file, commits, runs every test module on its own, and reports the
# failing modules the affected subset did not select. Import errors count.
A=${AFFECTED:-scripts/ci/affected.py}
# each mutant is undone with a hard reset: refuse to run over uncommitted work
if [ -n "$(git status --porcelain --untracked-files=all)" ]; then echo "recall.sh: worktree not clean; commit or remove changes first" >&2; exit 2; fi
for f in "$@"; do
  git ls-files --error-unmatch -- "$f" >/dev/null 2>&1 || { echo "recall.sh: $f is not tracked" >&2; exit 2; }
done
S=$(mktemp -d)
trap 'rm -rf "$S"' EXIT
for f in "$@"; do
  cp "$f" "$S/orig"
  case "$f" in
    *.py) { printf 'raise RuntimeError("mutant")\n'; cat "$S/orig"; } > "$f" ;;
    *) printf '\nMUTANT ::: {{{\n' >> "$f" ;;
  esac
  git add -- "$f" >/dev/null
  if ! git -c core.hooksPath=/dev/null -c user.email=probe@local -c user.name=probe commit -qm mutant; then
    cp "$S/orig" "$f"; git reset -q -- "$f"
    echo "$f: mutation commit failed; stopped before any reset" >&2
    exit 1
  fi
  sel=$(python3 "$A" --format args 2>/dev/null)
  # file names reach the shell as positional arguments, never as source text
  fails=$(git ls-files -z ${TEST_GLOB:-':(glob)**/test*.py' ':(glob)**/*_test.py'} | sort -zu |
    RUNNER=${RUNNER:-unittest} xargs -0 -P 24 -n 1 sh -c '
      if [ "$RUNNER" = pytest ]; then timeout 600 python3 -m pytest -q -p no:cacheprovider -- "$1" >/dev/null 2>&1; rc=$?; [ $rc -eq 5 ] && rc=0
      else timeout 600 python3 -m unittest -q "$(printf %s "$1" | sed "s#/#.#g; s#\.py\$##")" >/dev/null 2>&1; rc=$?; fi
      [ $rc -eq 0 ] || printf "%s\n" "$1"' _)
  git reset -q --hard HEAD^1
  missed=""
  if [ "$sel" != ALL ]; then
    for p in $fails; do
      case " $sel " in *" $p "*) ;; *) missed="$missed $p" ;; esac
    done
  fi
  n=$( [ "$sel" = ALL ] && echo ALL || echo $sel | wc -w)
  echo "$f: selected=$n failing=$(echo $fails | wc -w) missed=[${missed# }]"
done
