# The Ulap twin on Amini Cloud: frontend, backend and database

A three-tier deployment of the twin viewer, used to test Amini Cloud
`v1.0.0-alpha.rc1` end to end (CLOUD-1154). Each tier is a separate app in one
Amini Cloud project:

```
browser ──https──▶ twin-web ──http (private)──▶ twin-api ──postgres──▶ twin-db
                   ulap-twin-ui/                deploy/amini-cloud/       managed
                   server.py                    twin-api/app.py           Postgres
```

| App | Folder | What it does |
|---|---|---|
| `twin-db` | (managed database) | Holds the scene: towers, 585 building footprints, link metrics, page views. |
| `twin-api` | `deploy/amini-cloud/twin-api` | Creates its tables and loads `seed.json` on first start, then serves `/api/twin`, `/api/towers`, `/api/link-metrics`, `/api/stats` and `POST /api/views`. |
| `twin-web` | `ulap-twin-ui` | Serves the three.js viewer. Builds `data.js` from twin-api on each request and passes `/api/*` through, so the browser never talks to twin-api. |

The badge in the corner of the viewer shows that the data came through all three
tiers, how long it took, and a page-view count that was just written to Postgres.

## Data

Only open data. `seed.json` is made by `make_seed.py` from
`examples/data/newton-open_scene_manifest.json` (OpenStreetMap footprints,
ODbL 1.0, © OpenStreetMap contributors) and `examples/data/newton_link_metrics.csv`.
The towers are the placeholder sites from `examples/data/towers.template.json`.
The licence-restricted `ulap-twin-ui/data.js` is never served and is left out of
the twin-web image (see `DATA.md`).

```bash
python deploy/amini-cloud/make_seed.py   # rebuild seed.json
```

## Deploy it

In one project (for example `qa-rc1`):

1. **Databases**, **New database**: name it `twin-db`.
2. **Apps**, **Deploy a repo**: this repository and branch, folder
   `deploy/amini-cloud/twin-api`, port `8080`, name the app `twin-api`. Under
   **Use it from** on the database, tick `twin-api`, then **Redeploy** it.
   It reads `DATABASE_URL`.
3. **Deploy a repo** again: folder `ulap-twin-ui`, port `8080`, name the app
   `twin-web`. It finds twin-api through `APP_URL_TWIN_API`, which Amini Cloud
   sets for an app named `twin-api` in the same project. Set `TWIN_API_URL` to
   override it.
4. Open twin-web's outside address, then `scene.html`.

Both apps build from their own Dockerfile (pinned `python:3.13.9-slim`), run as
a non-root user and listen on `$PORT` (default 8080) on all addresses.

## Check it

| Request (on twin-web) | Expect |
|---|---|
| `/healthz` | `{"status":"ok"}` |
| `/readyz` | `{"twin_api":"ready"}`, or 503 when twin-api or Postgres is down |
| `/api/stats` | 2 towers, 585 buildings, 14 link metrics, the page-view count |
| `/scene.html` | the 3-D scene and the badge "twin-web → twin-api → Postgres" |

When twin-api is unreachable the viewer loads with no buildings and the badge
says "Data not loaded"; `/api/*` answers 502. When Postgres is down twin-api's
`/readyz` answers 503.

## Run it locally

```bash
docker network create twin
docker run -d --name twin-pg --network twin -e POSTGRES_PASSWORD=<local password> -e POSTGRES_DB=twin postgres:17.6-alpine
docker build -t twin-api deploy/amini-cloud/twin-api
docker build -t twin-web ulap-twin-ui
docker run -d --name twin-api --network twin -e DATABASE_URL=postgresql://postgres:<local password>@twin-pg:5432/twin twin-api
docker run -d --name twin-web --network twin -p 8080:8080 -e TWIN_API_URL=http://twin-api:8080 twin-web
open http://localhost:8080/scene.html
```

## Limits

- The viewer's header still says 576 buildings (it is fixed in the HTML); the
  open scene has 585, as the badge shows.
- `POST /api/views` takes no identity and stores only the page name and time.
  Amini Cloud's outside address needs a signed-in user, so it is not open to the
  internet; do not deploy it anywhere that is.
- twin-api seeds once. To load a new `seed.json`, empty the tables first.
