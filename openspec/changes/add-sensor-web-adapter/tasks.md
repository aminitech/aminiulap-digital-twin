# Tasks — add-sensor-web-adapter

## 1. Research & design (this change — spec only, no code)

- [x] 1.1 Ground the proposal in the existing, documented architecture gap
      (`docs/ARCHITECTURE.md` layer 4, network-as-a-sensor, dashed/unbuilt)
- [x] 1.2 Research the OGC SWE standard suite (O&M, SensorML, SOS, SPS, SAS,
      WNS, SensorThings API) and how the Information/Service Model split works
- [x] 1.3 Research sensor-discovery precedent (Jirka et al. 2010): the
      discovery-metadata profile and the lower-level-registry → catalogue
      pattern, and adapt the registry pattern to a tower set that changes
      between studies rather than a live/mobile deployment
- [x] 1.4 Map the integration onto hexagonal architecture (ports & adapters),
      identifying the existing file-based stage contracts as the port so the
      RT/simulation core needs zero modification
- [x] 1.5 Write `proposal.md`, `design.md`, and the `sensor-web-adapter`
      spec delta with reviewable Requirement/Scenario blocks

## 2. Port definition (follow-up implementation change)

- [ ] 2.1 Formal, versioned schema for exactly which fields of `study.toml` /
      `scene_manifest.json` / `sionna_out/*` the adapter may depend on
- [ ] 2.2 Compatibility policy so a future pipeline-output change fails loudly
      in the adapter's tests rather than silently breaking discovery

## 3. SensorML-equivalent mapping (follow-up)

- [ ] 3.1 Tower/receiver → sensor description (identity, position, temporal
      validity, observed phenomena/bands, access endpoint)
- [ ] 3.2 Per-study registry that regenerates descriptions on
      `study.toml`/`scene_manifest.json` change; drops a study's sensors when
      its working directory disappears

## 4. O&M-equivalent mapping (follow-up)

- [ ] 4.1 Per-path CIR (delay, angle of arrival/departure, Doppler, path
      gain) → observation records
- [ ] 4.2 Tie every observation to its originating tower/receiver pair and
      study run identifier; never merge or overwrite across re-runs

## 5. SensorThings API surface (follow-up)

- [ ] 5.1 Read-only endpoints: list sensors ("Things") for a study, describe
      one sensor, list its observations
- [ ] 5.2 Time-range filtering on observations
- [ ] 5.3 No tasking (SPS-equivalent) or alerting (SAS/WNS-equivalent)
      endpoints — explicitly out of scope, see §7

## 6. Tests & docs (follow-up)

- [ ] 6.1 Unit tests: SensorML/O&M mapping against known
      `scene_manifest.json`/`sionna_out/` fixtures
- [ ] 6.2 Contract test: adapter never fabricates observations for a stage
      that has not been run
- [ ] 6.3 Regression test: existing fast suite and pipeline stages unaffected
      by the adapter's presence
- [ ] 6.4 Update `docs/ARCHITECTURE.md`'s S-CDT diagram to move the
      network-as-a-sensor node from dashed to solid once implemented and
      merged
- [ ] 6.5 README/docs cross-reference from the existing "network as a sensor"
      callout to the new adapter

## 7. Out of scope (future changes, not this one)

- [ ] 7.1 Full OGC Catalogue (CSW) integration for cross-study/cross-system
      discovery — no second consumer exists yet to justify it
- [ ] 7.2 Push-based alerting (Sensor Alert Service / Web Notification
      Service equivalents)
- [ ] 7.3 Sensor tasking (Sensor Planning Service equivalent) — not
      applicable; towers are simulation inputs, not taskable devices
- [ ] 7.4 Ledger anchoring, cryptographic admission gate, belief-state sync,
      AI-RAN control loop — the other dashed S-CDT layer-4/6 nodes; unrelated
      to sensor discovery and out of scope here
