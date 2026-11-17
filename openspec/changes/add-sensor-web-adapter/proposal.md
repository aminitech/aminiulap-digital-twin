# Add Sensor Web Adapter (OGC SWE / Geospatial Sensor Web)

## Why

`docs/ARCHITECTURE.md` already names the gap this change fills. The S-CDT
six-layer stack places this repo as "the propagation-study engine ... plus the
RF half of layer 4," and layer 4 is **network-as-a-sensor** — the paper's term
for treating the RF network itself as the sensing substrate. The architecture
doc is explicit that this layer is currently a dashed, unbuilt node: "the ISAC
feed ... [is] still design" (`docs/ARCHITECTURE.md:107-109`). It further notes
that the ray-tracer already produces the raw material for it: "per-path
channel impulse responses (delay, angle, Doppler) logged from the twin become
the sensing observables of the deployed network" (`docs/ARCHITECTURE.md:112-113`).
The README makes the same point as a design principle, not just an aspiration:
"Don't build a second sensing estate — the waveform already carrying the
traffic can also be listened to" (`README.md:255`).

So the repo already has (a) the data that would make it a sensor, and (b) a
documented intent to expose it as one. What it does not have is a
**standards-based way to expose it** — today `sionna_out/` is a pile of
PNG/CSV/GIF files meant for a human running the pipeline locally, not
something an external system can discover or query.

A **Geospatial Sensor Web (GSW)** is the established answer to exactly this
problem. The OGC Sensor Web Enablement (SWE) initiative exists to enable "real
time integration of heterogeneous sensor webs and the Internet of Things into
the information infrastructure," standardizing "access to sensor measurements
(including real-time as well as time-series data)" and "retrieval of metadata
for determining sensor capabilities and the quality/reliability of
measurements" across sensor types as different as flood gauges, air-pollution
monitors, and earth-imaging systems.
[[OGC SWE overview, allatlanticocean.org]](https://allatlanticocean.org/initiatives/ogc-sensor-web-enablement/)
The suite splits into an **Information Model** (SensorML for describing a
sensor/system/process; Observations & Measurements, O&M, for encoding what it
measured) and a **Service Model** (SOS for pull-based retrieval, SPS for
tasking, SAS/WNS for alerting, and the newer SensorThings API, a REST/JSON
service for "interconnect[ing] Internet of Things devices, data, and
applications over the Web").
[[OGC standards page]](https://www.ogc.org/standards/swes/)

Treating each modeled tower/receiver as a "sensor" and each ray-traced path's
channel impulse response as an "observation" is not a stretch of these
standards — it is precisely the shape they were built for. And the field has
already solved the specific problem this repo would otherwise hit first:
**sensor sets that change between runs.** Jirka et al. (2010) built their
sensor-discovery framework because "sensor networks and sensor data have
specific characteristics ... [including] the highly dynamic structure of
sensor networks (e.g. mobility of sensors, continuous addition of new sensors,
defective sensors and removal of sensors)," and solved it with a **lower-level
sensor registry** that aggregates SensorML metadata from live SWE services
before pushing a generalized record up to a catalogue (their Fig. 1: `Sensor` /
`SWE Service` → `GetCapabilities`/`DescribeSensor` → `Lower Level Sensor
Registry` → aggregated push → `OGC Catalogue`).
[[Jirka, Nüst, Schulte, Houbie 2010, ISPRS Proceedings XXXVIII-4/W13]](https://www.isprs.org/proceedings/xxxviii/4-W13/ID_13.pdf)
A `study.toml`'s tower registry is exactly this kind of set — static within one
run, but added-to, edited, or replaced between studies (`ulap-scope init`,
per the `study-cli` capability) — so the same registry-then-aggregate pattern
applies directly, just without the mobility/battery-loss churn a live
wireless-sensor deployment would add.

**Why this matters for the project, concretely:**

1. It closes a named architecture gap with prior art instead of inventing a
   bespoke telemetry format — `docs/ARCHITECTURE.md`'s own diagram marks this
   as missing.
2. It makes the "network as a sensor" pitch (`README.md:254-255`) real: a
   claim that the network can be listened to is only useful to a planner or a
   downstream system if there's a standard interface to listen through.
3. O&M and SensorML are ISO-19156-aligned, mature (in production use across
   ocean and environmental observation networks — `allatlanticocean.org` is
   itself an ocean-observation initiative built on this exact framework), so
   adopting them buys interoperability with existing Spatial Data
   Infrastructures (SDIs) for free, rather than requiring every future
   consumer to write a one-off integration against this repo's file layout.
4. It keeps the numerically-validated ray-tracing core (see
   `docs/VALIDATION.md`, `comparison/`) untouched — see `design.md` for how a
   hexagonal (ports & adapters) boundary makes this an additive, low-risk
   change rather than a modification to the simulation stages.

## What Changes

- New OpenSpec capability `sensor-web-adapter`, specified in full in this
  change (see `specs/sensor-web-adapter/spec.md`).
- **No implementation code in this change.** Per `openspec/project.md`'s Git
  Workflow convention ("spec-first for behaviour changes"), this proposal
  establishes *what* the adapter must do and *why*; a follow-up change
  implements it once the spec is reviewed.
- The follow-up implementation (scoped in `tasks.md`, sections 2–6) will add a
  new adapter boundary — outside `ulap_scope/stages/` — that:
  - Treats the existing file contracts (`scene_manifest.json`, `sionna_out/*`)
    as the **port**: the one thing the adapter is allowed to depend on.
  - Maps each tower/receiver to a SensorML-equivalent description, using the
    discovery-metadata profile from Jirka et al. (2010) §3.1: identity,
    spatial position, temporal validity, observed phenomena, access endpoint.
  - Maps per-path CIR outputs (delay, angle, Doppler, path gain) to
    O&M-equivalent observation records.
  - Serves both through the **OGC SensorThings API** — chosen over classic
    XML/SOAP SOS because it is REST/JSON, actively maintained by OGC, and
    fits this project's "small, dependency-light modules" code style
    (`openspec/project.md`) far better than a SOAP stack would.
  - Maintains a small per-study registry that regenerates sensor descriptions
    whenever `study.toml`/`scene_manifest.json` changes — the lower-level
    registry pattern from Jirka et al. (2010), scoped down to fit a tower set
    that changes between studies rather than a live mobile deployment.

## Impact

- Affected specs: `sensor-web-adapter` (new capability, spec-only in this
  change).
- Affected code: **none in this change.** The follow-up implementation change
  will add a new adapter module/service; it will not modify
  `ulap_scope/stages/`, `ulap_scope/pipeline.py`, the CLI, or any existing
  file format.
- No change to existing tests, CI, or the fast test suite.
- Directly answers the "not yet implemented" ISAC/network-as-sensor gap in
  `docs/ARCHITECTURE.md`'s S-CDT diagram; once implemented, that node's status
  in the diagram should move from dashed to solid (tracked in `tasks.md`).

## References

1. OGC Sensor Web Enablement initiative overview —
   <https://allatlanticocean.org/initiatives/ogc-sensor-web-enablement/>
2. OGC, *SWE Service Model Implementation* standard page —
   <https://www.ogc.org/standards/swes/>
3. Jirka, S., Nüst, D., Schulte, J., Houbie, F. (2010). *Integrating the OGC
   Sensor Web Enablement Framework into the OGC Catalogue.* ISPRS Proceedings
   XXXVIII-4/W13. <https://www.isprs.org/proceedings/xxxviii/4-W13/ID_13.pdf>
4. `docs/ARCHITECTURE.md` (this repo) — S-CDT layer diagram, built-vs-specified
   status, "sensing observables" note.
5. `README.md:254-255` (this repo) — "network as a sensor" design principle.
6. `openspec/project.md` (this repo) — architecture and code-style
   conventions this change must respect.
