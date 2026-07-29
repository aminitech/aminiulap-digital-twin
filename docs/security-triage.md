# Security scan triage

Evidence for the pre-publication security review of this repository.

## Secret scanning — gitleaks

| Scan | Scope | Result |
|---|---|---|
| `gitleaks detect --log-opts="--all"` | Full git history, all 6 commits, 2.13 MB | **No leaks found** |
| `gitleaks detect --no-git --source=.` | Scrubbed working tree, 186.50 MB | **No leaks found** |

Supporting checks, all negative:

- No `.env`, `.pem`, `.key`, `.p12`, `.pfx`, `id_rsa*`, service-account JSON or
  `credentials*.json` has ever been added in any commit.
- No private IP ranges, `.internal`/`.local` hostnames, Coolify project names,
  `root@` or `ssh -i` invocations anywhere in the tree.
- No internal Notion, Linear, Slack or Google Drive links remain. Two internal
  Notion links were removed from `README.md` during this pass.

Because no credential was ever committed, there is nothing to rotate on the
"assume it is burned" rule.

## SAST — semgrep

Config: `p/security-audit` and `p/secrets`. Submodules, and geospatial data are
excluded. **4 findings, all LOW confidence, across 2 distinct rules.** Each is
duplicated because `blender/` and `ulap-scope/ulap_scope/stages/` hold parallel
copies of the same two scripts.

All 4 are **accepted, not fixed**. Rationale below.

### 1. `use-defused-xml` — ERROR severity, LOW confidence — 2 occurrences

`blender/sionna_mmwave_sinr.py:32`, `ulap-scope/ulap_scope/stages/sionna_mmwave_sinr.py:32`

```python
import xml.etree.ElementTree as ET
tree = ET.parse(SCENE)
```

**Accepted.** `SCENE` is the Mitsuba scene XML that this pipeline exported
itself, one stage earlier in the same run. It is a local build artefact, not
network- or user-supplied input, so the XXE and billion-laughs vectors the rule
guards against are not reachable in the intended flow.

**Residual risk.** A user who points the stage at a Mitsuba scene from an
untrusted third party would parse untrusted XML. We judged this acceptable
rather than adding `defusedxml` to what is deliberately a numpy-only install.
Anyone running third-party scene files should install `defusedxml` and swap the
import.

### 2. `dynamic-urllib-use-detected` — WARNING severity, LOW confidence — 2 occurrences

`blender/fetch_basemap.py:62`, `ulap-scope/ulap_scope/stages/fetch_basemap.py:62`

```python
TILE_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}")
url = TILE_URL.format(z=z, x=x, y=y)
```

**Accepted — effectively a false positive.** The rule fires on any non-literal
argument to `urlopen`. Here the scheme and host are a hardcoded `https://`
constant and the only interpolated values are `z`, `x`, `y` — integer tile
coordinates derived from the scene manifest's bounding box. The `file://`
redirection the rule warns about is not constructible.

## Not covered by these scans

Two classes of risk are **not** decidable by any scanner and are tracked
separately:

1. **Patent disclosure.** Whether publishing the implementation discloses
   material covered by a pending filing is a legal question, under separate
   review. This repository must not be made public until that review closes.
2. **Sensitive geospatial disclosure.** Whether national infrastructure geometry
   and vulnerability grids may be republished is a government disclosure
   question, also under separate review. This repository ships no geospatial data
   at all (see [DATA.md](../DATA.md)), which reduces but does not by itself
   settle that question — the `docs/renders/` figures are derived products.

## Reproducing this triage

```bash
gitleaks detect --log-opts="--all" --redact
gitleaks detect --no-git --source=. --redact
semgrep scan --config=p/security-audit --config=p/secrets \
  --exclude=BlenderGIS --exclude=mitsuba-blender --exclude=bbd-geo-portal \
  ulap-scope blender ulap-twin-ui scripts
```
