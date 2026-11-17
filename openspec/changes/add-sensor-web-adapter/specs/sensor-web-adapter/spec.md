# sensor-web-adapter — delta for add-sensor-web-adapter

## ADDED Requirements

### Requirement: Adapter boundary — no modification to the simulation core

The sensor-web adapter SHALL be implemented entirely outside
`ulap_scope/stages/` and `ulap_scope/pipeline.py`, consuming only the existing
file-based contracts (`study.toml`, `scene_manifest.json`, `sionna_out/*`) as
its sole input. It SHALL NOT require any change to the shape, naming, or
location of those existing outputs, and SHALL NOT introduce OGC/SWE,
HTTP-framework, or serialization dependencies into the package's core import
surface.

#### Scenario: Pipeline stages remain unaffected

- **WHEN** the sensor-web adapter is added to the codebase
- **THEN** every existing pipeline stage, the CLI, and the fast test suite
  behave identically to before, byte-for-byte on their outputs

#### Scenario: Adapter added with no core dependency changes

- **WHEN** `pip install -e .` is run without the adapter's optional extra
- **THEN** `ulap-scope info` and the fast test suite still work with no
  OGC/SWE or web-service libraries present

### Requirement: SensorML-equivalent sensor description

For every tower and receiver defined in a study, the adapter SHALL produce a
SensorML-equivalent description containing: a unique, stable identifier; a
human-readable name; spatial position (derived from `study.toml`/
`scene_manifest.json`); the temporal validity of the description (the study
run it belongs to); the observed phenomena (the frequency bands modeled for
that study); and an access endpoint through which its observations can be
retrieved. This mirrors the discovery-metadata profile of Jirka et al. (2010)
§3.1 (general description, identification, spatial/temporal/thematic
properties, access properties).

#### Scenario: Describe towers for a study

- **WHEN** a `study.toml` defines two towers
- **THEN** the adapter produces two sensor descriptions, each independently
  retrievable by identifier and discoverable by a spatial bounding-box query

#### Scenario: Missing spatial data

- **WHEN** a tower entry lacks a resolvable position
- **THEN** the adapter excludes it from discovery results and records why,
  rather than publishing a description with a fabricated or default location

### Requirement: O&M-equivalent observation encoding

The adapter SHALL encode every ray-traced propagation path's channel impulse
response — delay, angle of arrival/departure, Doppler shift, and path gain —
as an Observations & Measurements-equivalent record for each study's
coverage/analysis run, tied to the originating tower/receiver pair and to the
specific run that produced it.

#### Scenario: Coverage run produces retrievable observations

- **WHEN** `ulap-scope coverage` completes for a study
- **THEN** the adapter can enumerate one or more observation records per
  tower for that run, each carrying delay, angle, Doppler, and path-gain
  values traceable to the source `sionna_out/` artifact

#### Scenario: Study run superseded

- **WHEN** a study is re-run with different parameters
- **THEN** observations from the prior run remain retrievable by their
  original run identifier and are not silently overwritten or merged with
  the new run's observations

### Requirement: Discovery and retrieval interface

The adapter SHALL expose sensor descriptions and observations through a
pull-based, OGC-standard-aligned interface (OGC SensorThings API), supporting
at minimum: listing sensors ("Things") for a study, describing a single
sensor, and retrieving its observations filtered by time range. Sensor
tasking (Sensor Planning Service) and push-based alerting (Sensor Alert
Service / Web Notification Service) are explicitly out of scope, since
towers in this repo are simulation inputs, not physical devices that can be
tasked or that emit their own alerts.

#### Scenario: List sensors for a study

- **WHEN** a client requests the sensor collection for a study's adapter
  endpoint
- **THEN** it receives one entry per tower/receiver with location and
  SensorML-equivalent metadata, with no tasking or alerting operations
  exposed

#### Scenario: Filter observations by time range

- **WHEN** a client requests a tower's observations bounded to a specific
  study run's time window
- **THEN** only observations from that run are returned

### Requirement: Per-study registry for tower sets that change between studies

The adapter SHALL maintain a per-study registry that regenerates sensor
descriptions whenever a study's `study.toml` or `scene_manifest.json` changes
on disk, without requiring a service restart or manual re-registration,
because a study's tower registry can be created, edited, or replaced between
pipeline runs (via the `study-cli` capability). This is the file-triggered
analogue of the lower-level sensor registry pattern in Jirka et al. (2010)
§5, scoped down from a live/mobile sensor network to a set that changes
between studies rather than continuously at runtime.

#### Scenario: Tower added between runs

- **WHEN** a study's `study.toml` is edited to add a third tower and the
  pipeline is re-run
- **THEN** the adapter's next sensor listing for that study includes three
  sensors without manual reconfiguration

#### Scenario: Study removed

- **WHEN** a study's working directory is deleted
- **THEN** the adapter stops listing that study's sensors on its next
  registry refresh

### Requirement: No fabricated sensor data

The adapter SHALL only publish sensor descriptions and observations backed by
actual pipeline outputs on disk. It SHALL NOT synthesize, interpolate, or
default observation values for a study stage that has not yet been run.

#### Scenario: Study initialized but not yet run

- **WHEN** a study has been created with `ulap-scope init` but
  `ulap-scope coverage`/`analysis` has not been run
- **THEN** the adapter lists the study's sensors (from `study.toml`'s tower
  registry) but returns zero observations for it, rather than placeholder
  values
