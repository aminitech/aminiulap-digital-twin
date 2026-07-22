# Tasks — add-study-wizard

## 1. Study model

- [x] 1.1 `StudySpec` dataclass with defaults matching the Barbados pilot
- [x] 1.2 UTM zone/EPSG recommendation from lon/lat
- [x] 1.3 Bounding-box derivation from centre + half-width
- [x] 1.4 TOML emit + parse (tomllib with pre-3.11 fallback) + validation

## 2. Wizard

- [x] 2.1 Prompt helpers (default-on-Enter, choices, multi-select, yes/no)
- [x] 2.2 ASCII banner: towers ↔ laptop, hearts ♥ (ASCII fallback)
- [x] 2.3 Prompts: name, location, bbox, projection (UTM recommended,
      3857 warning), signals, layers (open-data fallbacks), outputs
- [x] 2.4 `--defaults` non-interactive mode; `-o` output path
- [x] 2.5 Wire `init` into `ulap-scope` CLI

## 3. Tests & docs

- [x] 3.1 Unit tests: UTM cases, bbox math, round-trip, validation errors
- [x] 3.2 Scripted wizard test (fed answers, asserts written file)
- [x] 3.3 README updates (root + ulap-scope)

## 4. Follow-up (separate change: `apply-study-config`)

- [ ] 4.1 `load_config(study=...)` — derive `Config` from a `study.toml`
- [ ] 4.2 Layer fetchers for the recommended open sources (OSM, GLO-30)
