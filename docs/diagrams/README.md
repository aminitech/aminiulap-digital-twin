# Diagrams

Mermaid sources for the S-CDT architecture figure, themed to the Amini design
system. **These are the source of truth — never hand-edit the rendered PNG or
SVG.**

```bash
./render.sh                    # every .mmd here, dark + light, PNG + SVG
./render.sh scdt-architecture  # just one
```

`render.sh` needs node. `mermaid-cli` is fetched on demand with `npx`; there is
nothing to install and nothing added to `package.json`.

## Outputs

Rendered one level up into `docs/`, so the paths referenced by `README.md` and
`ARCHITECTURE.md` stay stable:

| File | Use |
|---|---|
| `../scdt-architecture.png` · `.svg` | **dark** — repo docs, web, decks (brand default) |
| `../scdt-architecture-light.png` · `.svg` | **light** — print, papers, light-background slides |

## Reading the figure

Node styling encodes deployment status, matching Table I and the Fig. 1 caption
in the paper. This is the single most important thing the diagram communicates:
it is a *target* architecture, and most of the cognitive layer is not built.

| Style | Meaning |
|---|---|
| Solid border, filled | **Built** — shipped in the Ulap SCOPE deployment today |
| Dashed border, dimmed | **Designed** — specified in the paper, not implemented |
| Sunglow border | The load-bearing artifact (the spatio-temporal data cube) |
| Dashed + grey | Outside the sovereignty boundary |

To change what is marked built, edit the `class ... built` / `class ... designed`
lines at the bottom of `scdt-architecture.mmd` and re-render. Keep them honest
against Table I — a diagram that overstates what runs is worse than no diagram.

## Theme files

`theme-dark.json` and `theme-light.json` carry the palette from
`brandkit/DESIGN.md`: Space Black `#121212`, Charcoal `#202020`, Marble White
`#FFFFFF`, Sunglow `#FFC83C` as the only accent. Cluster labels are set in
Geist Mono, uppercase, 6% tracking, per the type scale.

Sunglow is used for **strokes only, never for text** — `#FFC83C` on white is
about 1.7:1 and fails WCAG AA, which the design system requires.

## Duplication and drift

`scdt-architecture.mmd` and both theme files are **duplicated** into the paper
repository at `ulap-research-papers/working-directory/6g-isac-sovereign-cognitive-digital-twin/diagrams/`.

The two copies previously drifted apart unnoticed — the twin repo said *"Amini
Node Network"* and *"National Sovereign Data Lake"* where the paper said *"Amini
Cloud"* and *"Amini Origin"*, and the two figures showed different layer-6
contents. After editing either copy, run:

```bash
./check-sync.sh                          # uses the default sibling path
ULAP_TWIN_REPO=/path/to/repo ./check-sync.sh
```

`render.sh` differs between the two on purpose — the paper copy writes the
filenames the LaTeX source already includes. Only the `.mmd` and the two theme
files must match.
