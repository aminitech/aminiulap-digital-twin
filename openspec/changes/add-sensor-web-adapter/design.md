# Design — Sensor Web Adapter

## Context

A colleague's framing of this problem was: "Think hexagonal architecture."
This document takes that literally and works out exactly where the seam is,
because the answer determines how much of this repo the change is allowed to
touch.

Hexagonal architecture (ports & adapters, Cockburn) puts an application's
domain logic at the center, with zero knowledge of the outside world. Every
interaction with something external — a database, a UI, a message queue, an
external standard like OGC SWE — crosses a **port** (an interface the domain
defines and depends on) implemented by an **adapter** (code that knows the
external technology). The domain can be tested and changed without ever
importing the adapter's dependencies, and a new adapter can be added without
touching the domain.

## Where the seam already exists in this repo

This repo did not need to invent that seam — it already has one, described in
`openspec/project.md`'s Architecture Patterns section:

> Pipeline stages communicate via files (`scene_manifest.json`, Mitsuba XML)
> under `$ULAP_WORK_DIR`; every stage re-runnable in isolation.

and in `docs/ARCHITECTURE.md`:

> **File-based contracts between stages.** Each stage reads/writes plain
> files; any stage can be re-run in isolation, and the manifest is validated
> by the fast test suite (`tests/test_manifest.py`) without any GIS deps
> installed.

That is a hexagonal boundary already, just not named as one: `ulap_scope/stages/`
is the domain core (clip → preprocess → build → export → coverage → analysis →
mmwave-sinr → terrain-ground → animate), and `scene_manifest.json` /
`sionna_out/*` are its **outbound port** — the one thing anything downstream is
allowed to depend on.

**The consequence for this change:** a Geospatial Sensor Web / OGC SWE
integration is just another consumer of that same port. It does not need a new
seam cut into the simulation core; it needs a new adapter reading the port
that already exists.

```
┌─────────────────────────────── DOMAIN CORE ───────────────────────────────┐
│  ulap_scope/stages/                                                       │
│  clip → preprocess → build → export → coverage/analysis/mmwave/animate    │
│  (numerically validated: docs/VALIDATION.md, comparison/)                 │
└───────────────────────────────────┬────────────────────────────────────--┘
                                     │  writes
                                     ▼
                   ┌───────────────────────────────────┐
                   │  PORT (already exists, unchanged)  │
                   │  scene_manifest.json                │
                   │  sionna_out/*.png .csv .gif          │
                   └───────────────────┬─────────────────┘
                                        │  read-only
                                        ▼
                   ┌───────────────────────────────────┐
                   │  NEW ADAPTER: sensor-web-adapter    │
                   │  scope of THIS change's follow-up   │
                   │  ─ tower/receiver → SensorML         │
                   │  ─ per-path CIR   → O&M              │
                   │  ─ served over SensorThings API      │
                   │  ─ per-study registry (§ below)      │
                   └───────────────────┬─────────────────┘
                                        │  HTTP/JSON
                                        ▼
                     External GSW / SDI / OGC Catalogue
                     clients (planners, other Amini/Ulap
                     services, third-party sensor webs)
```

## Why the adapter, not the core, owns every OGC-specific decision

Everything SWE-specific — SensorML XML shape (or its JSON-LD equivalent under
STA), O&M encoding, HTTP routing, pagination, content negotiation — lives
entirely inside the adapter. Concretely, this means the follow-up
implementation:

- **Must not** import OGC/SWE libraries, HTTP frameworks, or serialization
  code into `ulap_scope/stages/` or `ulap_scope/pipeline.py`.
- **Must not** change the shape of `scene_manifest.json` or `sionna_out/`
  outputs to make the adapter's job easier — the port's consumer adapts to the
  port, not the other way around. If a field is genuinely missing from the
  manifest, that is a separate, explicit change to the `study-pipeline`
  capability, reviewed on its own merits.
- **May** read `study.toml` (via the `study-cli` capability's public
  `StudySpec`) and `scene_manifest.json`/`sionna_out/*` directly, since those
  are already the stable, tested contracts the rest of the system depends on.

This mirrors why `openspec/project.md` calls for "No heavy GIS imports in the
package's import surface — stages run out-of-process": the domain core's
dependency-light property is a project value already, not something this
change introduces. A hexagonal boundary is how that value gets extended to a
brand-new external standard without eroding it.

## Choosing SensorThings API as the primary transport

OGC's SWE Service Model offers several service standards for exposing
sensor data: SOS (pull), SPS (tasking), SAS/WNS (alerting), and the newer
SensorThings API (STA), a "RESTful web service based on JSON encoding"
[[OGC standards page]](https://www.ogc.org/standards/swes/). SOS's classic
binding is XML/SOAP-heavy; STA is REST/JSON and OGC-official. Given this
project's stated code-style constraint — "Small, dependency-light modules"
(`openspec/project.md`) — STA is the better transport fit. This is a transport
choice, not a deviation from the SWE model: the **Information Model** (what a
sensor is, what an observation is) is defined separately from the **Service
Model** (how you ask for it) in the SWE architecture itself
[[allatlanticocean.org]](https://allatlanticocean.org/initiatives/ogc-sensor-web-enablement/),
so serving SensorML-equivalent and O&M-equivalent data over STA instead of SOS
stays inside the standard, not outside it.

Tasking (SPS) and alerting (SAS/WNS) are explicitly **out of scope** — see
`tasks.md` §7 — because towers in this repo are simulated inputs to a
ray-tracer, not physical devices that can be tasked or that emit alerts.

## The registry: adapting Jirka et al.'s pattern to a non-mobile sensor set

Jirka et al. (2010) solved sensor discovery for **live, dynamic** sensor
networks — sensors that move, run out of battery, or get added/removed at
runtime — with a two-tier design: a **lower-level sensor registry** harvests
SensorML from each SWE service via `GetCapabilities`/`DescribeSensor`,
aggregates and generalizes it, and only then pushes a summary up to an OGC
Catalogue (their Fig. 1). The reason for the extra tier was explicitly
temporal: "such a high rate of change ... was not specifically taken into
account when the concept of the OGC Catalogue was designed."

This repo's tower/receiver sets do **not** have that runtime volatility — a
study's towers are fixed for the duration of a pipeline run. But they are not
static across the project's lifetime either: `ulap-scope init` (the
`study-cli` capability) can define a new study with a different tower registry
at any time, and an existing study can be edited and re-run. So the same
two-tier shape applies, just triggered by file changes instead of a live
push/pull protocol:

- **Lower tier (this adapter's registry):** watches a study's
  `study.toml`/`scene_manifest.json` for changes and regenerates that study's
  SensorML-equivalent descriptions — the direct analogue of Jirka et al.'s
  registry aggregating from `GetCapabilities`/`DescribeSensor`.
- **Upper tier (explicitly out of scope, `tasks.md` §7):** publishing that
  aggregated metadata into a real OGC Catalogue (CSW) for cross-study,
  cross-system discovery. Building this now would be speculative — there is
  no second system in this repo's ecosystem yet asking to discover studies
  this way — so it is left for a future change if/when that consumer exists.

## Alternatives considered

- **Bespoke JSON feed instead of OGC SWE.** Rejected: it would solve today's
  problem but require every future consumer (another Amini service, a
  government SDI, a research partner) to write custom integration code
  against a schema unique to this repo, exactly the interoperability cost the
  SWE standards exist to avoid.
- **Full classic SOS/XML implementation.** Rejected as the primary transport
  for the reason above (dependency weight, code-style mismatch); not
  precluded as an additional adapter later if a consumer specifically
  requires it — the hexagonal boundary makes that a pure addition, not a
  rewrite.
- **Embedding OGC serialization directly into `sionna_analysis.py`/
  `sionna_coverage.py`.** Rejected: it would couple the validated RT stages
  to an external standard's release cycle and dependencies, violating the
  project's existing "file-based contracts between stages" principle for no
  benefit — the adapter can read the same files just as well from outside.

## References

Same as `proposal.md`; the OGC SWE information/service model split and the
registry pattern are drawn specifically from:

- <https://allatlanticocean.org/initiatives/ogc-sensor-web-enablement/>
- <https://www.ogc.org/standards/swes/>
- Jirka, Nüst, Schulte, Houbie (2010), <https://www.isprs.org/proceedings/xxxviii/4-W13/ID_13.pdf>
