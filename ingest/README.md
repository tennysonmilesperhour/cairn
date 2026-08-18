# Phase 0 ingest

Pulls Wasatch Front trails from OpenStreetMap, samples elevation from the
Copernicus GLO-30 DEM, and prints a coverage report. The report is the point of
this phase. See DECISIONS.md D010.

Nothing here writes to Supabase unless you explicitly ask it to.

## Setup

Python 3.11 or newer.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Only `SUPABASE_DB_URL` has to be filled in, and only for the database write.
Overpass and the DEM bucket are both public and need no credentials.

## Run

```bash
python ingest/ingest.py       # Overpass to data/normalized/
python ingest/elevation.py    # adds elevation fields in place
python ingest/report.py       # the coverage report
```

Each step reads what the previous one wrote, so run them in that order.

### Timings

| Step | Time | Notes |
|---|---|---|
| `ingest.py` first run | 2 to 10 min | Overpass queues the query behind other users. Most of the wait is server side. |
| `ingest.py` cached run | under 30 s | Reads the cached response from `data/cache/`. |
| `elevation.py` first run | 15 to 40 min | Includes a 136 MB DEM download. Runtime scales with total trail mileage. |
| `report.py` | seconds | |

Estimates. They have not been measured against the real dataset yet, because the
environment this was written in cannot reach Overpass. See below.

### Useful flags

```bash
python ingest/ingest.py --refresh              # ignore the cache, re-query Overpass
python ingest/ingest.py --endpoint <mirror>    # when overpass-api.de is over quota
python ingest/elevation.py --limit 50          # quick check on the first 50 trails
python ingest/report.py --longest 60           # show more of the long tail
```

## Writing to Supabase

Apply the migration first, then run the ingest with the write flag:

```bash
psql "$SUPABASE_DB_URL" -f supabase/migrations/0001_init.sql
python ingest/ingest.py --write-supabase
```

Run `elevation.py` before the write so the elevation columns are populated in
the same pass. Use a development project until the report has been reviewed.

## Working from a cached Overpass response

`ingest.py` caches the raw Overpass response under `data/cache/` keyed by a hash
of the endpoint and the query text. Reruns read that file instead of hitting the
API, which is what makes iterating on the normalization cheap.

It also means the fetch and the processing can happen on different machines. If
the machine doing the processing cannot reach Overpass, run the query anywhere
that can, then drop the response into `data/cache/`. Print the exact query and
its expected cache filename with:

```bash
python - <<'EOF'
import sys; sys.path.insert(0, "ingest")
import ingest
q = ingest.build_query(ingest.BBOX, 300)
print(q)
print("save the response to:", ingest.cache_path(ingest.DEFAULT_ENDPOINT, q))
EOF
```

Paste the query into <https://overpass-turbo.eu>, export the raw JSON, and save
it at that path. `ingest.py` will then run entirely offline.

## Data sources and licensing

- Trails and trailheads: OpenStreetMap via the Overpass API, ODbL. Attribution
  is required and is a permanent part of the map UI, not a settings page entry.
- Elevation: Copernicus GLO-30 DEM from the AWS open data bucket. Free to use
  with attribution to the European Space Agency.

DEM tiles land in `data/dem/` and the normalized output in `data/normalized/`.
All of `data/` is gitignored and regenerable.

## Tests

```bash
pytest ingest/test_elevation.py -v
```

Covers the elevation and distance maths, which is what the report is judged on.
The DEM tests download one 38 MB tile on first run and skip without network. The
known trail comparison skips until `ingest.py` has produced `trails.geojson`.
