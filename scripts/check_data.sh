#!/usr/bin/env bash
# Verify that the geospatial layers the pipeline needs are present before you
# run it. This repository ships no data (see DATA.md) — you supply it.
#
# Usage:
#   ./scripts/check_data.sh
#   ULAP_DATA_DIR=/path/to/shapefiles ./scripts/check_data.sh
#
# Exits non-zero if a required layer is missing.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ULAP_DATA_DIR:-${ULAP_PROJECT_ROOT:-$REPO_ROOT}/bbd-geo-portal}"

echo "Checking data root: $DATA_DIR"
echo

if [ ! -d "$DATA_DIR" ]; then
  echo "MISSING: data root does not exist."
  echo
  echo "Create it and populate it as described in DATA.md, then set:"
  echo "  export ULAP_DATA_DIR=$DATA_DIR"
  exit 1
fi

# A shapefile is only usable with its sidecars. Check all four.
check_layer() {
  local label="$1" required="$2" path="$3"
  local base="${path%.shp}"
  local missing=()

  for ext in shp shx dbf prj; do
    [ -f "${base}.${ext}" ] || missing+=("${ext}")
  done

  if [ ${#missing[@]} -eq 0 ]; then
    printf '  %-8s %-38s ok\n' "[$required]" "$label"
    return 0
  elif [ ! -f "${base}.shp" ]; then
    printf '  %-8s %-38s NOT FOUND\n' "[$required]" "$label"
    return 1
  else
    printf '  %-8s %-38s incomplete (missing: %s)\n' \
      "[$required]" "$label" "${missing[*]}"
    return 1
  fi
}

fail=0

echo "Required layers:"
check_layer "BuildingFootprints" "required" \
  "$DATA_DIR/shapefiles/BuildingFootprints/BuildingFootprints.shp" || fail=1
check_layer "Barbados_antennes_August2023" "required" \
  "$DATA_DIR/shapefiles/Telecommunications/Barbados_antennes_August2023.shp" || fail=1

echo
echo "Optional layers (wider twin and vulnerability analysis):"
for spec in \
  "Main_roads:Transports/Main_roads" \
  "Bridges:Transports/Bridges" \
  "Ports_landing_facilities:Transports/Ports_landing_facilities" \
  "Major_capital_projects:Major_projects/Major_capital_projects" \
  "Population_vulnerability:Vulnerability_maps/Population_vulnerability" \
  "Environmental_vulnerability:Vulnerability_maps/Environmental_vulnerability" \
  "Equipment_vulnerability:Vulnerability_maps/Equipment_vulnerability" \
  "Global_vulnerability:Vulnerability_maps/Global_vulnerability" \
; do
  check_layer "${spec%%:*}" "optional" \
    "$DATA_DIR/shapefiles/${spec#*:}.shp" || true
done

echo
if [ "$fail" -ne 0 ]; then
  cat <<'EOF'
One or more REQUIRED layers are missing.

The Barbados layers come from the Barbados Geoportal, published by the Lands
and Surveys Department, Government of Barbados. They are not redistributed in
this repository — see DATA.md for provenance, sensitivity, and the expected
directory layout.

If you do not have access to the Barbados layers, you do not need them: run

    ulap-scope init

to define a study area anywhere in the world using open sources (OSM building
footprints, Copernicus GLO-30 DEM, ESRI World Imagery).
EOF
  exit 1
fi

echo "All required layers present. Run 'ulap-scope info' to confirm resolved paths."
