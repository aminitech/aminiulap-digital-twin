# Publication Readiness Checklist

For paper #2, *Sovereign Cognitive Digital Twins: Fusing 6G ISAC, AI-RAN, and
Zero-Trust Edge Grids* (`research-paper/README.md`, under internal review,
arXiv cs.NI planned).

Status as of `6f68419`, 2026-07-29. `[x]` = confirmed done, `[ ]` = outstanding,
`[~]` = partially done. Items link to
[REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md) IDs where applicable.

---

## A. Paper submission

Blocking. These affect whether a reviewer can trust the results.

- [ ] **Seed every ray-tracing solver, or state the tolerance** (C1). Currently
      1 of 8 solver calls is seeded. Either make runs deterministic, or measure
      run-to-run variance and publish it as a tolerance. Do not claim
      reproducibility that has not been tested.
- [ ] **Map every paper figure to the command that produced it** (C2). One table:
      figure → stage → mode → study/config → date/version. This is the
      MMDetection model-zoo row adapted to our case.
- [ ] **State the environment the figures were produced in** (C5). Solver
      versions (`sionna-rt==2.0.1`, `mitsuba==3.8.0`, `drjit==1.3.1`), OS, CPU,
      RAM, and wall-clock per stage.
- [ ] **Publish expected values with tolerances** for at least the headline
      result (C3). The log-distance fit (`n = 1.73`, RMS 0.15 dB) is already
      guarded in `examples/tests`; extend the idea to the radio maps.
- [x] Dependency versions pinned — `requirements/*.txt`, `environment-*.yml`.
- [x] Data preparation documented — `DATA.md`, `scripts/check_data.sh`.
- [x] Evaluation commands documented — `ulap-scope <stage>`, `Makefile`.
- [x] Hyperparameters centralised — `ulap_scope/config.py`.
- [x] Limitations stated — README lines 79–83 (projection distortion, optimistic
      materials, flat-top extrusions, no field calibration).
- [x] Licence present — Apache-2.0.
- [ ] **Resolve the licence inconsistency** (C4): `pyproject.toml` says MIT.
- [ ] State explicitly whether released code is the **exact paper
      implementation** or a later version. It is currently a later version — the
      figures predate the 2026-07-29 refactor.

## B. Anonymous review (if the venue requires it)

- [ ] Strip identifying material from the anonymous artifact: `CITATION.cff`
      (names, affiliation), `research-paper/README.md`, `NOTICE`, the Amini
      branding in `README.md`, and the `aminitech` remote URL.
- [x] No developer paths or usernames in the tree — enforced by
      `test_no_developer_paths_in_tracked_files`.
- [ ] Check figure metadata for author/machine identifiers before submission —
      one PNG previously carried an absolute home path in a `tEXt` chunk; the
      guard covers tracked files, but re-verify any newly generated figure.
- [ ] Decide whether `publish/squashed` (single commit, no history) is the
      anonymous artifact. It is already the cleanest branch.
- [ ] Confirm the venue permits a link to open data sources (OSM, AWS Terrain
      Tiles) that could de-anonymise the study region. **The Barbados study area
      is itself identifying** — consider whether the anonymous version should
      ship only the generic `fetch_open_scene.py` path.

## C. Camera-ready

- [ ] Replace the `arXiv:TODO` placeholder in `CITATION.cff` with the real eprint
      ID and DOI, and mirror it in `research-paper/README.md` (the file already
      instructs this).
- [ ] Move paper #2 from "In preparation" to "Published" in
      `research-paper/README.md`.
- [ ] Tag a release matching the paper (e.g. `v0.1.0-paper`) so the cited code is
      immutable.
- [ ] Add the paper's BibTeX to `README.md` under "Citing".
- [ ] Update `research-paper/README.md`'s "which code backs which paper" table —
      it currently cites `blender/`, which is now a 3-file working directory (I5).
- [ ] Verify every figure in the paper still matches `docs/renders/`.

## D. Public code release

- [x] `LICENSE`, `NOTICE`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`,
      `SECURITY.md`, `CITATION.cff` present — **more than five of the seven
      reference projects ship**.
- [x] No secrets — gitleaks over full history, per `docs/security-triage.md`.
- [x] No licence-restricted geospatial data in the tracked tree — enforced by
      `test_no_geoportal_derived_scene_is_committed`.
- [x] Quick start that works on a laptop — `examples/`, verified on a fresh clone
      in clean Python 3.11/3.12 virtualenvs.
- [x] CI green on Python 3.10–3.12, including notebook execution.
- [ ] **Decide the history question** (`DATA.md`): geoportal-derived files remain
      in past commits on all branches back to `14fd043`. `publish/squashed` is
      clean because it has no history. Either publish that branch, or rewrite.
- [ ] **Merge `6f68419` to `main`** — `main` currently lacks the fixes and both
      regression guards.
- [ ] Issue templates, including an irreproducible-result template (I1).
- [ ] PR template (I2).
- [ ] `CHANGELOG.md` (I3).
- [ ] Clarify that `study.toml` does not yet drive the pipeline (I4).
- [ ] Confirm submodule licences are compatible with Apache-2.0 distribution —
      **BlenderGIS is GPL-3.0**. As a submodule (not vendored code) this is a
      reference, not a derivative work, but confirm before release.

## E. Post-release maintenance

- [ ] Declare scope: what this project will and will not accept. SB3's
      "development is focused on bug fixes and maintenance" is the model.
- [ ] State a support expectation — response time, or explicitly none.
- [ ] Decide a versioning policy and whether `study.toml`'s `SCHEMA_VERSION`
      carries compatibility guarantees.
- [ ] Curate 3–5 `good first issue`s before announcing.
- [ ] Decide whether to publish `ulap-scope` to PyPI (V3).
- [ ] Deprecation policy for `config.py` defaults once `apply-study-config` lands.
- [ ] Contributor recognition mechanism.

---

## The one-paragraph honesty test

Before submission, this paragraph must be true:

> *Every figure in this paper was produced by a named command, on a recorded
> commit, in a documented environment, from data whose provenance and licence are
> stated. Re-running that command reproduces the figure to within a stated
> tolerance. Where it cannot, we say so.*

Today the first sentence is **partly** true (commands exist; the figure→command
mapping and environment record do not), and the second is **not established**
(unseeded Monte Carlo, no measured tolerance). Items **C1, C2, C3 and C5** are
exactly what closes that gap.
