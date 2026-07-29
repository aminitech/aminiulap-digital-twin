# 🌐 Twin viewer

Serves [`ulap-twin-ui/`](../../../ulap-twin-ui/) — the three.js viewer for the
Barbados twin — on localhost and opens it.

```bash
python examples/apps/twin_viewer/serve.py
```

**Zero dependencies.** Standard library only: no numpy, no pip install, nothing.
The viewer itself is plain HTML/JS with a vendored three.js. The only reason it
needs a server at all is that browsers refuse to load scripts and assets over
`file://`.

## Options

```bash
python serve.py --port 8080         # pick a port (falls back if it's taken)
python serve.py --page scene.html   # jump straight to the 3-D scene
python serve.py --no-open           # don't launch a browser
python serve.py -v                  # log every request
```

## What you're looking at

The viewer renders the same data the pipeline ray-traces: 576 building footprints
extruded to their LiDAR heights, both towers at their real positions and heights,
and the study-area geometry — read straight from `ulap-twin-ui/data.js`, which
was exported from the scene manifest.

Rotate with the left mouse button, pan with the right, scroll to zoom.

## Feeding it your own scene

`data.js` is a single `window.TWIN_DATA = {...}` assignment with `towers` and
`buildings` (rings in lon/lat, plus a height). Regenerate it from your own study's
`scene_manifest.json` and the viewer will render your twin instead.
