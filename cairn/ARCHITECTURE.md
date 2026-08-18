# ARCHITECTURE.md

## Stack

| Layer | Choice |
|---|---|
| App | Next.js 15 (App Router), TypeScript, React 19 |
| Styling | Tailwind CSS |
| Map rendering | MapLibre GL JS v5 |
| Basemap tiles | Protomaps `.pmtiles`, served from Cloudflare R2 |
| Database | Supabase Postgres + PostGIS |
| Auth | Supabase Auth (phase 4 only, optional) |
| Hosting | Vercel |
| Ingest | Python in GitHub Actions (monthly cron) |
| Client storage | IndexedDB via `idb`, Cache API via service worker |

## Why these choices

**Protomaps over Mapbox.** A pmtiles file is a single archive addressed by HTTP range requests. That means the same file serves online tile requests and, once cached, offline ones. No tile server, no per-request billing. The Wasatch extract is roughly 100 to 200MB at zoom 14, which is a viable phone download. Mapbox would cost money and its offline story requires their native SDK.

**PostGIS over a flat GeoJSON file.** Bounding-box queries and nearest-trailhead lookups need a spatial index. `ST_Simplify` at query time also lets the API return lighter geometry for low zooms.

**IndexedDB over localStorage.** localStorage is synchronous, string-only, and capped around 5MB. Track recording writes continuously and needs to survive a browser kill.

## Data pipeline

```
Overpass API  ──┐
                ├──> ingest.py ──> normalize ──> Supabase (PostGIS)
Copernicus DEM ─┘                     │
                                      └──> elevation profile (jsonb)

Geofabrik OSM extract ──> pmtiles CLI ──> region.pmtiles ──> Cloudflare R2
```

### Trail ingest

Overpass query against the region bbox for:
- `way[highway~"^(path|footway|track|bridleway)$"]`
- `way[highway=steps]` (stairs are part of trails in the Wasatch)
- `relation[route=hiking]`
- `node[amenity=parking][~"."~"trailhead"]` and `node[highway=trailhead]`

Ways belonging to a hiking relation get merged into a single named trail via `ST_LineMerge`. Orphan ways with a `name` tag become standalone trails. Unnamed orphan ways are stored as connector segments, rendered but not searchable.

### Elevation

Download Copernicus GLO-30 DEM tiles covering the bbox once, store in the repo's `data/dem/` directory (gitignored) or fetch in CI. Sample the DEM along each trail geometry at ~20m intervals with `rasterio`. Compute:

- `elev_gain_m`, `elev_loss_m` using a 5m noise threshold. DEM sampling without a threshold inflates gain badly on flat trails. This is the single most common bug in elevation calculation.
- `elev_min_m`, `elev_max_m`
- `elevation_profile`: array of `[cumulative_distance_m, elevation_m]` pairs, downsampled to at most 200 points

Store the profile as jsonb. Never recompute at request time.

### Basemap generation

```bash
# One time, per region
wget https://download.geofabrik.de/north-america/us/utah-latest.osm.pbf
pmtiles convert --bbox=-112.20,40.35,-111.35,41.00 --maxzoom=14 utah-latest.osm.pbf wasatch.pmtiles
```

Upload to R2 with public read and CORS allowing Range requests. R2 has no egress fees, which is the reason for choosing it over S3.

## Schema

```sql
create extension if not exists postgis;

create table regions (
  id text primary key,
  name text not null,
  bbox geometry(Polygon, 4326) not null,
  pmtiles_url text not null,
  pmtiles_bytes bigint,
  trail_count int,
  updated_at timestamptz default now()
);

create table trails (
  id uuid primary key default gen_random_uuid(),
  region_id text references regions(id),
  osm_id bigint,
  osm_type text check (osm_type in ('way','relation')),
  name text,
  geom geometry(LineString, 4326) not null,
  length_m double precision not null,
  elev_gain_m double precision,
  elev_loss_m double precision,
  elev_min_m double precision,
  elev_max_m double precision,
  elevation_profile jsonb,
  surface text,
  is_named boolean generated always as (name is not null) stored,
  tags jsonb default '{}'::jsonb,
  updated_at timestamptz default now(),
  unique (osm_type, osm_id)
);

create index trails_geom_idx on trails using gist (geom);
create index trails_name_idx on trails using gin (to_tsvector('english', coalesce(name,'')));
create index trails_region_idx on trails (region_id);

create table trailheads (
  id uuid primary key default gen_random_uuid(),
  region_id text references regions(id),
  osm_id bigint unique,
  name text,
  geom geometry(Point, 4326) not null,
  has_parking boolean default false,
  has_toilets boolean default false,
  tags jsonb default '{}'::jsonb
);

create index trailheads_geom_idx on trailheads using gist (geom);

create table tracks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  name text,
  geom geometry(LineStringZ, 4326),
  points jsonb not null,          -- [{lat,lon,ele,t,acc}]
  distance_m double precision,
  duration_s int,
  elev_gain_m double precision,
  started_at timestamptz,
  created_at timestamptz default now()
);

create table saved_trails (
  user_id uuid references auth.users(id) on delete cascade,
  trail_id uuid references trails(id) on delete cascade,
  created_at timestamptz default now(),
  primary key (user_id, trail_id)
);
```

### RLS

```sql
alter table trails enable row level security;
alter table trailheads enable row level security;
alter table regions enable row level security;
create policy "public read" on trails for select using (true);
create policy "public read" on trailheads for select using (true);
create policy "public read" on regions for select using (true);

alter table tracks enable row level security;
create policy "own tracks" on tracks for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

alter table saved_trails enable row level security;
create policy "own saves" on saved_trails for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
```

## API routes

| Route | Purpose |
|---|---|
| `GET /api/trails?bbox=&zoom=` | Trails intersecting bbox, geometry simplified by zoom |
| `GET /api/trails/:id` | Full trail with elevation profile |
| `GET /api/search?q=` | Full-text name search, named trails only |
| `GET /api/regions` | Available regions with pmtiles URL and download size |
| `POST /api/tracks` | Sync a recorded track (phase 4) |

`/api/trails` must return a GeoJSON FeatureCollection and set `Cache-Control: public, max-age=3600, stale-while-revalidate=86400`. Vercel edge caching does most of the work here.

## Offline architecture

Three separate caches, deliberately not unified:

1. **App shell**: service worker precaches the Next.js build output. Standard Workbox precaching.
2. **Basemap**: pmtiles range requests cached via Cache API. On "download region," the client fetches the entire pmtiles file in sequential range chunks and stores the responses so `protomaps-leaflet`/`pmtiles` protocol handler hits cache on later reads.
3. **Trail data**: on region download, fetch all trails for the region as GeoJSON and write to IndexedDB store `trails`. The map reads from IndexedDB when `navigator.onLine` is false.

Region download must show byte size before starting and a progress bar during. Silently consuming 200MB of someone's storage is unacceptable.

## Recording architecture

```
navigator.geolocation.watchPosition({ enableHighAccuracy: true })
  → filter: drop points with accuracy > 30m
  → filter: drop points less than 5m from previous (GPS jitter while stationary)
  → append to IndexedDB store `active_track` on every accepted point
  → update in-memory stats and redraw the trace
```

**Critical details:**

- Request a `navigator.wakeLock` screen lock while recording. Without it iOS suspends the page and the track has holes.
- Write every point to IndexedDB immediately. Never batch. A crash must lose at most one point.
- On app start, check for an unfinished `active_track` and offer to resume or save it.
- Compute elevation gain from the DEM-corrected trail elevation where the user is on a known trail, not from GPS altitude. GPS altitude on phones is unreliable by tens of meters and will report thousands of feet of phantom gain.
- iOS Safari will not deliver background geolocation to a PWA when the screen is off. Document this limitation in the UI honestly. If it proves fatal in field testing, that is the trigger for a Capacitor native shell.

## Repo layout

```
/app                  Next.js App Router
  /(map)/page.tsx     Main map view
  /trail/[id]         Trail detail
  /tracks             Recorded tracks list + detail
  /downloads          Region management
  /api                Route handlers
/components
  /map                MapLibre wrapper, layers, controls
  /recording          Recorder UI, stats HUD
/lib
  /db                 Supabase client, typed queries
  /offline            IndexedDB wrappers, sync logic
  /geo                Distance, elevation gain, GPX export
/ingest
  ingest.py           Overpass → Supabase
  elevation.py        DEM sampling
  requirements.txt
/supabase
  /migrations
/public
  sw.js               Service worker
/docs                 CONTEXT, INTENT, IDENTITY, DECISIONS, ARCHITECTURE
```

## Cost model at small scale

| Item | Cost |
|---|---|
| Vercel Hobby | $0 |
| Supabase Free (500MB) | $0 |
| Cloudflare R2 (200MB stored, no egress fee) | ~$0.01/mo |
| GitHub Actions monthly cron | $0 |

Total under $1/month until roughly a few thousand users.
