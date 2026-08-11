# study-cli — delta for add-study-wizard

## ADDED Requirements

This change introduces the `study-cli` capability in full, adopted as
`openspec/specs/study-cli/spec.md`.

### Requirement: Interactive study wizard

The CLI SHALL provide an `init` command that interactively prompts for: study
name, study centre location (longitude/latitude), bounding box (half-width in
metres or explicit bounds), projection (EPSG), frequency bands to model, and
available geospatial layers (building footprints, DEM, basemap, land cover,
towers). Every prompt SHALL offer a default accepted by pressing Enter.

#### Scenario: Accept all defaults

- **WHEN** a user runs `ulap-scope init` and presses Enter at every prompt
- **THEN** a valid `study.toml` for the Newton, Barbados pilot is written

#### Scenario: Non-interactive mode

- **WHEN** a user runs `ulap-scope init --defaults`
- **THEN** the wizard writes the default study file without prompting, so the
  command is scriptable and testable

### Requirement: Projection recommendation

The wizard SHALL compute the UTM zone (and its EPSG code) from the study
centre's longitude and latitude, present it as the recommended projection, and
SHALL warn when the user selects a non-metric projection (e.g. Web Mercator,
EPSG:3857) that distances/link budgets will be distorted.

#### Scenario: Metric UTM recommendation

- **WHEN** the study centre is longitude −59.5339, latitude 13.0881
- **THEN** the wizard recommends EPSG:32621 (UTM zone 21N)

#### Scenario: Web Mercator warning

- **WHEN** the user enters EPSG 3857
- **THEN** the wizard accepts it but prints a distance-distortion warning

### Requirement: Signal catalog with recommendations

The wizard SHALL offer a band catalog (1.8, 3.5, 6, 10, 28, 60 GHz) with 3.5 GHz
marked as the recommended primary band, annotate mmWave bands as LoS-only, and
capture TX power and bandwidth with defaults.

#### Scenario: Default band selection

- **WHEN** the user accepts the default signal selection
- **THEN** `study.toml` records 3.5 GHz as primary with the sub-6 sweep bands

### Requirement: Geospatial layer fallbacks

For each layer the user does not have locally, the wizard SHALL recommend an
open source to pull instead — OSM/Overpass for building footprints, Copernicus
GLO-30 (or SRTM) for the DEM, ESRI World Imagery for the basemap, ESA
WorldCover for land cover — and record the chosen source in `study.toml`.

#### Scenario: No local DEM

- **WHEN** the user answers that they have no DEM file
- **THEN** the wizard records `source = "copernicus-glo30"` for the terrain
  layer and prints where it will be fetched from

### Requirement: Versioned, machine-readable study file

The study file SHALL be TOML, carry a schema version, be round-trippable
(parse → same values), and be validated on load with descriptive errors
(longitude ∈ [−180, 180], latitude ∈ [−90, 90], positive half-width, at least
one band).

#### Scenario: Round trip

- **WHEN** a study spec is written and re-read
- **THEN** all fields compare equal

#### Scenario: Invalid latitude

- **WHEN** a study file declares latitude 95
- **THEN** loading fails with an error naming the field and valid range

### Requirement: Delightful terminal UX

The wizard SHALL open with ASCII art of cell towers communicating with a laptop
(hearts included ♥) and SHALL mark recommendations with a heart glyph, while
remaining fully functional in plain non-UTF-8 terminals (ASCII fallback).

#### Scenario: Banner

- **WHEN** the wizard starts
- **THEN** the tower/laptop banner and a short welcome are printed before the
  first prompt
