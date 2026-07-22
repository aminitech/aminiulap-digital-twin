# study-cli — delta for add-study-wizard

## ADDED Requirements

This change introduces the `study-cli` capability in full. See
`openspec/specs/study-cli/spec.md` for the adopted requirements:

- Interactive study wizard (`init`, default-on-Enter, `--defaults`)
- Projection recommendation (computed UTM zone; non-metric CRS warning)
- Signal catalog with recommendations (3.5 GHz primary; mmWave LoS-only note)
- Geospatial layer fallbacks (OSM / Copernicus GLO-30 / ESRI / WorldCover)
- Versioned, machine-readable `study.toml` with validation
- Delightful terminal UX (tower↔laptop ASCII banner, ♥ recommendations)
