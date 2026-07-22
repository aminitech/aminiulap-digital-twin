# Add Study Wizard (`ulap-scope init`)

## Why

The pipeline is currently hard-wired to the Newton, Barbados pilot (CRS, origin,
bbox, bands baked into `config.py` defaults). To make digital-twin propagation
studies **reusable and reproducible** for any location, users need a guided way
to define a study — with the projection/fidelity lessons from the pilot encoded
as defaults and warnings rather than tribal knowledge.

## What Changes

- New `ulap_scope.study` module: `StudySpec` dataclass, bbox math, UTM
  recommendation from longitude/latitude, band + layer catalogs, TOML
  write/read with validation.
- New `ulap_scope.wizard` module: interactive prompts (defaults on Enter),
  ASCII tower/laptop banner with hearts, `--defaults` non-interactive mode.
- `ulap-scope init [--defaults] [-o PATH]` wired into the CLI.
- Unit tests for study math/serialization and a scripted wizard run.

## Impact

- Affected specs: `study-cli` (new capability)
- Affected code: `ulap_scope/cli.py` (+2 new modules, +2 test files)
- No change to existing stages; `study.toml` is additive — stages continue to
  read `config.py` until a follow-up change (`apply-study-config`) points the
  pipeline at the study file.
