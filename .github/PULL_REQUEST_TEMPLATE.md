<!--
Thanks for contributing. CONTRIBUTING.md has the full guide; this template is
the short version of what a reviewer needs to see.
-->

## What changed

<!-- One or two sentences. -->

## What changed in the physics or geometry

<!--
CONTRIBUTING.md asks for this specifically: describe the scientific effect, not
just the code change. For example: "adds foliage loss, mmWave medians drop ~8 dB".

Write "none — infrastructure only" if this PR cannot change a result.
-->

## Type

- [ ] Bug fix (no change to results)
- [ ] Documentation
- [ ] New example, notebook or app
- [ ] New study area
- [ ] Behaviour change — **has an OpenSpec proposal under `openspec/changes/`**
- [ ] Infrastructure / CI

## Checklist

- [ ] Tests pass — `cd examples && python -m pytest -q` and `cd ulap-scope && python -m pytest -q`
- [ ] New behaviour has a test; a fixed bug has a test that fails without the fix
- [ ] Notebooks committed with outputs stripped (`jupyter nbconvert --clear-output --inplace`)
- [ ] No geospatial data committed — see [DATA.md](../DATA.md). No absolute paths, no usernames.
- [ ] If a result changed: the affected figure in `docs/renders/` is regenerated and
      [`docs/renders/README.md`](../docs/renders/README.md) is updated
- [ ] If behaviour changed: the matching spec under `openspec/specs/` is updated
- [ ] `CHANGELOG.md` updated under `[Unreleased]`

## Related

<!-- Issue numbers, OpenSpec change id, or "none". -->
