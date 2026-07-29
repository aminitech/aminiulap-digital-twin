#!/usr/bin/env bash
# The diagram source is deliberately DUPLICATED across two repositories:
#
#   amini-ulap-digital-twin/docs/diagrams/     (engineering docs, dark default)
#   ulap-research-papers/.../diagrams/         (paper figure, light default)
#
# Duplication is how the two copies drifted apart before — the twin repo said
# "Amini Node Network / National Sovereign Data Lake" while the paper said
# "Amini Cloud / Amini Origin", and nobody noticed. This script makes that
# drift loud instead of silent.
#
#   ./check-sync.sh                       compare against the default path
#   ./check-sync.sh /path/to/twin/repo    compare against an explicit checkout
#
# Exits non-zero if any shared file differs. Wire it into CI if the repos ever
# land in the same pipeline.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_TWIN="$HOME/Downloads/01. projects/2026.07/ulap-digital-twin/amini-ulap-digital-twin"
TWIN="${1:-${ULAP_TWIN_REPO:-$DEFAULT_TWIN}}"
OTHER="$TWIN/docs/diagrams"

# render.sh differs by design: the paper emits the LaTeX filenames.
SHARED=(scdt-architecture.mmd theme-dark.json theme-light.json)

if [ ! -d "$OTHER" ]; then
  echo "cannot find the twin repo's diagrams at:"
  echo "  $OTHER"
  echo "pass the repo root as \$1, or set ULAP_TWIN_REPO."
  exit 2
fi

status=0
for f in "${SHARED[@]}"; do
  if [ ! -f "$OTHER/$f" ]; then
    echo "MISSING  $f  (not in $OTHER)"
    status=1
  elif cmp -s "$HERE/$f" "$OTHER/$f"; then
    echo "ok       $f"
  else
    echo "DRIFT    $f"
    diff -u "$OTHER/$f" "$HERE/$f" | sed 's/^/         /'
    status=1
  fi
done

if [ "$status" -ne 0 ]; then
  echo
  echo "The two copies have drifted. Decide which is correct, copy it over the"
  echo "other, and re-run ./render.sh in BOTH repos so the images match again."
fi
exit "$status"
